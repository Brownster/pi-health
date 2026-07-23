"""AO-008 durable repair-canary evidence and gate contracts."""

from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from agent_actions.canary import CanaryGateError, CanaryGateService
from agent_actions.capability import (
    AuthorityMode,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
    TriggerType,
)
from agent_actions.ledger import ActionLedger, ActionState, NewAction
from agent_actions.defaults import read_agent_release_commit


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
RELEASE_COMMIT = "a" * 40


def _capability(
    *,
    version: str = "1",
    risk: RiskClass = RiskClass.REVERSIBLE,
    modes: tuple[AuthorityMode, ...] = (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
        AuthorityMode.SUPERVISED,
    ),
) -> CapabilitySpec:
    return CapabilitySpec(
        operation="container.restart",
        version=version,
        risk=risk,
        eligible_modes=modes,
        normalize_params=lambda params: {"name": params["name"]},
        select_target=lambda params: params["name"],
        read_precondition=lambda params: {"name": params["name"], "started_at": "old"},
        render_impact=lambda params: f"Restart container {params['name']}",
    )


def _new_action(action_id: str = "action-1", **overrides) -> NewAction:
    values = {
        "action_id": action_id,
        "idempotency_key": f"canary:{action_id}",
        "operation": "container.restart",
        "capability_version": "1",
        "target": "get_iplayer",
        "risk": "R1",
        "trigger": "interactive",
        "authority_mode": "approval",
        "params": {"name": "get_iplayer"},
        "evidence_ids": ["audit-1"],
        "payload_hash": "b" * 64,
        "reason": "The container remained unhealthy after repeated checks.",
        "impact": "Restart container get_iplayer",
        "precondition_hash": "c" * 64,
        "actor_type": "mattermost",
        "actor_id": "user-1",
        "actor_username": "marc",
        "state": ActionState.AWAITING_APPROVAL,
        "created_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(minutes=15)).isoformat(),
    }
    values.update(overrides)
    return NewAction(**values)


def _successful_action(
    ledger: ActionLedger,
    action_id: str = "action-1",
    *,
    record_success_event: bool = True,
    **overrides,
) -> None:
    action = _new_action(action_id, **overrides)
    ledger.create(action)
    ledger.approve(
        action_id,
        payload_hash=action.payload_hash,
        approver_type="mattermost",
        approver_id="user-1",
        approver_username="marc",
        approved_at=NOW.isoformat(),
    )
    ledger.claim_execution(
        action_id,
        payload_hash=action.payload_hash,
        approval_required=True,
        claimed_at=NOW.isoformat(),
    )
    ledger.begin_verification(action_id)
    ledger.finish_execution(
        action_id,
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    if record_success_event:
        ledger.record_event(
            action_id,
            phase="succeeded",
            created_at=NOW.isoformat(),
            details={
                "action_audit_id": f"audit-{action_id}",
                "after": {
                    "name": "get_iplayer",
                    "status": "running",
                    "started_at": "new",
                },
            },
        )


def _service(
    tmp_path,
    *,
    ledger: ActionLedger | None = None,
    capability: CapabilitySpec | None = None,
    attestation_id: str = "canary-1",
) -> tuple[CanaryGateService, ActionLedger]:
    action_ledger = ledger or ActionLedger(tmp_path / "actions.sqlite3")
    service = CanaryGateService(
        registry=CapabilityRegistry([capability or _capability()]),
        ledger=action_ledger,
        release_commit_provider=lambda: RELEASE_COMMIT,
        clock=lambda: NOW,
        id_factory=lambda: attestation_id,
    )
    return service, action_ledger


def _local_admin(username: str = "marc") -> dict[str, str]:
    return {"type": "local", "id": "admin", "username": username}


def test_attestation_derives_exact_evidence_and_is_idempotent(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)

    first, created = service.attest("action-1", actor=_local_admin())
    replay, replay_created = service.attest(
        "action-1", actor=_local_admin("renamed-admin")
    )

    assert created is True and replay_created is False
    assert replay == first
    assert first == {
        "id": "canary-1",
        "operation": "container.restart",
        "target": "get_iplayer",
        "trigger": "scheduled",
        "capability_version": "1",
        "risk": "R1",
        "source_action_id": "action-1",
        "release_commit": RELEASE_COMMIT,
        "attested_by": {
            "type": "local",
            "id": "admin",
            "username": "marc",
        },
        "attested_at": NOW.isoformat(),
        "revoked_by": None,
        "revoked_at": None,
    }
    assert [event["phase"] for event in ledger.events("action-1")] == [
        "succeeded",
        "canary_attested",
    ]
    assert len(service.list()) == 1

    restarted, _ = _service(tmp_path)
    assert restarted.list() == [first]


def test_attestation_replay_uses_persisted_evidence_when_release_lookup_fails(
    tmp_path,
):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    expected, _ = service.attest("action-1", actor=_local_admin())
    replay = CanaryGateService(
        registry=CapabilityRegistry([_capability(version="2")]),
        ledger=ledger,
        release_commit_provider=lambda: (_ for _ in ()).throw(
            RuntimeError("release lookup failed")
        ),
        clock=lambda: NOW,
        id_factory=lambda: "another-canary",
    )

    actual, created = replay.attest("action-1", actor=_local_admin())

    assert created is False
    assert actual == expected


@pytest.mark.parametrize(
    ("overrides", "record_success_event", "code"),
    [
        ({"risk": "R2"}, True, "ineligible_source"),
        ({"trigger": "scheduled"}, True, "ineligible_source"),
        ({"authority_mode": "supervised"}, True, "ineligible_source"),
        ({"capability_version": "2"}, True, "stale_capability"),
        ({}, False, "unverified_source"),
    ],
)
def test_attestation_rejects_ineligible_or_unverified_source(
    tmp_path, overrides, record_success_event, code
):
    service, ledger = _service(tmp_path)
    _successful_action(
        ledger,
        record_success_event=record_success_event,
        **overrides,
    )

    with pytest.raises(CanaryGateError) as denied:
        service.attest("action-1", actor=_local_admin())

    assert denied.value.code == code
    assert service.list() == []


def test_attestation_requires_succeeded_terminal_state(tmp_path):
    service, ledger = _service(tmp_path)
    ledger.create(_new_action())

    with pytest.raises(CanaryGateError) as denied:
        service.attest("action-1", actor=_local_admin())

    assert denied.value.code == "ineligible_source"


@pytest.mark.parametrize(
    "actor",
    [
        {"type": "mattermost", "id": "user-1", "username": "marc"},
        {"type": "system", "id": "worker"},
        {"type": "local", "id": "../admin"},
        {"type": "local", "id": "admin", "username": "bad\nname"},
    ],
)
def test_attestation_rejects_non_local_or_invalid_actor(tmp_path, actor):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)

    with pytest.raises(CanaryGateError) as denied:
        service.attest("action-1", actor=actor)

    assert denied.value.code == "denied_actor"
    assert service.list() == []


def test_only_one_active_attestation_can_exist_for_exact_tuple(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger, "action-1")
    _successful_action(ledger, "action-2")
    service.attest("action-1", actor=_local_admin())

    with pytest.raises(CanaryGateError) as conflict:
        service.attest("action-2", actor=_local_admin())

    assert conflict.value.code == "active_conflict"
    assert len(service.list()) == 1
    assert [event["phase"] for event in ledger.events("action-2")] == ["succeeded"]


def test_concurrent_attestation_creates_one_active_record(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    _successful_action(ledger, "action-1")
    _successful_action(ledger, "action-2")
    barrier = Barrier(2)

    def attest(action_id: str, attestation_id: str):
        service, _ = _service(
            tmp_path,
            ledger=ledger,
            attestation_id=attestation_id,
        )
        barrier.wait()
        try:
            service.attest(action_id, actor=_local_admin())
            return "created"
        except CanaryGateError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = {
            pool.submit(attest, "action-1", "canary-1"),
            pool.submit(attest, "action-2", "canary-2"),
        }
        results = {future.result() for future in outcomes}

    assert results == {"created", "active_conflict"}
    assert len(ledger.canaries()) == 1


def test_revoke_retains_evidence_and_closes_exact_gate(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())

    allowed = service.require_supervised(
        operation="container.restart",
        target="get_iplayer",
        trigger=TriggerType.SCHEDULED,
        mode=AuthorityMode.SUPERVISED,
    )
    revoked = service.revoke("canary-1", actor=_local_admin())

    assert allowed["id"] == "canary-1"
    assert revoked["revoked_by"] == _local_admin()
    assert revoked["revoked_at"] == NOW.isoformat()
    assert [event["phase"] for event in ledger.events("action-1")] == [
        "succeeded",
        "canary_attested",
        "canary_revoked",
    ]
    with pytest.raises(CanaryGateError) as denied:
        service.require_supervised(
            operation="container.restart",
            target="get_iplayer",
            trigger=TriggerType.SCHEDULED,
            mode=AuthorityMode.SUPERVISED,
        )
    assert denied.value.code == "canary_required"
    with pytest.raises(CanaryGateError) as repeated:
        service.revoke("canary-1", actor=_local_admin())
    assert repeated.value.code == "already_revoked"


def test_concurrent_revocation_is_a_single_transition(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())
    barrier = Barrier(2)

    def revoke():
        barrier.wait()
        try:
            service.revoke("canary-1", actor=_local_admin())
            return "revoked"
        except CanaryGateError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = {pool.submit(revoke), pool.submit(revoke)}
        results = {future.result() for future in outcomes}

    assert results == {"revoked", "already_revoked"}
    assert [event["phase"] for event in ledger.events("action-1")].count(
        "canary_revoked"
    ) == 1


@pytest.mark.parametrize(
    ("operation", "target", "trigger", "mode", "code"),
    [
        (
            "container.restart",
            "other",
            TriggerType.SCHEDULED,
            AuthorityMode.SUPERVISED,
            "canary_required",
        ),
        (
            "container.restart",
            "get_iplayer",
            TriggerType.INTERACTIVE,
            AuthorityMode.SUPERVISED,
            "scheduled_only",
        ),
        (
            "container.restart",
            "get_iplayer",
            TriggerType.EVENT,
            AuthorityMode.SUPERVISED,
            "scheduled_only",
        ),
        (
            "container.restart",
            "get_iplayer",
            TriggerType.SCHEDULED,
            AuthorityMode.AUTONOMOUS,
            "autonomous_unavailable",
        ),
    ],
)
def test_gate_is_exact_and_never_grants_autonomous_authority(
    tmp_path, operation, target, trigger, mode, code
):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())

    with pytest.raises(CanaryGateError) as denied:
        service.require_supervised(
            operation=operation,
            target=target,
            trigger=trigger,
            mode=mode,
        )

    assert denied.value.code == code


def test_capability_change_invalidates_existing_evidence(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())
    changed, _ = _service(tmp_path, capability=_capability(version="2"))

    with pytest.raises(CanaryGateError) as stale:
        changed.require_supervised(
            operation="container.restart",
            target="get_iplayer",
            trigger=TriggerType.SCHEDULED,
            mode=AuthorityMode.SUPERVISED,
        )

    assert stale.value.code == "canary_required"
    snapshot = changed.snapshot()
    assert snapshot["canaries"][0]["status"] == "stale"
    assert snapshot["gate"] == {
        "supervised": "canary_required",
        "autonomous": "unavailable",
        "eligible_count": 0,
    }


def test_snapshot_distinguishes_eligible_and_revoked_evidence(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())

    assert service.snapshot()["canaries"][0]["status"] == "eligible"
    assert service.snapshot()["gate"]["eligible_count"] == 1

    service.revoke("canary-1", actor=_local_admin())

    assert service.snapshot()["canaries"][0]["status"] == "revoked"
    assert service.snapshot()["gate"]["eligible_count"] == 0


def test_release_commit_reader_accepts_only_secure_owned_regular_file(tmp_path):
    release = tmp_path / ".release"
    release.write_text(f"{RELEASE_COMMIT}\n")
    release.chmod(0o644)
    owner_ids = frozenset({os.geteuid()})

    assert (
        read_agent_release_commit(release, allowed_owner_ids=owner_ids)
        == RELEASE_COMMIT
    )

    release.chmod(0o664)
    with pytest.raises(RuntimeError):
        read_agent_release_commit(release, allowed_owner_ids=owner_ids)


def test_release_commit_reader_rejects_links_wrong_owner_and_oversized_data(tmp_path):
    release = tmp_path / ".release"
    release.write_text(f"{RELEASE_COMMIT}\n")
    link = tmp_path / "release-link"
    link.symlink_to(release)

    with pytest.raises(RuntimeError):
        read_agent_release_commit(
            link,
            allowed_owner_ids=frozenset({os.geteuid()}),
        )
    with pytest.raises(RuntimeError):
        read_agent_release_commit(release, allowed_owner_ids=frozenset())

    release.write_text("a" * 66)
    with pytest.raises(RuntimeError):
        read_agent_release_commit(
            release,
            allowed_owner_ids=frozenset({os.geteuid()}),
        )

    fifo = tmp_path / "release-fifo"
    os.mkfifo(fifo)
    with pytest.raises(RuntimeError):
        read_agent_release_commit(
            fifo,
            allowed_owner_ids=frozenset({os.geteuid()}),
        )


def test_attestation_and_audit_event_are_atomic(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    with sqlite3.connect(tmp_path / "actions.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_canary_event
            BEFORE INSERT ON action_events
            WHEN NEW.phase = 'canary_attested'
            BEGIN
                SELECT RAISE(ABORT, 'simulated audit failure');
            END
            """
        )

    with pytest.raises(CanaryGateError) as failed:
        service.attest("action-1", actor=_local_admin())

    assert failed.value.code == "store_failure"
    assert service.list() == []
    assert [event["phase"] for event in ledger.events("action-1")] == ["succeeded"]


def test_revocation_and_audit_event_are_atomic(tmp_path):
    service, ledger = _service(tmp_path)
    _successful_action(ledger)
    service.attest("action-1", actor=_local_admin())
    with sqlite3.connect(tmp_path / "actions.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_canary_revoke_event
            BEFORE INSERT ON action_events
            WHEN NEW.phase = 'canary_revoked'
            BEGIN
                SELECT RAISE(ABORT, 'simulated audit failure');
            END
            """
        )

    with pytest.raises(CanaryGateError) as failed:
        service.revoke("canary-1", actor=_local_admin())

    assert failed.value.code == "store_failure"
    assert service.list()[0]["revoked_at"] is None
    assert [event["phase"] for event in ledger.events("action-1")] == [
        "succeeded",
        "canary_attested",
    ]
