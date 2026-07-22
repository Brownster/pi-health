from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent_automation.service import (
    AutomationError,
    AutomationStore,
    ReportSchedulerService,
)


NOW = datetime(2026, 7, 22, 7, 0, tzinfo=timezone.utc)


class FakeScheduler:
    def __init__(self):
        self.running = False
        self.jobs = {}
        self.added = []
        self.removed = []

    def start(self):
        self.running = True

    def add_job(self, func, trigger, *, id, replace_existing=True, **kwargs):
        job = SimpleNamespace(
            func=func,
            trigger=trigger,
            id=id,
            next_run_time=NOW,
            kwargs=kwargs,
        )
        self.jobs[id] = job
        self.added.append(job)
        return job

    def remove_job(self, job_id):
        self.removed.append(job_id)
        if self.jobs.pop(job_id, None) is None:
            raise KeyError(job_id)

    def get_job(self, job_id):
        return self.jobs.get(job_id)


def schedule(**overrides):
    value = {
        "name": "Morning health report",
        "enabled": True,
        "checks": [
            {"operation": "system.status", "params": {}},
            {
                "operation": "service.status",
                "params": {"unit": "limeopsd"},
            },
        ],
        "window": {
            "cron": "0 7 * * *",
            "timezone": "Europe/London",
            "duration_minutes": 30,
        },
        "budgets": {
            "max_checks": 8,
            "max_reports": 1,
            "max_actions": 0,
            "max_downtime_seconds": 0,
            "max_retries": 0,
            "max_model_invocations": 0,
        },
        "delivery": {"channel": "mattermost-alerts", "mode": "immediate"},
    }
    value.update(overrides)
    return value


def service(tmp_path, *, diagnostic=None, reporter=None, scheduler=None, clock=None):
    scheduler = scheduler or FakeScheduler()
    diagnostic = diagnostic or (
        lambda operation, params, actor: {
            "ok": True,
            "data": {"operation": operation, "status": "healthy"},
            "error": None,
            "audit_id": f"audit-{operation}",
        }
    )
    reports = []
    reporter = reporter or reports.append
    instance = ReportSchedulerService(
        store=AutomationStore(tmp_path / "automation.sqlite3"),
        scheduler=scheduler,
        diagnostic=diagnostic,
        reporter=reporter,
        trigger_factory=lambda cron, timezone: (cron, timezone),
        clock=clock or (lambda: NOW),
        id_factory=lambda: "schedule-1",
    )
    return instance, scheduler, reports


def owner():
    return {"type": "local", "id": "admin", "username": "admin"}


def test_schedule_is_private_strict_and_revisioned(tmp_path):
    automation, _scheduler, _reports = service(tmp_path)

    created = automation.create(schedule(), owner=owner())

    assert created["id"] == "schedule-1"
    assert created["owner"] == owner()
    assert created["revision"] == 1
    assert created["next_run"] == NOW.isoformat()
    assert os.stat(tmp_path / "automation.sqlite3").st_mode & 0o777 == 0o660
    assert automation.get(created["id"])["name"] == "Morning health report"


@pytest.mark.parametrize(
    "values",
    [
        schedule(extra=True),
        schedule(checks=[{"operation": "action.propose", "params": {}}]),
        schedule(checks=[{"operation": "service.logs", "params": {"unit": "limeopsd"}}]),
        schedule(checks=[{"operation": "service.status", "params": {"name": "limeopsd"}}]),
        schedule(window={"cron": "bad cron", "timezone": "Europe/London", "duration_minutes": 30}),
        schedule(window={"cron": "0 7 * * *", "timezone": "Mars/Olympus", "duration_minutes": 30}),
        schedule(budgets={
            "max_checks": 8,
            "max_reports": 1,
            "max_actions": 1,
            "max_downtime_seconds": 0,
            "max_retries": 0,
            "max_model_invocations": 0,
        }),
    ],
)
def test_schedule_rejects_unbounded_or_mutating_contracts(tmp_path, values):
    automation, _scheduler, _reports = service(tmp_path)

    with pytest.raises(AutomationError) as invalid:
        automation.create(values, owner=owner())

    assert invalid.value.code == "invalid_schedule"


def test_enabled_schedule_registers_one_coalesced_window_job(tmp_path):
    automation, scheduler, _reports = service(tmp_path)

    automation.create(schedule(), owner=owner())

    job = scheduler.jobs["agent-report:schedule-1"]
    assert job.trigger == ("0 7 * * *", "Europe/London")
    assert job.kwargs == {
        "args": ["schedule-1"],
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 1800,
    }


def test_occurrence_is_deduplicated_and_delivered_once(tmp_path):
    calls = []

    def diagnostic(operation, params, actor):
        calls.append((operation, params, actor))
        return {
            "ok": True,
            "data": {"active_state": "active"},
            "error": None,
            "audit_id": f"audit-{operation}",
        }

    automation, _scheduler, reports = service(tmp_path, diagnostic=diagnostic)
    automation.create(schedule(), owner=owner())

    first = automation.run("schedule-1", scheduled_for=NOW)
    repeated = automation.run("schedule-1", scheduled_for=NOW)

    assert first["state"] == "delivered"
    assert repeated["id"] == first["id"]
    assert len(calls) == 2
    assert calls[0][2] == {
        "type": "system",
        "id": "agent-scheduler",
        "username": None,
    }
    assert len(reports) == 1
    assert reports[0]["status"] == "healthy"
    assert [check["audit_id"] for check in reports[0]["checks"]] == [
        "audit-system.status",
        "audit-service.status",
    ]


def test_failed_check_creates_partial_redacted_report(tmp_path):
    def diagnostic(operation, _params, _actor):
        if operation == "system.status":
            return {
                "ok": True,
                "data": {"token": "secret-value", "status": "healthy"},
                "error": None,
                "audit_id": "audit-system",
            }
        return {
            "ok": False,
            "data": None,
            "error": {"code": "unavailable_dependency", "message": "private"},
            "audit_id": "audit-service",
        }

    automation, _scheduler, reports = service(tmp_path, diagnostic=diagnostic)
    automation.create(schedule(), owner=owner())

    occurrence = automation.run("schedule-1", scheduled_for=NOW)

    assert occurrence["state"] == "delivered"
    assert reports[0]["status"] == "partial"
    assert reports[0]["counts"] == {"healthy": 1, "attention": 0, "failed": 1}
    assert reports[0]["checks"][1]["error_code"] == "unavailable_dependency"
    assert "private" not in json.dumps(reports[0])
    assert "secret-value" not in json.dumps(reports[0])


def test_update_requires_current_revision_and_disable_removes_job(tmp_path):
    automation, scheduler, _reports = service(tmp_path)
    created = automation.create(schedule(), owner=owner())

    with pytest.raises(AutomationError) as stale:
        automation.update(created["id"], {**schedule(enabled=False), "revision": 9})
    assert stale.value.code == "conflict"

    updated = automation.update(
        created["id"], {**schedule(enabled=False), "revision": created["revision"]}
    )

    assert updated["enabled"] is False
    assert updated["revision"] == 2
    assert "agent-report:schedule-1" not in scheduler.jobs
    with pytest.raises(AutomationError) as disabled:
        automation.run(created["id"], scheduled_for=NOW)
    assert disabled.value.code == "schedule_disabled"


def test_startup_recovers_reads_but_never_retries_ambiguous_delivery(tmp_path):
    automation, scheduler, reports = service(tmp_path)
    automation.create(schedule(enabled=False), owner=owner())
    store = automation.store

    running, _ = store.begin_occurrence(
        schedule_id="schedule-1",
        occurrence_id="running-1",
        scheduled_for="2026-07-22T06:00:00+00:00",
        started_at="2026-07-22T06:00:00+00:00",
    )
    ready, _ = store.begin_occurrence(
        schedule_id="schedule-1",
        occurrence_id="ready-1",
        scheduled_for="2026-07-22T06:30:00+00:00",
        started_at="2026-07-22T06:30:00+00:00",
    )
    report = {
        "schedule_id": "schedule-1",
        "schedule_name": "Morning health report",
        "occurrence_id": ready["id"],
        "scheduled_for": ready["scheduled_for"],
        "generated_at": "2026-07-22T06:31:00+00:00",
        "status": "healthy",
        "counts": {"healthy": 1, "attention": 0, "failed": 0},
        "checks": [],
    }
    store.save_report(ready["id"], report=report, at=report["generated_at"])
    ambiguous, _ = store.begin_occurrence(
        schedule_id="schedule-1",
        occurrence_id="ambiguous-1",
        scheduled_for="2026-07-22T06:45:00+00:00",
        started_at="2026-07-22T06:45:00+00:00",
    )
    store.save_report(ambiguous["id"], report=report, at=report["generated_at"])
    store.claim_delivery(ambiguous["id"], at="2026-07-22T06:46:00+00:00")

    automation.init_scheduler()

    assert scheduler.running is True
    assert store.get_occurrence(running["id"])["state"] == "delivered"
    assert store.get_occurrence(ready["id"])["state"] == "delivered"
    assert store.get_occurrence(ambiguous["id"])["state"] == "delivery_unknown"
    assert len(reports) == 2
