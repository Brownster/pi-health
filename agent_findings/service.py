"""Transactional local drafts for bugs, feature requests, and operational gaps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_actions.capability import ActionActor, canonical_json
from limeops.operations import redact_text


KINDS = frozenset({"bug", "feature_request", "maintenance_gap", "documentation_gap"})
SOURCES = frozenset({"user_discussion", "failed_action", "recurring_incident", "review", "manual"})
CONFIDENCE = frozenset({"low", "medium", "high"})
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_FIELDS = frozenset(
    {
        "kind",
        "title",
        "summary",
        "component",
        "affected_version",
        "expected_behavior",
        "actual_behavior",
        "reproduction_steps",
        "impact",
        "frequency",
        "workaround",
        "confidence",
        "acceptance_criteria",
        "source_type",
    }
)


class FindingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FindingsService:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o770)
        if self._path.is_symlink():
            raise FindingError("unsafe_store", "Findings store cannot be a symlink")
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS findings (
                        finding_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        state TEXT NOT NULL,
                        content_json TEXT NOT NULL,
                        evidence_json TEXT NOT NULL,
                        actor_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_username TEXT,
                        redaction_applied INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        revision INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE INDEX IF NOT EXISTS findings_updated_idx
                        ON findings(updated_at DESC);
                    """
                )
            os.chmod(self._path, 0o660)
        except (OSError, sqlite3.Error) as exc:
            raise FindingError("store_unavailable", "Findings store is unavailable") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def propose(
        self,
        *,
        finding: Any,
        actor: Any,
        evidence_ids: Sequence[str],
        finding_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        source_actor = ActionActor.from_mapping(actor)
        content, redacted = self._normalize(finding)
        evidence = self._evidence(evidence_ids)
        fingerprint = self._fingerprint(content)
        now = datetime.now(timezone.utc).isoformat()
        finding_id = finding_id or uuid.uuid4().hex
        if not _ID_RE.fullmatch(finding_id):
            raise FindingError("invalid_input", "Finding ID is invalid")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM findings WHERE fingerprint = ?", (fingerprint,)
                ).fetchone()
                if existing is not None:
                    return self._public(existing), False
                connection.execute(
                    """
                    INSERT INTO findings (
                        finding_id, fingerprint, state, content_json, evidence_json,
                        actor_type, actor_id, actor_username, redaction_applied,
                        created_at, updated_at
                    ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        fingerprint,
                        canonical_json(content),
                        canonical_json(evidence),
                        source_actor.type,
                        source_actor.id,
                        source_actor.username,
                        int(redacted),
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
                ).fetchone()
                return self._public(row), True
        except FindingError:
            raise
        except (sqlite3.Error, ValueError) as exc:
            raise FindingError("store_failure", "Finding could not be saved") from exc

    def list(self, *, limit: int = 50) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise FindingError("invalid_input", "Finding limit is invalid")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM findings ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return {"findings": [self._public(row) for row in rows]}
        except sqlite3.Error as exc:
            raise FindingError("store_failure", "Findings could not be read") from exc

    def get(self, finding_id: str) -> dict[str, Any]:
        if not isinstance(finding_id, str) or not _ID_RE.fullmatch(finding_id):
            raise FindingError("not_found", "Finding was not found")
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM findings WHERE finding_id = ?", (finding_id,)
                ).fetchone()
        except sqlite3.Error as exc:
            raise FindingError("store_failure", "Finding could not be read") from exc
        if row is None:
            raise FindingError("not_found", "Finding was not found")
        return self._public(row)

    def update(self, finding_id: str, finding: Any) -> dict[str, Any]:
        current = self.get(finding_id)
        if current["state"] != "draft":
            raise FindingError("invalid_state", "Finding is no longer editable")
        content, redacted = self._normalize(finding)
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE findings SET content_json = ?, redaction_applied = ?,
                        updated_at = ?, revision = revision + 1
                    WHERE finding_id = ? AND revision = ? AND state = 'draft'
                    """,
                    (
                        canonical_json(content),
                        int(redacted or current["redaction_applied"]),
                        now,
                        finding_id,
                        current["revision"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise FindingError("conflict", "Finding changed concurrently")
            return self.get(finding_id)
        except FindingError:
            raise
        except sqlite3.Error as exc:
            raise FindingError("store_failure", "Finding could not be updated") from exc

    def reject(self, finding_id: str) -> dict[str, Any]:
        current = self.get(finding_id)
        if current["state"] != "draft":
            raise FindingError("invalid_state", "Finding state has changed")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE findings SET state = 'rejected', updated_at = ?,
                        revision = revision + 1
                    WHERE finding_id = ? AND revision = ? AND state = 'draft'
                    """,
                    (now, finding_id, current["revision"]),
                )
                if cursor.rowcount != 1:
                    raise FindingError("conflict", "Finding changed concurrently")
            return self.get(finding_id)
        except FindingError:
            raise
        except sqlite3.Error as exc:
            raise FindingError("store_failure", "Finding could not be rejected") from exc

    @classmethod
    def _normalize(cls, value: Any) -> tuple[dict[str, Any], bool]:
        if not isinstance(value, Mapping) or set(value) != _FIELDS:
            raise FindingError("invalid_input", "Finding fields are invalid")
        if value.get("kind") not in KINDS or value.get("source_type") not in SOURCES:
            raise FindingError("invalid_input", "Finding classification is invalid")
        if value.get("confidence") not in CONFIDENCE:
            raise FindingError("invalid_input", "Finding confidence is invalid")
        content = {
            "kind": value["kind"],
            "source_type": value["source_type"],
            "confidence": value["confidence"],
        }
        redacted = False
        limits = {
            "title": 160,
            "summary": 2000,
            "component": 128,
            "affected_version": 128,
            "expected_behavior": 1500,
            "actual_behavior": 1500,
            "impact": 1000,
            "frequency": 256,
            "workaround": 1000,
        }
        for field, limit in limits.items():
            required = field in {"title", "summary", "component", "impact"}
            text, changed = cls._text(value.get(field), limit=limit, required=required)
            content[field] = text
            redacted = redacted or changed
        for field in ("reproduction_steps", "acceptance_criteria"):
            raw = value.get(field)
            if not isinstance(raw, list) or len(raw) > 12:
                raise FindingError("invalid_input", "Finding list field is invalid")
            items = []
            for item in raw:
                text, changed = cls._text(item, limit=500, required=True)
                items.append(text)
                redacted = redacted or changed
            content[field] = items
        return content, redacted

    @staticmethod
    def _text(value: Any, *, limit: int, required: bool) -> tuple[str, bool]:
        if not isinstance(value, str) or len(value) > limit or any(c in value for c in "\x00\r"):
            raise FindingError("invalid_input", "Finding text is invalid")
        value = value.strip()
        if required and not value:
            raise FindingError("invalid_input", "Required finding text is missing")
        safe = redact_text(value)
        return safe, safe != value

    @staticmethod
    def _evidence(value: Sequence[str]) -> list[str]:
        if isinstance(value, (str, bytes)) or len(value) > 16:
            raise FindingError("invalid_input", "Finding evidence is invalid")
        result = []
        for item in value:
            if not isinstance(item, str) or not _ID_RE.fullmatch(item) or item in result:
                raise FindingError("invalid_input", "Finding evidence is invalid")
            result.append(item)
        return result

    @staticmethod
    def _fingerprint(content: Mapping[str, Any]) -> str:
        basis = {
            "kind": content["kind"],
            "component": content["component"].casefold(),
            "title": " ".join(content["title"].casefold().split()),
            "actual_behavior": " ".join(content["actual_behavior"].casefold().split()),
        }
        return hashlib.sha256(canonical_json(basis).encode()).hexdigest()

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        try:
            return {
                "id": row["finding_id"],
                "fingerprint": row["fingerprint"],
                "state": row["state"],
                **json.loads(row["content_json"]),
                "evidence_ids": json.loads(row["evidence_json"]),
                "actor": {
                    "type": row["actor_type"],
                    "id": row["actor_id"],
                    "username": row["actor_username"],
                },
                "redaction_applied": bool(row["redaction_applied"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "revision": row["revision"],
                "publication": None,
            }
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FindingError("corrupt_store", "Finding record is invalid") from exc


class LazyFindingsService:
    def __init__(self, path: str | Path) -> None:
        self._path = path
        self._service: FindingsService | None = None
        self._lock = threading.Lock()

    def _get(self) -> FindingsService:
        with self._lock:
            if self._service is None:
                self._service = FindingsService(self._path)
            return self._service

    def __getattr__(self, name: str):
        return getattr(self._get(), name)
