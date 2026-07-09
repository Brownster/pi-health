"""Framework-neutral alert evaluator for the agent-investigate MVP (brick B2).

Turns point-in-time health *signals* into deduplicated *incidents* and *recovery*
notifications: a fault must persist for `fail_threshold` consecutive evaluations before it
opens an incident, an open incident is not re-notified while it stays broken, and it emits
exactly one recovery when it clears. State persists across process/host restarts so a reboot
neither loses an active incident nor re-fires resolved ones.

No model is involved here — detection is cheap and native; the model only runs later when a
human asks the assistant to investigate an incident (brick B4).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Signal:
    """One health reading. `key` must be stable for the same underlying resource."""

    key: str
    ok: bool
    summary: str
    kind: str = "generic"
    severity: str = "warning"  # "warning" | "critical"


@dataclass
class Incident:
    key: str
    kind: str
    severity: str
    summary: str
    opened_at: str
    updated_at: str


@dataclass(frozen=True)
class Notification:
    event: str  # "incident" | "recovery"
    key: str
    kind: str
    severity: str
    summary: str
    at: str


@dataclass
class AlertEvaluatorConfig:
    fail_threshold: int = 2  # consecutive failing evaluations before opening an incident


@dataclass
class _State:
    streaks: dict[str, int] = field(default_factory=dict)
    incidents: dict[str, Incident] = field(default_factory=dict)


class AlertEvaluator:
    def __init__(
        self,
        *,
        state_path: Path | str,
        config: AlertEvaluatorConfig | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._state_path = Path(state_path)
        self._config = config or AlertEvaluatorConfig()
        self._clock = clock
        self._state = self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> _State:
        try:
            raw = json.loads(self._state_path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return _State()
        incidents = {
            key: Incident(**value)
            for key, value in (raw.get("incidents") or {}).items()
            if isinstance(value, dict)
        }
        streaks = {
            key: int(value)
            for key, value in (raw.get("streaks") or {}).items()
            if isinstance(value, (int, float))
        }
        return _State(streaks=streaks, incidents=incidents)

    def _persist(self) -> None:
        payload = {
            "streaks": self._state.streaks,
            "incidents": {key: asdict(inc) for key, inc in self._state.incidents.items()},
        }
        directory = self._state_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        # Atomic replace so a crash mid-write can't corrupt the incident ledger.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{self._state_path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self._state_path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # -- evaluation ----------------------------------------------------------
    @property
    def active_incidents(self) -> list[Incident]:
        return list(self._state.incidents.values())

    def evaluate(self, signals: Iterable[Signal]) -> list[Notification]:
        """Fold one round of signals into incident state; return what to notify.

        Signals whose key is absent this round are left untouched — only an explicit
        healthy (`ok`) reading resolves an incident, so a resource that momentarily
        disappears does not spuriously "recover".
        """
        now = self._clock()
        stamp = now.isoformat()
        notifications: list[Notification] = []

        for signal in signals:
            if signal.ok:
                self._state.streaks.pop(signal.key, None)
                incident = self._state.incidents.pop(signal.key, None)
                if incident is not None:
                    notifications.append(
                        Notification(
                            event="recovery",
                            key=signal.key,
                            kind=incident.kind,
                            severity=incident.severity,
                            summary=signal.summary,
                            at=stamp,
                        )
                    )
                continue

            existing = self._state.incidents.get(signal.key)
            if existing is not None:
                existing.summary = signal.summary
                existing.severity = signal.severity
                existing.updated_at = stamp
                continue

            streak = self._state.streaks.get(signal.key, 0) + 1
            if streak < self._config.fail_threshold:
                self._state.streaks[signal.key] = streak
                continue

            self._state.streaks.pop(signal.key, None)
            self._state.incidents[signal.key] = Incident(
                key=signal.key,
                kind=signal.kind,
                severity=signal.severity,
                summary=signal.summary,
                opened_at=stamp,
                updated_at=stamp,
            )
            notifications.append(
                Notification(
                    event="incident",
                    key=signal.key,
                    kind=signal.kind,
                    severity=signal.severity,
                    summary=signal.summary,
                    at=stamp,
                )
            )

        self._persist()
        return notifications
