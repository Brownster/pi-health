"""Safe package-repair status shared by proposal and actuator processes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any

from limeos_packages import (
    check_packages,
    compliance_report,
    load_manifest,
    repair_managed_packages,
)


PACKAGE_ACTION_UNIT = "limeos-package-reconcile-action.service"


def package_repair_status(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read compliance for the immutable agent-repair subset."""
    specs = repair_managed_packages(load_manifest())

    def version_of(spec):
        if spec.manager != "apt":
            return None
        result = runner(
            ["dpkg-query", "-W", "-f", "${Version}", spec.name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return (result.stdout.strip() or None) if result.returncode == 0 else None

    def version_ge(current: str, expected: str) -> bool:
        return (
            runner(
                ["dpkg", "--compare-versions", current, "ge", expected],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).returncode
            == 0
        )

    return compliance_report(
        check_packages(specs, version_of, version_ge=version_ge)
    )


def package_job_status(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Read bounded systemd state for the fixed reconciliation job."""
    result = runner(
        [
            "systemctl",
            "show",
            PACKAGE_ACTION_UNIT,
            "--property=ActiveState",
            "--property=Result",
            "--property=InvocationID",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return {
            "active_state": "unavailable",
            "result": "unknown",
            "invocation_id": "",
        }
    values = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    return {
        "active_state": values.get("ActiveState", "unknown").lower(),
        "result": values.get("Result", "unknown").lower(),
        "invocation_id": values.get("InvocationID", ""),
    }
