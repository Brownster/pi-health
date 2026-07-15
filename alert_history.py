"""Bounded incident and recovery history for the Overview dashboard."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from alert_evaluator import Notification


MAX_ALERT_EVENTS = 200
MAX_LEDGER_BYTES = 1024 * 1024
_FIELDS = ("at", "event", "key", "kind", "severity", "summary")


def _clean(value, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or any(character in value for character in "\x00\r\n"):
        return None
    return value[:maximum]


def _normalize(record: Mapping) -> dict | None:
    event = _clean(record.get("event"), maximum=16)
    key = _clean(record.get("key"), maximum=256)
    at = _clean(record.get("at"), maximum=64)
    kind = _clean(record.get("kind"), maximum=64)
    severity = _clean(record.get("severity"), maximum=16)
    summary = _clean(record.get("summary"), maximum=512)
    if (
        event not in {"incident", "recovery"}
        or not key
        or not at
        or not kind
        or severity not in {"warning", "critical"}
        or not summary
    ):
        return None
    return {
        "at": at,
        "event": event,
        "key": key,
        "kind": kind,
        "severity": severity,
        "summary": summary,
    }


class AlertEventLedger:
    """Read and atomically rewrite a small transition ledger."""

    def __init__(self, path: Path | str, *, max_records: int = MAX_ALERT_EVENTS) -> None:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        self._path = Path(path)
        self._max_records = max_records

    def record(self, notification: Notification) -> bool:
        record = _normalize(
            {
                "at": notification.at,
                "event": notification.event,
                "key": notification.key,
                "kind": notification.kind,
                "severity": notification.severity,
                "summary": notification.summary,
            }
        )
        if record is None:
            raise ValueError("alert event is invalid")
        records = self.records()
        latest_for_key = next(
            (item for item in reversed(records) if item["key"] == record["key"]),
            None,
        )
        if latest_for_key is not None and latest_for_key["event"] == record["event"]:
            return False
        records.append(record)
        self._write(records[-self._max_records :])
        return True

    def records(self) -> list[dict]:
        try:
            if self._path.stat().st_size > MAX_LEDGER_BYTES:
                return []
            lines = self._path.read_text().splitlines()
        except FileNotFoundError:
            return []
        except OSError:
            return []
        records = []
        for line in lines[-self._max_records :]:
            try:
                raw = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(raw, Mapping) or set(raw) != set(_FIELDS):
                continue
            record = _normalize(raw)
            if record is not None:
                records.append(record)
        return records

    def recent(self, *, event: str | None = None, limit: int = 5) -> list[dict]:
        if event not in {None, "incident", "recovery"}:
            raise ValueError("event filter is invalid")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        records = self.records()
        if event is not None:
            records = [record for record in records if record["event"] == event]
        return list(reversed(records[-limit:]))

    def _write(self, records: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        fd, temporary_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w") as handle:
                for record in records:
                    handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            # The alert daemon writes as container root while the host dashboard reads as
            # the pi-health service user. The 0750 runtime directory provides the access
            # boundary; a world-readable file mode permits that bind-mount handoff.
            temporary.chmod(0o644)
            os.replace(temporary, self._path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
