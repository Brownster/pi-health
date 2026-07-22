"""Durable report-only schedules over the typed LimeOps read boundary."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger

from limeops.operations import redact_text


MAX_CHECKS = 12
MAX_SUMMARY_CHARS = 500
SCHEDULE_FIELDS = frozenset(
    {"name", "enabled", "checks", "window", "budgets", "delivery"}
)
WINDOW_FIELDS = frozenset({"cron", "timezone", "duration_minutes"})
BUDGET_FIELDS = frozenset(
    {
        "max_checks",
        "max_reports",
        "max_actions",
        "max_downtime_seconds",
        "max_retries",
        "max_model_invocations",
    }
)
DELIVERY_FIELDS = frozenset({"channel", "mode"})
CHECK_FIELDS = frozenset({"operation", "params"})
OWNER_FIELDS = frozenset({"type", "id", "username"})
SYSTEM_ACTOR = {"type": "system", "id": "agent-scheduler", "username": None}
_SECRET_FIELD = re.compile(
    r"(?i)(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"authorization|webhook|dsn|database[_-]?url|connection[_-]?string)"
)

_NO_PARAM_CHECKS = frozenset(
    {
        "system.status",
        "container.list",
        "stack.list",
        "disk.health",
        "mount.status",
        "snapraid.status",
        "installation.inventory",
        "packages.status",
        "packages.pending",
    }
)
_RESOURCE_CHECKS = {
    "container.status": "name",
    "stack.status": "name",
    "service.status": "unit",
    "network.check": "target",
}
CHECK_CATALOGUE = tuple(
    {"operation": operation, "parameter": None}
    for operation in sorted(_NO_PARAM_CHECKS)
) + tuple(
    {"operation": operation, "parameter": parameter}
    for operation, parameter in sorted(_RESOURCE_CHECKS.items())
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    checks_json TEXT NOT NULL,
    window_json TEXT NOT NULL,
    budgets_json TEXT NOT NULL,
    delivery_json TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    owner_username TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS schedules_updated_idx
    ON schedules(updated_at DESC, schedule_id DESC);
CREATE TABLE IF NOT EXISTS schedule_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES schedules(schedule_id),
    scheduled_for TEXT NOT NULL,
    state TEXT NOT NULL,
    report_json TEXT,
    terminal_code TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(schedule_id, scheduled_for)
);
CREATE INDEX IF NOT EXISTS schedule_occurrences_schedule_idx
    ON schedule_occurrences(schedule_id, scheduled_for DESC);
CREATE INDEX IF NOT EXISTS schedule_occurrences_state_idx
    ON schedule_occurrences(state, updated_at);
"""


class AutomationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise AutomationError("invalid_schedule", "Schedule time must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise AutomationError(
            "invalid_schedule", f"Unknown {label} field: {sorted(unknown)[0]}"
        )


def _short_string(value: Any, label: str, *, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character in value for character in "\x00\r\n")
    ):
        raise AutomationError("invalid_schedule", f"{label} must be a short string")
    return value.strip()


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise AutomationError(
            "invalid_schedule", f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _normalize_check(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AutomationError("invalid_schedule", "Each schedule check must be an object")
    _reject_unknown(raw, CHECK_FIELDS, "check")
    operation = _short_string(raw.get("operation"), "Check operation")
    params = raw.get("params")
    if not isinstance(params, Mapping):
        raise AutomationError("invalid_schedule", "Check parameters must be an object")
    if operation in _NO_PARAM_CHECKS:
        if params:
            raise AutomationError(
                "invalid_schedule", f"{operation} accepts no schedule parameters"
            )
        return {"operation": operation, "params": {}}
    parameter = _RESOURCE_CHECKS.get(operation)
    if parameter is None:
        raise AutomationError("invalid_schedule", "Check operation is not report-only")
    if set(params) != {parameter}:
        raise AutomationError(
            "invalid_schedule", f"{operation} requires only the {parameter} parameter"
        )
    return {
        "operation": operation,
        "params": {parameter: _short_string(params.get(parameter), parameter)},
    }


def normalize_schedule(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AutomationError("invalid_schedule", "Schedule must be an object")
    _reject_unknown(raw, SCHEDULE_FIELDS, "schedule")
    if set(raw) != SCHEDULE_FIELDS:
        raise AutomationError("invalid_schedule", "Schedule fields are incomplete")

    name = _short_string(raw.get("name"), "Schedule name", maximum=120)
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise AutomationError("invalid_schedule", "Schedule enabled must be a boolean")

    checks_raw = raw.get("checks")
    if not isinstance(checks_raw, list) or not 1 <= len(checks_raw) <= MAX_CHECKS:
        raise AutomationError(
            "invalid_schedule", f"Schedule requires between 1 and {MAX_CHECKS} checks"
        )
    checks = [_normalize_check(check) for check in checks_raw]

    window_raw = raw.get("window")
    if not isinstance(window_raw, Mapping):
        raise AutomationError("invalid_schedule", "Schedule window must be an object")
    _reject_unknown(window_raw, WINDOW_FIELDS, "window")
    if set(window_raw) != WINDOW_FIELDS:
        raise AutomationError("invalid_schedule", "Schedule window fields are incomplete")
    cron = _short_string(window_raw.get("cron"), "Schedule cron", maximum=120)
    timezone_name = _short_string(
        window_raw.get("timezone"), "Schedule timezone", maximum=64
    )
    try:
        zone = ZoneInfo(timezone_name)
        CronTrigger.from_crontab(cron, timezone=zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AutomationError(
            "invalid_schedule", "Schedule cron or timezone is invalid"
        ) from exc
    window = {
        "cron": cron,
        "timezone": timezone_name,
        "duration_minutes": _integer(
            window_raw.get("duration_minutes"), "Window duration", 1, 1440
        ),
    }

    budgets_raw = raw.get("budgets")
    if not isinstance(budgets_raw, Mapping):
        raise AutomationError("invalid_schedule", "Schedule budgets must be an object")
    _reject_unknown(budgets_raw, BUDGET_FIELDS, "budget")
    if set(budgets_raw) != BUDGET_FIELDS:
        raise AutomationError("invalid_schedule", "Schedule budget fields are incomplete")
    max_checks = _integer(budgets_raw.get("max_checks"), "Maximum checks", 1, MAX_CHECKS)
    if max_checks < len(checks):
        raise AutomationError(
            "invalid_schedule", "Maximum checks must cover every configured check"
        )
    fixed_budgets = {
        "max_reports": 1,
        "max_actions": 0,
        "max_downtime_seconds": 0,
        "max_retries": 0,
        "max_model_invocations": 0,
    }
    for field, expected in fixed_budgets.items():
        if budgets_raw.get(field) != expected:
            raise AutomationError(
                "invalid_schedule", f"{field} must remain {expected} in report-only mode"
            )
    budgets = {"max_checks": max_checks, **fixed_budgets}

    delivery_raw = raw.get("delivery")
    if not isinstance(delivery_raw, Mapping):
        raise AutomationError("invalid_schedule", "Schedule delivery must be an object")
    _reject_unknown(delivery_raw, DELIVERY_FIELDS, "delivery")
    if delivery_raw != {"channel": "mattermost-alerts", "mode": "immediate"}:
        raise AutomationError(
            "invalid_schedule", "Report-only delivery must use mattermost-alerts immediately"
        )

    return {
        "name": name,
        "enabled": enabled,
        "checks": checks,
        "window": window,
        "budgets": budgets,
        "delivery": {"channel": "mattermost-alerts", "mode": "immediate"},
    }


def _normalize_owner(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != OWNER_FIELDS:
        raise AutomationError("invalid_schedule", "Schedule owner is invalid")
    actor_type = raw.get("type")
    if actor_type not in {"local", "mattermost", "system"}:
        raise AutomationError("invalid_schedule", "Schedule owner is invalid")
    actor_id = _short_string(raw.get("id"), "Schedule owner ID")
    username = raw.get("username")
    if username is not None:
        username = _short_string(username, "Schedule owner username")
    return {"type": actor_type, "id": actor_id, "username": username}


class AutomationStore:
    """SQLite schedule and occurrence storage with strict transition methods."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self._path.is_symlink():
            raise AutomationError("unsafe_store", "Automation store cannot be a symlink")
        try:
            with self._connect() as connection:
                connection.executescript(_SCHEMA)
            try:
                os.chmod(self._path, 0o660)
            except PermissionError:
                metadata = self._path.stat(follow_symlinks=False)
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_IMODE(metadata.st_mode) != 0o660
                ):
                    raise
        except (OSError, sqlite3.Error) as exc:
            raise AutomationError(
                "store_unavailable", "Automation store is unavailable"
            ) from exc

    def create_schedule(
        self,
        *,
        schedule_id: str,
        values: Mapping[str, Any],
        owner: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO schedules (
                        schedule_id, name, enabled, checks_json, window_json,
                        budgets_json, delivery_json, owner_type, owner_id,
                        owner_username, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule_id,
                        values["name"],
                        int(values["enabled"]),
                        _json(values["checks"]),
                        _json(values["window"]),
                        _json(values["budgets"]),
                        _json(values["delivery"]),
                        owner["type"],
                        owner["id"],
                        owner.get("username"),
                        at,
                        at,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
                ).fetchone()
            return self._schedule(row)
        except sqlite3.IntegrityError as exc:
            raise AutomationError("conflict", "Schedule already exists") from exc
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Schedule could not be saved") from exc

    def update_schedule(
        self,
        schedule_id: str,
        *,
        values: Mapping[str, Any],
        expected_revision: int,
        at: str,
    ) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT revision FROM schedules WHERE schedule_id = ?", (schedule_id,)
                ).fetchone()
                if row is None:
                    raise AutomationError("not_found", "Schedule was not found")
                if row["revision"] != expected_revision:
                    raise AutomationError("conflict", "Schedule changed concurrently")
                cursor = connection.execute(
                    """
                    UPDATE schedules SET
                        name = ?, enabled = ?, checks_json = ?, window_json = ?,
                        budgets_json = ?, delivery_json = ?, updated_at = ?,
                        revision = revision + 1
                    WHERE schedule_id = ? AND revision = ?
                    """,
                    (
                        values["name"],
                        int(values["enabled"]),
                        _json(values["checks"]),
                        _json(values["window"]),
                        _json(values["budgets"]),
                        _json(values["delivery"]),
                        at,
                        schedule_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise AutomationError("conflict", "Schedule changed concurrently")
                updated = connection.execute(
                    "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
                ).fetchone()
            return self._schedule(updated)
        except AutomationError:
            raise
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Schedule could not be saved") from exc

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM schedules WHERE schedule_id = ?", (schedule_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Schedule could not be read") from exc
        if row is None:
            raise AutomationError("not_found", "Schedule was not found")
        return self._schedule(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM schedules ORDER BY updated_at DESC, schedule_id DESC"
                ).fetchall()
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Schedules could not be read") from exc
        return [self._schedule(row) for row in rows]

    def begin_occurrence(
        self,
        *,
        schedule_id: str,
        occurrence_id: str,
        scheduled_for: str,
        started_at: str,
    ) -> tuple[dict[str, Any], bool]:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT * FROM schedule_occurrences
                    WHERE schedule_id = ? AND scheduled_for = ?
                    """,
                    (schedule_id, scheduled_for),
                ).fetchone()
                if existing is not None:
                    return self._occurrence(existing), False
                connection.execute(
                    """
                    INSERT INTO schedule_occurrences (
                        occurrence_id, schedule_id, scheduled_for, state,
                        started_at, updated_at
                    ) VALUES (?, ?, ?, 'running', ?, ?)
                    """,
                    (
                        occurrence_id,
                        schedule_id,
                        scheduled_for,
                        started_at,
                        started_at,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM schedule_occurrences WHERE occurrence_id = ?",
                    (occurrence_id,),
                ).fetchone()
            return self._occurrence(row), True
        except sqlite3.IntegrityError as exc:
            raise AutomationError("not_found", "Schedule was not found") from exc
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Occurrence could not be saved") from exc

    def save_report(self, occurrence_id: str, *, report: Mapping[str, Any], at: str) -> None:
        self._transition_occurrence(
            occurrence_id,
            expected="running",
            state="report_ready",
            at=at,
            report=report,
        )

    def claim_delivery(self, occurrence_id: str, *, at: str) -> None:
        self._transition_occurrence(
            occurrence_id, expected="report_ready", state="delivering", at=at
        )

    def finish_delivery(
        self, occurrence_id: str, *, delivered: bool, at: str
    ) -> None:
        self._transition_occurrence(
            occurrence_id,
            expected="delivering",
            state="delivered" if delivered else "delivery_failed",
            at=at,
            terminal_code=None if delivered else "delivery_failed",
            finished=True,
        )

    def mark_delivery_unknown(self, occurrence_id: str, *, at: str) -> None:
        self._transition_occurrence(
            occurrence_id,
            expected="delivering",
            state="delivery_unknown",
            at=at,
            terminal_code="delivery_unknown",
            finished=True,
        )

    def mark_check_failed(self, occurrence_id: str, *, at: str) -> None:
        self._transition_occurrence(
            occurrence_id,
            expected="running",
            state="check_failed",
            at=at,
            terminal_code="check_failed",
            finished=True,
        )

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM schedule_occurrences WHERE occurrence_id = ?",
                    (occurrence_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Occurrence could not be read") from exc
        if row is None:
            raise AutomationError("not_found", "Occurrence was not found")
        return self._occurrence(row)

    def latest_occurrence(self, schedule_id: str) -> dict[str, Any] | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM schedule_occurrences WHERE schedule_id = ?
                    ORDER BY scheduled_for DESC, occurrence_id DESC LIMIT 1
                    """,
                    (schedule_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Occurrence could not be read") from exc
        return self._occurrence(row) if row is not None else None

    def incomplete_occurrences(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM schedule_occurrences
                    WHERE state IN ('running', 'report_ready', 'delivering')
                    ORDER BY scheduled_for, occurrence_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Occurrences could not be read") from exc
        return [self._occurrence(row) for row in rows]

    def _transition_occurrence(
        self,
        occurrence_id: str,
        *,
        expected: str,
        state: str,
        at: str,
        report: Mapping[str, Any] | None = None,
        terminal_code: str | None = None,
        finished: bool = False,
    ) -> None:
        assignments = ["state = ?", "updated_at = ?", "terminal_code = ?"]
        values: list[Any] = [state, at, terminal_code]
        if report is not None:
            assignments.append("report_json = ?")
            values.append(_json(report))
        if finished:
            assignments.append("finished_at = ?")
            values.append(at)
        values.extend([occurrence_id, expected])
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    f"UPDATE schedule_occurrences SET {', '.join(assignments)} "
                    "WHERE occurrence_id = ? AND state = ?",
                    values,
                )
                if cursor.rowcount != 1:
                    raise AutomationError("conflict", "Occurrence state has changed")
        except AutomationError:
            raise
        except sqlite3.Error as exc:
            raise AutomationError("store_failure", "Occurrence could not be saved") from exc

    @staticmethod
    def _schedule(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["schedule_id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "checks": json.loads(row["checks_json"]),
            "window": json.loads(row["window_json"]),
            "budgets": json.loads(row["budgets_json"]),
            "delivery": json.loads(row["delivery_json"]),
            "owner": {
                "type": row["owner_type"],
                "id": row["owner_id"],
                "username": row["owner_username"],
            },
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "revision": row["revision"],
        }

    @staticmethod
    def _occurrence(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["occurrence_id"],
            "schedule_id": row["schedule_id"],
            "scheduled_for": row["scheduled_for"],
            "state": row["state"],
            "report": json.loads(row["report_json"]) if row["report_json"] else None,
            "terminal_code": row["terminal_code"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }


class ReportSchedulerService:
    """Validate schedules, run bounded reads, and deliver one durable report."""

    def __init__(
        self,
        *,
        store: AutomationStore,
        scheduler: Any,
        diagnostic: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
        reporter: Callable[[Mapping[str, Any]], None],
        trigger_factory: Callable[[str, str], Any],
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self._scheduler = scheduler
        self._diagnostic = diagnostic
        self._reporter = reporter
        self._trigger_factory = trigger_factory
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._configured: dict[str, str] = {}

    def create(self, values: Any, *, owner: Any) -> dict[str, Any]:
        normalized = normalize_schedule(values)
        normalized_owner = _normalize_owner(owner)
        created = self.store.create_schedule(
            schedule_id=self._id_factory(),
            values=normalized,
            owner=normalized_owner,
            at=_iso(self._clock()),
        )
        self._sync_job(created)
        return self._public_schedule(created)

    def update(self, schedule_id: str, values: Any) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise AutomationError("invalid_schedule", "Schedule must be an object")
        expected = SCHEDULE_FIELDS | {"revision"}
        _reject_unknown(values, frozenset(expected), "schedule")
        if set(values) != expected:
            raise AutomationError("invalid_schedule", "Schedule fields are incomplete")
        revision = values.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise AutomationError("invalid_schedule", "Schedule revision is invalid")
        normalized = normalize_schedule(
            {field: values[field] for field in SCHEDULE_FIELDS}
        )
        updated = self.store.update_schedule(
            schedule_id,
            values=normalized,
            expected_revision=revision,
            at=_iso(self._clock()),
        )
        self._sync_job(updated)
        return self._public_schedule(updated)

    def get(self, schedule_id: str) -> dict[str, Any]:
        return self._public_schedule(self.store.get_schedule(schedule_id))

    def list(self) -> dict[str, Any]:
        return {
            "schedules": [
                self._public_schedule(schedule)
                for schedule in self.store.list_schedules()
            ],
            "diagnostic_catalogue": [dict(item) for item in CHECK_CATALOGUE],
        }

    def init_scheduler(self) -> None:
        self.sync_scheduler()
        self._scheduler.add_job(
            self.sync_scheduler,
            "interval",
            id="agent-report:sync",
            replace_existing=True,
            seconds=15,
            coalesce=True,
            max_instances=1,
        )
        if not self._scheduler.running:
            self._scheduler.start()
        self.recover()

    def sync_scheduler(self) -> None:
        schedules = self.store.list_schedules()
        seen = set()
        for schedule in schedules:
            schedule_id = schedule["id"]
            signature = _schedule_signature(schedule)
            if schedule["enabled"]:
                seen.add(schedule_id)
            if self._configured.get(schedule_id) != signature:
                self._sync_job(schedule)
                if schedule["enabled"]:
                    self._configured[schedule_id] = signature
                else:
                    self._configured.pop(schedule_id, None)
        for schedule_id in set(self._configured) - seen:
            try:
                self._scheduler.remove_job(f"agent-report:{schedule_id}")
            except Exception:
                pass
            self._configured.pop(schedule_id, None)

    def recover(self) -> None:
        for occurrence in self.store.incomplete_occurrences():
            if occurrence["state"] == "delivering":
                self.store.mark_delivery_unknown(
                    occurrence["id"], at=_iso(self._clock())
                )
                continue
            schedule = self.store.get_schedule(occurrence["schedule_id"])
            if occurrence["state"] == "running":
                self._execute(schedule, occurrence)
            elif occurrence["state"] == "report_ready":
                self._deliver(occurrence)

    def run(
        self, schedule_id: str, *, scheduled_for: datetime | None = None
    ) -> dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id)
        if not schedule["enabled"]:
            raise AutomationError("schedule_disabled", "Schedule is disabled")
        now = self._clock()
        due = (scheduled_for or now).replace(second=0, microsecond=0)
        due_at = _iso(due)
        occurrence_id = hashlib.sha256(
            f"{schedule_id}:{due_at}".encode("utf-8")
        ).hexdigest()[:32]
        occurrence, created = self.store.begin_occurrence(
            schedule_id=schedule_id,
            occurrence_id=occurrence_id,
            scheduled_for=due_at,
            started_at=_iso(now),
        )
        if not created:
            return occurrence
        return self._execute(schedule, occurrence)

    def _execute(
        self, schedule: Mapping[str, Any], occurrence: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            checks = [self._run_check(check) for check in schedule["checks"]]
            counts = {
                state: sum(check["outcome"] == state for check in checks)
                for state in ("healthy", "attention", "failed")
            }
            status = (
                "partial"
                if counts["failed"]
                else "attention"
                if counts["attention"]
                else "healthy"
            )
            generated_at = _iso(self._clock())
            report = {
                "schedule_id": schedule["id"],
                "schedule_name": schedule["name"],
                "occurrence_id": occurrence["id"],
                "scheduled_for": occurrence["scheduled_for"],
                "generated_at": generated_at,
                "status": status,
                "counts": counts,
                "checks": checks,
            }
            self.store.save_report(
                occurrence["id"], report=report, at=generated_at
            )
        except AutomationError:
            raise
        except Exception as exc:
            self.store.mark_check_failed(occurrence["id"], at=_iso(self._clock()))
            raise AutomationError(
                "check_failed", "Scheduled report could not be generated"
            ) from exc
        return self._deliver(self.store.get_occurrence(occurrence["id"]))

    def _deliver(self, occurrence: Mapping[str, Any]) -> dict[str, Any]:
        claimed_at = _iso(self._clock())
        self.store.claim_delivery(occurrence["id"], at=claimed_at)
        try:
            self._reporter(occurrence["report"])
        except Exception:
            self.store.finish_delivery(
                occurrence["id"], delivered=False, at=_iso(self._clock())
            )
        else:
            self.store.finish_delivery(
                occurrence["id"], delivered=True, at=_iso(self._clock())
            )
        return self.store.get_occurrence(occurrence["id"])

    def _run_check(self, check: Mapping[str, Any]) -> dict[str, Any]:
        operation = check["operation"]
        params = check["params"]
        target = next(iter(params.values()), "host")
        try:
            response = self._diagnostic(operation, params, SYSTEM_ACTOR)
        except Exception:
            response = {
                "ok": False,
                "error": {"code": "unavailable_dependency"},
                "audit_id": "unavailable",
            }
        audit_id = response.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            audit_id = "unavailable"
        if response.get("ok") is not True:
            error = response.get("error")
            code = error.get("code") if isinstance(error, Mapping) else None
            code = code if isinstance(code, str) and code else "upstream_failure"
            return {
                "operation": operation,
                "target": target,
                "outcome": "failed",
                "summary": f"Check failed: {code.replace('_', ' ')}",
                "audit_id": audit_id,
                "error_code": code,
            }
        data = response.get("data")
        summary = _bounded_summary(data)
        return {
            "operation": operation,
            "target": target,
            "outcome": "attention" if _needs_attention(data) else "healthy",
            "summary": summary,
            "audit_id": audit_id,
            "error_code": None,
        }

    def _sync_job(self, schedule: Mapping[str, Any]) -> None:
        job_id = f"agent-report:{schedule['id']}"
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        if not schedule["enabled"]:
            self._configured.pop(schedule["id"], None)
            return
        window = schedule["window"]
        trigger = self._trigger_factory(window["cron"], window["timezone"])
        self._scheduler.add_job(
            self.run,
            trigger,
            id=job_id,
            replace_existing=True,
            args=[schedule["id"]],
            coalesce=True,
            max_instances=1,
            misfire_grace_time=window["duration_minutes"] * 60,
        )
        self._configured[schedule["id"]] = _schedule_signature(schedule)

    def _public_schedule(self, schedule: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(schedule)
        job = self._scheduler.get_job(f"agent-report:{schedule['id']}")
        next_run = getattr(job, "next_run_time", None) if job is not None else None
        value["next_run"] = next_run.isoformat() if next_run is not None else None
        value["last_occurrence"] = self.store.latest_occurrence(schedule["id"])
        return value


class LazyReportSchedulerService:
    """Construct the production scheduler only when its first method is used."""

    def __init__(self, factory: Callable[[], ReportSchedulerService]) -> None:
        self._factory = factory
        self._service: ReportSchedulerService | None = None

    def _get(self) -> ReportSchedulerService:
        if self._service is None:
            self._service = self._factory()
        return self._service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


class ScheduleAdminService:
    """Edit durable schedules without access to the read broker or runner."""

    def __init__(
        self,
        *,
        store: AutomationStore,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def create(self, values: Any, *, owner: Any) -> dict[str, Any]:
        normalized = normalize_schedule(values)
        created = self.store.create_schedule(
            schedule_id=self._id_factory(),
            values=normalized,
            owner=_normalize_owner(owner),
            at=_iso(self._clock()),
        )
        return self._public_schedule(created)

    def update(self, schedule_id: str, values: Any) -> dict[str, Any]:
        revision, normalized = _normalize_schedule_update(values)
        updated = self.store.update_schedule(
            schedule_id,
            values=normalized,
            expected_revision=revision,
            at=_iso(self._clock()),
        )
        return self._public_schedule(updated)

    def get(self, schedule_id: str) -> dict[str, Any]:
        return self._public_schedule(self.store.get_schedule(schedule_id))

    def list(self) -> dict[str, Any]:
        return {
            "schedules": [
                self._public_schedule(schedule)
                for schedule in self.store.list_schedules()
            ],
            "diagnostic_catalogue": [dict(item) for item in CHECK_CATALOGUE],
        }

    def _public_schedule(self, schedule: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(schedule)
        value["next_run"] = _next_run(schedule, self._clock())
        value["last_occurrence"] = self.store.latest_occurrence(schedule["id"])
        return value


class LazyScheduleAdminService:
    """Open the shared schedule store only when the API is first used."""

    def __init__(self, path: str | Path) -> None:
        self._path = path
        self._service: ScheduleAdminService | None = None
        self._lock = threading.Lock()

    def _get(self) -> ScheduleAdminService:
        with self._lock:
            if self._service is None:
                self._service = ScheduleAdminService(
                    store=AutomationStore(self._path)
                )
            return self._service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


def _json(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise AutomationError("invalid_schedule", "Automation data is invalid") from exc


def _normalize_schedule_update(values: Any) -> tuple[int, dict[str, Any]]:
    if not isinstance(values, Mapping):
        raise AutomationError("invalid_schedule", "Schedule must be an object")
    expected = SCHEDULE_FIELDS | {"revision"}
    _reject_unknown(values, frozenset(expected), "schedule")
    if set(values) != expected:
        raise AutomationError("invalid_schedule", "Schedule fields are incomplete")
    revision = values.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise AutomationError("invalid_schedule", "Schedule revision is invalid")
    return revision, normalize_schedule({field: values[field] for field in SCHEDULE_FIELDS})


def _schedule_signature(schedule: Mapping[str, Any]) -> str:
    return _json(
        {
            field: schedule[field]
            for field in ("enabled", "checks", "window", "budgets", "delivery")
        }
    )


def _next_run(schedule: Mapping[str, Any], now: datetime) -> str | None:
    if not schedule["enabled"]:
        return None
    window = schedule["window"]
    trigger = CronTrigger.from_crontab(
        window["cron"], timezone=ZoneInfo(window["timezone"])
    )
    next_fire = trigger.get_next_fire_time(None, now)
    return next_fire.isoformat() if next_fire is not None else None


def _bounded_summary(value: Any) -> str:
    try:
        text = json.dumps(
            _redact_report_value(value), separators=(",", ":"), sort_keys=True
        )
    except (TypeError, ValueError):
        text = "Diagnostic returned invalid data"
    text = redact_text(text)
    return text[:MAX_SUMMARY_CHARS]


def _redact_report_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "[truncated]"
    if isinstance(value, Mapping):
        redacted = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 50:
                redacted["truncated"] = True
                break
            label = str(key)
            redacted[label] = (
                "[redacted]"
                if _SECRET_FIELD.search(label)
                else _redact_report_value(item, depth=depth + 1)
            )
        return redacted
    if isinstance(value, (list, tuple)):
        return [
            _redact_report_value(item, depth=depth + 1) for item in value[:50]
        ]
    if isinstance(value, str):
        return redact_text(value)[:MAX_SUMMARY_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_SUMMARY_CHARS]


def _needs_attention(value: Any) -> bool:
    text = _bounded_summary(value).lower()
    adverse = (
        '"ok":false',
        '"healthy":false',
        '"active_state":"inactive"',
        '"active_state":"failed"',
        '"status":"failed"',
        '"status":"unhealthy"',
        '"status":"exited"',
        '"state":"failed"',
        '"state":"unhealthy"',
        '"state":"exited"',
    )
    return any(marker in text for marker in adverse)
