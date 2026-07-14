"""Target wiring for the AA-002 diagnostic operations.

Builds real `DiagnosticDependencies` from the host's domain services. Everything is
lazily imported and constructed per call so the broker process starts without Docker or
the helper being up, and one unavailable subsystem fails only its own operation (the
broker maps handler exceptions to `upstream_failure`).

This module is integration glue validated on the target (AA-009); the behavioral logic
it feeds lives in `limeops.operations` and is unit-tested there.
"""

from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

from limeops.operations import DiagnosticDependencies, build_operations

_SERVICE_UNITS = {
    "docker": "docker.service",
    "pi-health": "pi-health.service",
    "pihealth-helper": "pihealth-helper.service",
    "limeos-alertd": "limeos-alertd.service",
    "limeos-mattermost": "limeos-mattermost.service",
    "limeopsd": "limeopsd.service",
    "limeos-agent": "limeos-agent.service",
}
_NETWORK_TARGETS = {
    "internet": ("8.8.8.8", 53),
    "mattermost": ("127.0.0.1", 8065),
}


def _docker_command(*args: str, timeout: int = 15) -> str:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Docker operation failed")
    return result.stdout


def _system_status() -> dict:  # pragma: no cover - target integration
    import psutil

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "hostname": platform.node(),
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "load_average": list(psutil.getloadavg()),
        "memory": {"total": memory.total, "available": memory.available,
                   "percent": memory.percent},
        "root_disk": {"total": disk.total, "free": disk.free, "percent": disk.percent},
    }


def _container_summary(attrs: dict) -> dict:  # pragma: no cover - target integration
    config = attrs.get("Config") or {}
    state = attrs.get("State") or {}
    return {
        "name": str(attrs.get("Name") or "").removeprefix("/"),
        "status": state.get("Status") or "unknown",
        "image": config.get("Image") or "",
        "health": ((state.get("Health") or {}).get("Status")) or None,
        "stack": (config.get("Labels") or {}).get("com.docker.compose.project"),
        "restart_policy": ((attrs.get("HostConfig") or {}).get("RestartPolicy") or {}).get(
            "Name"
        ),
    }


def _list_containers() -> list:  # pragma: no cover - target integration
    ids = _docker_command("container", "ls", "--all", "--quiet", "--no-trunc").splitlines()
    ids = [container_id for container_id in ids if container_id]
    if not ids:
        return []
    containers = json.loads(_docker_command("container", "inspect", "--", *ids))
    if not isinstance(containers, list):
        raise ValueError("Invalid Docker response")
    return [_container_summary(container) for container in containers]


def _container_status(name: str) -> dict:  # pragma: no cover - target integration
    containers = json.loads(_docker_command("container", "inspect", "--", name))
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("Invalid Docker response")
    return _container_summary(containers[0])


def _container_logs(name: str, lines: int) -> str:  # pragma: no cover - target integration
    return _docker_command("container", "logs", "--tail", str(lines), "--", name)


def _stack_reads():  # pragma: no cover - target integration
    from stack_manager import default_stack_read_service

    return default_stack_read_service()


def _list_stacks() -> list:  # pragma: no cover - target integration
    stacks, _error = _stack_reads().list_stacks()
    return [
        {"name": s.get("name"), "status": s.get("status"),
         "running_count": s.get("running_count"), "container_count": s.get("container_count")}
        for s in stacks
    ]


def _stack_status(name: str) -> dict:  # pragma: no cover - target integration
    status, _output = _stack_reads().status(name)
    return {"name": name, "status": status}


def _stack_inspect(name: str) -> dict:  # pragma: no cover - target integration
    from compose_yaml import load_compose_yaml
    from limeops.operations import sanitize_stack_details

    details = _stack_reads().stack_details(name)
    try:
        compose = load_compose_yaml(details.get("compose_content") or "") or {}
    except Exception:
        compose = {}
    # sanitize_stack_details keeps structure and env KEYS only — raw compose_content
    # and env_content never leave this function.
    return sanitize_stack_details(details, compose)


def _systemctl(*args: str) -> str:  # pragma: no cover - target integration
    result = subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def _service_status(unit_key: str) -> dict:  # pragma: no cover - target integration
    unit = _SERVICE_UNITS.get(unit_key, unit_key)
    return {
        "unit": unit,
        "active_state": _systemctl("is-active", unit) or "unknown",
        "enabled_state": _systemctl("is-enabled", unit) or "unknown",
    }


def _service_logs(unit_key: str, lines: int) -> str:  # pragma: no cover - target integration
    unit = _SERVICE_UNITS.get(unit_key, unit_key)
    result = subprocess.run(
        ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result.stdout


def _disk_health() -> dict:  # pragma: no cover - target integration
    from ports import HelperClientAdapter
    from smart_monitor import parse_smartctl_json
    from smart_service import SmartService

    return SmartService(
        helper=HelperClientAdapter(), parser=parse_smartctl_json
    ).all_devices()


def _mount_status() -> dict:  # pragma: no cover - target integration
    mounts = []
    for line in Path("/proc/self/mounts").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1].startswith(("/mnt/", "/media/")):
            mounts.append({"mountpoint": fields[1], "fstype": fields[2]})
    return {"mounts": mounts}


def _snapraid_status() -> dict:  # pragma: no cover - target integration
    from storage_plugins.snapraid_plugin import SnapRAIDPlugin

    status = SnapRAIDPlugin().get_status()
    return {"status": status.get("status"), "message": status.get("message"),
            "details": status.get("details") or {}}


def _default_gateway_ip() -> str | None:  # pragma: no cover - target integration
    for line in Path("/proc/net/route").read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "00000000":
            raw = int(fields[2], 16)
            return socket.inet_ntoa(raw.to_bytes(4, "little"))
    return None


def _network_check(target: str) -> dict:  # pragma: no cover - target integration
    if target == "gateway":
        gateway_ip = _default_gateway_ip()
        if not gateway_ip:
            return {"target": target, "ok": False, "detail": "no default route"}
        host, port = gateway_ip, 53
    else:
        host, port = _NETWORK_TARGETS[target]
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=5):
            latency_ms = int((time.monotonic() - started) * 1000)
        return {"target": target, "ok": True, "latency_ms": latency_ms}
    except OSError as exc:
        return {"target": target, "ok": False, "detail": str(exc)}


def _installation_inventory() -> dict:  # pragma: no cover - target integration
    import os

    units = {key: _service_status(key)["active_state"] for key in _SERVICE_UNITS}
    return {
        "limeos_version": os.getenv("LIMEOS_VERSION") or None,
        "platform": f"{platform.system()} {platform.machine()}",
        "units": units,
        "docker_cli": bool(shutil.which("docker")),
    }


def _dpkg_version(name: str) -> str | None:  # pragma: no cover - target integration
    result = subprocess.run(
        ["dpkg-query", "-W", "-f", "${Version}", name],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _dpkg_ge(a: str, b: str) -> bool:  # pragma: no cover - target integration
    return subprocess.run(["dpkg", "--compare-versions", a, "ge", b], timeout=10).returncode == 0


def _package_status() -> dict:  # pragma: no cover - target integration
    from limeos_packages import check_packages, compliance_report, load_manifest

    specs = load_manifest()

    def version_of(spec):
        return _dpkg_version(spec.name) if spec.manager == "apt" else None

    return compliance_report(check_packages(specs, version_of, version_ge=_dpkg_ge))


def default_dependencies() -> DiagnosticDependencies:  # pragma: no cover - target integration
    return DiagnosticDependencies(
        system_status=_system_status,
        list_containers=_list_containers,
        container_status=_container_status,
        container_logs=_container_logs,
        list_stacks=_list_stacks,
        stack_status=_stack_status,
        stack_inspect=_stack_inspect,
        service_status=_service_status,
        service_logs=_service_logs,
        disk_health=_disk_health,
        mount_status=_mount_status,
        snapraid_status=_snapraid_status,
        network_check=_network_check,
        installation_inventory=_installation_inventory,
        package_status=_package_status,
    )


def default_operation_factory():  # pragma: no cover - target integration
    """`operation_factory` for `limeops.server`: the full AA-002 diagnostic set."""
    return build_operations(default_dependencies())
