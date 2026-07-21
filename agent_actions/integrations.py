"""Bounded AI Agents integration state shared by proposal and execution."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from typing import Any


AGENT_REPAIR_UNIT = "limeos-agent-repair.service"
AGENT_RUNTIME_UNITS = (
    "limeos-agent.service",
    "limeopsd.service",
    "limeops-actuatord.service",
    "limeops-action-worker.service",
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
        "claude_installed": status.get("claude_installed") is True,
        "claude_compatible": status.get("claude_compatible") is True,
        "claude_authenticated": status.get("claude_authenticated") is True,
        "configured": status.get("configured") is True,
        "enabled": status.get("enabled") is True,
    }
