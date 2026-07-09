"""Signal providers for the alert evaluator (brick B2, part 2).

Pure functions that turn normalized health records into `Signal`s. Extraction from the
live services (Docker, SMART helper, mounts, SnapRAID) lives in `alert_daemon.py`; keeping
these pure makes the alerting policy trivially testable.

Severity defaults (agreed): SMART failing, a missing required mount, and a SnapRAID error are
critical; a container that is meant to stay up going down/unhealthy, and SnapRAID needing a
sync, are warnings.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from alert_evaluator import Signal

# Restart policies that declare a container is meant to stay running. One-shot / cron-style
# containers (policy "no" or "on-failure") are intentionally ignored so a job that exits does
# not page.
LONG_RUNNING_POLICIES = frozenset({"always", "unless-stopped"})


@dataclass(frozen=True)
class ContainerRecord:
    name: str
    running: bool
    health: str | None  # "healthy" | "unhealthy" | "starting" | None
    restart_policy: str  # "always" | "unless-stopped" | "no" | "on-failure" | ...


@dataclass(frozen=True)
class DiskHealth:
    device: str
    passed: bool | None  # SMART overall-health assessment; None = unknown (do not alert)
    summary: str = ""


def container_signals(records: Iterable[ContainerRecord]) -> list[Signal]:
    signals: list[Signal] = []
    for record in records:
        if record.restart_policy not in LONG_RUNNING_POLICIES:
            continue
        key = f"container:{record.name}"
        if not record.running:
            signals.append(Signal(key, False, f"{record.name} is not running", "container", "warning"))
        elif record.health == "unhealthy":
            signals.append(Signal(key, False, f"{record.name} healthcheck is failing", "container", "warning"))
        else:
            signals.append(Signal(key, True, f"{record.name} is healthy", "container", "warning"))
    return signals


def smart_signals(disks: Iterable[DiskHealth]) -> list[Signal]:
    signals: list[Signal] = []
    for disk in disks:
        if disk.passed is None:
            continue  # unknown assessment -> no alert (avoid false criticals on parse gaps)
        key = f"smart:{disk.device}"
        if disk.passed:
            signals.append(Signal(key, True, f"{disk.device} SMART OK", "smart", "critical"))
        else:
            summary = disk.summary or f"{disk.device} SMART assessment FAILED"
            signals.append(Signal(key, False, summary, "smart", "critical"))
    return signals


def mount_signals(present: set[str], required: Iterable[str]) -> list[Signal]:
    signals: list[Signal] = []
    for path in required:
        key = f"mount:{path}"
        if path in present:
            signals.append(Signal(key, True, f"{path} is mounted", "mount", "critical"))
        else:
            signals.append(Signal(key, False, f"{path} is not mounted", "mount", "critical"))
    return signals


def snapraid_signals(status: dict | None) -> list[Signal]:
    state = (status or {}).get("status")
    if state in (None, "", "unconfigured"):
        return []  # nothing configured to watch
    key = "snapraid:status"
    message = (status or {}).get("message") or ""
    if state == "error":
        return [Signal(key, False, message or "SnapRAID reported an error", "snapraid", "critical")]
    if state == "degraded":
        return [Signal(key, False, message or "SnapRAID needs a sync", "snapraid", "warning")]
    return [Signal(key, True, message or "SnapRAID healthy", "snapraid", "critical")]
