from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from agent_supervision import (
    ACTION_DEADLINE_SECONDS,
    ASSESSMENT_INTERVAL_SECONDS,
    CONSECUTIVE_FAILURE_THRESHOLD,
    MAX_ACTIONS_PER_TARGET_24H,
    MAX_ACTIONS_PER_WINDOW,
    MAX_AUTOMATIC_RETRIES,
    MAX_CONCURRENT_SUPERVISED_MUTATIONS,
    SupervisionError,
    SupervisionService,
    SupervisionStore,
    assessment_bucket,
    classify_container_status,
)


NOW = datetime(2026, 7, 23, 10, 5, 18, tzinfo=timezone.utc)


def schedule(**overrides):
    value = {
        "name": "Recover get_iplayer",
        "enabled": True,
        "operation": "container.restart",
        "params": {"name": "get_iplayer"},
        "service_priority": "normal",
        "window": {
            "cron": "0 2 * * *",
            "timezone": "Europe/London",
            "duration_minutes": 60,
        },
        "delivery": {
            "channel": "mattermost-alerts",
            "mode": "threaded",
        },
    }
    value.update(overrides)
    return value


def owner():
    return {"type": "local", "id": "admin", "username": "marc"}


def broker_status(
    status="running", *, health=None, name="get_iplayer", audit_id="audit-1"
):
    return {
        "ok": True,
        "data": {"name": name, "status": status, "health": health},
        "error": None,
        "audit_id": audit_id,
    }


def service(tmp_path, *, schedule_id="schedule-1", clock=None):
    instance = SupervisionService(
        store=SupervisionStore(tmp_path / "supervision.sqlite3"),
        clock=clock or (lambda: NOW),
        id_factory=lambda: schedule_id,
    )
    return instance


def test_schedule_is_strict_private_revisioned_and_server_derived(tmp_path):
    supervision = service(tmp_path)

    created = supervision.create(schedule(), owner=owner())

    assert created["id"] == "schedule-1"
    assert created["target"] == "get_iplayer"
    assert created["risk"] == "R1"
    assert created["capability_version"] == "1"
    assert created["assessment_operation"] == "container.status"
    assert created["assessment_interval_seconds"] == ASSESSMENT_INTERVAL_SECONDS
    assert created["failure_threshold"] == CONSECUTIVE_FAILURE_THRESHOLD
    assert created["budgets"] == {
        "max_actions_per_target_24h": MAX_ACTIONS_PER_TARGET_24H,
        "max_actions_per_window": MAX_ACTIONS_PER_WINDOW,
        "max_automatic_retries": MAX_AUTOMATIC_RETRIES,
        "max_concurrent_mutations": MAX_CONCURRENT_SUPERVISED_MUTATIONS,
        "action_deadline_seconds": ACTION_DEADLINE_SECONDS,
    }
    assert created["owner"] == owner()
    assert created["revision"] == 1
    assert os.stat(tmp_path / "supervision.sqlite3").st_mode & 0o777 == 0o660


@pytest.mark.parametrize(
    "values",
    [
        schedule(extra=True),
        schedule(operation="stack.restart"),
        schedule(params={"name": "jellyfin"}),
        schedule(params={"name": "get_iplayer", "force": True}),
        schedule(service_priority="essential"),
        schedule(
            window={
                "cron": "bad cron",
                "timezone": "Europe/London",
                "duration_minutes": 60,
            }
        ),
        schedule(
            window={
                "cron": "0 2 * * *",
                "timezone": "Mars/Olympus",
                "duration_minutes": 60,
            }
        ),
        schedule(
            delivery={"channel": "mattermost-alerts", "mode": "immediate"}
        ),
    ],
)
def test_schedule_rejects_unregistered_or_unbounded_contracts(tmp_path, values):
    supervision = service(tmp_path)

    with pytest.raises(SupervisionError) as invalid:
        supervision.create(values, owner=owner())

    assert invalid.value.code == "invalid_schedule"


def test_schedule_update_requires_revision_and_keeps_target_owned(tmp_path):
    supervision = service(tmp_path)
    created = supervision.create(schedule(), owner=owner())

    with pytest.raises(SupervisionError) as stale:
        supervision.update(
            created["id"],
            {**schedule(name="Changed"), "revision": 9},
        )

    assert stale.value.code == "conflict"
    updated = supervision.update(
        created["id"],
        {
            **schedule(
                name="Changed",
                enabled=False,
                service_priority="critical",
            ),
            "revision": 1,
        },
    )
    assert updated["name"] == "Changed"
    assert updated["enabled"] is False
    assert updated["service_priority"] == "critical"
    assert updated["revision"] == 2


def test_exact_operation_target_has_one_schedule_owner(tmp_path):
    first = service(tmp_path, schedule_id="schedule-1")
    first.create(schedule(), owner=owner())
    second = SupervisionService(
        store=first.store,
        clock=lambda: NOW,
        id_factory=lambda: "schedule-2",
    )

    with pytest.raises(SupervisionError) as conflict:
        second.create(schedule(name="Duplicate"), owner=owner())

    assert conflict.value.code == "conflict"


def test_priority_orders_work_but_does_not_change_derived_authority(tmp_path):
    supervision = service(tmp_path)
    created = supervision.create(
        schedule(service_priority="critical"), owner=owner()
    )

    result = supervision.list()

    assert result["service_priorities"] == [
        "critical",
        "high",
        "normal",
        "low",
    ]
    assert result["schedules"][0]["service_priority"] == "critical"
    assert result["schedules"][0]["budgets"] == created["budgets"]
    assert "authority_mode" not in result["schedules"][0]


def test_assessment_bucket_is_timezone_safe_and_requires_aware_time():
    offset = datetime.fromisoformat("2026-07-23T11:19:59+01:00")

    assert assessment_bucket(offset) == datetime(
        2026, 7, 23, 10, 10, tzinfo=timezone.utc
    )
    with pytest.raises(SupervisionError) as invalid:
        assessment_bucket(datetime(2026, 7, 23, 10, 10))
    assert invalid.value.code == "invalid_time"


@pytest.mark.parametrize(
    ("response", "outcome", "code"),
    [
        (broker_status("running"), "healthy", "container_healthy"),
        (
            broker_status("running", health="healthy"),
            "healthy",
            "container_healthy",
        ),
        (
            broker_status("running", health="unhealthy"),
            "failed",
            "container_unhealthy",
        ),
        (broker_status("stopped"), "failed", "container_stopped"),
        (broker_status("exited"), "failed", "container_exited"),
        (broker_status("dead"), "failed", "container_dead"),
        (broker_status("restarting"), "failed", "container_restarting"),
        (
            broker_status("running", health="starting"),
            "unknown",
            "container_state_transitional",
        ),
        ({"ok": False, "error": {"secret": "no"}}, "unknown", "assessment_unavailable"),
        ({"ok": True, "data": "private"}, "unknown", "malformed_response"),
        (
            broker_status(name="jellyfin"),
            "unknown",
            "target_mismatch",
        ),
        (broker_status("mystery"), "unknown", "unrecognized_status"),
    ],
)
def test_container_assessment_is_code_owned_and_bounded(
    response, outcome, code
):
    result = classify_container_status(
        response, expected_target="get_iplayer"
    )

    assert result["outcome"] == outcome
    assert result["code"] == code
    assert "secret" not in str(result)


def test_two_adjacent_failures_open_one_durable_incident(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())

    first = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW,
    )
    second = supervision.assess(
        "schedule-1",
        broker_status("exited", audit_id="audit-2"),
        assessed_at=NOW + timedelta(minutes=10),
    )

    assert first["incident"] is None
    assert second["incident"]["state"] == "confirmed"
    assert second["incident"]["consecutive_failures"] == 2
    incidents = supervision.store.list_incidents()
    assert len(incidents) == 1
    transitions = supervision.store.list_transitions(incidents[0]["id"])
    assert [item["type"] for item in transitions] == ["fault_confirmed"]
    assert transitions[0]["details"] == {
        "assessment_code": "container_exited",
        "outcome": "failed",
    }


def test_duplicate_bucket_is_idempotent_even_with_different_result(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())

    first = supervision.assess(
        "schedule-1", broker_status("exited"), assessed_at=NOW
    )
    repeated = supervision.assess(
        "schedule-1", broker_status("running"), assessed_at=NOW
    )

    assert first["created"] is True
    assert repeated["created"] is False
    assert repeated["assessment"]["id"] == first["assessment"]["id"]
    assert repeated["assessment"]["outcome"] == "failed"
    assert len(supervision.store.list_assessments("schedule-1")) == 1


def test_store_rejects_unbounded_assessment_evidence(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())

    with pytest.raises(SupervisionError) as invalid:
        supervision.store.record_assessment(
            schedule_id="schedule-1",
            assessed_for="2026-07-23T10:00:00+00:00",
            evidence={
                "outcome": "failed",
                "code": "private model diagnosis",
                "observed_status": "exited",
                "observed_health": None,
                "audit_id": "audit-1",
                "raw": {"token": "secret"},
            },
            recorded_at="2026-07-23T10:05:18+00:00",
        )

    assert invalid.value.code == "invalid_assessment"
    assert supervision.store.list_assessments("schedule-1") == []


def test_missed_bucket_prevents_stale_failure_confirmation(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())

    supervision.assess(
        "schedule-1", broker_status("exited"), assessed_at=NOW
    )
    result = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW + timedelta(minutes=20),
    )

    assert result["incident"] is None


def test_unknown_breaks_streak_and_blocks_open_incident(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.assess(
        "schedule-1", broker_status("exited"), assessed_at=NOW
    )
    opened = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW + timedelta(minutes=10),
    )

    blocked = supervision.assess(
        "schedule-1",
        {"ok": False, "audit_id": "audit-3"},
        assessed_at=NOW + timedelta(minutes=20),
    )
    pending = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW + timedelta(minutes=30),
    )
    confirmed = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW + timedelta(minutes=40),
    )

    assert blocked["incident"]["id"] == opened["incident"]["id"]
    assert blocked["incident"]["state"] == "infrastructure_blocked"
    assert blocked["incident"]["consecutive_failures"] == 0
    assert pending["incident"]["state"] == "reconfirming"
    assert pending["incident"]["consecutive_failures"] == 1
    assert confirmed["incident"]["state"] == "confirmed"
    assert confirmed["incident"]["consecutive_failures"] == 2
    assert [
        item["type"]
        for item in supervision.store.list_transitions(
            opened["incident"]["id"]
        )
    ] == [
        "fault_confirmed",
        "infrastructure_blocked",
        "fault_pending",
        "fault_reconfirmed",
    ]


def test_healthy_assessment_resolves_incident_and_new_fault_opens_another(
    tmp_path,
):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.assess(
        "schedule-1", broker_status("dead"), assessed_at=NOW
    )
    opened = supervision.assess(
        "schedule-1",
        broker_status("dead"),
        assessed_at=NOW + timedelta(minutes=10),
    )

    recovered = supervision.assess(
        "schedule-1",
        broker_status("running"),
        assessed_at=NOW + timedelta(minutes=20),
    )
    supervision.assess(
        "schedule-1",
        broker_status("dead"),
        assessed_at=NOW + timedelta(minutes=30),
    )
    reopened = supervision.assess(
        "schedule-1",
        broker_status("dead"),
        assessed_at=NOW + timedelta(minutes=40),
    )

    assert recovered["incident"]["state"] == "recovered"
    assert recovered["incident"]["terminal_code"] == "healthy_before_action"
    assert recovered["incident"]["resolved_at"] is not None
    assert reopened["incident"]["state"] == "confirmed"
    assert reopened["incident"]["id"] != opened["incident"]["id"]
    assert len(supervision.store.list_incidents()) == 2


def test_late_assessment_is_evidence_but_does_not_rewind_incident(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.assess(
        "schedule-1", broker_status("exited"), assessed_at=NOW
    )
    opened = supervision.assess(
        "schedule-1",
        broker_status("exited"),
        assessed_at=NOW + timedelta(minutes=10),
    )

    late = supervision.assess(
        "schedule-1",
        broker_status("running"),
        assessed_at=NOW - timedelta(minutes=10),
    )

    assert late["created"] is True
    assert late["incident"] is None
    assert supervision.store.get_incident(opened["incident"]["id"])[
        "state"
    ] == "confirmed"


def test_assessment_recording_is_concurrency_safe(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    barrier = Barrier(2)

    def assess():
        barrier.wait()
        return supervision.assess(
            "schedule-1", broker_status("exited"), assessed_at=NOW
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: assess(), range(2)))

    assert sorted(result["created"] for result in results) == [False, True]
    assert len(supervision.store.list_assessments("schedule-1")) == 1


def test_disabled_schedule_cannot_be_assessed(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(enabled=False), owner=owner())

    with pytest.raises(SupervisionError) as disabled:
        supervision.assess("schedule-1", broker_status())

    assert disabled.value.code == "schedule_disabled"


def test_budget_charge_is_idempotent_and_reports_fixed_usage(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())

    first = supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-1",
        occurrence_key="occurrence-1",
        action_id="action-1",
        charged_at=NOW,
    )
    repeated = supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-1",
        occurrence_key="occurrence-1",
        action_id="action-1",
        charged_at=NOW,
    )
    status = supervision.store.budget_status(
        "schedule-1", window_key="window-1", at=NOW
    )

    assert first["created"] is True
    assert repeated == {"charge": first["charge"], "created": False}
    assert status["rolling_24h"] == {"used": 1, "limit": 1}
    assert status["window"] == {"used": 1, "limit": 1}
    assert status["last_charge"] == first["charge"]


def test_budget_occurrence_cannot_be_rebound(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-1",
        occurrence_key="occurrence-1",
        action_id="action-1",
        charged_at=NOW,
    )

    with pytest.raises(SupervisionError) as conflict:
        supervision.store.charge_budget(
            schedule_id="schedule-1",
            window_key="window-2",
            occurrence_key="occurrence-1",
            action_id="action-1",
            charged_at=NOW,
        )

    assert conflict.value.code == "conflict"


def test_budget_blocks_same_window_then_rolling_cooldown(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-1",
        occurrence_key="occurrence-1",
        action_id="action-1",
        charged_at=NOW,
    )

    with pytest.raises(SupervisionError) as same_window:
        supervision.store.charge_budget(
            schedule_id="schedule-1",
            window_key="window-1",
            occurrence_key="occurrence-2",
            action_id="action-2",
            charged_at=NOW + timedelta(minutes=20),
        )
    with pytest.raises(SupervisionError) as cooldown:
        supervision.store.charge_budget(
            schedule_id="schedule-1",
            window_key="window-2",
            occurrence_key="occurrence-3",
            action_id="action-3",
            charged_at=NOW + timedelta(hours=23),
        )

    assert same_window.value.code == "window_budget_exhausted"
    assert cooldown.value.code == "cooldown_active"


def test_budget_allows_next_action_at_rolling_boundary(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-1",
        occurrence_key="occurrence-1",
        action_id="action-1",
        charged_at=NOW,
    )

    next_charge = supervision.store.charge_budget(
        schedule_id="schedule-1",
        window_key="window-2",
        occurrence_key="occurrence-2",
        action_id="action-2",
        charged_at=NOW + timedelta(hours=24),
    )

    assert next_charge["created"] is True


def test_budget_charge_is_concurrency_safe(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(), owner=owner())
    barrier = Barrier(2)

    def charge(index):
        barrier.wait()
        try:
            return supervision.store.charge_budget(
                schedule_id="schedule-1",
                window_key=f"window-{index}",
                occurrence_key=f"occurrence-{index}",
                action_id=f"action-{index}",
                charged_at=NOW,
            )["created"]
        except SupervisionError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(charge, range(2)))

    assert sorted(map(str, results)) == ["True", "cooldown_active"]
    status = supervision.store.budget_status(
        "schedule-1", window_key="window-1", at=NOW
    )
    assert status["rolling_24h"]["used"] == 1


def test_disabled_schedule_cannot_charge_budget(tmp_path):
    supervision = service(tmp_path)
    supervision.create(schedule(enabled=False), owner=owner())

    with pytest.raises(SupervisionError) as disabled:
        supervision.store.charge_budget(
            schedule_id="schedule-1",
            window_key="window-1",
            occurrence_key="occurrence-1",
            action_id="action-1",
            charged_at=NOW,
        )

    assert disabled.value.code == "schedule_disabled"


def test_store_rejects_symlink(tmp_path):
    destination = tmp_path / "destination.sqlite3"
    destination.touch()
    link = tmp_path / "supervision.sqlite3"
    link.symlink_to(destination)

    with pytest.raises(SupervisionError) as unsafe:
        SupervisionStore(link)

    assert unsafe.value.code == "unsafe_store"
