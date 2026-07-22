"""Bounded AI Agents integration state shared by proposal and execution."""

from __future__ import annotations

import subprocess
import re
from collections.abc import Callable, Mapping
from typing import Any


AGENT_REPAIR_UNIT = "limeos-agent-repair.service"
MATTERMOST_REPAIR_UNIT = "limeos-mattermost-repair.service"
EXTENSION_REPAIR_UNIT = "limeos-extension-repair@{name}.service"
_EXTENSION_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
AGENT_RUNTIME_UNITS = (
    "limeos-agent.service",
    "limeopsd.service",
    "limeops-actuatord.service",
    "limeops-action-worker.service",
    "limeops-report-scheduler.service",
)


def _systemd_properties(
    unit: str,
    properties: tuple[str, ...],
    runner: Callable[..., Any],
) -> dict[str, str]:
    result = runner(
        [
            "systemctl",
            "show",
            unit,
            *(f"--property={property_name}" for property_name in properties),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return {}
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in properties:
            values[key] = value
    return values


def agent_integration_status(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read only fixed unit presence, enablement, and activity."""
    units = []
    for name in AGENT_RUNTIME_UNITS:
        values = _systemd_properties(
            name,
            ("LoadState", "ActiveState", "UnitFileState"),
            runner,
        )
        units.append(
            {
                "name": name,
                "load_state": values.get("LoadState", "unavailable").lower(),
                "active_state": values.get("ActiveState", "unknown").lower(),
                "unit_file_state": values.get("UnitFileState", "unknown").lower(),
            }
        )
    return {"name": "agents", "units": units}


def agent_repair_job_status(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Read bounded systemd state for the fixed integration repair job."""
    values = _systemd_properties(
        AGENT_REPAIR_UNIT,
        ("LoadState", "ActiveState", "Result", "InvocationID"),
        runner,
    )
    if values.get("LoadState", "").lower() != "loaded":
        return {
            "active_state": "unavailable",
            "result": "unknown",
            "invocation_id": "",
        }
    return {
        "active_state": values.get("ActiveState", "unknown").lower(),
        "result": values.get("Result", "unknown").lower(),
        "invocation_id": values.get("InvocationID", ""),
    }


def _repair_job_status(unit: str, runner: Callable[..., Any]) -> dict[str, str]:
    values = _systemd_properties(
        unit,
        ("LoadState", "ActiveState", "Result", "InvocationID"),
        runner,
    )
    if values.get("LoadState", "").lower() != "loaded":
        return {
            "active_state": "unavailable",
            "result": "unknown",
            "invocation_id": "",
        }
    return {
        "active_state": values.get("ActiveState", "unknown").lower(),
        "result": values.get("Result", "unknown").lower(),
        "invocation_id": values.get("InvocationID", ""),
    }


def mattermost_repair_job_status(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Read bounded systemd state for the fixed Mattermost repair job."""
    return _repair_job_status(MATTERMOST_REPAIR_UNIT, runner)


def extension_repair_job_status(
    name: str,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Read one validated extension repair instance."""
    if (
        not isinstance(name, str)
        or len(name) > 64
        or not _EXTENSION_ID.fullmatch(name)
    ):
        return {
            "active_state": "unavailable",
            "result": "unknown",
            "invocation_id": "",
        }
    return _repair_job_status(EXTENSION_REPAIR_UNIT.format(name=name), runner)


def safe_agent_runtime_health(status: Mapping[str, Any]) -> dict[str, Any]:
    """Drop configuration identifiers and credentials from helper status."""
    return {
        "runtime_installed": status.get("runtime_installed") is True,
        "agent_active": str(status.get("agent_active") or "unknown").lower(),
        "broker_active": str(status.get("broker_active") or "unknown").lower(),
        "action_broker_active": str(
            status.get("action_broker_active") or "unknown"
        ).lower(),
        "action_worker_active": str(
            status.get("action_worker_active") or "unknown"
        ).lower(),
        "report_scheduler_active": str(
            status.get("report_scheduler_active") or "unknown"
        ).lower(),
        "claude_installed": status.get("claude_installed") is True,
        "claude_compatible": status.get("claude_compatible") is True,
        "claude_authenticated": status.get("claude_authenticated") is True,
        "configured": status.get("configured") is True,
        "enabled": status.get("enabled") is True,
    }


def safe_extension_health(status: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the extension fields needed for authorisation and verification."""
    return {
        "name": str(status.get("name") or ""),
        "type": str(status.get("type") or "unknown").lower(),
        "enabled": status.get("enabled") is True,
        "installed": status.get("installed") is True,
        "source_configured": status.get("source_configured") is True,
        "repairable": status.get("repairable") is True,
        "registered": status.get("registered") is True,
        "configured": status.get("configured") is True,
        "status": str(status.get("status") or "unknown").lower(),
        "healthy": status.get("healthy") is True,
    }


def safe_mattermost_health(status: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only bounded Mattermost lifecycle and container health."""
    services = sorted(
        (
            {
                "name": str(item.get("name") or ""),
                "state": str(item.get("state") or "unknown").lower(),
                "health": str(item.get("health") or "").lower(),
            }
            for item in status.get("services") or []
            if isinstance(item, Mapping) and item.get("name")
        ),
        key=lambda item: item["name"],
    )
    return {
        "name": "mattermost",
        "state": str(status.get("state") or "unknown").lower(),
        "installed": status.get("installed") is True,
        "stack_name": str(status.get("stack_name") or ""),
        "webhook_configured": status.get("webhook_configured") is True,
        "services": services,
    }
