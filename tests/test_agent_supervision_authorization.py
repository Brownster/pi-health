from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from agent_actions.actuator import (
    ActionActuator,
    ActionActuatorError,
    ExecutionSpec,
)
from agent_actions.canary import CanaryGateService
from agent_actions.capability import (
    AuthorityMode,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
    canonical_hash,
)
from agent_actions.ledger import (
    ActionLedger,
    ActionLedgerError,
    ActionState,
    NewAction,
)
from agent_actions.policy import ActionPolicy
from agent_actions.worker import run_once
from agent_supervision.authorization import (
    SupervisionAuthorizationError,
    SupervisionAuthorizer,
    maintenance_window,
)
from agent_supervision.service import SupervisionService, SupervisionStore


NOW = datetime(2026, 7, 23, 10, 5, tzinfo=timezone.utc)
RELEASE_COMMIT = "a" * 40


def _schedule(**overrides):
    value = {
        "name": "Recover get_iplayer",
        "enabled": True,
        "operation": "container.restart",
        "params": {"name": "get_iplayer"},
        "service_priority": "normal",
        "window": {
            "cron": "0 10 * * *",
            "timezone": "UTC",
            "duration_minutes": 60,
        },
        "delivery": {
            "channel": "mattermost-alerts",
            "mode": "threaded",
        },
    }
    value.update(overrides)
    return value


def _owner():
    return {"type": "local", "id": "admin", "username": "marc"}


def _status(status, audit_id):
    return {
        "ok": True,
        "data": {
            "name": "get_iplayer",
            "status": status,
            "health": None,
        },
        "error": None,
        "audit_id": audit_id,
    }


def _capability():
    def normalize(params):
        if dict(params) != {"name": "get_iplayer"}:
            raise ValueError("unexpected target")
        return {"name": "get_iplayer"}

    return CapabilitySpec(
        operation="container.restart",
        version="1",
        risk=RiskClass.REVERSIBLE,
        eligible_modes=(
            AuthorityMode.PROPOSE,
            AuthorityMode.APPROVAL,
            AuthorityMode.SUPERVISED,
        ),
        normalize_params=normalize,
        select_target=lambda params: params["name"],
        read_precondition=lambda params: {
            "name": params["name"],
            "status": "exited",
            "started_at": "before",
        },
        render_impact=lambda params: f"Restart container {params['name']}",
    )


def _policy():
    return ActionPolicy.from_mapping(
        {
            "schema_version": "1",
            "kill_switch": False,
            "defaults": {"proposal_ttl_seconds": 900},
            "operations": {
                "container.restart": {
                    "enabled": True,
                    "approvers": ["local:admin"],
                    "targets": {
                        "get_iplayer": {
                            "interactive": "approval",
                            "scheduled": "supervised",
                            "event": "observe",
                        }
                    },
                }
            },
        }
    )


def _canary(ledger, registry):
    source = NewAction(
        action_id="action-canary",
        idempotency_key="canary-source-action",
        operation="container.restart",
        capability_version="1",
        target="get_iplayer",
        risk="R1",
        trigger="interactive",
        authority_mode="approval",
        params={"name": "get_iplayer"},
        evidence_ids=["audit-canary"],
        payload_hash="b" * 64,
        reason="Approval-bound release repair.",
        impact="Restart container get_iplayer",
        precondition_hash="c" * 64,
        actor_type="local",
        actor_id="admin",
        actor_username="marc",
        state=ActionState.AWAITING_APPROVAL,
        created_at=(NOW - timedelta(hours=1)).isoformat(),
        expires_at=(NOW + timedelta(minutes=15)).isoformat(),
    )
    ledger.create(source)
    ledger.approve(
        source.action_id,
        payload_hash=source.payload_hash,
        approver_type="local",
        approver_id="admin",
        approver_username="marc",
        approved_at=(NOW - timedelta(minutes=59)).isoformat(),
    )
    ledger.claim_execution(
        source.action_id,
        payload_hash=source.payload_hash,
        approval_required=True,
        claimed_at=(NOW - timedelta(minutes=58)).isoformat(),
    )
    ledger.begin_verification(source.action_id)
    ledger.finish_execution(
        source.action_id,
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    ledger.record_event(
        source.action_id,
        phase="succeeded",
        created_at=(NOW - timedelta(minutes=57)).isoformat(),
        details={
            "action_audit_id": "audit-canary",
            "after": {
                "name": "get_iplayer",
                "status": "running",
                "started_at": "canary",
            },
        },
    )
    gate = CanaryGateService(
        registry=registry,
        ledger=ledger,
        release_commit_provider=lambda: RELEASE_COMMIT,
        clock=lambda: NOW - timedelta(minutes=56),
        id_factory=lambda: "canary-1",
    )
    gate.attest(
        source.action_id,
        actor={"type": "local", "id": "admin", "username": "marc"},
    )
    return gate


def _setup(tmp_path, *, clock=None, precondition_provider=None):
    store = SupervisionStore(tmp_path / "supervision.sqlite3")
    schedules = SupervisionService(
        store=store,
        clock=lambda: NOW,
        id_factory=lambda: "schedule-1",
    )
    schedules.create(_schedule(), owner=_owner())
    schedules.assess(
        "schedule-1",
        _status("exited", "audit-assessment-1"),
        assessed_at=NOW - timedelta(minutes=15),
    )
    opened = schedules.assess(
        "schedule-1",
        _status("exited", "audit-assessment-2"),
        assessed_at=NOW - timedelta(minutes=5),
    )
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    registry = CapabilityRegistry([_capability()])
    gate = _canary(ledger, registry)
    authorizer = SupervisionAuthorizer(
        store=store,
        ledger=ledger,
        registry=registry,
        policy_provider=_policy,
        canary_gate=gate,
        clock=clock or (lambda: NOW),
        precondition_provider=precondition_provider,
        id_factory=lambda: "action-supervised",
    )
    return (
        authorizer,
        schedules,
        ledger,
        opened["incident"]["id"],
        registry,
        gate,
    )


def test_maintenance_window_has_exact_start_and_deadline():
    configured = {
        "id": "schedule-1",
        "revision": 1,
        "window": {
            "cron": "0 10 * * *",
            "timezone": "UTC",
            "duration_minutes": 60,
        },
    }

    at_start = maintenance_window(
        configured, datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
    )
    at_end = maintenance_window(
        configured, datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc)
    )

    assert at_start["start"] == datetime(
        2026, 7, 23, 10, 0, tzinfo=timezone.utc
    )
    assert at_start["deadline"] == datetime(
        2026, 7, 23, 11, 0, tzinfo=timezone.utc
    )
    assert at_end is None


def test_maintenance_window_uses_configured_timezone_across_summer_offset():
    configured = {
        "id": "schedule-1",
        "revision": 1,
        "window": {
            "cron": "0 2 * * *",
            "timezone": "Europe/London",
            "duration_minutes": 60,
        },
    }

    summer = maintenance_window(
        configured, datetime(2026, 7, 23, 1, 30, tzinfo=timezone.utc)
    )
    winter = maintenance_window(
        configured, datetime(2026, 12, 23, 2, 30, tzinfo=timezone.utc)
    )

    assert summer["start"] == datetime(
        2026, 7, 23, 1, 0, tzinfo=timezone.utc
    )
    assert winter["start"] == datetime(
        2026, 12, 23, 2, 0, tzinfo=timezone.utc
    )


def test_authorization_atomically_creates_action_lease_and_budget(tmp_path):
    authorizer, schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )

    result, created = authorizer.authorize("schedule-1", incident_id)

    assert created is True
    assert result["action"]["state"] == "authorised"
    assert result["action"]["authority_mode"] == "supervised"
    assert result["action"]["actor"] == {
        "type": "system",
        "id": "limeops-supervisor",
        "username": None,
    }
    authorization = ledger.supervision_authorization("action-supervised")
    assert authorization is not None
    assert authorization.incident_id == incident_id
    assert authorization.release_commit == RELEASE_COMMIT
    assert ledger.active_target_lease(
        operation="container.restart", target="get_iplayer"
    ).action_id == "action-supervised"
    budget = schedules.store.budget_status(
        "schedule-1",
        window_key=authorization.window_key,
        at=NOW,
    )
    assert budget["rolling_24h"]["used"] == 1
    assert budget["window"]["used"] == 1


def test_authorization_uses_trusted_precondition_instead_of_public_status(
    tmp_path,
):
    trusted_hash = "f" * 64
    authorizer, _schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path,
        precondition_provider=lambda operation, params: {
            "operation": operation,
            "capability_version": "1",
            "target": params["name"],
            "params": dict(params),
            "precondition_hash": trusted_hash,
        },
    )

    result, created = authorizer.authorize("schedule-1", incident_id)

    assert created is True
    assert result["action"]["id"] == "action-supervised"
    assert ledger.get("action-supervised").precondition_hash == trusted_hash


def test_authorization_occurrence_replay_does_not_duplicate_charge(tmp_path):
    authorizer, schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )

    first, _ = authorizer.authorize("schedule-1", incident_id)
    repeated, created = authorizer.authorize("schedule-1", incident_id)

    assert created is False
    assert repeated == first
    authorization = ledger.supervision_authorization("action-supervised")
    budget = schedules.store.budget_status(
        "schedule-1",
        window_key=authorization.window_key,
        at=NOW,
    )
    assert budget["rolling_24h"]["used"] == 1


def test_active_interactive_action_blocks_without_charging_budget(tmp_path):
    authorizer, schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    ledger.create(
        NewAction(
            action_id="action-interactive",
            idempotency_key="interactive-repair-action",
            operation="container.restart",
            capability_version="1",
            target="get_iplayer",
            risk="R1",
            trigger="interactive",
            authority_mode="approval",
            params={"name": "get_iplayer"},
            evidence_ids=[],
            payload_hash="d" * 64,
            reason="Administrator requested repair.",
            impact="Restart container get_iplayer",
            precondition_hash="e" * 64,
            actor_type="local",
            actor_id="admin",
            actor_username="marc",
            state=ActionState.AWAITING_APPROVAL,
            created_at=NOW.isoformat(),
            expires_at=(NOW + timedelta(minutes=15)).isoformat(),
        )
    )

    with pytest.raises(SupervisionAuthorizationError) as busy:
        authorizer.authorize("schedule-1", incident_id)

    assert busy.value.code == "target_busy"
    assert ledger.supervision_authorization("action-supervised") is None
    assert schedules.store.budget_status(
        "schedule-1", window_key="window-unused", at=NOW
    )["rolling_24h"]["used"] == 0


def test_authorization_requires_fresh_in_window_failure(tmp_path):
    moment = NOW + timedelta(hours=1)
    (
        authorizer,
        schedules,
        ledger,
        incident_id,
        _registry,
        _gate,
    ) = _setup(tmp_path, clock=lambda: moment)
    schedules.assess(
        "schedule-1",
        _status("exited", "audit-assessment-3"),
        assessed_at=moment - timedelta(minutes=15),
    )
    schedules.assess(
        "schedule-1",
        _status("exited", "audit-assessment-4"),
        assessed_at=moment - timedelta(minutes=5),
    )

    with pytest.raises(SupervisionAuthorizationError) as closed:
        authorizer.authorize("schedule-1", incident_id)

    assert closed.value.code == "window_closed"
    assert [action.action_id for action in ledger.list()] == ["action-canary"]


def test_authorization_claim_consumes_once_and_holds_global_slot(tmp_path):
    authorizer, _schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    action = result["action"]

    claimed = ledger.claim_execution(
        action["id"],
        payload_hash=action["payload_hash"],
        approval_required=False,
        claimed_at=(NOW + timedelta(seconds=30)).isoformat(),
    )

    assert claimed.state == ActionState.EXECUTING
    assert ledger.has_supervised_execution_slot(action["id"]) is True
    assert ledger.supervision_authorization(action["id"]).consumed_at == (
        NOW + timedelta(seconds=30)
    ).isoformat()
    ledger.finish_execution(
        action["id"],
        state=ActionState.EXECUTION_FAILED,
        terminal_code="executor_failed",
    )
    assert ledger.has_supervised_execution_slot(action["id"]) is False


def test_global_slot_blocks_a_second_supervised_target(tmp_path):
    authorizer, _schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    first, _ = authorizer.authorize("schedule-1", incident_id)
    second = NewAction(
        action_id="action-second-target",
        idempotency_key="second-target-occurrence",
        operation="container.restart",
        capability_version="1",
        target="sonarr",
        risk="R1",
        trigger="scheduled",
        authority_mode="supervised",
        params={"name": "sonarr"},
        evidence_ids=["assessment-second", "audit-second"],
        payload_hash="d" * 64,
        reason="Second supervised target failed.",
        impact="Restart container sonarr",
        precondition_hash="e" * 64,
        actor_type="system",
        actor_id="limeops-supervisor",
        actor_username=None,
        state=ActionState.AUTHORISED,
        created_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(seconds=120)).isoformat(),
    )
    ledger.create(second)
    first_authorization = ledger.supervision_authorization(
        first["action"]["id"]
    )
    with sqlite3.connect(tmp_path / "actions.sqlite3") as connection:
        connection.execute(
            """
            INSERT INTO supervision_authorizations (
                authorization_id, occurrence_key, action_id, schedule_id,
                schedule_revision, incident_id, assessment_id, assessed_for,
                operation, target, capability_version, release_commit,
                window_key, window_start, window_deadline, authorized_at,
                expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "authorization-second",
                "occurrence-second",
                second.action_id,
                "schedule-second",
                1,
                "incident-second",
                "assessment-second",
                first_authorization.assessed_for,
                second.operation,
                second.target,
                second.capability_version,
                RELEASE_COMMIT,
                "window-second",
                first_authorization.window_start,
                first_authorization.window_deadline,
                NOW.isoformat(),
                second.expires_at,
            ),
        )
    ledger.claim_execution(
        first["action"]["id"],
        payload_hash=first["action"]["payload_hash"],
        approval_required=False,
        claimed_at=(NOW + timedelta(seconds=30)).isoformat(),
    )

    with pytest.raises(ActionLedgerError) as busy:
        ledger.claim_execution(
            second.action_id,
            payload_hash=second.payload_hash,
            approval_required=False,
            claimed_at=(NOW + timedelta(seconds=30)).isoformat(),
        )

    assert busy.value.code == "supervised_busy"
    assert ledger.get(second.action_id).state == ActionState.AUTHORISED


def test_actuator_independently_accepts_bound_authorization(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    calls = []
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda params: calls.append(dict(params))
        or {"status": "restarted"},
        verify=lambda params, before: (
            True,
            {
                "name": params["name"],
                "status": "running",
                "started_at": "after",
            },
        ),
        no_rollback_reason="No safe rollback",
    )
    actuator = ActionActuator(
        registry=registry,
        executors={"container.restart": executor},
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    completed = actuator.execute(
        result["action"]["id"], audit_id="audit-supervised-action"
    )

    assert completed["state"] == "succeeded"
    assert completed["approval_consumed"] is False
    assert calls == [{"name": "get_iplayer"}]
    assert ledger.has_supervised_execution_slot(result["action"]["id"]) is False


def test_trusted_fingerprint_matches_actuator_private_status_reader(tmp_path):
    private_before = {
        "name": "get_iplayer",
        "id": "container-id",
        "status": "exited",
        "health": "",
        "started_at": "2026-07-23T09:00:00Z",
        "image_id": "sha256:image-id",
    }
    trusted_hash = canonical_hash(private_before)
    authorizer, _schedules, ledger, incident_id, _registry, gate = _setup(
        tmp_path,
        precondition_provider=lambda operation, params: {
            "operation": operation,
            "capability_version": "1",
            "target": params["name"],
            "params": dict(params),
            "precondition_hash": trusted_hash,
        },
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    base = _capability()
    actuator_registry = CapabilityRegistry(
        [
            CapabilitySpec(
                operation=base.operation,
                version=base.version,
                risk=base.risk,
                eligible_modes=base.eligible_modes,
                normalize_params=base.normalize_params,
                select_target=base.select_target,
                read_precondition=lambda _params: private_before,
                render_impact=base.render_impact,
            )
        ]
    )
    calls = []
    actuator = ActionActuator(
        registry=actuator_registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=lambda params: calls.append(dict(params))
                or {"status": "restarted"},
                verify=lambda _params, _before: (
                    True,
                    {"status": "running"},
                ),
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    completed = actuator.execute(
        result["action"]["id"], audit_id="audit-private-fingerprint"
    )

    assert completed["state"] == "succeeded"
    assert calls == [{"name": "get_iplayer"}]


def test_disablement_atomically_cancels_queued_supervised_action(tmp_path):
    authorizer, _schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    action_id = result["action"]["id"]

    cancelled = ledger.cancel_pending_supervised_actions(
        cancelled_at=(NOW + timedelta(seconds=30)).isoformat()
    )

    assert [record.action_id for record in cancelled] == [action_id]
    assert ledger.get(action_id).state == ActionState.CANCELLED
    assert ledger.get(action_id).terminal_code == "integration_disabled"
    authorization = ledger.supervision_authorization(action_id)
    assert authorization.invalidated_at == (
        NOW + timedelta(seconds=30)
    ).isoformat()
    assert authorization.invalidation_code == "integration_disabled"
    assert ledger.active_target_lease(
        operation="container.restart", target="get_iplayer"
    ) is None
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ) is None
    assert ledger.cancel_pending_supervised_actions(
        cancelled_at=(NOW + timedelta(seconds=31)).isoformat()
    ) == []


def test_actuator_rechecks_agent_lifecycle_before_supervised_claim(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    calls = []
    actuator = ActionActuator(
        registry=registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=lambda params: calls.append(dict(params)),
                verify=lambda _params, _before: (True, {}),
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        supervision_enabled=lambda: False,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    with pytest.raises(ActionActuatorError) as disabled:
        actuator.execute(
            result["action"]["id"], audit_id="audit-supervised-disabled"
        )

    assert disabled.value.code == "supervision_disabled"
    assert calls == []
    assert ledger.get(result["action"]["id"]).state == ActionState.CANCELLED


@pytest.mark.parametrize(
    ("failure", "expected_state", "expected_cause"),
    [
        ("execution", ActionState.EXECUTION_FAILED, "execution_failed"),
        (
            "verification",
            ActionState.VERIFICATION_FAILED,
            "verification_failed",
        ),
    ],
)
def test_supervised_failure_atomically_demotes_target(
    tmp_path, failure, expected_state, expected_cause
):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    executor = ExecutionSpec(
        operation="container.restart",
        version="1",
        execute=lambda _params: (
            {"error": "private"} if failure == "execution" else {"ok": True}
        ),
        verify=lambda _params, _before: (False, {"status": "exited"}),
        no_rollback_reason="No safe rollback",
    )
    actuator = ActionActuator(
        registry=registry,
        executors={"container.restart": executor},
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    completed = actuator.execute(
        result["action"]["id"], audit_id="audit-supervised-action"
    )

    assert ledger.get(result["action"]["id"]).state == expected_state
    assert completed["state"] == expected_state.value
    demotion = ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    )
    assert demotion.cause == expected_cause
    assert demotion.source_action_id == result["action"]["id"]
    assert demotion.release_commit == RELEASE_COMMIT
    assert ledger.has_supervised_execution_slot(result["action"]["id"]) is False


def test_uncertain_verification_exception_demotes_target(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)

    def fail_verification(_params, _before):
        raise RuntimeError("private host detail")

    actuator = ActionActuator(
        registry=registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=lambda _params: {"ok": True},
                verify=fail_verification,
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    with pytest.raises(ActionActuatorError) as failed:
        actuator.execute(
            result["action"]["id"], audit_id="audit-supervised-action"
        )

    assert failed.value.code == "execution_failure"
    assert "private" not in str(failed.value)
    assert ledger.get(result["action"]["id"]).state == (
        ActionState.VERIFICATION_FAILED
    )
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ).cause == "verification_uncertain"


def test_expired_authorization_demotes_before_mutation(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    actuator = ActionActuator(
        registry=registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=lambda _params: pytest.fail("expired action executed"),
                verify=lambda _params, _before: (True, {}),
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=121),
    )

    with pytest.raises(ActionActuatorError) as expired:
        actuator.execute(
            result["action"]["id"], audit_id="audit-supervised-action"
        )

    assert expired.value.code == "expired"
    assert ledger.get(result["action"]["id"]).state == ActionState.EXPIRED
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ).cause == "authorisation_expired"


def test_execution_deadline_demotes_after_mutation(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)
    moment = {"now": NOW + timedelta(seconds=30)}

    def execute(_params):
        moment["now"] = NOW + timedelta(seconds=121)
        return {"ok": True}

    actuator = ActionActuator(
        registry=registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=execute,
                verify=lambda _params, _before: pytest.fail(
                    "late action verified"
                ),
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: moment["now"],
    )

    completed = actuator.execute(
        result["action"]["id"], audit_id="audit-supervised-action"
    )

    assert completed["state"] == "execution_failed"
    assert completed["terminal_code"] == "deadline_exceeded"
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ).cause == "deadline_exceeded"


def test_audit_failure_closes_action_and_demotes(tmp_path):
    authorizer, _schedules, ledger, incident_id, registry, gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)

    def reject_event(*_args, **_kwargs):
        raise ActionLedgerError("store_failure", "private")

    ledger.record_event = reject_event
    actuator = ActionActuator(
        registry=registry,
        executors={
            "container.restart": ExecutionSpec(
                operation="container.restart",
                version="1",
                execute=lambda _params: pytest.fail(
                    "unaudited action executed"
                ),
                verify=lambda _params, _before: (True, {}),
                no_rollback_reason="No safe rollback",
            )
        },
        policy_provider=_policy,
        ledger=ledger,
        canary_gate=gate,
        clock=lambda: NOW + timedelta(seconds=30),
    )

    with pytest.raises(ActionActuatorError) as failed:
        actuator.execute(
            result["action"]["id"], audit_id="audit-supervised-action"
        )

    assert failed.value.code == "audit_failure"
    assert "private" not in str(failed.value)
    assert ledger.get(result["action"]["id"]).state == (
        ActionState.EXECUTION_FAILED
    )
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ).cause == "audit_failure"


@pytest.mark.parametrize(
    ("broker_code", "expected_cause"),
    [
        ("audit_failure", "audit_failure"),
        ("denied_operation", "identity_failure"),
    ],
)
def test_worker_demotes_pre_execution_broker_integrity_failure(
    tmp_path, broker_code, expected_cause
):
    authorizer, _schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    result, _ = authorizer.authorize("schedule-1", incident_id)

    class Client:
        def request(self, _operation, _params, _actor):
            return {
                "ok": False,
                "data": None,
                "error": {"code": broker_code, "message": "private"},
            }

    worked = run_once(
        ledger,
        Client(),
        clock=lambda: NOW + timedelta(seconds=30),
    )

    assert worked is True
    action = ledger.get(result["action"]["id"])
    assert action.state == ActionState.ESCALATION_REQUIRED
    assert action.terminal_code == expected_cause
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ).cause == expected_cause


def test_concurrent_authorization_creates_one_action_and_charge(tmp_path):
    authorizer, schedules, ledger, incident_id, _registry, _gate = _setup(
        tmp_path
    )
    barrier = Barrier(2)

    def authorize():
        barrier.wait()
        return authorizer.authorize("schedule-1", incident_id)[1]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: authorize(), range(2)))

    assert sorted(results) == [False, True]
    assert len(ledger.list()) == 2  # release canary source plus one repair
    authorization = ledger.supervision_authorization("action-supervised")
    budget = schedules.store.budget_status(
        "schedule-1",
        window_key=authorization.window_key,
        at=NOW,
    )
    assert budget["rolling_24h"]["used"] == 1
