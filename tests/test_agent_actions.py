"""AO-000..AO-003 action capability, policy, ledger, and approval contracts."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from agent_actions.actuator import (
    ActionActuator,
    ActionActuatorError,
    ExecutionSpec,
    build_container_executors,
)
from agent_actions.capability import (
    ActionActor,
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
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


def _policy(*, kill_switch=False, interactive="approval", enabled=True):
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
                            "scheduled": "observe",
                            "event": "observe",
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


def _actuator(ledger, registry, policy, executor, *, clock=None):
    return ActionActuator(
        registry=registry,
        executors={"container.restart": executor},
        policy_provider=lambda: policy,
        ledger=ledger,
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
