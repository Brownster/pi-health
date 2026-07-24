"""Transactional action proposal, approval, and execution ledger."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from agent_actions.capability import (
    CAPABILITY_ID_RE,
    RESOURCE_RE,
    VERSION_RE,
    CapabilityError,
    canonical_json,
)


class ActionState(str, Enum):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTHORISED = "authorised"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    ESCALATION_REQUIRED = "escalation_required"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    PRECONDITION_CHANGED = "precondition_changed"


class ActionLedgerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class NewAction:
    action_id: str
    idempotency_key: str
    operation: str
    capability_version: str
    target: str
    risk: str
    trigger: str
    authority_mode: str
    params: dict[str, Any]
    evidence_ids: list[str]
    payload_hash: str
    reason: str
    impact: str
    precondition_hash: str
    actor_type: str
    actor_id: str
    actor_username: str | None
    state: ActionState
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class ActionRecord:
    action_id: str
    idempotency_key: str
    operation: str
    capability_version: str
    target: str
    risk: str
    trigger: str
    authority_mode: str
    params: dict[str, Any]
    evidence_ids: list[str]
    payload_hash: str
    reason: str
    impact: str
    precondition_hash: str
    actor_type: str
    actor_id: str
    actor_username: str | None
    state: ActionState
    created_at: str
    expires_at: str
    approved_by_type: str | None
    approved_by_id: str | None
    approved_by_username: str | None
    approved_at: str | None
    approval_used_at: str | None
    terminal_code: str | None
    revision: int

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.action_id,
            "operation": self.operation,
            "capability_version": self.capability_version,
            "target": self.target,
            "risk": self.risk,
            "trigger": self.trigger,
            "authority_mode": self.authority_mode,
            "params": self.params,
            "evidence_ids": self.evidence_ids,
            "payload_hash": self.payload_hash,
            "reason": self.reason,
            "impact": self.impact,
            "state": self.state.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "actor": {
                "type": self.actor_type,
                "id": self.actor_id,
                "username": self.actor_username,
            },
            "approval": (
                {
                    "actor": {
                        "type": self.approved_by_type,
                        "id": self.approved_by_id,
                        "username": self.approved_by_username,
                    },
                    "approved_at": self.approved_at,
                    "used_at": self.approval_used_at,
                }
                if self.approved_at
                else None
            ),
            "terminal_code": self.terminal_code,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class CanaryAttestationRecord:
    attestation_id: str
    operation: str
    target: str
    trigger: str
    capability_version: str
    risk: str
    source_action_id: str
    release_commit: str
    attested_by_type: str
    attested_by_id: str
    attested_by_username: str | None
    attested_at: str
    revoked_by_type: str | None
    revoked_by_id: str | None
    revoked_by_username: str | None
    revoked_at: str | None

    @property
    def active(self) -> bool:
        return self.revoked_at is None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.attestation_id,
            "operation": self.operation,
            "target": self.target,
            "trigger": self.trigger,
            "capability_version": self.capability_version,
            "risk": self.risk,
            "source_action_id": self.source_action_id,
            "release_commit": self.release_commit,
            "attested_by": {
                "type": self.attested_by_type,
                "id": self.attested_by_id,
                "username": self.attested_by_username,
            },
            "attested_at": self.attested_at,
            "revoked_by": (
                {
                    "type": self.revoked_by_type,
                    "id": self.revoked_by_id,
                    "username": self.revoked_by_username,
                }
                if self.revoked_at is not None
                else None
            ),
            "revoked_at": self.revoked_at,
        }


@dataclass(frozen=True)
class TargetLeaseRecord:
    lease_id: str
    operation: str
    target: str
    action_id: str
    acquired_at: str
    released_at: str | None
    terminal_code: str | None

    @property
    def active(self) -> bool:
        return self.released_at is None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.lease_id,
            "operation": self.operation,
            "target": self.target,
            "action_id": self.action_id,
            "acquired_at": self.acquired_at,
            "released_at": self.released_at,
            "terminal_code": self.terminal_code,
            "active": self.active,
        }


@dataclass(frozen=True)
class DemotionRecord:
    demotion_id: str
    operation: str
    target: str
    cause: str
    source_action_id: str
    release_commit: str
    demoted_at: str
    cleared_by_type: str | None
    cleared_by_id: str | None
    cleared_by_username: str | None
    cleared_at: str | None
    recovery_action_id: str | None
    revision: int

    @property
    def active(self) -> bool:
        return self.cleared_at is None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.demotion_id,
            "operation": self.operation,
            "target": self.target,
            "cause": self.cause,
            "source_action_id": self.source_action_id,
            "release_commit": self.release_commit,
            "demoted_at": self.demoted_at,
            "cleared_by": (
                {
                    "type": self.cleared_by_type,
                    "id": self.cleared_by_id,
                    "username": self.cleared_by_username,
                }
                if self.cleared_at is not None
                else None
            ),
            "cleared_at": self.cleared_at,
            "recovery_action_id": self.recovery_action_id,
            "revision": self.revision,
            "active": self.active,
        }


@dataclass(frozen=True)
class NewSupervisionAuthorization:
    authorization_id: str
    occurrence_key: str
    schedule_id: str
    schedule_revision: int
    incident_id: str
    assessment_id: str
    assessed_for: str
    window_key: str
    window_start: str
    window_deadline: str
    release_commit: str
    authorized_at: str
    expires_at: str


@dataclass(frozen=True)
class SupervisionAuthorizationRecord:
    authorization_id: str
    occurrence_key: str
    action_id: str
    schedule_id: str
    schedule_revision: int
    incident_id: str
    assessment_id: str
    assessed_for: str
    operation: str
    target: str
    capability_version: str
    release_commit: str
    window_key: str
    window_start: str
    window_deadline: str
    authorized_at: str
    expires_at: str
    consumed_at: str | None
    invalidated_at: str | None
    invalidation_code: str | None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.authorization_id,
            "occurrence_key": self.occurrence_key,
            "action_id": self.action_id,
            "schedule_id": self.schedule_id,
            "schedule_revision": self.schedule_revision,
            "incident_id": self.incident_id,
            "assessment_id": self.assessment_id,
            "assessed_for": self.assessed_for,
            "operation": self.operation,
            "target": self.target,
            "capability_version": self.capability_version,
            "release_commit": self.release_commit,
            "window_key": self.window_key,
            "window_start": self.window_start,
            "window_deadline": self.window_deadline,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
            "consumed_at": self.consumed_at,
            "invalidated_at": self.invalidated_at,
            "invalidation_code": self.invalidation_code,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    operation TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    target TEXT NOT NULL,
    risk TEXT NOT NULL,
    trigger TEXT NOT NULL,
    authority_mode TEXT NOT NULL,
    params_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    impact TEXT NOT NULL,
    precondition_hash TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_username TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    approved_by_type TEXT,
    approved_by_id TEXT,
    approved_by_username TEXT,
    approved_at TEXT,
    approval_used_at TEXT,
    terminal_code TEXT,
    revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS actions_created_idx ON actions(created_at DESC);
CREATE INDEX IF NOT EXISTS actions_state_idx ON actions(state, expires_at);
CREATE TABLE IF NOT EXISTS action_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL REFERENCES actions(action_id),
    phase TEXT NOT NULL,
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS action_events_action_idx
    ON action_events(action_id, event_id);
CREATE TABLE IF NOT EXISTS action_target_leases (
    lease_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
    acquired_at TEXT NOT NULL,
    released_at TEXT,
    terminal_code TEXT,
    CHECK (
        (released_at IS NULL AND terminal_code IS NULL)
        OR (released_at IS NOT NULL AND terminal_code IS NOT NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS action_target_leases_active_idx
    ON action_target_leases(operation, target)
    WHERE released_at IS NULL;
CREATE INDEX IF NOT EXISTS action_target_leases_action_idx
    ON action_target_leases(action_id);
CREATE TABLE IF NOT EXISTS action_demotions (
    demotion_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    cause TEXT NOT NULL,
    source_action_id TEXT NOT NULL REFERENCES actions(action_id),
    release_commit TEXT NOT NULL,
    demoted_at TEXT NOT NULL,
    cleared_by_type TEXT,
    cleared_by_id TEXT,
    cleared_by_username TEXT,
    cleared_at TEXT,
    recovery_action_id TEXT REFERENCES actions(action_id),
    revision INTEGER NOT NULL DEFAULT 1,
    CHECK (
        (
            cleared_at IS NULL
            AND cleared_by_type IS NULL
            AND cleared_by_id IS NULL
            AND cleared_by_username IS NULL
            AND recovery_action_id IS NULL
        )
        OR (
            cleared_at IS NOT NULL
            AND cleared_by_type = 'local'
            AND cleared_by_id IS NOT NULL
            AND recovery_action_id IS NOT NULL
        )
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS action_demotions_active_target_idx
    ON action_demotions(operation, target)
    WHERE cleared_at IS NULL;
CREATE INDEX IF NOT EXISTS action_demotions_created_idx
    ON action_demotions(demoted_at DESC, demotion_id DESC);
CREATE TABLE IF NOT EXISTS supervision_authorizations (
    authorization_id TEXT PRIMARY KEY,
    occurrence_key TEXT NOT NULL UNIQUE,
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
    schedule_id TEXT NOT NULL,
    schedule_revision INTEGER NOT NULL,
    incident_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    assessed_for TEXT NOT NULL,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    capability_version TEXT NOT NULL,
    release_commit TEXT NOT NULL,
    window_key TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_deadline TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    invalidated_at TEXT,
    invalidation_code TEXT,
    CHECK (
        invalidated_at IS NULL
        OR (consumed_at IS NULL AND invalidation_code IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS supervision_authorizations_action_idx
    ON supervision_authorizations(action_id);
CREATE TABLE IF NOT EXISTS supervised_execution_slot (
    slot INTEGER PRIMARY KEY CHECK (slot = 1),
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
    acquired_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS canary_attestations (
    attestation_id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    trigger TEXT NOT NULL CHECK (trigger = 'scheduled'),
    capability_version TEXT NOT NULL,
    risk TEXT NOT NULL CHECK (risk = 'R1'),
    source_action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
    release_commit TEXT NOT NULL,
    attested_by_type TEXT NOT NULL CHECK (attested_by_type = 'local'),
    attested_by_id TEXT NOT NULL,
    attested_by_username TEXT,
    attested_at TEXT NOT NULL,
    revoked_by_type TEXT,
    revoked_by_id TEXT,
    revoked_by_username TEXT,
    revoked_at TEXT,
    CHECK (
        (
            revoked_at IS NULL
            AND revoked_by_type IS NULL
            AND revoked_by_id IS NULL
            AND revoked_by_username IS NULL
        )
        OR (
            revoked_at IS NOT NULL
            AND revoked_by_type = 'local'
            AND revoked_by_id IS NOT NULL
        )
    )
);
CREATE INDEX IF NOT EXISTS canary_attestations_created_idx
    ON canary_attestations(attested_at DESC, attestation_id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS canary_attestations_active_tuple_idx
    ON canary_attestations(operation, target, trigger, capability_version)
    WHERE revoked_at IS NULL;
INSERT OR IGNORE INTO action_target_leases (
    lease_id, operation, target, action_id, acquired_at
)
SELECT
    'lease:' || action_id, operation, target, action_id, created_at
FROM actions AS candidate
WHERE state IN (
    'proposed', 'awaiting_approval', 'authorised', 'executing', 'verifying'
)
AND NOT EXISTS (
    SELECT 1
    FROM actions AS earlier
    WHERE earlier.operation = candidate.operation
      AND earlier.target = candidate.target
      AND earlier.state IN (
          'proposed', 'awaiting_approval', 'authorised', 'executing', 'verifying'
      )
      AND (
          earlier.created_at < candidate.created_at
          OR (
              earlier.created_at = candidate.created_at
              AND earlier.action_id < candidate.action_id
          )
      )
);
"""

_ACTIVE_ACTION_STATES = frozenset(
    {
        ActionState.PROPOSED,
        ActionState.AWAITING_APPROVAL,
        ActionState.AUTHORISED,
        ActionState.EXECUTING,
        ActionState.VERIFYING,
        ActionState.ROLLING_BACK,
    }
)
DEMOTION_CAUSES = frozenset(
    {
        "execution_failed",
        "verification_uncertain",
        "verification_failed",
        "authorisation_expired",
        "deadline_exceeded",
        "audit_failure",
        "identity_failure",
    }
)
_SUPERVISION_ASSESSMENT_MAX_AGE_SECONDS = 600


class ActionLedger:
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
            raise ActionLedgerError("unsafe_store", "Action ledger cannot be a symlink")
        try:
            with self._connect() as connection:
                connection.executescript(_SCHEMA)
            # The dashboard, proposal broker, and isolated actuator are separate
            # service identities in the trusted ``pihealth`` state group.
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
            raise ActionLedgerError("store_unavailable", "Action ledger is unavailable") from exc

    def create(self, action: NewAction) -> tuple[ActionRecord, bool]:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM actions WHERE idempotency_key = ?",
                    (action.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    record = self._record(existing)
                    if record.payload_hash != action.payload_hash:
                        raise ActionLedgerError(
                            "idempotency_conflict",
                            "Idempotency key belongs to another payload",
                        )
                    return record, False
                if action.state in _ACTIVE_ACTION_STATES:
                    occupied = connection.execute(
                        """
                        SELECT action_id FROM actions
                        WHERE operation = ? AND target = ?
                          AND state IN (
                              'proposed', 'awaiting_approval', 'authorised',
                              'executing', 'verifying'
                          )
                        LIMIT 1
                        """,
                        (action.operation, action.target),
                    ).fetchone()
                    if occupied is not None:
                        raise ActionLedgerError(
                            "target_busy",
                            "Another action is active for this exact target",
                        )
                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id, idempotency_key, operation, capability_version,
                        target, risk, trigger, authority_mode, params_json,
                        evidence_json, payload_hash, reason, impact, precondition_hash,
                        actor_type, actor_id, actor_username, state, created_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.action_id,
                        action.idempotency_key,
                        action.operation,
                        action.capability_version,
                        action.target,
                        action.risk,
                        action.trigger,
                        action.authority_mode,
                        canonical_json(action.params),
                        canonical_json(action.evidence_ids),
                        action.payload_hash,
                        action.reason,
                        action.impact,
                        action.precondition_hash,
                        action.actor_type,
                        action.actor_id,
                        action.actor_username,
                        action.state.value,
                        action.created_at,
                        action.expires_at,
                    ),
                )
                if action.state in _ACTIVE_ACTION_STATES:
                    connection.execute(
                        """
                        INSERT INTO action_target_leases (
                            lease_id, operation, target, action_id, acquired_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            f"lease:{action.action_id}",
                            action.operation,
                            action.target,
                            action.action_id,
                            action.created_at,
                        ),
                    )
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action.action_id,)
                ).fetchone()
                return self._record(row), True
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError("store_failure", "Action proposal could not be saved") from exc

    def get(self, action_id: str) -> ActionRecord:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise ActionLedgerError("store_failure", "Action could not be read") from exc
        if row is None:
            raise ActionLedgerError("not_found", "Action was not found")
        return self._record(row)

    def list(self, *, limit: int = 50) -> list[ActionRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ActionLedgerError("invalid_input", "Action limit must be between 1 and 200")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM actions ORDER BY created_at DESC, action_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise ActionLedgerError("store_failure", "Actions could not be read") from exc
        return [self._record(row) for row in rows]

    def active_target_lease(
        self, *, operation: str, target: str
    ) -> TargetLeaseRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM action_target_leases
                    WHERE operation = ? AND target = ? AND released_at IS NULL
                    """,
                    (operation, target),
                ).fetchone()
            return self._target_lease(row) if row is not None else None
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action target lease could not be read"
            ) from exc

    def create_supervised_action(
        self,
        action: NewAction,
        authorization: NewSupervisionAuthorization,
        *,
        supervision_path: str | Path,
    ) -> tuple[ActionRecord, SupervisionAuthorizationRecord, bool]:
        """Atomically bind supervision evidence, budget, lease, and action."""

        path = Path(supervision_path)
        if path.is_symlink() or not path.is_file():
            raise ActionLedgerError(
                "supervision_unavailable", "Supervision evidence is unavailable"
            )
        identifiers = (
            authorization.authorization_id,
            authorization.occurrence_key,
            authorization.schedule_id,
            authorization.incident_id,
            authorization.assessment_id,
            authorization.window_key,
        )
        if (
            any(
                not isinstance(value, str)
                or RESOURCE_RE.fullmatch(value) is None
                for value in identifiers
            )
            or isinstance(authorization.schedule_revision, bool)
            or not isinstance(authorization.schedule_revision, int)
            or authorization.schedule_revision < 1
            or action.state != ActionState.AUTHORISED
            or action.trigger != "scheduled"
            or action.authority_mode != "supervised"
            or action.risk != "R1"
            or authorization.expires_at != action.expires_at
            or not self._valid_release_commit(authorization.release_commit)
        ):
            raise ActionLedgerError(
                "invalid_input", "Supervision authorization is invalid"
            )
        times = (
            authorization.assessed_for,
            authorization.window_start,
            authorization.window_deadline,
            authorization.authorized_at,
            authorization.expires_at,
        )
        if not all(self._valid_time(value) for value in times):
            raise ActionLedgerError(
                "invalid_input", "Supervision authorization time is invalid"
            )
        assessed_for = self._parse_record_time(authorization.assessed_for)
        window_start = self._parse_record_time(authorization.window_start)
        window_deadline = self._parse_record_time(
            authorization.window_deadline
        )
        authorized_at = self._parse_record_time(authorization.authorized_at)
        expires_at = self._parse_record_time(authorization.expires_at)
        if (
            not window_start <= assessed_for <= authorized_at < window_deadline
            or (authorized_at - assessed_for).total_seconds()
            >= _SUPERVISION_ASSESSMENT_MAX_AGE_SECONDS
            or not authorized_at < expires_at
        ):
            raise ActionLedgerError(
                "window_closed", "Supervised repair window is closed"
            )
        cutoff = (
            authorized_at - timedelta(hours=24)
        ).astimezone(timezone.utc).isoformat()

        try:
            with self._connect() as connection:
                connection.execute(
                    "ATTACH DATABASE ? AS supervision", (str(path),)
                )
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT * FROM supervision_authorizations
                    WHERE occurrence_key = ?
                    """,
                    (authorization.occurrence_key,),
                ).fetchone()
                if existing is not None:
                    record = self._authorization(existing)
                    action_row = connection.execute(
                        "SELECT * FROM actions WHERE action_id = ?",
                        (record.action_id,),
                    ).fetchone()
                    if (
                        action_row is None
                        or record.authorization_id
                        != authorization.authorization_id
                        or record.schedule_id != authorization.schedule_id
                        or record.assessment_id != authorization.assessment_id
                        or self._record(action_row).payload_hash
                        != action.payload_hash
                    ):
                        raise ActionLedgerError(
                            "idempotency_conflict",
                            "Supervision occurrence belongs to another action",
                        )
                    return self._record(action_row), record, False

                schedule = connection.execute(
                    """
                    SELECT * FROM supervision.supervision_schedules
                    WHERE schedule_id = ?
                    """,
                    (authorization.schedule_id,),
                ).fetchone()
                if (
                    schedule is None
                    or not bool(schedule["enabled"])
                    or schedule["revision"] != authorization.schedule_revision
                    or schedule["operation"] != action.operation
                    or schedule["target"] != action.target
                    or json.loads(schedule["params_json"]) != action.params
                ):
                    raise ActionLedgerError(
                        "schedule_changed",
                        "Supervision schedule changed before authorization",
                    )
                incident = connection.execute(
                    """
                    SELECT * FROM supervision.supervision_incidents
                    WHERE incident_id = ?
                    """,
                    (authorization.incident_id,),
                ).fetchone()
                if (
                    incident is None
                    or incident["schedule_id"] != authorization.schedule_id
                    or incident["operation"] != action.operation
                    or incident["target"] != action.target
                    or incident["state"] != "confirmed"
                    or incident["resolved_at"] is not None
                    or incident["last_assessment_id"]
                    != authorization.assessment_id
                ):
                    raise ActionLedgerError(
                        "incident_changed",
                        "Supervision incident is not confirmed",
                    )
                assessment = connection.execute(
                    """
                    SELECT * FROM supervision.supervision_assessments
                    WHERE assessment_id = ? AND schedule_id = ?
                    """,
                    (
                        authorization.assessment_id,
                        authorization.schedule_id,
                    ),
                ).fetchone()
                latest = connection.execute(
                    """
                    SELECT assessment_id
                    FROM supervision.supervision_assessments
                    WHERE schedule_id = ?
                    ORDER BY assessed_for DESC, assessment_id DESC LIMIT 1
                    """,
                    (authorization.schedule_id,),
                ).fetchone()
                if (
                    assessment is None
                    or assessment["outcome"] != "failed"
                    or assessment["assessed_for"] != authorization.assessed_for
                    or latest is None
                    or latest["assessment_id"] != authorization.assessment_id
                ):
                    raise ActionLedgerError(
                        "assessment_changed",
                        "Fresh failed assessment is unavailable",
                    )
                canary = connection.execute(
                    """
                    SELECT 1 FROM canary_attestations
                    WHERE operation = ? AND target = ? AND trigger = 'scheduled'
                      AND capability_version = ? AND risk = 'R1'
                      AND release_commit = ? AND revoked_at IS NULL
                    LIMIT 1
                    """,
                    (
                        action.operation,
                        action.target,
                        action.capability_version,
                        authorization.release_commit,
                    ),
                ).fetchone()
                if canary is None:
                    raise ActionLedgerError(
                        "canary_required",
                        "A current repair canary is required",
                    )
                demotion = connection.execute(
                    """
                    SELECT 1 FROM action_demotions
                    WHERE operation = ? AND target = ? AND cleared_at IS NULL
                    LIMIT 1
                    """,
                    (action.operation, action.target),
                ).fetchone()
                if demotion is not None:
                    raise ActionLedgerError(
                        "demoted",
                        "Supervised authority is demoted to approval",
                    )
                active = connection.execute(
                    """
                    SELECT 1 FROM actions
                    WHERE operation = ? AND target = ?
                      AND state IN (
                          'proposed', 'awaiting_approval', 'authorised',
                          'executing', 'verifying', 'rolling_back'
                      )
                    LIMIT 1
                    """,
                    (action.operation, action.target),
                ).fetchone()
                if active is not None:
                    raise ActionLedgerError(
                        "target_busy",
                        "Another action is active for this exact target",
                    )
                window_used = connection.execute(
                    """
                    SELECT 1
                    FROM supervision.supervision_budget_charges
                    WHERE operation = ? AND target = ? AND window_key = ?
                    LIMIT 1
                    """,
                    (
                        action.operation,
                        action.target,
                        authorization.window_key,
                    ),
                ).fetchone()
                if window_used is not None:
                    raise ActionLedgerError(
                        "window_budget_exhausted",
                        "Repair budget for this maintenance window is exhausted",
                    )
                rolling_used = connection.execute(
                    """
                    SELECT 1
                    FROM supervision.supervision_budget_charges
                    WHERE operation = ? AND target = ? AND charged_at > ?
                    LIMIT 1
                    """,
                    (action.operation, action.target, cutoff),
                ).fetchone()
                if rolling_used is not None:
                    raise ActionLedgerError(
                        "cooldown_active",
                        "Repair target is inside its rolling cooldown",
                    )

                connection.execute(
                    """
                    INSERT INTO actions (
                        action_id, idempotency_key, operation,
                        capability_version, target, risk, trigger,
                        authority_mode, params_json, evidence_json,
                        payload_hash, reason, impact, precondition_hash,
                        actor_type, actor_id, actor_username, state,
                        created_at, expires_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?
                    )
                    """,
                    (
                        action.action_id,
                        action.idempotency_key,
                        action.operation,
                        action.capability_version,
                        action.target,
                        action.risk,
                        action.trigger,
                        action.authority_mode,
                        canonical_json(action.params),
                        canonical_json(action.evidence_ids),
                        action.payload_hash,
                        action.reason,
                        action.impact,
                        action.precondition_hash,
                        action.actor_type,
                        action.actor_id,
                        action.actor_username,
                        action.state.value,
                        action.created_at,
                        action.expires_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO action_target_leases (
                        lease_id, operation, target, action_id, acquired_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"lease:{action.action_id}",
                        action.operation,
                        action.target,
                        action.action_id,
                        action.created_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO supervision_authorizations (
                        authorization_id, occurrence_key, action_id,
                        schedule_id, schedule_revision, incident_id,
                        assessment_id, assessed_for, operation, target,
                        capability_version, release_commit, window_key,
                        window_start, window_deadline, authorized_at, expires_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        authorization.authorization_id,
                        authorization.occurrence_key,
                        action.action_id,
                        authorization.schedule_id,
                        authorization.schedule_revision,
                        authorization.incident_id,
                        authorization.assessment_id,
                        authorization.assessed_for,
                        action.operation,
                        action.target,
                        action.capability_version,
                        authorization.release_commit,
                        authorization.window_key,
                        authorization.window_start,
                        authorization.window_deadline,
                        authorization.authorized_at,
                        authorization.expires_at,
                    ),
                )
                budget_digest = hashlib.sha256(
                    (
                        f"{authorization.schedule_id}\x00"
                        f"{authorization.occurrence_key}"
                    ).encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO supervision.supervision_budget_charges (
                        charge_id, schedule_id, operation, target, window_key,
                        occurrence_key, action_id, charged_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"budget-{budget_digest[:32]}",
                        authorization.schedule_id,
                        action.operation,
                        action.target,
                        authorization.window_key,
                        authorization.occurrence_key,
                        action.action_id,
                        authorization.authorized_at,
                    ),
                )
                action_row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?",
                    (action.action_id,),
                ).fetchone()
                authorization_row = connection.execute(
                    """
                    SELECT * FROM supervision_authorizations
                    WHERE authorization_id = ?
                    """,
                    (authorization.authorization_id,),
                ).fetchone()
            return (
                self._record(action_row),
                self._authorization(authorization_row),
                True,
            )
        except ActionLedgerError:
            raise
        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
            sqlite3.IntegrityError,
        ) as exc:
            raise ActionLedgerError(
                "conflict", "Supervision authorization conflicts"
            ) from exc
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Supervision authorization could not be saved"
            ) from exc

    def supervision_authorization(
        self, action_id: str
    ) -> SupervisionAuthorizationRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM supervision_authorizations
                    WHERE action_id = ?
                    """,
                    (action_id,),
                ).fetchone()
            return self._authorization(row) if row is not None else None
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Supervision authorization could not be read"
            ) from exc

    def has_supervised_execution_slot(self, action_id: str) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT 1 FROM supervised_execution_slot
                    WHERE slot = 1 AND action_id = ?
                    """,
                    (action_id,),
                ).fetchone()
            return row is not None
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Supervised execution slot could not be read"
            ) from exc

    def create_demotion(
        self,
        *,
        operation: str,
        target: str,
        cause: str,
        source_action_id: str,
        release_commit: str,
        demoted_at: str,
    ) -> tuple[DemotionRecord, bool]:
        self._validate_demotion_input(
            operation=operation,
            target=target,
            cause=cause,
            source_action_id=source_action_id,
            release_commit=release_commit,
            at=demoted_at,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """
                    SELECT * FROM action_demotions
                    WHERE operation = ? AND target = ? AND cleared_at IS NULL
                    """,
                    (operation, target),
                ).fetchone()
                if existing is not None:
                    return self._demotion(existing), False
                source = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?",
                    (source_action_id,),
                ).fetchone()
                if source is None:
                    raise ActionLedgerError(
                        "not_found", "Demotion source action was not found"
                    )
                action = self._record(source)
                if (
                    action.operation != operation
                    or action.target != target
                    or action.trigger != "scheduled"
                    or action.authority_mode != "supervised"
                ):
                    raise ActionLedgerError(
                        "ineligible_source",
                        "Demotion source action is not an exact supervised repair",
                    )
                digest = hashlib.sha256(
                    (
                        f"{operation}\x00{target}\x00{source_action_id}"
                        f"\x00{cause}\x00{demoted_at}"
                    ).encode("utf-8")
                ).hexdigest()
                demotion_id = f"demotion-{digest[:32]}"
                connection.execute(
                    """
                    INSERT INTO action_demotions (
                        demotion_id, operation, target, cause, source_action_id,
                        release_commit, demoted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        demotion_id,
                        operation,
                        target,
                        cause,
                        source_action_id,
                        release_commit,
                        demoted_at,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM action_demotions WHERE demotion_id = ?",
                    (demotion_id,),
                ).fetchone()
            return self._demotion(row), True
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action demotion could not be saved"
            ) from exc

    def active_demotion(
        self, *, operation: str, target: str
    ) -> DemotionRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM action_demotions
                    WHERE operation = ? AND target = ? AND cleared_at IS NULL
                    """,
                    (operation, target),
                ).fetchone()
            return self._demotion(row) if row is not None else None
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action demotion could not be read"
            ) from exc

    def demotions(self, *, limit: int = 200) -> list[DemotionRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ActionLedgerError(
                "invalid_input", "Demotion limit must be between 1 and 200"
            )
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM action_demotions
                    ORDER BY (cleared_at IS NULL) DESC, demoted_at DESC,
                             demotion_id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._demotion(row) for row in rows]
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action demotions could not be read"
            ) from exc

    def clear_demotion(
        self,
        demotion_id: str,
        *,
        expected_revision: int,
        recovery_action_id: str,
        release_commit: str,
        cleared_by_type: str,
        cleared_by_id: str,
        cleared_by_username: str | None,
        cleared_at: str,
    ) -> DemotionRecord:
        values = {
            "demotion_id": demotion_id,
            "recovery_action_id": recovery_action_id,
            "release_commit": release_commit,
            "cleared_by_id": cleared_by_id,
            "cleared_at": cleared_at,
        }
        if (
            any(
                not isinstance(value, str)
                or not value
                or len(value) > 128
                for value in values.values()
            )
            or not RESOURCE_RE.fullmatch(demotion_id)
            or not RESOURCE_RE.fullmatch(recovery_action_id)
            or not RESOURCE_RE.fullmatch(cleared_by_id)
            or cleared_by_type != "local"
            or not self._valid_release_commit(release_commit)
            or not self._valid_time(cleared_at)
            or isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 1
            or (
                cleared_by_username is not None
                and (
                    not isinstance(cleared_by_username, str)
                    or not cleared_by_username
                    or len(cleared_by_username) > 128
                    or any(
                        character in cleared_by_username
                        for character in "\x00\r\n"
                    )
                )
            )
        ):
            raise ActionLedgerError(
                "invalid_input", "Demotion clearance is invalid"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM action_demotions WHERE demotion_id = ?",
                    (demotion_id,),
                ).fetchone()
                if row is None:
                    raise ActionLedgerError(
                        "not_found", "Action demotion was not found"
                    )
                demotion = self._demotion(row)
                if not demotion.active:
                    raise ActionLedgerError(
                        "already_cleared", "Action demotion is already cleared"
                    )
                if demotion.revision != expected_revision:
                    raise ActionLedgerError(
                        "conflict", "Action demotion changed concurrently"
                    )
                recovery = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?",
                    (recovery_action_id,),
                ).fetchone()
                if recovery is None:
                    raise ActionLedgerError(
                        "recovery_required",
                        "A verified approval-bound recovery is required",
                    )
                action = self._record(recovery)
                if (
                    action.operation != demotion.operation
                    or action.target != demotion.target
                    or action.trigger != "interactive"
                    or action.authority_mode != "approval"
                    or action.state != ActionState.SUCCEEDED
                    or action.terminal_code != "verified"
                    or self._parse_record_time(action.created_at)
                    < self._parse_record_time(demotion.demoted_at)
                ):
                    raise ActionLedgerError(
                        "recovery_required",
                        "A verified approval-bound recovery is required",
                    )
                succeeded = connection.execute(
                    """
                    SELECT 1 FROM action_events
                    WHERE action_id = ? AND phase = 'succeeded'
                    LIMIT 1
                    """,
                    (recovery_action_id,),
                ).fetchone()
                current_canary = connection.execute(
                    """
                    SELECT 1 FROM canary_attestations
                    WHERE source_action_id = ? AND operation = ? AND target = ?
                      AND release_commit = ? AND revoked_at IS NULL
                    LIMIT 1
                    """,
                    (
                        recovery_action_id,
                        demotion.operation,
                        demotion.target,
                        release_commit,
                    ),
                ).fetchone()
                if succeeded is None or current_canary is None:
                    raise ActionLedgerError(
                        "recovery_required",
                        "A current-release verified recovery is required",
                    )
                cursor = connection.execute(
                    """
                    UPDATE action_demotions SET
                        cleared_by_type = 'local', cleared_by_id = ?,
                        cleared_by_username = ?, cleared_at = ?,
                        recovery_action_id = ?, revision = revision + 1
                    WHERE demotion_id = ? AND revision = ? AND cleared_at IS NULL
                    """,
                    (
                        cleared_by_id,
                        cleared_by_username,
                        cleared_at,
                        recovery_action_id,
                        demotion_id,
                        expected_revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError(
                        "conflict", "Action demotion changed concurrently"
                    )
                updated = connection.execute(
                    "SELECT * FROM action_demotions WHERE demotion_id = ?",
                    (demotion_id,),
                ).fetchone()
            return self._demotion(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action demotion could not be cleared"
            ) from exc

    def approve(
        self,
        action_id: str,
        *,
        payload_hash: str,
        approver_type: str,
        approver_id: str,
        approver_username: str | None,
        approved_at: str,
    ) -> ActionRecord:
        return self._transition(
            action_id,
            expected={ActionState.AWAITING_APPROVAL},
            state=ActionState.AUTHORISED,
            payload_hash=payload_hash,
            values={
                "approved_by_type": approver_type,
                "approved_by_id": approver_id,
                "approved_by_username": approver_username,
                "approved_at": approved_at,
            },
        )

    def reject(self, action_id: str, *, rejected_at: str) -> ActionRecord:
        return self._transition(
            action_id,
            expected={ActionState.PROPOSED, ActionState.AWAITING_APPROVAL},
            state=ActionState.REJECTED,
            values={"terminal_code": f"rejected:{rejected_at}"},
        )

    def cancel(self, action_id: str, *, cancelled_at: str) -> ActionRecord:
        return self._transition(
            action_id,
            expected={
                ActionState.PROPOSED,
                ActionState.AWAITING_APPROVAL,
                ActionState.AUTHORISED,
            },
            state=ActionState.CANCELLED,
            values={"terminal_code": f"cancelled:{cancelled_at}"},
        )

    def cancel_pending_supervised_actions(
        self, *, cancelled_at: str
    ) -> list[ActionRecord]:
        """Invalidate every queued supervised mutation during integration disable."""
        if not self._valid_time(cancelled_at):
            raise ActionLedgerError(
                "invalid_input", "Supervision cancellation time is invalid"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT * FROM actions
                    WHERE authority_mode = 'supervised'
                      AND state = 'authorised'
                    ORDER BY created_at, action_id
                    """
                ).fetchall()
                cancelled: list[ActionRecord] = []
                for row in rows:
                    action = self._record(row)
                    cursor = connection.execute(
                        """
                        UPDATE actions SET
                            state = 'cancelled',
                            terminal_code = 'integration_disabled',
                            revision = revision + 1
                        WHERE action_id = ? AND revision = ?
                          AND state = 'authorised'
                        """,
                        (action.action_id, action.revision),
                    )
                    if cursor.rowcount != 1:
                        raise ActionLedgerError(
                            "conflict", "Action changed concurrently"
                        )
                    self._release_target_lease(
                        connection,
                        action_id=action.action_id,
                        released_at=cancelled_at,
                        terminal_code="integration_disabled",
                    )
                    self._close_supervision_authorization(
                        connection,
                        action_id=action.action_id,
                        invalidated_at=cancelled_at,
                        invalidation_code="integration_disabled",
                    )
                    updated = connection.execute(
                        "SELECT * FROM actions WHERE action_id = ?",
                        (action.action_id,),
                    ).fetchone()
                    cancelled.append(self._record(updated))
                return cancelled
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure",
                "Pending supervision actions could not be cancelled",
            ) from exc

    def invalidate_precondition(self, action_id: str) -> ActionRecord:
        return self._transition(
            action_id,
            expected={ActionState.AWAITING_APPROVAL, ActionState.AUTHORISED},
            state=ActionState.PRECONDITION_CHANGED,
            values={"terminal_code": "precondition_changed"},
        )

    def expire(self, action_id: str) -> ActionRecord:
        return self._transition(
            action_id,
            expected={
                ActionState.PROPOSED,
                ActionState.AWAITING_APPROVAL,
                ActionState.AUTHORISED,
            },
            state=ActionState.EXPIRED,
            values={"terminal_code": "expired"},
        )

    def expire_supervised_authorization(
        self,
        action_id: str,
        *,
        release_commit: str,
        expired_at: str,
    ) -> ActionRecord:
        if not self._valid_release_commit(release_commit) or not self._valid_time(
            expired_at
        ):
            raise ActionLedgerError(
                "invalid_input", "Supervision expiration is invalid"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                if row is None:
                    raise ActionLedgerError(
                        "not_found", "Action was not found"
                    )
                action = self._record(row)
                if (
                    action.state != ActionState.AUTHORISED
                    or action.trigger != "scheduled"
                    or action.authority_mode != "supervised"
                ):
                    raise ActionLedgerError(
                        "invalid_state", "Action state has changed"
                    )
                cursor = connection.execute(
                    """
                    UPDATE actions
                    SET state = 'expired', terminal_code = 'authorisation_expired',
                        revision = revision + 1
                    WHERE action_id = ? AND revision = ?
                    """,
                    (action_id, action.revision),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError(
                        "conflict", "Action changed concurrently"
                    )
                self._release_target_lease(
                    connection,
                    action_id=action_id,
                    released_at=expired_at,
                    terminal_code="authorisation_expired",
                )
                self._close_supervision_authorization(
                    connection,
                    action_id=action_id,
                    invalidated_at=expired_at,
                    invalidation_code="authorisation_expired",
                )
                self._insert_demotion(
                    connection,
                    action=action,
                    cause="authorisation_expired",
                    release_commit=release_commit,
                    demoted_at=expired_at,
                )
                updated = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
            return self._record(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure",
                "Supervision authorization could not be expired",
            ) from exc

    def fail_supervised_authorization(
        self,
        action_id: str,
        *,
        cause: str,
        release_commit: str,
        failed_at: str,
    ) -> ActionRecord:
        if (
            cause not in {"audit_failure", "identity_failure"}
            or not self._valid_release_commit(release_commit)
            or not self._valid_time(failed_at)
        ):
            raise ActionLedgerError(
                "invalid_input", "Supervision failure is invalid"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                if row is None:
                    raise ActionLedgerError(
                        "not_found", "Action was not found"
                    )
                action = self._record(row)
                authorization = connection.execute(
                    """
                    SELECT * FROM supervision_authorizations
                    WHERE action_id = ?
                    """,
                    (action_id,),
                ).fetchone()
                if (
                    action.state != ActionState.AUTHORISED
                    or action.trigger != "scheduled"
                    or action.authority_mode != "supervised"
                    or authorization is None
                    or self._authorization(authorization).release_commit
                    != release_commit
                ):
                    raise ActionLedgerError(
                        "invalid_state", "Action state has changed"
                    )
                cursor = connection.execute(
                    """
                    UPDATE actions SET
                        state = 'escalation_required', terminal_code = ?,
                        revision = revision + 1
                    WHERE action_id = ? AND revision = ?
                    """,
                    (cause, action_id, action.revision),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError(
                        "conflict", "Action changed concurrently"
                    )
                self._release_target_lease(
                    connection,
                    action_id=action_id,
                    released_at=failed_at,
                    terminal_code=cause,
                )
                self._close_supervision_authorization(
                    connection,
                    action_id=action_id,
                    invalidated_at=failed_at,
                    invalidation_code=cause,
                )
                self._insert_demotion(
                    connection,
                    action=action,
                    cause=cause,
                    release_commit=release_commit,
                    demoted_at=failed_at,
                )
                updated = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
            return self._record(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Supervision failure could not be saved"
            ) from exc

    def claim_execution(
        self,
        action_id: str,
        *,
        payload_hash: str,
        approval_required: bool,
        claimed_at: str,
    ) -> ActionRecord:
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                if row is None:
                    raise ActionLedgerError("not_found", "Action was not found")
                record = self._record(row)
                if record.state != ActionState.AUTHORISED:
                    raise ActionLedgerError("invalid_state", "Action state has changed")
                if record.payload_hash != payload_hash:
                    raise ActionLedgerError("payload_changed", "Action payload has changed")
                lease = connection.execute(
                    """
                    SELECT * FROM action_target_leases
                    WHERE action_id = ? AND operation = ? AND target = ?
                      AND released_at IS NULL
                    """,
                    (action_id, record.operation, record.target),
                ).fetchone()
                if lease is None:
                    raise ActionLedgerError(
                        "target_lease_missing",
                        "Action does not own its exact-target lease",
                    )
                if (
                    record.trigger == "scheduled"
                    and record.authority_mode == "supervised"
                ):
                    authorization = connection.execute(
                        """
                        SELECT * FROM supervision_authorizations
                        WHERE action_id = ?
                        """,
                        (action_id,),
                    ).fetchone()
                    if authorization is None:
                        raise ActionLedgerError(
                            "authorization_required",
                            "Supervised action authorization is unavailable",
                        )
                    authorization_record = self._authorization(authorization)
                    claimed_time = self._parse_record_time(claimed_at)
                    if (
                        authorization_record.consumed_at is not None
                        or authorization_record.invalidated_at is not None
                        or claimed_time
                        >= self._parse_record_time(
                            authorization_record.expires_at
                        )
                        or claimed_time
                        >= self._parse_record_time(
                            authorization_record.window_deadline
                        )
                    ):
                        raise ActionLedgerError(
                            "authorization_expired",
                            "Supervised action authorization has expired",
                        )
                    occupied_slot = connection.execute(
                        "SELECT action_id FROM supervised_execution_slot WHERE slot = 1"
                    ).fetchone()
                    if occupied_slot is not None:
                        raise ActionLedgerError(
                            "supervised_busy",
                            "Another supervised mutation is executing",
                        )
                    connection.execute(
                        """
                        INSERT INTO supervised_execution_slot (
                            slot, action_id, acquired_at
                        ) VALUES (1, ?, ?)
                        """,
                        (action_id, claimed_at),
                    )
                    cursor = connection.execute(
                        """
                        UPDATE supervision_authorizations
                        SET consumed_at = ?
                        WHERE action_id = ? AND consumed_at IS NULL
                          AND invalidated_at IS NULL
                        """,
                        (claimed_at, action_id),
                    )
                    if cursor.rowcount != 1:
                        raise ActionLedgerError(
                            "conflict", "Supervision authorization changed"
                        )
                if approval_required and (
                    record.approved_at is None or record.approval_used_at is not None
                ):
                    raise ActionLedgerError("invalid_approval", "Approval is not executable")
                approval_used_at = claimed_at if approval_required else record.approval_used_at
                cursor = connection.execute(
                    """
                    UPDATE actions
                    SET state = ?, approval_used_at = ?, revision = revision + 1
                    WHERE action_id = ? AND revision = ?
                    """,
                    (
                        ActionState.EXECUTING.value,
                        approval_used_at,
                        action_id,
                        record.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError("conflict", "Action changed concurrently")
                updated = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                return self._record(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError("store_failure", "Action could not be claimed") from exc

    def begin_verification(self, action_id: str) -> ActionRecord:
        return self._transition(
            action_id,
            expected={ActionState.EXECUTING},
            state=ActionState.VERIFYING,
        )

    def finish_execution(
        self,
        action_id: str,
        *,
        state: ActionState,
        terminal_code: str,
        demotion_cause: str | None = None,
        release_commit: str | None = None,
        finished_at: str | None = None,
    ) -> ActionRecord:
        if state not in {
            ActionState.SUCCEEDED,
            ActionState.EXECUTION_FAILED,
            ActionState.VERIFICATION_FAILED,
            ActionState.ESCALATION_REQUIRED,
        }:
            raise ActionLedgerError("invalid_update", "Execution result is invalid")
        expected = (
            {ActionState.EXECUTING}
            if state == ActionState.EXECUTION_FAILED
            else {ActionState.VERIFYING}
        )
        if (demotion_cause is None) != (release_commit is None):
            raise ActionLedgerError(
                "invalid_update", "Execution demotion is incomplete"
            )
        completed_at = finished_at or utc_now().isoformat()
        if not self._valid_time(completed_at):
            raise ActionLedgerError(
                "invalid_update", "Execution completion time is invalid"
            )
        if demotion_cause is not None and (
            demotion_cause not in DEMOTION_CAUSES
            or not self._valid_release_commit(release_commit)
        ):
            raise ActionLedgerError(
                "invalid_update", "Execution demotion is invalid"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                if row is None:
                    raise ActionLedgerError(
                        "not_found", "Action was not found"
                    )
                action = self._record(row)
                if action.state not in expected:
                    raise ActionLedgerError(
                        "invalid_state", "Action state has changed"
                    )
                cursor = connection.execute(
                    """
                    UPDATE actions
                    SET state = ?, terminal_code = ?, revision = revision + 1
                    WHERE action_id = ? AND revision = ?
                    """,
                    (
                        state.value,
                        terminal_code,
                        action_id,
                        action.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError(
                        "conflict", "Action changed concurrently"
                    )
                self._release_target_lease(
                    connection,
                    action_id=action_id,
                    released_at=completed_at,
                    terminal_code=terminal_code,
                )
                self._release_supervised_slot(
                    connection, action_id=action_id
                )
                self._close_supervision_authorization(
                    connection,
                    action_id=action_id,
                    invalidated_at=completed_at,
                    invalidation_code=terminal_code,
                )
                if demotion_cause is not None:
                    if (
                        action.trigger != "scheduled"
                        or action.authority_mode != "supervised"
                    ):
                        raise ActionLedgerError(
                            "ineligible_source",
                            "Only a supervised repair can create a demotion",
                        )
                    self._insert_demotion(
                        connection,
                        action=action,
                        cause=demotion_cause,
                        release_commit=release_commit,
                        demoted_at=completed_at,
                    )
                updated = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
            return self._record(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Action execution could not be finished"
            ) from exc

    def record_event(
        self,
        action_id: str,
        *,
        phase: str,
        created_at: str,
        details: dict[str, Any],
    ) -> None:
        if (
            not isinstance(phase, str)
            or not phase
            or len(phase) > 64
            or not isinstance(details, dict)
        ):
            raise ActionLedgerError("invalid_input", "Action event is invalid")
        try:
            payload = canonical_json(details)
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO action_events (action_id, phase, created_at, details_json)
                    SELECT action_id, ?, ?, ? FROM actions WHERE action_id = ?
                    """,
                    (phase, created_at, payload, action_id),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError("not_found", "Action was not found")
        except ActionLedgerError:
            raise
        except (CapabilityError, sqlite3.Error) as exc:
            raise ActionLedgerError("store_failure", "Action event could not be saved") from exc

    def events(self, action_id: str) -> list[dict[str, Any]]:
        self.get(action_id)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT phase, created_at, details_json
                    FROM action_events WHERE action_id = ? ORDER BY event_id
                    """,
                    (action_id,),
                ).fetchall()
            return [
                {
                    "phase": row["phase"],
                    "created_at": row["created_at"],
                    "details": json.loads(row["details_json"]),
                }
                for row in rows
            ]
        except (sqlite3.Error, ValueError, TypeError) as exc:
            raise ActionLedgerError("store_failure", "Action events could not be read") from exc

    def attest_canary(
        self,
        *,
        attestation_id: str,
        source_action_id: str,
        operation: str,
        target: str,
        capability_version: str,
        risk: str,
        release_commit: str,
        attested_by_type: str,
        attested_by_id: str,
        attested_by_username: str | None,
        attested_at: str,
    ) -> tuple[CanaryAttestationRecord, bool]:
        values = {
            "attestation_id": attestation_id,
            "source_action_id": source_action_id,
            "operation": operation,
            "target": target,
            "capability_version": capability_version,
            "risk": risk,
            "release_commit": release_commit,
            "attested_by_type": attested_by_type,
            "attested_by_id": attested_by_id,
            "attested_at": attested_at,
        }
        if any(
            not isinstance(value, str) or not value or len(value) > 128
            for value in values.values()
        ) or (
            attested_by_username is not None
            and (
                not isinstance(attested_by_username, str)
                or not attested_by_username
                or len(attested_by_username) > 128
                or any(character in attested_by_username for character in "\x00\r\n")
            )
        ):
            raise ActionLedgerError("invalid_input", "Canary attestation is invalid")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM canary_attestations WHERE source_action_id = ?",
                    (source_action_id,),
                ).fetchone()
                if existing is not None:
                    return self._canary_record(existing), False

                source = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?",
                    (source_action_id,),
                ).fetchone()
                if source is None:
                    raise ActionLedgerError("not_found", "Source action was not found")
                action = self._record(source)
                if (
                    action.state != ActionState.SUCCEEDED
                    or action.terminal_code != "verified"
                    or action.operation != operation
                    or action.target != target
                    or action.capability_version != capability_version
                    or action.risk != risk
                    or action.trigger != "interactive"
                    or action.authority_mode != "approval"
                ):
                    raise ActionLedgerError(
                        "ineligible_source", "Source action is not eligible"
                    )

                succeeded = connection.execute(
                    """
                    SELECT details_json FROM action_events
                    WHERE action_id = ? AND phase = 'succeeded'
                    ORDER BY event_id DESC LIMIT 1
                    """,
                    (source_action_id,),
                ).fetchone()
                if succeeded is None:
                    raise ActionLedgerError(
                        "unverified_source", "Source action has no verification evidence"
                    )
                success_details = json.loads(succeeded["details_json"])
                if (
                    not isinstance(success_details, dict)
                    or not isinstance(success_details.get("action_audit_id"), str)
                    or not success_details["action_audit_id"]
                    or not isinstance(success_details.get("after"), dict)
                ):
                    raise ActionLedgerError(
                        "unverified_source", "Source action has invalid verification evidence"
                    )

                active = connection.execute(
                    """
                    SELECT attestation_id FROM canary_attestations
                    WHERE operation = ? AND target = ? AND trigger = 'scheduled'
                      AND capability_version = ? AND revoked_at IS NULL
                    """,
                    (operation, target, capability_version),
                ).fetchone()
                if active is not None:
                    raise ActionLedgerError(
                        "active_conflict", "An active canary already exists"
                    )

                connection.execute(
                    """
                    INSERT INTO canary_attestations (
                        attestation_id, operation, target, trigger,
                        capability_version, risk, source_action_id, release_commit,
                        attested_by_type, attested_by_id, attested_by_username,
                        attested_at
                    ) VALUES (?, ?, ?, 'scheduled', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attestation_id,
                        operation,
                        target,
                        capability_version,
                        risk,
                        source_action_id,
                        release_commit,
                        attested_by_type,
                        attested_by_id,
                        attested_by_username,
                        attested_at,
                    ),
                )
                event_details = canonical_json(
                    {
                        "actor": {
                            "type": attested_by_type,
                            "id": attested_by_id,
                            "username": attested_by_username,
                        },
                        "attestation_id": attestation_id,
                        "capability_version": capability_version,
                        "operation": operation,
                        "release_commit": release_commit,
                        "target": target,
                        "trigger": "scheduled",
                    }
                )
                connection.execute(
                    """
                    INSERT INTO action_events (
                        action_id, phase, created_at, details_json
                    ) VALUES (?, 'canary_attested', ?, ?)
                    """,
                    (source_action_id, attested_at, event_details),
                )
                row = connection.execute(
                    "SELECT * FROM canary_attestations WHERE attestation_id = ?",
                    (attestation_id,),
                ).fetchone()
                return self._canary_record(row), True
        except ActionLedgerError:
            raise
        except (CapabilityError, json.JSONDecodeError, TypeError, sqlite3.Error) as exc:
            raise ActionLedgerError(
                "store_failure", "Canary attestation could not be saved"
            ) from exc

    def revoke_canary(
        self,
        attestation_id: str,
        *,
        revoked_by_type: str,
        revoked_by_id: str,
        revoked_by_username: str | None,
        revoked_at: str,
    ) -> CanaryAttestationRecord:
        values = {
            "attestation_id": attestation_id,
            "revoked_by_type": revoked_by_type,
            "revoked_by_id": revoked_by_id,
            "revoked_at": revoked_at,
        }
        if any(
            not isinstance(value, str) or not value or len(value) > 128
            for value in values.values()
        ) or (
            revoked_by_username is not None
            and (
                not isinstance(revoked_by_username, str)
                or not revoked_by_username
                or len(revoked_by_username) > 128
                or any(character in revoked_by_username for character in "\x00\r\n")
            )
        ):
            raise ActionLedgerError("invalid_input", "Canary revocation is invalid")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM canary_attestations WHERE attestation_id = ?",
                    (attestation_id,),
                ).fetchone()
                if row is None:
                    raise ActionLedgerError("not_found", "Canary attestation was not found")
                record = self._canary_record(row)
                if not record.active:
                    raise ActionLedgerError(
                        "already_revoked", "Canary attestation is already revoked"
                    )
                cursor = connection.execute(
                    """
                    UPDATE canary_attestations
                    SET revoked_by_type = ?, revoked_by_id = ?,
                        revoked_by_username = ?, revoked_at = ?
                    WHERE attestation_id = ? AND revoked_at IS NULL
                    """,
                    (
                        revoked_by_type,
                        revoked_by_id,
                        revoked_by_username,
                        revoked_at,
                        attestation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError("conflict", "Canary attestation changed")
                event_details = canonical_json(
                    {
                        "actor": {
                            "type": revoked_by_type,
                            "id": revoked_by_id,
                            "username": revoked_by_username,
                        },
                        "attestation_id": attestation_id,
                    }
                )
                connection.execute(
                    """
                    INSERT INTO action_events (
                        action_id, phase, created_at, details_json
                    ) VALUES (?, 'canary_revoked', ?, ?)
                    """,
                    (record.source_action_id, revoked_at, event_details),
                )
                updated = connection.execute(
                    "SELECT * FROM canary_attestations WHERE attestation_id = ?",
                    (attestation_id,),
                ).fetchone()
                return self._canary_record(updated)
        except ActionLedgerError:
            raise
        except (CapabilityError, sqlite3.Error) as exc:
            raise ActionLedgerError(
                "store_failure", "Canary attestation could not be revoked"
            ) from exc

    def canaries(self, *, limit: int = 200) -> list[CanaryAttestationRecord]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ActionLedgerError("invalid_input", "Canary limit must be between 1 and 200")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT * FROM canary_attestations
                    ORDER BY attested_at DESC, attestation_id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            return [self._canary_record(row) for row in rows]
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Canary attestations could not be read"
            ) from exc

    def canary_for_source(
        self, source_action_id: str
    ) -> CanaryAttestationRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM canary_attestations
                    WHERE source_action_id = ?
                    """,
                    (source_action_id,),
                ).fetchone()
            return self._canary_record(row) if row is not None else None
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Canary attestation could not be read"
            ) from exc

    def active_canary(
        self,
        *,
        operation: str,
        target: str,
        trigger: str,
        capability_version: str,
    ) -> CanaryAttestationRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT * FROM canary_attestations
                    WHERE operation = ? AND target = ? AND trigger = ?
                      AND capability_version = ? AND revoked_at IS NULL
                    """,
                    (operation, target, trigger, capability_version),
                ).fetchone()
            return self._canary_record(row) if row is not None else None
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError(
                "store_failure", "Canary attestation could not be read"
            ) from exc

    def _transition(
        self,
        action_id: str,
        *,
        expected: set[ActionState],
        state: ActionState,
        values: dict[str, Any] | None = None,
        payload_hash: str | None = None,
    ) -> ActionRecord:
        values = values or {}
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                if row is None:
                    raise ActionLedgerError("not_found", "Action was not found")
                record = self._record(row)
                if record.state not in expected:
                    raise ActionLedgerError("invalid_state", "Action state has changed")
                if payload_hash is not None and record.payload_hash != payload_hash:
                    raise ActionLedgerError("payload_changed", "Action payload has changed")
                assignments = ["state = ?", "revision = revision + 1"]
                parameters: list[Any] = [state.value]
                for field, value in values.items():
                    if field not in {
                        "approved_by_type",
                        "approved_by_id",
                        "approved_by_username",
                        "approved_at",
                        "approval_used_at",
                        "terminal_code",
                    }:
                        raise ActionLedgerError("invalid_update", "Action update is invalid")
                    assignments.append(f"{field} = ?")
                    parameters.append(value)
                parameters.extend((action_id, record.revision))
                cursor = connection.execute(
                    f"UPDATE actions SET {', '.join(assignments)} "
                    "WHERE action_id = ? AND revision = ?",
                    parameters,
                )
                if cursor.rowcount != 1:
                    raise ActionLedgerError("conflict", "Action changed concurrently")
                if state not in _ACTIVE_ACTION_STATES:
                    released_at = utc_now().isoformat()
                    self._release_target_lease(
                        connection,
                        action_id=action_id,
                        released_at=released_at,
                        terminal_code=values.get("terminal_code") or state.value,
                    )
                    self._release_supervised_slot(
                        connection, action_id=action_id
                    )
                    self._close_supervision_authorization(
                        connection,
                        action_id=action_id,
                        invalidated_at=released_at,
                        invalidation_code=(
                            values.get("terminal_code") or state.value
                        ),
                    )
                updated = connection.execute(
                    "SELECT * FROM actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                return self._record(updated)
        except ActionLedgerError:
            raise
        except sqlite3.Error as exc:
            raise ActionLedgerError("store_failure", "Action could not be updated") from exc

    @staticmethod
    def _record(row: sqlite3.Row) -> ActionRecord:
        try:
            params = json.loads(row["params_json"])
            evidence_ids = json.loads(row["evidence_json"])
            if not isinstance(params, dict) or not isinstance(evidence_ids, list):
                raise ValueError("invalid action JSON")
            return ActionRecord(
                action_id=row["action_id"],
                idempotency_key=row["idempotency_key"],
                operation=row["operation"],
                capability_version=row["capability_version"],
                target=row["target"],
                risk=row["risk"],
                trigger=row["trigger"],
                authority_mode=row["authority_mode"],
                params=params,
                evidence_ids=evidence_ids,
                payload_hash=row["payload_hash"],
                reason=row["reason"],
                impact=row["impact"],
                precondition_hash=row["precondition_hash"],
                actor_type=row["actor_type"],
                actor_id=row["actor_id"],
                actor_username=row["actor_username"],
                state=ActionState(row["state"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                approved_by_type=row["approved_by_type"],
                approved_by_id=row["approved_by_id"],
                approved_by_username=row["approved_by_username"],
                approved_at=row["approved_at"],
                approval_used_at=row["approval_used_at"],
                terminal_code=row["terminal_code"],
                revision=row["revision"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ActionLedgerError("corrupt_store", "Action record is invalid") from exc

    @staticmethod
    def _canary_record(row: sqlite3.Row) -> CanaryAttestationRecord:
        try:
            record = CanaryAttestationRecord(
                attestation_id=row["attestation_id"],
                operation=row["operation"],
                target=row["target"],
                trigger=row["trigger"],
                capability_version=row["capability_version"],
                risk=row["risk"],
                source_action_id=row["source_action_id"],
                release_commit=row["release_commit"],
                attested_by_type=row["attested_by_type"],
                attested_by_id=row["attested_by_id"],
                attested_by_username=row["attested_by_username"],
                attested_at=row["attested_at"],
                revoked_by_type=row["revoked_by_type"],
                revoked_by_id=row["revoked_by_id"],
                revoked_by_username=row["revoked_by_username"],
                revoked_at=row["revoked_at"],
            )
            required = (
                record.attestation_id,
                record.operation,
                record.target,
                record.trigger,
                record.capability_version,
                record.risk,
                record.source_action_id,
                record.release_commit,
                record.attested_by_type,
                record.attested_by_id,
                record.attested_at,
            )
            if any(
                not isinstance(value, str) or not value or len(value) > 128
                for value in required
            ):
                raise ValueError("invalid canary value")
            if (
                not RESOURCE_RE.fullmatch(record.attestation_id)
                or not CAPABILITY_ID_RE.fullmatch(record.operation)
                or not RESOURCE_RE.fullmatch(record.target)
                or record.trigger != "scheduled"
                or not VERSION_RE.fullmatch(record.capability_version)
                or record.risk != "R1"
                or not RESOURCE_RE.fullmatch(record.source_action_id)
                or len(record.release_commit) not in {40, 64}
                or any(
                    character not in "0123456789abcdef"
                    for character in record.release_commit
                )
            ):
                raise ValueError("invalid canary contract")
            for actor_type, actor_id, username in (
                (
                    record.attested_by_type,
                    record.attested_by_id,
                    record.attested_by_username,
                ),
                (
                    record.revoked_by_type,
                    record.revoked_by_id,
                    record.revoked_by_username,
                ),
            ):
                if actor_type is not None and actor_type != "local":
                    raise ValueError("invalid canary actor")
                if actor_id is not None and (
                    not isinstance(actor_id, str)
                    or not RESOURCE_RE.fullmatch(actor_id)
                ):
                    raise ValueError("invalid canary actor")
                if username is not None and (
                    not isinstance(username, str)
                    or not username
                    or len(username) > 128
                    or any(character in username for character in "\x00\r\n")
                ):
                    raise ValueError("invalid canary actor")
            revoked_values = (
                record.revoked_by_type,
                record.revoked_by_id,
                record.revoked_at,
            )
            if any(value is None for value in revoked_values) != all(
                value is None for value in revoked_values
            ):
                raise ValueError("partial canary revocation")
            return record
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionLedgerError(
                "corrupt_store", "Canary attestation is invalid"
            ) from exc

    @staticmethod
    def _release_target_lease(
        connection: sqlite3.Connection,
        *,
        action_id: str,
        released_at: str,
        terminal_code: str,
    ) -> None:
        connection.execute(
            """
            UPDATE action_target_leases
            SET released_at = ?, terminal_code = ?
            WHERE action_id = ? AND released_at IS NULL
            """,
            (released_at, terminal_code, action_id),
        )

    @staticmethod
    def _target_lease(row: sqlite3.Row) -> TargetLeaseRecord:
        try:
            return TargetLeaseRecord(
                lease_id=row["lease_id"],
                operation=row["operation"],
                target=row["target"],
                action_id=row["action_id"],
                acquired_at=row["acquired_at"],
                released_at=row["released_at"],
                terminal_code=row["terminal_code"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionLedgerError(
                "corrupt_store", "Action target lease is invalid"
            ) from exc

    @staticmethod
    def _authorization(
        row: sqlite3.Row,
    ) -> SupervisionAuthorizationRecord:
        try:
            record = SupervisionAuthorizationRecord(
                authorization_id=row["authorization_id"],
                occurrence_key=row["occurrence_key"],
                action_id=row["action_id"],
                schedule_id=row["schedule_id"],
                schedule_revision=row["schedule_revision"],
                incident_id=row["incident_id"],
                assessment_id=row["assessment_id"],
                assessed_for=row["assessed_for"],
                operation=row["operation"],
                target=row["target"],
                capability_version=row["capability_version"],
                release_commit=row["release_commit"],
                window_key=row["window_key"],
                window_start=row["window_start"],
                window_deadline=row["window_deadline"],
                authorized_at=row["authorized_at"],
                expires_at=row["expires_at"],
                consumed_at=row["consumed_at"],
                invalidated_at=row["invalidated_at"],
                invalidation_code=row["invalidation_code"],
            )
            identifiers = (
                record.authorization_id,
                record.occurrence_key,
                record.action_id,
                record.schedule_id,
                record.incident_id,
                record.assessment_id,
                record.window_key,
            )
            times = (
                record.assessed_for,
                record.window_start,
                record.window_deadline,
                record.authorized_at,
                record.expires_at,
            )
            if (
                any(RESOURCE_RE.fullmatch(value) is None for value in identifiers)
                or not CAPABILITY_ID_RE.fullmatch(record.operation)
                or not RESOURCE_RE.fullmatch(record.target)
                or not VERSION_RE.fullmatch(record.capability_version)
                or not ActionLedger._valid_release_commit(record.release_commit)
                or not all(ActionLedger._valid_time(value) for value in times)
                or isinstance(record.schedule_revision, bool)
                or not isinstance(record.schedule_revision, int)
                or record.schedule_revision < 1
                or (
                    record.consumed_at is not None
                    and not ActionLedger._valid_time(record.consumed_at)
                )
                or (
                    record.invalidated_at is not None
                    and (
                        not ActionLedger._valid_time(record.invalidated_at)
                        or not isinstance(record.invalidation_code, str)
                        or not record.invalidation_code
                        or len(record.invalidation_code) > 128
                    )
                )
                or (
                    record.invalidated_at is None
                    and record.invalidation_code is not None
                )
            ):
                raise ValueError("invalid supervision authorization")
            return record
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionLedgerError(
                "corrupt_store", "Supervision authorization is invalid"
            ) from exc

    @staticmethod
    def _release_supervised_slot(
        connection: sqlite3.Connection, *, action_id: str
    ) -> None:
        connection.execute(
            "DELETE FROM supervised_execution_slot WHERE action_id = ?",
            (action_id,),
        )

    @staticmethod
    def _close_supervision_authorization(
        connection: sqlite3.Connection,
        *,
        action_id: str,
        invalidated_at: str,
        invalidation_code: str,
    ) -> None:
        connection.execute(
            """
            UPDATE supervision_authorizations
            SET invalidated_at = ?, invalidation_code = ?
            WHERE action_id = ? AND consumed_at IS NULL
              AND invalidated_at IS NULL
            """,
            (invalidated_at, invalidation_code[:128], action_id),
        )

    @staticmethod
    def _demotion(row: sqlite3.Row) -> DemotionRecord:
        try:
            record = DemotionRecord(
                demotion_id=row["demotion_id"],
                operation=row["operation"],
                target=row["target"],
                cause=row["cause"],
                source_action_id=row["source_action_id"],
                release_commit=row["release_commit"],
                demoted_at=row["demoted_at"],
                cleared_by_type=row["cleared_by_type"],
                cleared_by_id=row["cleared_by_id"],
                cleared_by_username=row["cleared_by_username"],
                cleared_at=row["cleared_at"],
                recovery_action_id=row["recovery_action_id"],
                revision=row["revision"],
            )
            if (
                not RESOURCE_RE.fullmatch(record.demotion_id)
                or not CAPABILITY_ID_RE.fullmatch(record.operation)
                or not RESOURCE_RE.fullmatch(record.target)
                or record.cause not in DEMOTION_CAUSES
                or not RESOURCE_RE.fullmatch(record.source_action_id)
                or not ActionLedger._valid_release_commit(record.release_commit)
                or not ActionLedger._valid_time(record.demoted_at)
                or isinstance(record.revision, bool)
                or not isinstance(record.revision, int)
                or record.revision < 1
            ):
                raise ValueError("invalid demotion")
            cleared_values = (
                record.cleared_by_type,
                record.cleared_by_id,
                record.cleared_at,
                record.recovery_action_id,
            )
            if any(value is None for value in cleared_values) != all(
                value is None for value in cleared_values
            ):
                raise ValueError("partial demotion clearance")
            if record.cleared_at is not None and (
                record.cleared_by_type != "local"
                or not RESOURCE_RE.fullmatch(record.cleared_by_id or "")
                or not RESOURCE_RE.fullmatch(record.recovery_action_id or "")
                or not ActionLedger._valid_time(record.cleared_at)
            ):
                raise ValueError("invalid demotion clearance")
            if record.cleared_by_username is not None and (
                not isinstance(record.cleared_by_username, str)
                or not record.cleared_by_username
                or len(record.cleared_by_username) > 128
                or any(
                    character in record.cleared_by_username
                    for character in "\x00\r\n"
                )
            ):
                raise ValueError("invalid demotion actor")
            return record
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionLedgerError(
                "corrupt_store", "Action demotion is invalid"
            ) from exc

    @staticmethod
    def _insert_demotion(
        connection: sqlite3.Connection,
        *,
        action: ActionRecord,
        cause: str,
        release_commit: str,
        demoted_at: str,
    ) -> None:
        active = connection.execute(
            """
            SELECT 1 FROM action_demotions
            WHERE operation = ? AND target = ? AND cleared_at IS NULL
            LIMIT 1
            """,
            (action.operation, action.target),
        ).fetchone()
        if active is not None:
            return
        digest = hashlib.sha256(
            (
                f"{action.operation}\x00{action.target}\x00{action.action_id}"
                f"\x00{cause}\x00{demoted_at}"
            ).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO action_demotions (
                demotion_id, operation, target, cause, source_action_id,
                release_commit, demoted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"demotion-{digest[:32]}",
                action.operation,
                action.target,
                cause,
                action.action_id,
                release_commit,
                demoted_at,
            ),
        )

    @staticmethod
    def _validate_demotion_input(
        *,
        operation: str,
        target: str,
        cause: str,
        source_action_id: str,
        release_commit: str,
        at: str,
    ) -> None:
        if (
            not isinstance(operation, str)
            or not CAPABILITY_ID_RE.fullmatch(operation)
            or not isinstance(target, str)
            or not RESOURCE_RE.fullmatch(target)
            or cause not in DEMOTION_CAUSES
            or not isinstance(source_action_id, str)
            or not RESOURCE_RE.fullmatch(source_action_id)
            or not ActionLedger._valid_release_commit(release_commit)
            or not ActionLedger._valid_time(at)
        ):
            raise ActionLedgerError(
                "invalid_input", "Action demotion is invalid"
            )

    @staticmethod
    def _valid_release_commit(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) in {40, 64}
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _valid_time(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return False
        return parsed.tzinfo is not None

    @staticmethod
    def _parse_record_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ActionLedgerError(
                "corrupt_store", "Action ledger time is invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise ActionLedgerError(
                "corrupt_store", "Action ledger time is invalid"
            )
        return parsed.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
