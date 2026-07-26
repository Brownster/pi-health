"""Durable record of manual work LimeOS cannot finish on the user's behalf.

Some steps end with something only a person can decide to do — most often a
reboot after a boot-config change. The update that discovers this is the same
update that restarts the service, so a notice held in memory or shown once on
the update screen is exactly the notice most likely to be missed. These records
outlive the restart and stay visible until the work is done or dismissed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from ports import ConfigRepository, JsonFileRepository
from runtime_paths import STATE_DIR


PENDING_ACTIONS_PATH = STATE_DIR / "pending-actions.json"
MAX_ACTIONS = 20
SEVERITIES = ("info", "attention", "critical")
REBOOT_REQUIRED = "reboot_required"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _text(value, default: str = "", limit: int = 500) -> str:
    return (value.strip() if isinstance(value, str) else default)[:limit]


class PendingActionStore:
    """Append-and-dismiss store of outstanding manual actions, keyed by id."""

    def __init__(
        self,
        *,
        repository: ConfigRepository | None = None,
        path: str | Path = PENDING_ACTIONS_PATH,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repository = repository or JsonFileRepository()
        self._path = Path(path)
        self._clock = clock
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        """Return outstanding actions, most severe first."""
        records = self._read()
        rank = {severity: index for index, severity in enumerate(reversed(SEVERITIES))}
        records.sort(key=lambda item: (rank.get(item["severity"], 99), item["created_at"]))
        return records

    def record(
        self,
        action_id: str,
        *,
        title: str,
        detail: str = "",
        severity: str = "attention",
        source: str = "system",
        command: str = "",
    ) -> dict | None:
        """Record one outstanding action. Re-recording the same id is a no-op.

        Keeping the first timestamp matters: an action raised by one update and
        still outstanding three updates later should read as three updates old,
        not brand new.
        """
        identifier = _text(action_id, limit=64)
        if not identifier:
            return None

        record = {
            "id": identifier,
            "title": _text(title, "Manual action required"),
            "detail": _text(detail),
            "severity": severity if severity in SEVERITIES else "attention",
            "source": _text(source, "system", limit=64),
            "command": _text(command, limit=200),
            "created_at": self._clock().isoformat().replace("+00:00", "Z"),
        }

        with self._lock:
            records = self._read()
            if any(item["id"] == identifier for item in records):
                return next(item for item in records if item["id"] == identifier)
            records.append(record)
            self._write(records[-MAX_ACTIONS:])
        return record

    def dismiss(self, action_id: str) -> bool:
        """Drop one action. Returns whether anything was outstanding."""
        identifier = _text(action_id, limit=64)
        with self._lock:
            records = self._read()
            remaining = [item for item in records if item["id"] != identifier]
            if len(remaining) == len(records):
                return False
            self._write(remaining)
        return True

    def resolve(self, action_id: str) -> bool:
        """Drop an action because the condition behind it no longer holds."""
        return self.dismiss(action_id)

    # --- storage -----------------------------------------------------------

    def _read(self) -> list[dict]:
        payload = self._repository.read_json(self._path, default=[])
        if not isinstance(payload, list):
            return []
        return [self._normalize(item) for item in payload if isinstance(item, Mapping)]

    def _write(self, records: list[dict]) -> None:
        self._repository.write_json(self._path, records, mode=0o640)

    @staticmethod
    def _normalize(record: Mapping) -> dict:
        severity = _text(record.get("severity"), "attention")
        return {
            "id": _text(record.get("id"), "unknown", limit=64),
            "title": _text(record.get("title"), "Manual action required"),
            "detail": _text(record.get("detail")),
            "severity": severity if severity in SEVERITIES else "attention",
            "source": _text(record.get("source"), "system", limit=64),
            "command": _text(record.get("command"), limit=200),
            "created_at": _text(record.get("created_at")),
        }
