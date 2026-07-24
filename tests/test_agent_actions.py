"""AO-000..AO-003 action capability, policy, ledger, and approval contracts."""

from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock

import pytest

from agent_actions.actuator import (
    ActionActuator,
    ActionActuatorError,
    ExecutionSpec,
    build_container_executors,
)
from agent_actions.canary import CanaryGateError
from agent_actions.capability import (
    ActionActor,
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
    canonical_hash,
)
from agent_actions.ledger import ActionLedger, ActionLedgerError, ActionState, NewAction
from agent_actions.policy import ActionPolicy, ActionPolicyError
from agent_actions.service import AgentActionError, AgentActionService


NOW = datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc)


def _normalizer(params):
    if set(params) != {"name"} or not isinstance(params.get("name"), str):
        raise CapabilityError("container action accepts only a name")
    return {"name": params["name"]}


def _capability(state, *, risk=RiskClass.REVERSIBLE, modes=None):
    return CapabilitySpec(
        operation="container.restart",
        version="1",
        risk=risk,
        eligible_modes=modes
        or (
            AuthorityMode.PROPOSE,
            AuthorityMode.APPROVAL,
            AuthorityMode.SUPERVISED,
            AuthorityMode.AUTONOMOUS,
        ),
        normalize_params=_normalizer,
        select_target=lambda params: params["name"],
        read_precondition=lambda params: {
            "name": params["name"],
            "generation": state["generation"],
        },
        render_impact=lambda params: f"Restart container {params['name']}",
    )


def _policy(
    *,
    kill_switch=False,
    interactive="approval",
    scheduled="observe",
    event="observe",
    enabled=True,
):
    return ActionPolicy.from_mapping(
        {
            "schema_version": "1",
            "kill_switch": kill_switch,
            "defaults": {"proposal_ttl_seconds": 900},
            "operations": {
                "container.restart": {
                    "enabled": enabled,
                    "approvers": ["mattermost:user-1", "local:admin"],
                    "targets": {
                        "jellyfin": {
                            "interactive": interactive,
                            "scheduled": scheduled,
                            "event": event,
                        }
                    },
                }
            },
        }
    )


def _service(tmp_path, state, policy=None, clock=None):
    return AgentActionService(
        registry=CapabilityRegistry([_capability(state)]),
        policy_provider=lambda: policy or _policy(),
        ledger=ActionLedger(tmp_path / "actions.sqlite3"),
        clock=clock or (lambda: NOW),
        id_factory=lambda: "action-1",
    )


def _propose(service, **overrides):
    values = {
        "operation": "container.restart",
        "params": {"name": "jellyfin"},
        "actor": {"type": "mattermost", "id": "user-1", "username": "marc"},
        "trigger": "interactive",
        "reason": "Jellyfin is unhealthy after three checks.",
        "evidence_ids": ["audit-1"],
        "idempotency_key": "mattermost:post-1:restart",
    }
    values.update(overrides)
    return service.propose(**values)


def _new_action(**overrides):
    values = {
        "action_id": "action-1",
        "idempotency_key": "mattermost:post-1:restart",
        "operation": "container.restart",
        "capability_version": "1",
        "target": "jellyfin",
        "risk": "R1",
        "trigger": "interactive",
        "authority_mode": "approval",
        "params": {"name": "jellyfin"},
        "evidence_ids": ["audit-1"],
        "payload_hash": "a" * 64,
        "reason": "Container is unhealthy.",
        "impact": "Restart container jellyfin",
        "precondition_hash": "b" * 64,
        "actor_type": "mattermost",
        "actor_id": "user-1",
        "actor_username": "marc",
        "state": ActionState.AWAITING_APPROVAL,
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
    }
    values.update(overrides)
    return NewAction(**values)


def _failed_supervised_action(ledger, *, action_id="action-1"):
    ledger.create(
        _new_action(
            action_id=action_id,
            idempotency_key=f"scheduler:{action_id}:repair",
            trigger="scheduled",
            authority_mode="supervised",
            state=ActionState.EXECUTION_FAILED,
        )
    )


def _authorised_supervised_action(*, action_id="action-2"):
    params = {"name": "jellyfin"}
    evidence = ["audit-1"]
    return _new_action(
        action_id=action_id,
        idempotency_key=f"scheduler:{action_id}:repair",
        trigger="scheduled",
        authority_mode="supervised",
        state=ActionState.AUTHORISED,
        params=params,
        evidence_ids=evidence,
        payload_hash=canonical_hash(
            {
                "operation": "container.restart",
                "capability_version": "1",
                "target": "jellyfin",
                "params": params,
                "trigger": "scheduled",
                "evidence_ids": evidence,
            }
        ),
        precondition_hash=canonical_hash(
            {"name": "jellyfin", "generation": 1}
        ),
    )


# -- identity and capability contracts ---------------------------------------
def test_actor_authority_uses_type_and_immutable_id():
    actor = ActionActor.from_mapping(
        {"type": "mattermost", "id": "user-1", "username": "renamed-user"}
    )
    assert actor.key == "mattermost:user-1"
    with pytest.raises(CapabilityError):
        ActionActor.from_mapping({"type": "mattermost", "id": "../user"})


def test_registry_rejects_duplicate_and_prohibited_capabilities():
    state = {"generation": 1}
    capability = _capability(state)
    with pytest.raises(CapabilityError):
        CapabilityRegistry([capability, capability])
    with pytest.raises(CapabilityError):
        _capability(state, risk=RiskClass.PROHIBITED)


def test_sensitive_capability_cannot_declare_automatic_authority():
    with pytest.raises(CapabilityError):
        _capability(
            {"generation": 1},
            risk=RiskClass.SENSITIVE,
            modes=(AuthorityMode.APPROVAL, AuthorityMode.AUTONOMOUS),
        )


def test_precondition_returns_exact_private_capability_fingerprint(tmp_path):
    state = {"generation": 7}
    service = _service(
        tmp_path, state, policy=_policy(scheduled="supervised")
    )

    result = service.precondition(
        operation="container.restart",
        params={"name": "jellyfin"},
    )

    assert result == {
        "operation": "container.restart",
        "capability_version": "1",
        "target": "jellyfin",
        "params": {"name": "jellyfin"},
        "precondition_hash": canonical_hash(
            {"name": "jellyfin", "generation": 7}
        ),
    }


# -- policy ------------------------------------------------------------------
def test_policy_is_deny_by_default_per_operation_target_and_trigger():
    policy = _policy()
    assert (
        policy.mode_for("container.restart", "jellyfin", trigger=_interactive())
        == AuthorityMode.APPROVAL
    )
    with pytest.raises(ActionPolicyError) as denied:
        policy.mode_for("container.restart", "sonarr", trigger=_interactive())
    assert denied.value.code == "denied_target"
    with pytest.raises(ActionPolicyError):
        _policy(enabled=False).mode_for(
            "container.restart", "jellyfin", trigger=_interactive()
        )


def _interactive():
    from agent_actions.capability import TriggerType

    return TriggerType.INTERACTIVE


@pytest.mark.parametrize(
    "change",
    [
        {"unknown": True},
        {"kill_switch": "yes"},
        {"defaults": {"proposal_ttl_seconds": 1}},
    ],
)
def test_policy_rejects_unknown_and_invalid_fields(change):
    raw = {
        "schema_version": "1",
        "kill_switch": True,
        "defaults": {"proposal_ttl_seconds": 900},
        "operations": {},
    }
    raw.update(change)
    with pytest.raises(ActionPolicyError):
        ActionPolicy.from_mapping(raw)


def test_kill_switch_blocks_authorisation_not_policy_reads():
    policy = _policy(kill_switch=True)
    assert policy.mode_for("container.restart", "jellyfin", _interactive())
    with pytest.raises(ActionPolicyError) as blocked:
        policy.require_execution_enabled()
    assert blocked.value.code == "kill_switch"


# -- durable ledger -----------------------------------------------------------
def test_ledger_is_private_and_idempotent(tmp_path):
    ledger = ActionLedger(tmp_path / "state" / "actions.sqlite3")
    first, created = ledger.create(_new_action())
    replay, replay_created = ledger.create(_new_action(action_id="action-2"))
    assert created is True and replay_created is False
    assert replay.action_id == first.action_id
    assert first.evidence_ids == ["audit-1"]
    assert os.stat(tmp_path / "state" / "actions.sqlite3").st_mode & 0o777 == 0o660


def test_ledger_accepts_secure_group_file_owned_by_another_identity(
    tmp_path, monkeypatch
):
    path = tmp_path / "actions.sqlite3"
    ActionLedger(path)
    real_chmod = os.chmod

    def deny_database_chmod(target, mode, *args, **kwargs):
        if os.fspath(target) == os.fspath(path):
            raise PermissionError("owned by another service identity")
        return real_chmod(target, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", deny_database_chmod)

    ActionLedger(path)


def test_ledger_rejects_insecure_file_owned_by_another_identity(
    tmp_path, monkeypatch
):
    path = tmp_path / "actions.sqlite3"
    ActionLedger(path)
    path.chmod(0o666)

    def deny_chmod(*_args, **_kwargs):
        raise PermissionError("owned by another service identity")

    monkeypatch.setattr(os, "chmod", deny_chmod)

    with pytest.raises(ActionLedgerError) as unavailable:
        ActionLedger(path)

    assert unavailable.value.code == "store_unavailable"


def test_ledger_rejects_idempotency_payload_conflict(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    ledger.create(_new_action())
    with pytest.raises(ActionLedgerError) as conflict:
        ledger.create(_new_action(action_id="action-2", payload_hash="c" * 64))
    assert conflict.value.code == "idempotency_conflict"


def test_ledger_approval_is_single_transition_and_payload_bound(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    ledger.create(_new_action())
    approved = ledger.approve(
        "action-1",
        payload_hash="a" * 64,
        approver_type="mattermost",
        approver_id="user-1",
        approver_username="marc",
        approved_at=NOW.isoformat(),
    )
    assert approved.state == ActionState.AUTHORISED
    assert approved.approved_by_id == "user-1"
    with pytest.raises(ActionLedgerError) as replay:
        ledger.approve(
            "action-1",
            payload_hash="a" * 64,
            approver_type="mattermost",
            approver_id="user-1",
            approver_username="marc",
            approved_at=NOW.isoformat(),
        )
    assert replay.value.code == "invalid_state"


def test_ledger_can_cancel_only_before_execution(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    ledger.create(_new_action())
    cancelled = ledger.cancel("action-1", cancelled_at=NOW.isoformat())
    assert cancelled.state == ActionState.CANCELLED
    with pytest.raises(ActionLedgerError) as repeated:
        ledger.cancel("action-1", cancelled_at=NOW.isoformat())
    assert repeated.value.code == "invalid_state"


def test_exact_target_lease_blocks_every_non_terminal_action(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    first, _ = ledger.create(_new_action())

    lease = ledger.active_target_lease(
        operation="container.restart", target="jellyfin"
    )
    assert lease is not None
    assert lease.action_id == first.action_id

    with pytest.raises(ActionLedgerError) as busy:
        ledger.create(
            _new_action(
                action_id="action-2",
                idempotency_key="mattermost:post-2:restart",
            )
        )
    assert busy.value.code == "target_busy"

    ledger.cancel("action-1", cancelled_at=NOW.isoformat())
    assert (
        ledger.active_target_lease(
            operation="container.restart", target="jellyfin"
        )
        is None
    )
    replacement, created = ledger.create(
        _new_action(
            action_id="action-2",
            idempotency_key="mattermost:post-2:restart",
        )
    )
    assert created is True
    assert replacement.action_id == "action-2"


def test_exact_target_lease_claim_is_concurrency_safe(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    barrier = Barrier(2)

    def create(index):
        barrier.wait()
        try:
            return ledger.create(
                _new_action(
                    action_id=f"action-{index}",
                    idempotency_key=f"mattermost:post-{index}:restart",
                )
            )[1]
        except ActionLedgerError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, (1, 2)))

    assert sorted(map(str, results)) == ["True", "target_busy"]


def test_existing_active_action_gains_fail_closed_lease_on_migration(tmp_path):
    path = tmp_path / "actions.sqlite3"
    ledger = ActionLedger(path)
    ledger.create(_new_action())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE action_target_leases")

    migrated = ActionLedger(path)

    lease = migrated.active_target_lease(
        operation="container.restart", target="jellyfin"
    )
    assert lease is not None
    assert lease.action_id == "action-1"
    assert lease.active is True


def test_lease_survives_execution_and_releases_only_at_terminal_state(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    ledger.create(_new_action(state=ActionState.AUTHORISED))

    ledger.claim_execution(
        "action-1",
        payload_hash="a" * 64,
        approval_required=False,
        claimed_at=NOW.isoformat(),
    )
    ledger.begin_verification("action-1")

    assert (
        ledger.active_target_lease(
            operation="container.restart", target="jellyfin"
        ).action_id
        == "action-1"
    )
    ledger.finish_execution(
        "action-1",
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    assert (
        ledger.active_target_lease(
            operation="container.restart", target="jellyfin"
        )
        is None
    )


def test_demotion_is_exact_durable_and_idempotent(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    _failed_supervised_action(ledger)

    demotion, created = ledger.create_demotion(
        operation="container.restart",
        target="jellyfin",
        cause="execution_failed",
        source_action_id="action-1",
        release_commit="a" * 40,
        demoted_at=NOW.isoformat(),
    )
    repeated, repeated_created = ledger.create_demotion(
        operation="container.restart",
        target="jellyfin",
        cause="verification_failed",
        source_action_id="action-1",
        release_commit="a" * 40,
        demoted_at=(NOW + timedelta(seconds=1)).isoformat(),
    )

    assert created is True
    assert repeated_created is False
    assert repeated == demotion
    assert demotion.active is True
    assert demotion.cause == "execution_failed"
    assert ledger.active_demotion(
        operation="container.restart", target="jellyfin"
    ) == demotion
    assert ledger.active_demotion(
        operation="container.restart", target="sonarr"
    ) is None


def test_demotion_blocks_service_and_actuator_independently(tmp_path):
    state = {"generation": 1}
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    _failed_supervised_action(ledger)
    gate = Mock()
    policy = _policy(scheduled="supervised")
    registry = CapabilityRegistry([_capability(state)])
    service = AgentActionService(
        registry=registry,
        policy_provider=lambda: policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW,
        id_factory=lambda: "action-2",
    )
    ledger.create(_authorised_supervised_action())

    ledger.create_demotion(
        operation="container.restart",
        target="jellyfin",
        cause="execution_failed",
        source_action_id="action-1",
        release_commit="a" * 40,
        demoted_at=NOW.isoformat(),
    )
    with pytest.raises(AgentActionError) as service_denied:
        _propose(
            service,
            trigger="scheduled",
            idempotency_key="scheduler:incident-3:repair",
        )
    assert service_denied.value.code == "demoted"

    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: pytest.fail("demoted action executed"),
        verify=lambda params, before: (True, {}),
        no_rollback_reason="No safe rollback",
    )
    with pytest.raises(ActionActuatorError) as actuator_denied:
        _actuator(
            ledger,
            registry,
            policy,
            executor,
            canary_gate=gate,
        ).execute("action-2", audit_id="action-audit-2")
    assert actuator_denied.value.code == "demoted"
    assert ledger.get("action-2").state == ActionState.AUTHORISED


def test_demotion_clear_requires_current_release_verified_recovery(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    _failed_supervised_action(ledger)
    demotion, _ = ledger.create_demotion(
        operation="container.restart",
        target="jellyfin",
        cause="execution_failed",
        source_action_id="action-1",
        release_commit="a" * 40,
        demoted_at=NOW.isoformat(),
    )
    recovery_time = NOW + timedelta(minutes=1)
    recovery = _new_action(
        action_id="action-recovery",
        idempotency_key="mattermost:recovery:restart",
        created_at=recovery_time.isoformat(),
        expires_at=(recovery_time + timedelta(minutes=15)).isoformat(),
    )
    ledger.create(recovery)
    ledger.approve(
        recovery.action_id,
        payload_hash=recovery.payload_hash,
        approver_type="mattermost",
        approver_id="user-1",
        approver_username="marc",
        approved_at=recovery_time.isoformat(),
    )
    ledger.claim_execution(
        recovery.action_id,
        payload_hash=recovery.payload_hash,
        approval_required=True,
        claimed_at=recovery_time.isoformat(),
    )
    ledger.begin_verification(recovery.action_id)
    ledger.finish_execution(
        recovery.action_id,
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    ledger.record_event(
        recovery.action_id,
        phase="succeeded",
        created_at=recovery_time.isoformat(),
        details={
            "action_audit_id": "audit-recovery",
            "after": {"name": "jellyfin", "status": "running"},
        },
    )

    with pytest.raises(ActionLedgerError) as no_canary:
        ledger.clear_demotion(
            demotion.demotion_id,
            expected_revision=demotion.revision,
            recovery_action_id=recovery.action_id,
            release_commit="b" * 40,
            cleared_by_type="local",
            cleared_by_id="admin",
            cleared_by_username="marc",
            cleared_at=(recovery_time + timedelta(minutes=1)).isoformat(),
        )
    assert no_canary.value.code == "recovery_required"

    ledger.attest_canary(
        attestation_id="canary-recovery",
        source_action_id=recovery.action_id,
        operation="container.restart",
        target="jellyfin",
        capability_version="1",
        risk="R1",
        release_commit="b" * 40,
        attested_by_type="local",
        attested_by_id="admin",
        attested_by_username="marc",
        attested_at=(recovery_time + timedelta(minutes=1)).isoformat(),
    )
    cleared = ledger.clear_demotion(
        demotion.demotion_id,
        expected_revision=demotion.revision,
        recovery_action_id=recovery.action_id,
        release_commit="b" * 40,
        cleared_by_type="local",
        cleared_by_id="admin",
        cleared_by_username="marc",
        cleared_at=(recovery_time + timedelta(minutes=2)).isoformat(),
    )

    assert cleared.active is False
    assert cleared.recovery_action_id == recovery.action_id
    assert cleared.cleared_by_id == "admin"
    assert cleared.revision == 2
    assert (
        ledger.active_demotion(
            operation="container.restart", target="jellyfin"
        )
        is None
    )


def test_service_rejection_records_immutable_mattermost_actor(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    _propose(service)
    rejected = service.reject(
        "action-1",
        rejector={"type": "mattermost", "id": "user-1", "username": "renamed"},
    )
    detail = service.get("action-1")

    assert rejected["state"] == "rejected"
    assert detail["events"][-1]["details"]["actor"] == {
        "type": "mattermost",
        "id": "user-1",
        "username": "renamed",
    }


def test_service_rejection_denies_unconfigured_mattermost_actor(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    _propose(service)
    with pytest.raises(AgentActionError) as denied:
        service.reject(
            "action-1",
            rejector={"type": "mattermost", "id": "other", "username": "marc"},
        )
    assert denied.value.code == "denied_approver"
    assert service.get("action-1")["state"] == "awaiting_approval"


def test_ledger_rejects_symlink_store(tmp_path):
    target = tmp_path / "real.sqlite3"
    target.touch()
    link = tmp_path / "actions.sqlite3"
    link.symlink_to(target)
    with pytest.raises(ActionLedgerError) as unsafe:
        ActionLedger(link)
    assert unsafe.value.code == "unsafe_store"


# -- proposal and approval service -------------------------------------------
def test_service_creates_exact_expiring_approval_proposal(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    action, created = _propose(service)
    assert created is True
    assert action["state"] == "awaiting_approval"
    assert action["target"] == "jellyfin"
    assert action["risk"] == "R1"
    assert action["evidence_ids"] == ["audit-1"]
    assert action["expires_at"] == (NOW + timedelta(minutes=15)).isoformat()
    assert len(action["payload_hash"]) == 64


def test_service_deduplicates_same_proposal_and_rejects_changed_payload(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    first, _ = _propose(service)
    replay, created = _propose(service)
    assert created is False and replay["id"] == first["id"]
    with pytest.raises(AgentActionError) as conflict:
        _propose(service, reason="same key, different reason", params={"name": "sonarr"})
    assert conflict.value.code in {"denied_target", "idempotency_conflict"}


def test_service_approval_checks_kill_switch_and_immutable_approver(tmp_path):
    state = {"generation": 1}
    active = _policy(kill_switch=False)
    current = {"policy": active}
    service = AgentActionService(
        registry=CapabilityRegistry([_capability(state)]),
        policy_provider=lambda: current["policy"],
        ledger=ActionLedger(tmp_path / "actions.sqlite3"),
        clock=lambda: NOW,
        id_factory=lambda: "action-1",
    )
    _propose(service)

    with pytest.raises(AgentActionError) as wrong_actor:
        service.approve(
            "action-1",
            approver={"type": "mattermost", "id": "other", "username": "marc"},
        )
    assert wrong_actor.value.code == "denied_approver"

    current["policy"] = _policy(kill_switch=True)
    with pytest.raises(AgentActionError) as disabled:
        service.approve(
            "action-1",
            approver={"type": "mattermost", "id": "user-1", "username": "renamed"},
        )
    assert disabled.value.code == "kill_switch"

    current["policy"] = active
    approved = service.approve(
        "action-1",
        approver={"type": "mattermost", "id": "user-1", "username": "renamed"},
    )
    assert approved["state"] == "authorised"
    assert approved["approval"]["actor"]["id"] == "user-1"


def test_service_invalidates_when_precondition_changes(tmp_path):
    state = {"generation": 1}
    service = _service(tmp_path, state)
    _propose(service)
    state["generation"] = 2
    with pytest.raises(AgentActionError) as changed:
        service.approve(
            "action-1",
            approver={"type": "mattermost", "id": "user-1"},
        )
    assert changed.value.code == "precondition_changed"
    assert service.get("action-1")["state"] == "precondition_changed"


def test_service_expires_approval_and_closes_action(tmp_path):
    moment = {"now": NOW}
    state = {"generation": 1}
    service = _service(tmp_path, state, clock=lambda: moment["now"])
    _propose(service)
    moment["now"] += timedelta(minutes=16)
    with pytest.raises(AgentActionError) as expired:
        service.approve(
            "action-1",
            approver={"type": "mattermost", "id": "user-1"},
        )
    assert expired.value.code == "expired"
    assert service.get("action-1")["state"] == "expired"


def test_observe_mode_cannot_create_proposal(tmp_path):
    service = _service(tmp_path, {"generation": 1}, policy=_policy(interactive="observe"))
    with pytest.raises(AgentActionError) as observe:
        _propose(service)
    assert observe.value.code == "observe_only"


def test_automatic_mode_still_obeys_kill_switch(tmp_path):
    policy = _policy(kill_switch=True, interactive="autonomous")
    service = _service(tmp_path, {"generation": 1}, policy=policy)
    with pytest.raises(AgentActionError) as disabled:
        _propose(service)
    assert disabled.value.code == "kill_switch"


def test_generic_service_cannot_bypass_supervision_authorization(tmp_path):
    state = {"generation": 1}
    gate = Mock()
    service = AgentActionService(
        registry=CapabilityRegistry([_capability(state)]),
        policy_provider=lambda: _policy(scheduled="supervised"),
        ledger=ActionLedger(tmp_path / "actions.sqlite3"),
        canary_gate=gate,
        clock=lambda: NOW,
        id_factory=lambda: "action-1",
    )

    with pytest.raises(AgentActionError) as denied:
        _propose(service, trigger="scheduled")

    assert denied.value.code == "supervision_required"
    gate.require_supervised.assert_not_called()
    assert service.list()["actions"] == []


def test_supervised_proposal_fails_closed_after_canary_revocation(tmp_path):
    gate = Mock()
    gate.require_supervised.side_effect = CanaryGateError(
        "canary_required",
        "A current repair canary is required for supervised authority",
    )
    service = AgentActionService(
        registry=CapabilityRegistry([_capability({"generation": 1})]),
        policy_provider=lambda: _policy(scheduled="supervised"),
        ledger=ActionLedger(tmp_path / "actions.sqlite3"),
        canary_gate=gate,
        clock=lambda: NOW,
        id_factory=lambda: "action-1",
    )

    with pytest.raises(AgentActionError) as denied:
        _propose(service, trigger="scheduled")

    assert denied.value.code == "supervision_required"


def test_service_exposes_server_owned_capabilities_and_policy(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    catalogue = service.capabilities()
    assert catalogue["kill_switch"] is False
    assert catalogue["capabilities"] == [
        {
            "operation": "container.restart",
            "version": "1",
            "risk": "R1",
            "eligible_modes": ["propose", "approval", "supervised", "autonomous"],
            "policy": {
                "enabled": True,
                "targets": {
                    "jellyfin": {
                        "interactive": "approval",
                        "scheduled": "observe",
                        "event": "observe",
                    }
                },
            },
        }
    ]
    assert service.policy()["operations"]["container.restart"]["approvers"] == [
        "mattermost:user-1",
        "local:admin",
    ]


def test_service_cancels_authorised_action_and_records_event(tmp_path):
    state = {"generation": 1}
    ledger, registry, policy = _authorised_action(tmp_path, state)
    service = AgentActionService(
        registry=registry,
        policy_provider=lambda: policy,
        ledger=ledger,
        clock=lambda: NOW,
    )
    cancelled = service.cancel("action-1")
    assert cancelled["state"] == "cancelled"
    assert service.get("action-1")["events"] == [
        {
            "phase": "cancelled",
            "created_at": NOW.isoformat(),
            "details": {"code": "cancelled_by_administrator"},
        }
    ]


def test_policy_update_requires_exact_registry_and_blocks_automatic_modes(tmp_path):
    service = _service(tmp_path, {"generation": 1})
    valid = _policy().public_dict()
    assert service.validate_policy(valid) == valid
    invalid = _policy(interactive="supervised").public_dict()
    with pytest.raises(AgentActionError) as gated:
        service.validate_policy(invalid)
    assert gated.value.code == "invalid_policy"
    invalid["operations"]["unknown.operation"] = invalid["operations"].pop(
        "container.restart"
    )
    with pytest.raises(AgentActionError):
        service.validate_policy(invalid)


# -- isolated execution ------------------------------------------------------
def _authorised_action(tmp_path, state, *, policy=None):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    active_policy = policy or _policy()
    registry = CapabilityRegistry([_capability(state)])
    service = AgentActionService(
        registry=registry,
        policy_provider=lambda: active_policy,
        ledger=ledger,
        clock=lambda: NOW,
        id_factory=lambda: "action-1",
    )
    _propose(service)
    service.approve(
        "action-1",
        approver={"type": "mattermost", "id": "user-1", "username": "marc"},
    )
    return ledger, registry, active_policy


def _actuator(
    ledger,
    registry,
    policy,
    executor,
    *,
    canary_gate=None,
    clock=None,
):
    return ActionActuator(
        registry=registry,
        executors={"container.restart": executor},
        policy_provider=lambda: policy,
        ledger=ledger,
        canary_gate=canary_gate,
        clock=clock or (lambda: NOW),
    )


def test_actuator_revalidates_and_consumes_approval_once(tmp_path):
    state = {"generation": 1}
    ledger, registry, policy = _authorised_action(tmp_path, state)
    calls = []
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(dict(params)) or {"status": "restarted"},
        verify=lambda params, before: (
            True,
            {"name": params["name"], "status": "running", "generation": 2},
        ),
        no_rollback_reason="No safe rollback",
    )

    result = _actuator(ledger, registry, policy, executor).execute(
        "action-1", audit_id="action-audit-1"
    )

    assert result["state"] == "succeeded"
    assert result["approval_consumed"] is True
    assert calls == [{"name": "jellyfin"}]
    assert ledger.get("action-1").approval_used_at == NOW.isoformat()
    assert [event["phase"] for event in ledger.events("action-1")] == [
        "execution_started",
        "succeeded",
    ]
    with pytest.raises(ActionActuatorError) as replay:
        _actuator(ledger, registry, policy, executor).execute(
            "action-1", audit_id="action-audit-2"
        )
    assert replay.value.code == "invalid_state"


def test_actuator_rejects_policy_or_precondition_change_before_mutation(tmp_path):
    state = {"generation": 1}
    ledger, registry, _policy_at_approval = _authorised_action(tmp_path, state)
    calls = []
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(params) or {"status": "restarted"},
        verify=lambda params, before: (True, {}),
        no_rollback_reason="No safe rollback",
    )
    state["generation"] = 2
    with pytest.raises(ActionActuatorError) as changed:
        _actuator(ledger, registry, _policy(), executor).execute(
            "action-1", audit_id="action-audit-1"
        )
    assert changed.value.code == "precondition_changed"
    assert calls == []
    assert ledger.get("action-1").state == ActionState.PRECONDITION_CHANGED


def test_actuator_kill_switch_is_checked_immediately_before_mutation(tmp_path):
    state = {"generation": 1}
    ledger, registry, _ = _authorised_action(tmp_path, state)
    calls = []
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(params) or {"status": "restarted"},
        verify=lambda params, before: (True, {}),
        no_rollback_reason="No safe rollback",
    )
    with pytest.raises(ActionActuatorError) as disabled:
        _actuator(ledger, registry, _policy(kill_switch=True), executor).execute(
            "action-1", audit_id="action-audit-1"
        )
    assert disabled.value.code == "kill_switch"
    assert calls == []
    assert ledger.get("action-1").state == ActionState.AUTHORISED


def test_actuator_rechecks_canary_immediately_before_supervised_mutation(tmp_path):
    state = {"generation": 1}
    policy = _policy(scheduled="supervised")
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    registry = CapabilityRegistry([_capability(state)])
    gate = Mock()
    ledger.create(_authorised_supervised_action(action_id="action-1"))
    gate.require_supervised.reset_mock()
    gate.require_supervised.side_effect = CanaryGateError(
        "canary_required",
        "A current repair canary is required for supervised authority",
    )
    calls = []
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(params) or {"status": "restarted"},
        verify=lambda params, before: (True, {}),
        no_rollback_reason="No safe rollback",
    )

    with pytest.raises(ActionActuatorError) as denied:
        _actuator(
            ledger,
            registry,
            policy,
            executor,
            canary_gate=gate,
        ).execute("action-1", audit_id="action-audit-1")

    assert denied.value.code == "canary_required"
    assert calls == []
    assert ledger.get("action-1").state == ActionState.AUTHORISED


def test_actuator_closes_execution_and_verification_failures(tmp_path):
    state = {"generation": 1}
    ledger, registry, policy = _authorised_action(tmp_path / "execute", state)
    failed_executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: {"error": "host detail must not be persisted"},
        verify=lambda params, before: (True, {}),
        no_rollback_reason="No safe rollback",
    )
    result = _actuator(ledger, registry, policy, failed_executor).execute(
        "action-1", audit_id="action-audit-1"
    )
    assert result["state"] == "execution_failed"
    assert "host detail" not in str(ledger.events("action-1"))

    state = {"generation": 1}
    ledger, registry, policy = _authorised_action(tmp_path / "verify", state)
    verify_executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: {"status": "restarted"},
        verify=lambda params, before: (
            False,
            {"name": "jellyfin", "status": "exited"},
        ),
        no_rollback_reason="Container stop is not allowlisted",
    )
    result = _actuator(ledger, registry, policy, verify_executor).execute(
        "action-1", audit_id="action-audit-2"
    )
    assert result["state"] == "verification_failed"
    assert result["terminal_code"] == "verification_failed:no_safe_rollback"


def test_actuator_resumes_pending_verification_without_reexecuting(tmp_path):
    state = {"generation": 1}
    ledger, registry, policy = _authorised_action(tmp_path, state)
    calls = []
    verification = iter(
        [
            (None, {"job": {"active_state": "activating"}}),
            (True, {"job": {"active_state": "inactive", "result": "success"}}),
        ]
    )
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(dict(params)) or {"started": True},
        verify=lambda params, before: next(verification),
        no_rollback_reason="No safe rollback",
        max_verification_seconds=3600,
    )

    first = _actuator(ledger, registry, policy, executor).execute(
        "action-1", audit_id="action-audit-1"
    )
    resumed = _actuator(
        ledger,
        registry,
        policy,
        executor,
        clock=lambda: NOW + timedelta(minutes=20),
    ).execute("action-1", audit_id="action-audit-2")

    assert first["state"] == "verifying"
    assert resumed["state"] == "succeeded"
    assert calls == [{"name": "jellyfin"}]


def test_container_restart_executor_requires_running_and_new_start_time():
    statuses = iter(
        [
            {"name": "jellyfin", "status": "running", "health": "healthy",
             "started_at": "before"},
            {"name": "jellyfin", "status": "running", "health": "healthy",
             "started_at": "after"},
        ]
    )
    controls = []
    sleeps = []
    executor = build_container_executors(
        control=lambda name, action: controls.append((name, action)) or {"status": "ok"},
        status_reader=lambda name: next(statuses),
        attempts=2,
        interval_seconds=0.1,
        sleeper=sleeps.append,
    )["container.restart"]

    assert executor.execute({"name": "jellyfin"}) == {"status": "ok"}
    verified, after = executor.verify(
        {"name": "jellyfin"}, {"started_at": "before"}
    )
    assert verified is True and after["started_at"] == "after"
    assert controls == [("jellyfin", "restart")]
    assert sleeps == [0.1]
