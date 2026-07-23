"""Durable domain state for code-owned supervised repair assessments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger


ASSESSMENT_INTERVAL_SECONDS = 600
CONSECUTIVE_FAILURE_THRESHOLD = 2
MAX_ACTIONS_PER_TARGET_24H = 1
MAX_ACTIONS_PER_WINDOW = 1
MAX_AUTOMATIC_RETRIES = 0
MAX_CONCURRENT_SUPERVISED_MUTATIONS = 1
ACTION_DEADLINE_SECONDS = 120
SERVICE_PRIORITIES = ("critical", "high", "normal", "low")

SCHEDULE_FIELDS = frozenset(
    {
        "name",
        "enabled",
        "operation",
        "params",
        "service_priority",
        "window",
        "delivery",
    }
)
WINDOW_FIELDS = frozenset({"cron", "timezone", "duration_minutes"})
DELIVERY_FIELDS = frozenset({"channel", "mode"})
OWNER_FIELDS = frozenset({"type", "id", "username"})

SUPERVISED_CATALOGUE = (
    {
        "operation": "container.restart",
        "params": {"name": "get_iplayer"},
        "target": "get_iplayer",
        "risk": "R1",
        "capability_version": "1",
        "assessment_operation": "container.status",
        "assessment_interval_seconds": ASSESSMENT_INTERVAL_SECONDS,
        "failure_threshold": CONSECUTIVE_FAILURE_THRESHOLD,
        "budgets": {
            "max_actions_per_target_24h": MAX_ACTIONS_PER_TARGET_24H,
            "max_actions_per_window": MAX_ACTIONS_PER_WINDOW,
            "max_automatic_retries": MAX_AUTOMATIC_RETRIES,
            "max_concurrent_mutations": MAX_CONCURRENT_SUPERVISED_MUTATIONS,
            "action_deadline_seconds": ACTION_DEADLINE_SECONDS,
        },
    },
)

_CATALOGUE_BY_OPERATION = {
    item["operation"]: item for item in SUPERVISED_CATALOGUE
}
_FAILED_CONTAINER_STATES = frozenset(
    {"stopped", "exited", "dead", "restarting"}
)
_VALID_CONTAINER_STATES = _FAILED_CONTAINER_STATES | {
    "running",
    "created",
    "paused",
    "removing",
}
_VALID_HEALTH_STATES = frozenset({"healthy", "unhealthy", "starting"})
_ASSESSMENT_CODES = {
    "assessment_unavailable": "unknown",
    "malformed_response": "unknown",
    "target_mismatch": "unknown",
    "unrecognized_status": "unknown",
    "unrecognized_health": "unknown",
    "container_state_transitional": "unknown",
    "container_healthy": "healthy",
    "container_stopped": "failed",
    "container_exited": "failed",
    "container_dead": "failed",
    "container_restarting": "failed",
    "container_unhealthy": "failed",
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS supervision_schedules (
    schedule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    operation TEXT NOT NULL,
    params_json TEXT NOT NULL,
    target TEXT NOT NULL,
    service_priority TEXT NOT NULL,
    window_json TEXT NOT NULL,
    delivery_json TEXT NOT NULL,
    owner_type TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    owner_username TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    UNIQUE(operation, target)
);
CREATE INDEX IF NOT EXISTS supervision_schedules_priority_idx
    ON supervision_schedules(enabled, service_priority, updated_at, schedule_id);

CREATE TABLE IF NOT EXISTS supervision_assessments (
    assessment_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES supervision_schedules(schedule_id),
    assessed_for TEXT NOT NULL,
    outcome TEXT NOT NULL,
    code TEXT NOT NULL,
    observed_status TEXT,
    observed_health TEXT,
    audit_id TEXT,
    recorded_at TEXT NOT NULL,
    UNIQUE(schedule_id, assessed_for)
);
CREATE INDEX IF NOT EXISTS supervision_assessments_schedule_idx
    ON supervision_assessments(schedule_id, assessed_for DESC);

CREATE TABLE IF NOT EXISTS supervision_incidents (
    incident_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES supervision_schedules(schedule_id),
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    state TEXT NOT NULL,
    consecutive_failures INTEGER NOT NULL,
    last_assessment_id TEXT NOT NULL
        REFERENCES supervision_assessments(assessment_id),
    thread_id TEXT,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    terminal_code TEXT,
    last_action_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS supervision_incidents_active_target_idx
    ON supervision_incidents(operation, target)
    WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS supervision_incidents_schedule_idx
    ON supervision_incidents(schedule_id, opened_at DESC);

CREATE TABLE IF NOT EXISTS supervision_incident_transitions (
    transition_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES supervision_incidents(incident_id),
    transition_key TEXT NOT NULL UNIQUE,
    transition_type TEXT NOT NULL,
    assessment_id TEXT REFERENCES supervision_assessments(assessment_id),
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS supervision_transitions_incident_idx
    ON supervision_incident_transitions(incident_id, created_at, transition_id);

CREATE TABLE IF NOT EXISTS supervision_budget_charges (
    charge_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES supervision_schedules(schedule_id),
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    window_key TEXT NOT NULL,
    occurrence_key TEXT NOT NULL UNIQUE,
    action_id TEXT NOT NULL UNIQUE,
    charged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS supervision_budget_target_idx
    ON supervision_budget_charges(operation, target, charged_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS supervision_budget_window_idx
    ON supervision_budget_charges(operation, target, window_key);

CREATE TABLE IF NOT EXISTS supervision_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    schedule_id TEXT NOT NULL REFERENCES supervision_schedules(schedule_id),
    assessed_for TEXT NOT NULL,
    state TEXT NOT NULL,
    assessment_id TEXT,
    incident_id TEXT,
    action_id TEXT,
    terminal_code TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(schedule_id, assessed_for)
);
CREATE INDEX IF NOT EXISTS supervision_occurrences_state_idx
    ON supervision_occurrences(state, assessed_for, occurrence_id);

CREATE TABLE IF NOT EXISTS supervision_deliveries (
    delivery_id TEXT PRIMARY KEY,
    transition_id TEXT NOT NULL UNIQUE
        REFERENCES supervision_incident_transitions(transition_id),
    incident_id TEXT NOT NULL REFERENCES supervision_incidents(incident_id),
    state TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS supervision_deliveries_state_idx
    ON supervision_deliveries(state, created_at, delivery_id);
"""

_DELIVERED_TRANSITIONS = frozenset(
    {
        "fault_confirmed",
        "fault_reconfirmed",
        "infrastructure_blocked",
        "window_deferred",
        "active_action_deferred",
        "budget_blocked",
        "supervision_blocked",
        "action_authorized",
        "action_started",
        "verification_started",
        "escalated",
        "demoted",
        "recovered",
        "recovered_after_action",
    }
)


class SupervisionError(RuntimeError):
    """A bounded error safe to expose through a later administrator API."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime, *, label: str = "Time") -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SupervisionError("invalid_time", f"{label} must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise SupervisionError("store_failure", "Stored supervision time is invalid") from exc
    if parsed.tzinfo is None:
        raise SupervisionError("store_failure", "Stored supervision time is invalid")
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], label: str
) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise SupervisionError(
            "invalid_schedule", f"Unknown {label} field: {sorted(unknown)[0]}"
        )


def _short_string(
    value: Any,
    label: str,
    *,
    maximum: int = 128,
    error_code: str = "invalid_schedule",
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(character in value for character in "\x00\r\n")
    ):
        raise SupervisionError(error_code, f"{label} must be a short string")
    return value.strip()


def _identifier(
    value: Any, label: str, *, error_code: str = "invalid_identifier"
) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise SupervisionError(error_code, f"{label} is invalid")
    return value


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise SupervisionError(
            "invalid_schedule", f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _normalize_owner(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != OWNER_FIELDS:
        raise SupervisionError("invalid_owner", "Schedule owner is invalid")
    actor_type = raw.get("type")
    if actor_type not in {"local", "mattermost", "system"}:
        raise SupervisionError("invalid_owner", "Schedule owner is invalid")
    actor_id = _short_string(
        raw.get("id"), "Schedule owner ID", error_code="invalid_owner"
    )
    username = raw.get("username")
    if username is not None:
        username = _short_string(
            username, "Schedule owner username", error_code="invalid_owner"
        )
    return {"type": actor_type, "id": actor_id, "username": username}


def normalize_schedule(raw: Any) -> dict[str, Any]:
    """Validate administrator input and attach only server-owned repair metadata."""

    if not isinstance(raw, Mapping):
        raise SupervisionError("invalid_schedule", "Schedule must be an object")
    _reject_unknown(raw, SCHEDULE_FIELDS, "schedule")
    if set(raw) != SCHEDULE_FIELDS:
        raise SupervisionError("invalid_schedule", "Schedule fields are incomplete")

    name = _short_string(raw.get("name"), "Schedule name", maximum=120)
    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise SupervisionError(
            "invalid_schedule", "Schedule enabled must be a boolean"
        )

    operation = _short_string(raw.get("operation"), "Schedule operation")
    catalogue = _CATALOGUE_BY_OPERATION.get(operation)
    if catalogue is None:
        raise SupervisionError(
            "invalid_schedule", "Operation is not registered for supervised repair"
        )
    params = raw.get("params")
    if not isinstance(params, Mapping) or dict(params) != catalogue["params"]:
        raise SupervisionError(
            "invalid_schedule", "Operation parameters are not a registered target"
        )

    priority = raw.get("service_priority")
    if priority not in SERVICE_PRIORITIES:
        raise SupervisionError(
            "invalid_schedule", "Service priority is not registered"
        )

    window_raw = raw.get("window")
    if not isinstance(window_raw, Mapping):
        raise SupervisionError(
            "invalid_schedule", "Schedule window must be an object"
        )
    _reject_unknown(window_raw, WINDOW_FIELDS, "window")
    if set(window_raw) != WINDOW_FIELDS:
        raise SupervisionError(
            "invalid_schedule", "Schedule window fields are incomplete"
        )
    cron = _short_string(window_raw.get("cron"), "Schedule cron", maximum=120)
    timezone_name = _short_string(
        window_raw.get("timezone"), "Schedule timezone", maximum=64
    )
    try:
        zone = ZoneInfo(timezone_name)
        CronTrigger.from_crontab(cron, timezone=zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise SupervisionError(
            "invalid_schedule", "Schedule cron or timezone is invalid"
        ) from exc
    window = {
        "cron": cron,
        "timezone": timezone_name,
        "duration_minutes": _integer(
            window_raw.get("duration_minutes"), "Window duration", 1, 1440
        ),
    }

    delivery = raw.get("delivery")
    if not isinstance(delivery, Mapping):
        raise SupervisionError(
            "invalid_schedule", "Schedule delivery must be an object"
        )
    _reject_unknown(delivery, DELIVERY_FIELDS, "delivery")
    if dict(delivery) != {
        "channel": "mattermost-alerts",
        "mode": "threaded",
    }:
        raise SupervisionError(
            "invalid_schedule",
            "Supervised repair delivery must use threaded mattermost-alerts",
        )

    return {
        "name": name,
        "enabled": enabled,
        "operation": operation,
        "params": dict(catalogue["params"]),
        "target": catalogue["target"],
        "service_priority": priority,
        "window": window,
        "delivery": {
            "channel": "mattermost-alerts",
            "mode": "threaded",
        },
        "risk": catalogue["risk"],
        "capability_version": catalogue["capability_version"],
        "assessment_operation": catalogue["assessment_operation"],
        "assessment_interval_seconds": catalogue[
            "assessment_interval_seconds"
        ],
        "failure_threshold": catalogue["failure_threshold"],
        "budgets": dict(catalogue["budgets"]),
    }


def assessment_bucket(value: datetime) -> datetime:
    """Return the deterministic UTC ten-minute bucket containing ``value``."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SupervisionError(
            "invalid_time", "Assessment time must include a timezone"
        )
    utc_value = value.astimezone(timezone.utc)
    epoch = int(utc_value.timestamp())
    bucket = epoch - (epoch % ASSESSMENT_INTERVAL_SECONDS)
    return datetime.fromtimestamp(bucket, timezone.utc)


def classify_container_status(
    response: Any, *, expected_target: str
) -> dict[str, Any]:
    """Reduce a broker envelope to bounded health evidence without raw payloads."""

    target = _identifier(
        expected_target, "Assessment target", error_code="invalid_assessment"
    )
    audit_id = None
    if isinstance(response, Mapping):
        candidate_audit_id = response.get("audit_id")
        if isinstance(candidate_audit_id, str) and _IDENTIFIER_RE.fullmatch(
            candidate_audit_id
        ):
            audit_id = candidate_audit_id

    if not isinstance(response, Mapping) or response.get("ok") is not True:
        return {
            "outcome": "unknown",
            "code": "assessment_unavailable",
            "observed_status": None,
            "observed_health": None,
            "audit_id": audit_id,
        }
    data = response.get("data")
    if not isinstance(data, Mapping):
        return {
            "outcome": "unknown",
            "code": "malformed_response",
            "observed_status": None,
            "observed_health": None,
            "audit_id": audit_id,
        }
    if data.get("name") != target:
        return {
            "outcome": "unknown",
            "code": "target_mismatch",
            "observed_status": None,
            "observed_health": None,
            "audit_id": audit_id,
        }

    status = data.get("status")
    health = data.get("health")
    if not isinstance(status, str) or status not in _VALID_CONTAINER_STATES:
        return {
            "outcome": "unknown",
            "code": "unrecognized_status",
            "observed_status": None,
            "observed_health": None,
            "audit_id": audit_id,
        }
    if health is not None and (
        not isinstance(health, str) or health not in _VALID_HEALTH_STATES
    ):
        return {
            "outcome": "unknown",
            "code": "unrecognized_health",
            "observed_status": status,
            "observed_health": None,
            "audit_id": audit_id,
        }
    if status in _FAILED_CONTAINER_STATES:
        outcome, code = "failed", f"container_{status}"
    elif health == "unhealthy":
        outcome, code = "failed", "container_unhealthy"
    elif status == "running" and health in {None, "healthy"}:
        outcome, code = "healthy", "container_healthy"
    else:
        outcome, code = "unknown", "container_state_transitional"
    return {
        "outcome": outcome,
        "code": code,
        "observed_status": status,
        "observed_health": health,
        "audit_id": audit_id,
    }


def _validate_assessment_record(
    assessed_for: Any,
    evidence: Any,
    recorded_at: Any,
) -> None:
    if not isinstance(assessed_for, str) or not isinstance(recorded_at, str):
        raise SupervisionError(
            "invalid_assessment", "Assessment times are invalid"
        )
    try:
        assessed = datetime.fromisoformat(assessed_for)
        recorded = datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise SupervisionError(
            "invalid_assessment", "Assessment times are invalid"
        ) from exc
    if (
        assessed.tzinfo is None
        or recorded.tzinfo is None
        or _iso(assessed) != assessed_for
        or _iso(recorded) != recorded_at
        or assessment_bucket(assessed) != assessed
    ):
        raise SupervisionError(
            "invalid_assessment", "Assessment times are invalid"
        )
    fields = {
        "outcome",
        "code",
        "observed_status",
        "observed_health",
        "audit_id",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != fields:
        raise SupervisionError(
            "invalid_assessment", "Assessment evidence is invalid"
        )
    code = evidence.get("code")
    outcome = evidence.get("outcome")
    if _ASSESSMENT_CODES.get(code) != outcome:
        raise SupervisionError(
            "invalid_assessment", "Assessment evidence is invalid"
        )
    status = evidence.get("observed_status")
    health = evidence.get("observed_health")
    if status is not None and status not in _VALID_CONTAINER_STATES:
        raise SupervisionError(
            "invalid_assessment", "Assessment evidence is invalid"
        )
    if health is not None and health not in _VALID_HEALTH_STATES:
        raise SupervisionError(
            "invalid_assessment", "Assessment evidence is invalid"
        )
    audit_id = evidence.get("audit_id")
    if audit_id is not None and (
        not isinstance(audit_id, str)
        or _IDENTIFIER_RE.fullmatch(audit_id) is None
    ):
        raise SupervisionError(
            "invalid_assessment", "Assessment evidence is invalid"
        )


def _validate_occurrence_times(assessed_for: str, started_at: str) -> None:
    try:
        assessed = _parse_iso(assessed_for)
        started = _parse_iso(started_at)
    except SupervisionError as exc:
        raise SupervisionError(
            "invalid_occurrence", "Assessment occurrence times are invalid"
        ) from exc
    if (
        _iso(assessed) != assessed_for
        or _iso(started) != started_at
        or assessment_bucket(assessed) != assessed
        or assessed > started
    ):
        raise SupervisionError(
            "invalid_occurrence", "Assessment occurrence times are invalid"
        )


def _normalize_transition_details(details: Any) -> dict[str, Any]:
    if not isinstance(details, Mapping) or len(details) > 8:
        raise SupervisionError(
            "invalid_transition", "Incident transition details are invalid"
        )
    normalized: dict[str, Any] = {}
    for key, value in details.items():
        name = _identifier(
            key, "Transition detail name", error_code="invalid_transition"
        )
        if value is None or isinstance(value, bool):
            normalized[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            if not -(2**31) <= value <= 2**31 - 1:
                raise SupervisionError(
                    "invalid_transition",
                    "Incident transition details are invalid",
                )
            normalized[name] = value
        elif isinstance(value, str):
            normalized[name] = _short_string(
                value,
                "Transition detail",
                maximum=256,
                error_code="invalid_transition",
            )
        else:
            raise SupervisionError(
                "invalid_transition", "Incident transition details are invalid"
            )
    return normalized


class SupervisionStore:
    """Private SQLite state with transactional assessment and incident updates."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        if self._path.is_symlink():
            raise SupervisionError(
                "unsafe_store", "Supervision store cannot be a symlink"
            )
        try:
            with self._connect() as connection:
                connection.executescript(_SCHEMA)
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(supervision_incidents)"
                    ).fetchall()
                }
                if "last_action_id" not in columns:
                    connection.execute(
                        "ALTER TABLE supervision_incidents "
                        "ADD COLUMN last_action_id TEXT"
                    )
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
            raise SupervisionError(
                "store_unavailable", "Supervision store is unavailable"
            ) from exc

    def create_schedule(
        self,
        *,
        schedule_id: str,
        values: Mapping[str, Any],
        owner: Mapping[str, Any],
        at: str,
    ) -> dict[str, Any]:
        _identifier(schedule_id, "Schedule ID")
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO supervision_schedules (
                        schedule_id, name, enabled, operation, params_json,
                        target, service_priority, window_json, delivery_json,
                        owner_type, owner_id, owner_username, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule_id,
                        values["name"],
                        int(values["enabled"]),
                        values["operation"],
                        _json(values["params"]),
                        values["target"],
                        values["service_priority"],
                        _json(values["window"]),
                        _json(values["delivery"]),
                        owner["type"],
                        owner["id"],
                        owner.get("username"),
                        at,
                        at,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
            return self._schedule(row)
        except sqlite3.IntegrityError as exc:
            raise SupervisionError(
                "conflict", "A schedule already owns this repair target"
            ) from exc
        except (KeyError, TypeError, sqlite3.Error) as exc:
            raise SupervisionError(
                "store_failure", "Schedule could not be saved"
            ) from exc

    def update_schedule(
        self,
        schedule_id: str,
        *,
        values: Mapping[str, Any],
        expected_revision: int,
        at: str,
    ) -> dict[str, Any]:
        _identifier(schedule_id, "Schedule ID")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT revision, operation, target
                    FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
                if row is None:
                    raise SupervisionError(
                        "not_found", "Schedule was not found"
                    )
                if row["revision"] != expected_revision:
                    raise SupervisionError(
                        "conflict", "Schedule changed concurrently"
                    )
                if (
                    row["operation"] != values["operation"]
                    or row["target"] != values["target"]
                ):
                    raise SupervisionError(
                        "invalid_schedule",
                        "Schedule operation and target cannot be changed",
                    )
                cursor = connection.execute(
                    """
                    UPDATE supervision_schedules SET
                        name = ?, enabled = ?, params_json = ?,
                        service_priority = ?, window_json = ?,
                        delivery_json = ?, updated_at = ?, revision = revision + 1
                    WHERE schedule_id = ? AND revision = ?
                    """,
                    (
                        values["name"],
                        int(values["enabled"]),
                        _json(values["params"]),
                        values["service_priority"],
                        _json(values["window"]),
                        _json(values["delivery"]),
                        at,
                        schedule_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise SupervisionError(
                        "conflict", "Schedule changed concurrently"
                    )
                updated = connection.execute(
                    """
                    SELECT * FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
            return self._schedule(updated)
        except SupervisionError:
            raise
        except (KeyError, TypeError, sqlite3.Error) as exc:
            raise SupervisionError(
                "store_failure", "Schedule could not be saved"
            ) from exc

    def get_schedule(self, schedule_id: str) -> dict[str, Any]:
        _identifier(schedule_id, "Schedule ID")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Schedule could not be read"
            ) from exc
        if row is None:
            raise SupervisionError("not_found", "Schedule was not found")
        return self._schedule(row)

    def list_schedules(self) -> list[dict[str, Any]]:
        priority = (
            "CASE service_priority "
            "WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'normal' THEN 2 ELSE 3 END"
        )
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM supervision_schedules
                    ORDER BY enabled DESC, {priority}, updated_at, schedule_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Schedules could not be read"
            ) from exc
        return [self._schedule(row) for row in rows]

    def record_assessment(
        self,
        *,
        schedule_id: str,
        assessed_for: str,
        evidence: Mapping[str, Any],
        recorded_at: str,
    ) -> dict[str, Any]:
        """Insert one bucket and atomically apply it to incident state once."""

        _identifier(schedule_id, "Schedule ID")
        _validate_assessment_record(assessed_for, evidence, recorded_at)
        assessment_id = self._stable_id(
            "assessment", schedule_id, assessed_for
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                schedule = connection.execute(
                    """
                    SELECT * FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
                if schedule is None:
                    raise SupervisionError(
                        "not_found", "Schedule was not found"
                    )
                existing = connection.execute(
                    """
                    SELECT * FROM supervision_assessments
                    WHERE schedule_id = ? AND assessed_for = ?
                    """,
                    (schedule_id, assessed_for),
                ).fetchone()
                if existing is not None:
                    incident = self._incident_for_assessment(
                        connection, existing["assessment_id"]
                    )
                    return {
                        "assessment": self._assessment(existing),
                        "incident": (
                            self._incident(incident)
                            if incident is not None
                            else None
                        ),
                        "created": False,
                        "transition": None,
                    }
                connection.execute(
                    """
                    INSERT INTO supervision_assessments (
                        assessment_id, schedule_id, assessed_for, outcome, code,
                        observed_status, observed_health, audit_id, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment_id,
                        schedule_id,
                        assessed_for,
                        evidence["outcome"],
                        evidence["code"],
                        evidence.get("observed_status"),
                        evidence.get("observed_health"),
                        evidence.get("audit_id"),
                        recorded_at,
                    ),
                )
                assessment = connection.execute(
                    """
                    SELECT * FROM supervision_assessments
                    WHERE assessment_id = ?
                    """,
                    (assessment_id,),
                ).fetchone()
                latest = connection.execute(
                    """
                    SELECT assessment_id FROM supervision_assessments
                    WHERE schedule_id = ?
                    ORDER BY assessed_for DESC, assessment_id DESC LIMIT 1
                    """,
                    (schedule_id,),
                ).fetchone()
                incident = None
                transition = None
                if latest["assessment_id"] == assessment_id:
                    incident, transition = self._apply_assessment(
                        connection,
                        schedule=schedule,
                        assessment=assessment,
                        recorded_at=recorded_at,
                    )
            return {
                "assessment": self._assessment(assessment),
                "incident": (
                    self._incident(incident) if incident is not None else None
                ),
                "created": True,
                "transition": (
                    self._transition(transition)
                    if transition is not None
                    else None
                ),
            }
        except SupervisionError:
            raise
        except (KeyError, TypeError, sqlite3.Error) as exc:
            raise SupervisionError(
                "store_failure", "Assessment could not be saved"
            ) from exc

    def list_assessments(
        self, schedule_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        _identifier(schedule_id, "Schedule ID")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise SupervisionError(
                "invalid_limit", "Assessment limit must be between 1 and 100"
            )
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM supervision_assessments
                    WHERE schedule_id = ?
                    ORDER BY assessed_for DESC, assessment_id DESC LIMIT ?
                    """,
                    (schedule_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessments could not be read"
            ) from exc
        return [self._assessment(row) for row in rows]

    def get_assessment(self, assessment_id: str) -> dict[str, Any]:
        _identifier(assessment_id, "Assessment ID")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_assessments
                    WHERE assessment_id = ?
                    """,
                    (assessment_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment could not be read"
            ) from exc
        if row is None:
            raise SupervisionError(
                "not_found", "Assessment was not found"
            )
        return self._assessment(row)

    def list_incidents(
        self, *, schedule_id: str | None = None
    ) -> list[dict[str, Any]]:
        parameters: tuple[Any, ...] = ()
        clause = ""
        if schedule_id is not None:
            _identifier(schedule_id, "Schedule ID")
            clause = "WHERE schedule_id = ?"
            parameters = (schedule_id,)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT * FROM supervision_incidents {clause}
                    ORDER BY (resolved_at IS NULL) DESC, opened_at DESC, incident_id
                    """,
                    parameters,
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incidents could not be read"
            ) from exc
        return [self._incident(row) for row in rows]

    def get_incident(self, incident_id: str) -> dict[str, Any]:
        _identifier(incident_id, "Incident ID")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_incidents WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident could not be read"
            ) from exc
        if row is None:
            raise SupervisionError("not_found", "Incident was not found")
        return self._incident(row)

    def list_transitions(self, incident_id: str) -> list[dict[str, Any]]:
        _identifier(incident_id, "Incident ID")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM supervision_incident_transitions
                    WHERE incident_id = ?
                    ORDER BY created_at, rowid
                    """,
                    (incident_id,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident transitions could not be read"
            ) from exc
        return [self._transition(row) for row in rows]

    def get_transition(self, transition_id: str) -> dict[str, Any]:
        _identifier(transition_id, "Transition ID")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_incident_transitions
                    WHERE transition_id = ?
                    """,
                    (transition_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident transition could not be read"
            ) from exc
        if row is None:
            raise SupervisionError(
                "not_found", "Incident transition was not found"
            )
        return self._transition(row)

    def begin_occurrence(
        self,
        *,
        schedule_id: str,
        assessed_for: str,
        started_at: str,
    ) -> tuple[dict[str, Any], bool]:
        """Claim one schedule bucket without duplicating work after overlap."""

        _identifier(schedule_id, "Schedule ID")
        _validate_occurrence_times(assessed_for, started_at)
        occurrence_id = self._stable_id(
            "occurrence", schedule_id, assessed_for
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                schedule = connection.execute(
                    """
                    SELECT 1 FROM supervision_schedules
                    WHERE schedule_id = ? AND enabled = 1
                    """,
                    (schedule_id,),
                ).fetchone()
                if schedule is None:
                    raise SupervisionError(
                        "schedule_disabled", "Schedule is disabled"
                    )
                existing = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE schedule_id = ? AND assessed_for = ?
                    """,
                    (schedule_id, assessed_for),
                ).fetchone()
                if existing is not None:
                    return self._occurrence(existing), False
                connection.execute(
                    """
                    INSERT INTO supervision_occurrences (
                        occurrence_id, schedule_id, assessed_for, state,
                        started_at, updated_at
                    ) VALUES (?, ?, ?, 'claimed', ?, ?)
                    """,
                    (
                        occurrence_id,
                        schedule_id,
                        assessed_for,
                        started_at,
                        started_at,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
            return self._occurrence(row), True
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment occurrence could not be claimed"
            ) from exc

    def mark_occurrence_assessed(
        self,
        occurrence_id: str,
        *,
        assessment_id: str,
        incident_id: str | None,
        at: str,
    ) -> dict[str, Any]:
        _identifier(occurrence_id, "Occurrence ID")
        _identifier(assessment_id, "Assessment ID")
        if incident_id is not None:
            _identifier(incident_id, "Incident ID")
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
                if row is None:
                    raise SupervisionError(
                        "not_found", "Assessment occurrence was not found"
                    )
                if row["state"] == "completed":
                    return self._occurrence(row)
                if row["state"] == "assessed":
                    if (
                        row["assessment_id"] != assessment_id
                        or row["incident_id"] != incident_id
                    ):
                        raise SupervisionError(
                            "conflict",
                            "Assessment occurrence changed concurrently",
                        )
                    return self._occurrence(row)
                cursor = connection.execute(
                    """
                    UPDATE supervision_occurrences SET
                        state = 'assessed', assessment_id = ?,
                        incident_id = ?, updated_at = ?
                    WHERE occurrence_id = ? AND state = 'claimed'
                    """,
                    (assessment_id, incident_id, at, occurrence_id),
                )
                if cursor.rowcount != 1:
                    raise SupervisionError(
                        "conflict",
                        "Assessment occurrence changed concurrently",
                    )
                updated = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
            return self._occurrence(updated)
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment occurrence could not be updated"
            ) from exc

    def link_occurrence_action(
        self,
        occurrence_id: str,
        *,
        incident_id: str,
        action_id: str,
        at: str,
    ) -> dict[str, Any]:
        """Atomically bind the authorised action to its occurrence and incident."""

        for value, label in (
            (occurrence_id, "Occurrence ID"),
            (incident_id, "Incident ID"),
            (action_id, "Action ID"),
        ):
            _identifier(value, label)
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                occurrence = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
                if occurrence is None:
                    raise SupervisionError(
                        "not_found", "Assessment occurrence was not found"
                    )
                if occurrence["action_id"] is not None:
                    if (
                        occurrence["action_id"] != action_id
                        or occurrence["incident_id"] != incident_id
                    ):
                        raise SupervisionError(
                            "conflict",
                            "Assessment occurrence belongs to another action",
                        )
                    return self._occurrence(occurrence)
                incident = connection.execute(
                    """
                    SELECT * FROM supervision_incidents
                    WHERE incident_id = ? AND resolved_at IS NULL
                    """,
                    (incident_id,),
                ).fetchone()
                if (
                    incident is None
                    or occurrence["state"] != "assessed"
                    or occurrence["incident_id"] != incident_id
                ):
                    raise SupervisionError(
                        "incident_changed",
                        "Supervision incident changed before action binding",
                    )
                connection.execute(
                    """
                    UPDATE supervision_occurrences SET
                        action_id = ?, updated_at = ?
                    WHERE occurrence_id = ?
                    """,
                    (action_id, at, occurrence_id),
                )
                connection.execute(
                    """
                    UPDATE supervision_incidents SET
                        state = 'action_authorized', last_action_id = ?,
                        updated_at = ?, revision = revision + 1
                    WHERE incident_id = ?
                    """,
                    (action_id, at, incident_id),
                )
                self._add_runtime_transition(
                    connection,
                    incident_id=incident_id,
                    transition_key=f"action:{action_id}:authorised",
                    transition_type="action_authorized",
                    details={
                        "action_id": action_id,
                        "action_state": "authorised",
                    },
                    at=at,
                )
                updated = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
            return self._occurrence(updated)
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Supervised action binding could not be saved"
            ) from exc

    def finish_occurrence(
        self,
        occurrence_id: str,
        *,
        terminal_code: str,
        at: str,
    ) -> dict[str, Any]:
        _identifier(occurrence_id, "Occurrence ID")
        code = _identifier(terminal_code, "Terminal code")
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE supervision_occurrences SET
                        state = 'completed', terminal_code = ?,
                        updated_at = ?, finished_at = COALESCE(finished_at, ?)
                    WHERE occurrence_id = ? AND state != 'completed'
                    """,
                    (code, at, at, occurrence_id),
                )
                row = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment occurrence could not be completed"
            ) from exc
        if row is None:
            raise SupervisionError(
                "not_found", "Assessment occurrence was not found"
            )
        return self._occurrence(row)

    def incomplete_occurrences(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE state != 'completed'
                    ORDER BY assessed_for, occurrence_id
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment occurrences could not be read"
            ) from exc
        return [self._occurrence(row) for row in rows]

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        _identifier(occurrence_id, "Occurrence ID")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_occurrences
                    WHERE occurrence_id = ?
                    """,
                    (occurrence_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Assessment occurrence could not be read"
            ) from exc
        if row is None:
            raise SupervisionError(
                "not_found", "Assessment occurrence was not found"
            )
        return self._occurrence(row)

    def record_incident_event(
        self,
        incident_id: str,
        *,
        transition_key: str,
        transition_type: str,
        details: Mapping[str, Any],
        state: str | None,
        terminal_code: str | None,
        resolved: bool,
        at: str,
    ) -> tuple[dict[str, Any], bool]:
        """Record one code-owned incident transition with durable deduplication."""

        _identifier(incident_id, "Incident ID")
        key = _short_string(
            transition_key,
            "Transition key",
            maximum=256,
            error_code="invalid_transition",
        )
        kind = _identifier(
            transition_type,
            "Transition type",
            error_code="invalid_transition",
        )
        if kind not in _DELIVERED_TRANSITIONS:
            raise SupervisionError(
                "invalid_transition", "Incident transition is unavailable"
            )
        normalized_details = _normalize_transition_details(details)
        if state is not None:
            state = _identifier(
                state, "Incident state", error_code="invalid_transition"
            )
        if terminal_code is not None:
            terminal_code = _identifier(
                terminal_code,
                "Incident terminal code",
                error_code="invalid_transition",
            )
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT * FROM supervision_incident_transitions
                    WHERE transition_key = ?
                    """,
                    (key,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["incident_id"] != incident_id
                        or existing["transition_type"] != kind
                        or json.loads(existing["details_json"])
                        != normalized_details
                    ):
                        raise SupervisionError(
                            "conflict",
                            "Incident transition conflicts with stored evidence",
                        )
                    if state is not None:
                        connection.execute(
                            """
                            UPDATE supervision_incidents SET
                                state = ?, terminal_code = ?,
                                updated_at = ?,
                                resolved_at = CASE
                                    WHEN ? THEN COALESCE(resolved_at, ?)
                                    ELSE resolved_at
                                END,
                                revision = CASE
                                    WHEN state != ? OR terminal_code IS NOT ?
                                         OR (? AND resolved_at IS NULL)
                                    THEN revision + 1 ELSE revision
                                END
                            WHERE incident_id = ?
                            """,
                            (
                                state,
                                terminal_code,
                                at,
                                int(resolved),
                                at,
                                state,
                                terminal_code,
                                int(resolved),
                                incident_id,
                            ),
                        )
                    return self._transition(existing), False
                incident = connection.execute(
                    """
                    SELECT * FROM supervision_incidents
                    WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()
                if incident is None:
                    raise SupervisionError(
                        "not_found", "Incident was not found"
                    )
                if incident["resolved_at"] is not None and not resolved:
                    raise SupervisionError(
                        "incident_changed", "Incident is already resolved"
                    )
                if state is not None:
                    connection.execute(
                        """
                        UPDATE supervision_incidents SET
                            state = ?, terminal_code = ?,
                            updated_at = ?,
                            resolved_at = CASE WHEN ? THEN ? ELSE resolved_at END,
                            revision = revision + 1
                        WHERE incident_id = ?
                        """,
                        (
                            state,
                            terminal_code,
                            at,
                            int(resolved),
                            at,
                            incident_id,
                        ),
                    )
                transition = self._add_runtime_transition(
                    connection,
                    incident_id=incident_id,
                    transition_key=key,
                    transition_type=kind,
                    details=normalized_details,
                    at=at,
                )
            return self._transition(transition), True
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident transition could not be saved"
            ) from exc

    def pending_deliveries(self) -> list[dict[str, Any]]:
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM supervision_deliveries
                    WHERE state = 'pending'
                    ORDER BY created_at, rowid
                    """
                ).fetchall()
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident deliveries could not be read"
            ) from exc
        return [self._delivery(row) for row in rows]

    def claim_delivery(self, delivery_id: str, *, at: str) -> dict[str, Any]:
        _identifier(delivery_id, "Delivery ID")
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT d.*, i.thread_id AS incident_thread_id
                    FROM supervision_deliveries d
                    JOIN supervision_incidents i
                      ON i.incident_id = d.incident_id
                    WHERE d.delivery_id = ?
                    """,
                    (delivery_id,),
                ).fetchone()
                if row is None:
                    raise SupervisionError(
                        "not_found", "Incident delivery was not found"
                    )
                if row["state"] != "pending":
                    raise SupervisionError(
                        "delivery_changed", "Incident delivery is not pending"
                    )
                if (
                    row["message_kind"] == "reply"
                    and row["incident_thread_id"] is None
                ):
                    raise SupervisionError(
                        "thread_unavailable",
                        "Incident thread is unavailable",
                    )
                connection.execute(
                    """
                    UPDATE supervision_deliveries SET
                        state = 'delivering', updated_at = ?
                    WHERE delivery_id = ? AND state = 'pending'
                    """,
                    (at, delivery_id),
                )
                updated = connection.execute(
                    """
                    SELECT d.*, i.thread_id AS incident_thread_id
                    FROM supervision_deliveries d
                    JOIN supervision_incidents i
                      ON i.incident_id = d.incident_id
                    WHERE d.delivery_id = ?
                    """,
                    (delivery_id,),
                ).fetchone()
            return self._delivery(updated)
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident delivery could not be claimed"
            ) from exc

    def finish_delivery(
        self,
        delivery_id: str,
        *,
        delivered: bool,
        post_id: str | None,
        at: str,
    ) -> dict[str, Any]:
        _identifier(delivery_id, "Delivery ID")
        if delivered:
            _identifier(post_id, "Mattermost post ID")
        elif post_id is not None:
            raise SupervisionError(
                "invalid_delivery", "Failed delivery cannot include a post ID"
            )
        _parse_iso(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT * FROM supervision_deliveries
                    WHERE delivery_id = ?
                    """,
                    (delivery_id,),
                ).fetchone()
                if row is None:
                    raise SupervisionError(
                        "not_found", "Incident delivery was not found"
                    )
                if row["state"] != "delivering":
                    raise SupervisionError(
                        "delivery_changed", "Incident delivery is not active"
                    )
                state = "delivered" if delivered else "failed"
                connection.execute(
                    """
                    UPDATE supervision_deliveries SET
                        state = ?, thread_id = ?, updated_at = ?,
                        delivered_at = CASE WHEN ? THEN ? ELSE NULL END
                    WHERE delivery_id = ?
                    """,
                    (state, post_id, at, int(delivered), at, delivery_id),
                )
                if delivered and row["message_kind"] == "root":
                    cursor = connection.execute(
                        """
                        UPDATE supervision_incidents SET
                            thread_id = ?, updated_at = ?,
                            revision = revision + 1
                        WHERE incident_id = ? AND thread_id IS NULL
                        """,
                        (post_id, at, row["incident_id"]),
                    )
                    if cursor.rowcount != 1:
                        raise SupervisionError(
                            "conflict", "Incident thread changed concurrently"
                        )
                updated = connection.execute(
                    """
                    SELECT d.*, i.thread_id AS incident_thread_id
                    FROM supervision_deliveries d
                    JOIN supervision_incidents i
                      ON i.incident_id = d.incident_id
                    WHERE d.delivery_id = ?
                    """,
                    (delivery_id,),
                ).fetchone()
            return self._delivery(updated)
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident delivery could not be completed"
            ) from exc

    def recover_deliveries(self, *, at: str) -> int:
        """Fail closed for posts whose outcome became unknowable after restart."""

        _parse_iso(at)
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE supervision_deliveries SET
                        state = 'delivery_unknown', updated_at = ?
                    WHERE state = 'delivering'
                    """,
                    (at,),
                )
                return cursor.rowcount
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Incident delivery recovery failed"
            ) from exc

    def charge_budget(
        self,
        *,
        schedule_id: str,
        window_key: str,
        occurrence_key: str,
        action_id: str,
        charged_at: datetime,
    ) -> dict[str, Any]:
        """Charge fixed disruption limits once for a newly created action."""

        _identifier(schedule_id, "Schedule ID")
        _identifier(window_key, "Window key")
        _identifier(occurrence_key, "Occurrence key")
        _identifier(action_id, "Action ID")
        charged_at_value = _iso(charged_at, label="Budget charge time")
        cutoff = _iso(
            charged_at - timedelta(hours=24), label="Budget charge time"
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT * FROM supervision_budget_charges
                    WHERE occurrence_key = ?
                    """,
                    (occurrence_key,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["schedule_id"] != schedule_id
                        or existing["window_key"] != window_key
                        or existing["action_id"] != action_id
                    ):
                        raise SupervisionError(
                            "conflict",
                            "Budget occurrence is bound to another action",
                        )
                    return {
                        "charge": self._budget_charge(existing),
                        "created": False,
                    }
                schedule = connection.execute(
                    """
                    SELECT * FROM supervision_schedules WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
                if schedule is None:
                    raise SupervisionError(
                        "not_found", "Schedule was not found"
                    )
                if not bool(schedule["enabled"]):
                    raise SupervisionError(
                        "schedule_disabled", "Schedule is disabled"
                    )
                in_window = connection.execute(
                    """
                    SELECT 1 FROM supervision_budget_charges
                    WHERE operation = ? AND target = ? AND window_key = ?
                    LIMIT 1
                    """,
                    (
                        schedule["operation"],
                        schedule["target"],
                        window_key,
                    ),
                ).fetchone()
                if in_window is not None:
                    raise SupervisionError(
                        "window_budget_exhausted",
                        "Repair budget for this maintenance window is exhausted",
                    )
                rolling = connection.execute(
                    """
                    SELECT 1 FROM supervision_budget_charges
                    WHERE operation = ? AND target = ? AND charged_at > ?
                    LIMIT 1
                    """,
                    (
                        schedule["operation"],
                        schedule["target"],
                        cutoff,
                    ),
                ).fetchone()
                if rolling is not None:
                    raise SupervisionError(
                        "cooldown_active",
                        "Repair target is inside its rolling cooldown",
                    )
                charge_id = self._stable_id(
                    "budget", schedule_id, occurrence_key
                )
                connection.execute(
                    """
                    INSERT INTO supervision_budget_charges (
                        charge_id, schedule_id, operation, target, window_key,
                        occurrence_key, action_id, charged_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        charge_id,
                        schedule_id,
                        schedule["operation"],
                        schedule["target"],
                        window_key,
                        occurrence_key,
                        action_id,
                        charged_at_value,
                    ),
                )
                charge = connection.execute(
                    """
                    SELECT * FROM supervision_budget_charges
                    WHERE charge_id = ?
                    """,
                    (charge_id,),
                ).fetchone()
            return {"charge": self._budget_charge(charge), "created": True}
        except SupervisionError:
            raise
        except sqlite3.IntegrityError as exc:
            raise SupervisionError(
                "conflict", "Budget charge conflicts with existing evidence"
            ) from exc
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Budget charge could not be saved"
            ) from exc

    def budget_status(
        self,
        schedule_id: str,
        *,
        window_key: str,
        at: datetime,
    ) -> dict[str, Any]:
        _identifier(schedule_id, "Schedule ID")
        _identifier(window_key, "Window key")
        cutoff = _iso(at - timedelta(hours=24), label="Budget status time")
        try:
            with self._connect() as connection:
                schedule = connection.execute(
                    """
                    SELECT operation, target FROM supervision_schedules
                    WHERE schedule_id = ?
                    """,
                    (schedule_id,),
                ).fetchone()
                if schedule is None:
                    raise SupervisionError(
                        "not_found", "Schedule was not found"
                    )
                rolling = connection.execute(
                    """
                    SELECT * FROM supervision_budget_charges
                    WHERE operation = ? AND target = ? AND charged_at > ?
                    ORDER BY charged_at DESC, charge_id DESC
                    """,
                    (
                        schedule["operation"],
                        schedule["target"],
                        cutoff,
                    ),
                ).fetchall()
                in_window = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM supervision_budget_charges
                    WHERE operation = ? AND target = ? AND window_key = ?
                    """,
                    (
                        schedule["operation"],
                        schedule["target"],
                        window_key,
                    ),
                ).fetchone()["count"]
        except SupervisionError:
            raise
        except sqlite3.Error as exc:
            raise SupervisionError(
                "store_failure", "Budget status could not be read"
            ) from exc
        return {
            "rolling_24h": {
                "used": len(rolling),
                "limit": MAX_ACTIONS_PER_TARGET_24H,
            },
            "window": {
                "used": in_window,
                "limit": MAX_ACTIONS_PER_WINDOW,
            },
            "last_charge": (
                self._budget_charge(rolling[0]) if rolling else None
            ),
        }

    def _apply_assessment(
        self,
        connection: sqlite3.Connection,
        *,
        schedule: sqlite3.Row,
        assessment: sqlite3.Row,
        recorded_at: str,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        active = connection.execute(
            """
            SELECT * FROM supervision_incidents
            WHERE operation = ? AND target = ? AND resolved_at IS NULL
            """,
            (schedule["operation"], schedule["target"]),
        ).fetchone()
        streak = self._failed_streak(connection, schedule["schedule_id"])
        outcome = assessment["outcome"]

        if outcome == "healthy":
            if active is None:
                return None, None
            recovered_after_action = active["last_action_id"] is not None
            self._update_incident(
                connection,
                active["incident_id"],
                state="recovered",
                consecutive_failures=0,
                assessment_id=assessment["assessment_id"],
                at=recorded_at,
                resolved_at=recorded_at,
                terminal_code=(
                    "healthy_after_action"
                    if recovered_after_action
                    else "healthy_before_action"
                ),
            )
            transition = self._add_transition(
                connection,
                incident_id=active["incident_id"],
                assessment=assessment,
                transition_type=(
                    "recovered_after_action"
                    if recovered_after_action
                    else "recovered"
                ),
                at=recorded_at,
            )
        elif outcome == "unknown":
            if active is None:
                return None, None
            self._update_incident(
                connection,
                active["incident_id"],
                state="infrastructure_blocked",
                consecutive_failures=0,
                assessment_id=assessment["assessment_id"],
                at=recorded_at,
            )
            transition = self._add_transition(
                connection,
                incident_id=active["incident_id"],
                assessment=assessment,
                transition_type="infrastructure_blocked",
                at=recorded_at,
            )
        elif streak < CONSECUTIVE_FAILURE_THRESHOLD:
            if active is None:
                return None, None
            self._update_incident(
                connection,
                active["incident_id"],
                state="reconfirming",
                consecutive_failures=streak,
                assessment_id=assessment["assessment_id"],
                at=recorded_at,
            )
            transition = self._add_transition(
                connection,
                incident_id=active["incident_id"],
                assessment=assessment,
                transition_type="fault_pending",
                at=recorded_at,
            )
        else:
            if active is None:
                incident_id = self._stable_id(
                    "incident",
                    schedule["operation"],
                    schedule["target"],
                    assessment["assessed_for"],
                )
                connection.execute(
                    """
                    INSERT INTO supervision_incidents (
                        incident_id, schedule_id, operation, target, state,
                        consecutive_failures, last_assessment_id, opened_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, 'confirmed', ?, ?, ?, ?)
                    """,
                    (
                        incident_id,
                        schedule["schedule_id"],
                        schedule["operation"],
                        schedule["target"],
                        streak,
                        assessment["assessment_id"],
                        recorded_at,
                        recorded_at,
                    ),
                )
                active = connection.execute(
                    """
                    SELECT * FROM supervision_incidents WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()
                transition_type = "fault_confirmed"
            elif active["last_action_id"] is not None:
                self._update_incident(
                    connection,
                    active["incident_id"],
                    state=active["state"],
                    consecutive_failures=streak,
                    assessment_id=assessment["assessment_id"],
                    at=recorded_at,
                    terminal_code=active["terminal_code"],
                )
                transition_type = "failure_observed"
            else:
                self._update_incident(
                    connection,
                    active["incident_id"],
                    state="confirmed",
                    consecutive_failures=streak,
                    assessment_id=assessment["assessment_id"],
                    at=recorded_at,
                )
                transition_type = (
                    "fault_reconfirmed"
                    if active["state"] != "confirmed"
                    else "failure_observed"
                )
            transition = self._add_transition(
                connection,
                incident_id=active["incident_id"],
                assessment=assessment,
                transition_type=transition_type,
                at=recorded_at,
            )

        incident = connection.execute(
            """
            SELECT * FROM supervision_incidents WHERE incident_id = ?
            """,
            (active["incident_id"],),
        ).fetchone()
        return incident, transition

    @staticmethod
    def _failed_streak(
        connection: sqlite3.Connection, schedule_id: str
    ) -> int:
        rows = connection.execute(
            """
            SELECT assessed_for, outcome FROM supervision_assessments
            WHERE schedule_id = ?
            ORDER BY assessed_for DESC, assessment_id DESC
            """,
            (schedule_id,),
        ).fetchall()
        streak = 0
        previous: datetime | None = None
        for row in rows:
            if row["outcome"] != "failed":
                break
            assessed_for = _parse_iso(row["assessed_for"])
            if previous is not None and (
                previous - assessed_for
            ).total_seconds() != ASSESSMENT_INTERVAL_SECONDS:
                break
            streak += 1
            previous = assessed_for
        return streak

    @staticmethod
    def _update_incident(
        connection: sqlite3.Connection,
        incident_id: str,
        *,
        state: str,
        consecutive_failures: int,
        assessment_id: str,
        at: str,
        resolved_at: str | None = None,
        terminal_code: str | None = None,
    ) -> None:
        cursor = connection.execute(
            """
            UPDATE supervision_incidents SET
                state = ?, consecutive_failures = ?, last_assessment_id = ?,
                updated_at = ?, resolved_at = ?, terminal_code = ?,
                revision = revision + 1
            WHERE incident_id = ? AND resolved_at IS NULL
            """,
            (
                state,
                consecutive_failures,
                assessment_id,
                at,
                resolved_at,
                terminal_code,
                incident_id,
            ),
        )
        if cursor.rowcount != 1:
            raise SupervisionError(
                "conflict", "Incident changed concurrently"
            )

    def _add_transition(
        self,
        connection: sqlite3.Connection,
        *,
        incident_id: str,
        assessment: sqlite3.Row,
        transition_type: str,
        at: str,
    ) -> sqlite3.Row:
        transition_key = (
            f"assessment:{assessment['assessment_id']}:{transition_type}"
        )
        transition_id = self._stable_id("transition", transition_key)
        connection.execute(
            """
            INSERT INTO supervision_incident_transitions (
                transition_id, incident_id, transition_key, transition_type,
                assessment_id, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition_id,
                incident_id,
                transition_key,
                transition_type,
                assessment["assessment_id"],
                _json(
                    {
                        "assessment_code": assessment["code"],
                        "outcome": assessment["outcome"],
                    }
                ),
                at,
            ),
        )
        transition = connection.execute(
            """
            SELECT * FROM supervision_incident_transitions
            WHERE transition_id = ?
            """,
            (transition_id,),
        ).fetchone()
        self._queue_transition_delivery(
            connection,
            transition=transition,
            incident_id=incident_id,
            at=at,
        )
        return transition

    def _add_runtime_transition(
        self,
        connection: sqlite3.Connection,
        *,
        incident_id: str,
        transition_key: str,
        transition_type: str,
        details: Mapping[str, Any],
        at: str,
    ) -> sqlite3.Row:
        transition_id = self._stable_id("transition", transition_key)
        connection.execute(
            """
            INSERT INTO supervision_incident_transitions (
                transition_id, incident_id, transition_key, transition_type,
                assessment_id, details_json, created_at
            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                transition_id,
                incident_id,
                transition_key,
                transition_type,
                _json(details),
                at,
            ),
        )
        transition = connection.execute(
            """
            SELECT * FROM supervision_incident_transitions
            WHERE transition_id = ?
            """,
            (transition_id,),
        ).fetchone()
        self._queue_transition_delivery(
            connection,
            transition=transition,
            incident_id=incident_id,
            at=at,
        )
        return transition

    def _queue_transition_delivery(
        self,
        connection: sqlite3.Connection,
        *,
        transition: sqlite3.Row,
        incident_id: str,
        at: str,
    ) -> None:
        if transition["transition_type"] not in _DELIVERED_TRANSITIONS:
            return
        incident = connection.execute(
            """
            SELECT thread_id FROM supervision_incidents
            WHERE incident_id = ?
            """,
            (incident_id,),
        ).fetchone()
        prior = connection.execute(
            """
            SELECT 1 FROM supervision_deliveries
            WHERE incident_id = ? LIMIT 1
            """,
            (incident_id,),
        ).fetchone()
        message_kind = (
            "root"
            if incident["thread_id"] is None and prior is None
            else "reply"
        )
        delivery_id = self._stable_id(
            "delivery", transition["transition_id"]
        )
        connection.execute(
            """
            INSERT INTO supervision_deliveries (
                delivery_id, transition_id, incident_id, state,
                message_kind, created_at, updated_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                delivery_id,
                transition["transition_id"],
                incident_id,
                message_kind,
                at,
                at,
            ),
        )

    @staticmethod
    def _incident_for_assessment(
        connection: sqlite3.Connection, assessment_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM supervision_incidents
            WHERE last_assessment_id = ?
            ORDER BY opened_at DESC LIMIT 1
            """,
            (assessment_id,),
        ).fetchone()

    @staticmethod
    def _stable_id(kind: str, *parts: str) -> str:
        digest = hashlib.sha256(
            "\x00".join((kind, *parts)).encode("utf-8")
        ).hexdigest()
        return f"{kind}-{digest[:32]}"

    @staticmethod
    def _derived_schedule_fields(operation: str) -> dict[str, Any]:
        item = _CATALOGUE_BY_OPERATION.get(operation)
        if item is None:
            raise SupervisionError(
                "store_failure", "Stored schedule operation is unavailable"
            )
        return {
            "risk": item["risk"],
            "capability_version": item["capability_version"],
            "assessment_operation": item["assessment_operation"],
            "assessment_interval_seconds": item[
                "assessment_interval_seconds"
            ],
            "failure_threshold": item["failure_threshold"],
            "budgets": dict(item["budgets"]),
        }

    @classmethod
    def _schedule(cls, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["schedule_id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "operation": row["operation"],
            "params": json.loads(row["params_json"]),
            "target": row["target"],
            "service_priority": row["service_priority"],
            "window": json.loads(row["window_json"]),
            "delivery": json.loads(row["delivery_json"]),
            **cls._derived_schedule_fields(row["operation"]),
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
    def _assessment(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["assessment_id"],
            "schedule_id": row["schedule_id"],
            "assessed_for": row["assessed_for"],
            "outcome": row["outcome"],
            "code": row["code"],
            "observed_status": row["observed_status"],
            "observed_health": row["observed_health"],
            "audit_id": row["audit_id"],
            "recorded_at": row["recorded_at"],
        }

    @staticmethod
    def _incident(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["incident_id"],
            "schedule_id": row["schedule_id"],
            "operation": row["operation"],
            "target": row["target"],
            "state": row["state"],
            "consecutive_failures": row["consecutive_failures"],
            "last_assessment_id": row["last_assessment_id"],
            "thread_id": row["thread_id"],
            "opened_at": row["opened_at"],
            "updated_at": row["updated_at"],
            "resolved_at": row["resolved_at"],
            "terminal_code": row["terminal_code"],
            "last_action_id": row["last_action_id"],
            "revision": row["revision"],
        }

    @staticmethod
    def _transition(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["transition_id"],
            "incident_id": row["incident_id"],
            "type": row["transition_type"],
            "assessment_id": row["assessment_id"],
            "details": json.loads(row["details_json"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _budget_charge(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["charge_id"],
            "schedule_id": row["schedule_id"],
            "operation": row["operation"],
            "target": row["target"],
            "window_key": row["window_key"],
            "occurrence_key": row["occurrence_key"],
            "action_id": row["action_id"],
            "charged_at": row["charged_at"],
        }

    @staticmethod
    def _occurrence(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["occurrence_id"],
            "schedule_id": row["schedule_id"],
            "assessed_for": row["assessed_for"],
            "state": row["state"],
            "assessment_id": row["assessment_id"],
            "incident_id": row["incident_id"],
            "action_id": row["action_id"],
            "terminal_code": row["terminal_code"],
            "started_at": row["started_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _delivery(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        return {
            "id": row["delivery_id"],
            "transition_id": row["transition_id"],
            "incident_id": row["incident_id"],
            "state": row["state"],
            "message_kind": row["message_kind"],
            "thread_id": row["thread_id"],
            "incident_thread_id": (
                row["incident_thread_id"]
                if "incident_thread_id" in keys
                else None
            ),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "delivered_at": row["delivered_at"],
        }


class SupervisionService:
    """Validate domain commands without performing reads or mutations."""

    def __init__(
        self,
        *,
        store: SupervisionStore,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self._clock = clock
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))

    def create(self, values: Any, *, owner: Any) -> dict[str, Any]:
        normalized = normalize_schedule(values)
        normalized_owner = _normalize_owner(owner)
        return self.store.create_schedule(
            schedule_id=self._id_factory(),
            values=normalized,
            owner=normalized_owner,
            at=_iso(self._clock()),
        )

    def update(self, schedule_id: str, values: Any) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise SupervisionError(
                "invalid_schedule", "Schedule must be an object"
            )
        expected = SCHEDULE_FIELDS | {"revision"}
        _reject_unknown(values, frozenset(expected), "schedule")
        if set(values) != expected:
            raise SupervisionError(
                "invalid_schedule", "Schedule fields are incomplete"
            )
        revision = values.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise SupervisionError(
                "invalid_schedule", "Schedule revision is invalid"
            )
        normalized = normalize_schedule(
            {field: values[field] for field in SCHEDULE_FIELDS}
        )
        return self.store.update_schedule(
            schedule_id,
            values=normalized,
            expected_revision=revision,
            at=_iso(self._clock()),
        )

    def get(self, schedule_id: str) -> dict[str, Any]:
        return self.store.get_schedule(schedule_id)

    def list(self) -> dict[str, Any]:
        return {
            "schedules": self.store.list_schedules(),
            "catalogue": [
                {
                    **item,
                    "params": dict(item["params"]),
                    "budgets": dict(item["budgets"]),
                }
                for item in SUPERVISED_CATALOGUE
            ],
            "service_priorities": list(SERVICE_PRIORITIES),
        }

    def assess(
        self,
        schedule_id: str,
        response: Any,
        *,
        assessed_at: datetime | None = None,
    ) -> dict[str, Any]:
        schedule = self.store.get_schedule(schedule_id)
        if not schedule["enabled"]:
            raise SupervisionError(
                "schedule_disabled", "Schedule is disabled"
            )
        bucket = assessment_bucket(assessed_at or self._clock())
        evidence = classify_container_status(
            response, expected_target=schedule["target"]
        )
        return self.store.record_assessment(
            schedule_id=schedule_id,
            assessed_for=_iso(bucket, label="Assessment time"),
            evidence=evidence,
            recorded_at=_iso(self._clock()),
        )
