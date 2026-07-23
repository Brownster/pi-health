"""Transactional action proposal, approval, and execution ledger."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
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
"""


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
        return self._transition(
            action_id,
            expected=expected,
            state=state,
            values={"terminal_code": terminal_code},
        )

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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
