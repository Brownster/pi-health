"""Usage ledger: user turns and provider invocations, recorded separately.

Baseline: "The gateway records user turns and provider invocations separately so later
API cost estimates use real workload data" and "Provider invocations per day: 20,
configurable". Counters persist across restarts; the daily invocation count rolls over
at UTC midnight. Turn records append to a JSONL file for the AA-006 usage/audit views.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UsageLedger:
    def __init__(self, state_dir: Path | str, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._counters_path = Path(state_dir) / "usage-counters.json"
        self._records_path = Path(state_dir) / "usage-records.jsonl"
        self._clock = clock
        self._counters = self._load()

    def _load(self) -> dict:
        try:
            raw = json.loads(self._counters_path.read_text())
            return raw if isinstance(raw, dict) else {}
        except (FileNotFoundError, ValueError, OSError):
            return {}

    def _persist(self) -> None:
        self._counters_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self._counters_path.parent, prefix=".usage.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(self._counters, handle)
            os.replace(tmp, self._counters_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _today(self) -> str:
        return self._clock().date().isoformat()

    # -- provider invocations (daily-capped) -----------------------------------
    def invocations_today(self) -> int:
        if self._counters.get("invocation_date") != self._today():
            return 0
        return int(self._counters.get("invocations", 0))

    def record_invocation(self) -> None:
        today = self._today()
        if self._counters.get("invocation_date") != today:
            self._counters["invocation_date"] = today
            self._counters["invocations"] = 0
        self._counters["invocations"] = int(self._counters.get("invocations", 0)) + 1
        self._counters["total_invocations"] = int(self._counters.get("total_invocations", 0)) + 1
        self._persist()

    # -- user turns --------------------------------------------------------------
    def record_turn(
        self,
        *,
        conversation_id: str,
        correlation_id: str,
        outcome: str,  # "ok" | "error" | "busy" | "limit"
        rounds: int,
        duration_seconds: float,
        tool_operations: list[str],
        tool_audit_ids: list[str] | None = None,
    ) -> None:
        self._counters["total_turns"] = int(self._counters.get("total_turns", 0)) + 1
        self._persist()
        record = {
            "at": self._clock().isoformat(),
            "conversation_id": conversation_id,
            "correlation_id": correlation_id,
            "outcome": outcome,
            "rounds": rounds,
            "duration_seconds": round(duration_seconds, 3),
            "tool_operations": tool_operations,
            "tool_audit_ids": tool_audit_ids or [],
        }
        self._records_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._records_path, "a") as handle:
            handle.write(json.dumps(record) + "\n")

    def totals(self) -> dict:
        return {
            "total_turns": int(self._counters.get("total_turns", 0)),
            "total_invocations": int(self._counters.get("total_invocations", 0)),
            "invocations_today": self.invocations_today(),
        }
