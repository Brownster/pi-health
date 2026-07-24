from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from agent_actions.ledger import ActionLedger, ActionState, NewAction
from agent_supervision.reporting import (
    IncidentDeliveryError,
    MattermostIncidentDelivery,
    load_delivery_config,
    load_delivery_token,
    render_incident_message,
)
from agent_supervision.runtime import SupervisedRepairRuntime
from agent_supervision.service import (
    SupervisionService,
    SupervisionStore,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)


def _schedule():
    return {
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


def _owner():
    return {"type": "local", "id": "admin", "username": "marc"}


def _new_action(action_id: str, now: datetime) -> NewAction:
    return NewAction(
        action_id=action_id,
        idempotency_key=f"runtime-{action_id}",
        operation="container.restart",
        capability_version="1",
        target="get_iplayer",
        risk="R1",
        trigger="interactive",
        authority_mode="supervised",
        params={"name": "get_iplayer"},
        evidence_ids=["assessment-evidence"],
        payload_hash="a" * 64,
        reason="Confirmed model-free health failure.",
        impact="Restart get_iplayer.",
        precondition_hash="b" * 64,
        actor_type="system",
        actor_id="limeops-supervisor",
        actor_username=None,
        state=ActionState.AUTHORISED,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=2)).isoformat(),
    )


class FakeScheduler:
    running = False

    def __init__(self):
        self.jobs = []

    def add_job(self, function, trigger, **values):
        self.jobs.append((function, trigger, values))

    def start(self):
        self.running = True


class FakeAuthorizer:
    def __init__(self, ledger: ActionLedger, now):
        self.ledger = ledger
        self.now = now
        self.calls = []

    def authorize(self, schedule_id, incident_id):
        self.calls.append((schedule_id, incident_id))
        try:
            action = self.ledger.get("action-supervised")
            created = False
        except Exception:
            action, created = self.ledger.create(
                _new_action("action-supervised", self.now())
            )
        return {
            "action": action.public_dict(),
            "authorization": {"incident_id": incident_id},
        }, created


def _runtime(tmp_path):
    current = [NOW]
    store = SupervisionStore(tmp_path / "supervision.sqlite3")
    service = SupervisionService(
        store=store,
        clock=lambda: current[0],
        id_factory=lambda: "schedule-1",
    )
    service.create(_schedule(), owner=_owner())
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    authorizer = FakeAuthorizer(ledger, lambda: current[0])
    diagnostics = []

    def diagnostic(operation, params, actor):
        diagnostics.append((operation, dict(params), dict(actor)))
        return {
            "ok": True,
            "data": {
                "name": "get_iplayer",
                "status": "exited",
                "health": None,
            },
            "error": None,
            "audit_id": f"audit-{len(diagnostics)}",
        }

    deliveries = []

    def deliver(context):
        deliveries.append(context)
        return f"post-{len(deliveries)}"

    runtime = SupervisedRepairRuntime(
        store=store,
        service=service,
        authorizer=authorizer,
        ledger=ledger,
        scheduler=FakeScheduler(),
        diagnostic=diagnostic,
        deliver=deliver,
        clock=lambda: current[0],
    )
    return runtime, store, ledger, authorizer, current, diagnostics, deliveries


def test_two_buckets_create_one_action_and_one_thread(tmp_path):
    (
        runtime,
        store,
        _ledger,
        authorizer,
        current,
        diagnostics,
        deliveries,
    ) = _runtime(tmp_path)

    assert runtime.run_cycle(at=current[0]) == {"assessed": 1, "skipped": 0}
    assert store.list_incidents() == []

    current[0] += timedelta(minutes=10)
    assert runtime.run_cycle(at=current[0]) == {"assessed": 1, "skipped": 0}

    incident = store.list_incidents()[0]
    transitions = store.list_transitions(incident["id"])
    assert incident["state"] == "action_authorized"
    assert incident["last_action_id"] == "action-supervised"
    assert incident["thread_id"] == "post-1"
    assert [item["type"] for item in transitions] == [
        "fault_confirmed",
        "action_authorized",
    ]
    assert [item["delivery"]["message_kind"] for item in deliveries] == [
        "root",
        "reply",
    ]
    assert deliveries[1]["delivery"]["incident_thread_id"] == "post-1"
    assert len(authorizer.calls) == 1
    assert len(diagnostics) == 2
    assert store.incomplete_occurrences() == []

    runtime.run_cycle(at=current[0])

    assert len(authorizer.calls) == 1
    assert len(diagnostics) == 2
    assert len(deliveries) == 2


def test_reconcile_reports_execution_verification_and_recovery_once(tmp_path):
    runtime, store, ledger, _authorizer, current, _diagnostics, deliveries = (
        _runtime(tmp_path)
    )
    runtime.run_cycle(at=current[0])
    current[0] += timedelta(minutes=10)
    runtime.run_cycle(at=current[0])

    ledger.claim_execution(
        "action-supervised",
        payload_hash="a" * 64,
        approval_required=False,
        claimed_at=current[0].isoformat(),
    )
    runtime.run_cycle(at=current[0])
    ledger.begin_verification("action-supervised")
    runtime.run_cycle(at=current[0])
    ledger.finish_execution(
        "action-supervised",
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    runtime.run_cycle(at=current[0])
    runtime.run_cycle(at=current[0])

    incident = store.list_incidents()[0]
    assert incident["state"] == "recovered"
    assert incident["terminal_code"] == "verified"
    assert incident["resolved_at"] == current[0].isoformat()
    assert [item["type"] for item in store.list_transitions(incident["id"])] == [
        "fault_confirmed",
        "action_authorized",
        "action_started",
        "verification_started",
        "recovered_after_action",
    ]
    assert len(deliveries) == 5


def test_disable_cancellation_is_blocked_without_creating_a_demotion(tmp_path):
    runtime, store, ledger, _authorizer, current, _diagnostics, _deliveries = (
        _runtime(tmp_path)
    )
    runtime.run_cycle(at=current[0])
    current[0] += timedelta(minutes=10)
    runtime.run_cycle(at=current[0])

    ledger.cancel_pending_supervised_actions(
        cancelled_at=current[0].isoformat()
    )
    runtime.run_cycle(at=current[0])

    incident = store.list_incidents()[0]
    assert incident["state"] == "supervision_blocked"
    assert incident["terminal_code"] == "integration_disabled"
    assert store.list_transitions(incident["id"])[-1]["type"] == (
        "supervision_blocked"
    )
    assert ledger.active_demotion(
        operation="container.restart", target="get_iplayer"
    ) is None


def test_restart_marks_uncertain_delivery_without_reposting(tmp_path):
    runtime, store, _ledger, _authorizer, current, _diagnostics, deliveries = (
        _runtime(tmp_path)
    )
    runtime.run_cycle(at=current[0])
    current[0] += timedelta(minutes=10)
    occurrence, _created = store.begin_occurrence(
        schedule_id="schedule-1",
        assessed_for=current[0].isoformat(),
        started_at=current[0].isoformat(),
    )
    runtime._process_occurrence(occurrence)
    pending = store.pending_deliveries()
    store.claim_delivery(pending[0]["id"], at=current[0].isoformat())

    runtime.recover()

    with sqlite3.connect(store.path) as connection:
        states = [
            row[0]
            for row in connection.execute(
                """
                SELECT state FROM supervision_deliveries
                ORDER BY created_at, rowid
                """
            )
        ]
    assert states == ["delivery_unknown", "pending"]
    assert deliveries == []


def test_runtime_bounds_overlap_and_scheduler_contract(tmp_path):
    runtime, _store, _ledger, _authorizer, _current, _diagnostics, _deliveries = (
        _runtime(tmp_path)
    )
    runtime._cycle_lock.acquire()
    try:
        assert runtime.run_cycle() == {"assessed": 0, "skipped": 1}
    finally:
        runtime._cycle_lock.release()

    runtime.init_scheduler()

    _function, trigger, values = runtime._scheduler.jobs[0]
    assert trigger == "interval"
    assert values["id"] == "supervised-repair:cycle"
    assert values["seconds"] == 60
    assert values["max_instances"] == 1


def _delivery_context(kind="root", transition_type="fault_confirmed"):
    return {
        "delivery": {
            "message_kind": kind,
            "incident_thread_id": "root-1" if kind == "reply" else None,
        },
        "incident": {
            "id": "incident-1",
            "operation": "container.restart",
            "target": "get_iplayer",
        },
        "transition": {
            "type": transition_type,
            "details": {"code": "window_closed"},
        },
        "schedule": {
            "name": "Recover get_iplayer",
            "service_priority": "normal",
        },
    }


def test_incident_delivery_uses_root_then_thread_and_redacts(tmp_path):
    config = tmp_path / "delivery.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "site_url": "https://mm.example",
                "channel_id": "channel-1",
            }
        )
    )
    secrets = tmp_path / "mattermost.env"
    secrets.write_text("MATTERMOST_BOT_TOKEN=secret-token\n")
    secrets.chmod(0o640)
    calls = []

    class Api:
        def use_token(self, token):
            assert token == "secret-token"

        def post_message(self, **values):
            calls.append(values)
            return f"post-{len(calls)}"

    delivery = MattermostIncidentDelivery(
        config_path=config,
        secrets_path=secrets,
        api_factory=lambda site_url: (
            calls.append({"site_url": site_url}) or Api()
        ),
    )

    assert delivery(_delivery_context()) == "post-2"
    assert delivery(_delivery_context("reply", "window_deferred")) == "post-3"
    assert calls[1]["root_id"] == ""
    assert calls[2]["root_id"] == "root-1"
    assert "secret-token" not in calls[1]["message"]
    assert "window_closed" in calls[2]["message"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema_version": "1",
            "site_url": "https://user:pass@mm.example",
            "channel_id": "channel-1",
        },
        {
            "schema_version": "1",
            "site_url": "https://mm.example",
            "channel_id": "../channel",
        },
    ],
)
def test_delivery_config_and_secret_fail_closed(tmp_path, payload):
    config = tmp_path / "delivery.json"
    config.write_text(json.dumps(payload))
    secrets = tmp_path / "mattermost.env"
    secrets.write_text("MATTERMOST_BOT_TOKEN=\n")

    with pytest.raises(IncidentDeliveryError):
        load_delivery_config(config)
    with pytest.raises(IncidentDeliveryError):
        load_delivery_token(secrets)


def test_delivery_secret_rejects_world_readable_projection(tmp_path):
    secrets = tmp_path / "mattermost.env"
    secrets.write_text("MATTERMOST_BOT_TOKEN=secret-token\n")
    secrets.chmod(0o644)

    with pytest.raises(IncidentDeliveryError):
        load_delivery_token(secrets)


def test_incident_renderer_rejects_unregistered_transition():
    context = _delivery_context(transition_type="invented")

    with pytest.raises(IncidentDeliveryError):
        render_incident_message(context)
