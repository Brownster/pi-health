"""Framework-neutral summary contract for physical disk operations."""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone


MAX_DEVICES = 128
MAX_ASSIGNMENTS = 256
MAX_WARNINGS = 20
HEALTH_STATES = frozenset({"healthy", "warning", "failing"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


def _warning(source: str, message: str, code: str = "source_unavailable") -> dict:
    return {"code": code, "source": source, "message": message}


def _mountpoint(value) -> str:
    return os.path.normpath(value) if isinstance(value, str) and value.startswith("/") else ""


def _record_mountpoint(record: Mapping) -> str:
    return _mountpoint(record.get("mountpoint")) or _mountpoint(
        record.get("configured_mountpoint")
    )


def _record_uuid(record: Mapping) -> str:
    value = record.get("uuid")
    return value if isinstance(value, str) else ""


def _children(record: Mapping) -> list[Mapping]:
    raw = record.get("partitions")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _flatten(record: Mapping) -> list[Mapping]:
    records = [record]
    for child in _children(record):
        records.extend(_flatten(child))
    return records


def _is_mounted(record: Mapping) -> bool:
    return record.get("mounted") is True or bool(_mountpoint(record.get("mountpoint")))


def _usage(record: Mapping) -> dict | None:
    raw = record.get("usage")
    if not isinstance(raw, Mapping):
        return None
    total = _number(raw.get("total"))
    used = _number(raw.get("used"))
    available = _number(raw.get("available"))
    if total is None:
        return None
    return {
        "mounted_total_bytes": total,
        "mounted_used_bytes": used or 0,
        "mounted_available_bytes": available or 0,
    }


def _device_capacity(device: Mapping) -> dict:
    direct = _usage(device) if _is_mounted(device) else None
    usages = [direct] if direct else []
    if not direct:
        usages = [
            usage
            for record in _flatten(device)[1:]
            if _is_mounted(record) and (usage := _usage(record)) is not None
        ]
    return {
        key: sum(item[key] for item in usages)
        for key in (
            "mounted_total_bytes",
            "mounted_used_bytes",
            "mounted_available_bytes",
        )
    }


class DiskSummaryService:
    """Compose a bounded disk snapshot from existing read providers."""

    def __init__(
        self,
        *,
        inventory_provider: Callable[[], Mapping],
        smart_provider: Callable[[], Mapping],
        assignment_provider: Callable[[], Mapping],
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._inventory_provider = inventory_provider
        self._smart_provider = smart_provider
        self._assignment_provider = assignment_provider
        self._clock = clock

    def snapshot(self) -> dict:
        warnings: list[dict] = []
        inventory = self._inventory(warnings)
        if inventory is None:
            return self._empty(warnings)

        devices = [
            item
            for item in inventory.get("disks", [])[:MAX_DEVICES]
            if isinstance(item, Mapping)
        ]
        smart, smart_source = self._smart(warnings)
        assignments, assignment_source = self._assignments(warnings)
        device_records = [
            self._device_record(device, smart, assignments) for device in devices
        ]

        health_counts = {state: 0 for state in ("healthy", "warning", "failing", "unknown")}
        for device in device_records:
            health_counts[device["health"]] += 1
        mounted = sum(1 for device in device_records if device["mounted"])

        counts = {
            "total": len(device_records),
            **health_counts,
            "mounted": mounted,
            "unmounted": len(device_records) - mounted,
            "assigned": None,
            "unassigned": None,
            "unused": None,
        }
        if assignment_source == "available":
            counts["assigned"] = sum(1 for device in device_records if device["assignments"])
            counts["unassigned"] = len(device_records) - counts["assigned"]
            counts["unused"] = sum(
                1
                for device in device_records
                if not device["mounted"] and not device["assignments"]
            )
        elif assignment_source == "degraded":
            counts["assigned"] = sum(1 for device in device_records if device["assignments"])

        capacity = self._capacity(device_records)
        state = "healthy"
        if (
            not device_records
            or warnings
            or health_counts["warning"]
            or health_counts["failing"]
            or health_counts["unknown"]
        ):
            state = "attention"

        return {
            "state": state,
            "counts": counts,
            "capacity": capacity,
            "sources": {
                "inventory": "available",
                "smart": smart_source,
                "assignments": assignment_source,
            },
            "devices": device_records,
            "warnings": warnings[:MAX_WARNINGS],
            "collected_at": _timestamp(self._clock()),
        }

    def _inventory(self, warnings: list[dict]) -> Mapping | None:
        try:
            inventory = self._inventory_provider()
            if not isinstance(inventory, Mapping):
                raise TypeError("inventory must be an object")
            if (
                inventory.get("helper_available") is not True
                or inventory.get("error")
                or not isinstance(inventory.get("disks"), list)
            ):
                raise RuntimeError("inventory unavailable")
            return inventory
        except Exception:
            warnings.append(_warning("inventory", "Disk inventory is unavailable"))
            return None

    def _smart(self, warnings: list[dict]) -> tuple[dict[str, Mapping], str]:
        try:
            result = self._smart_provider()
            if not isinstance(result, Mapping) or not isinstance(result.get("disks"), list):
                raise TypeError("SMART response must include disks")
            devices = {}
            for item in result["disks"][:MAX_DEVICES]:
                if not isinstance(item, Mapping) or not isinstance(item.get("data"), Mapping):
                    continue
                path = item.get("device")
                if isinstance(path, str) and path.startswith("/dev/"):
                    devices[path] = item["data"]
            return devices, "available"
        except Exception:
            warnings.append(_warning("smart", "SMART health is unavailable"))
            return {}, "unavailable"

    def _assignments(self, warnings: list[dict]) -> tuple[list[dict], str]:
        try:
            result = self._assignment_provider()
            if not isinstance(result, Mapping) or not isinstance(result.get("assignments"), list):
                raise TypeError("assignment response must include assignments")
            assignments = [
                item
                for item in result["assignments"][:MAX_ASSIGNMENTS]
                if isinstance(item, dict)
            ]
            provider_warnings = result.get("warnings", [])
            if not isinstance(provider_warnings, list):
                raise TypeError("assignment warnings must be a list")
            for item in provider_warnings[:MAX_WARNINGS]:
                if not isinstance(item, Mapping):
                    continue
                warnings.append(
                    _warning(
                        str(item.get("source", "assignments"))[:64],
                        str(item.get("message", "Provider assignments are incomplete"))[:256],
                        str(item.get("code", "provider_config_invalid"))[:64],
                    )
                )
            return assignments, "degraded" if provider_warnings else "available"
        except Exception:
            warnings.append(_warning("assignments", "Provider assignments are unavailable"))
            return [], "unavailable"

    @staticmethod
    def _device_record(device: Mapping, smart: dict[str, Mapping], assignments: list[dict]) -> dict:
        path = device.get("path") if isinstance(device.get("path"), str) else ""
        records = _flatten(device)
        matched = []
        for assignment in assignments:
            target_path = assignment.get("target_path")
            target_uuid = assignment.get("target_uuid")
            match = next(
                (
                    record
                    for record in records
                    if (target_path and _record_mountpoint(record) == target_path)
                    or (target_uuid and _record_uuid(record) == target_uuid)
                ),
                None,
            )
            if match is None:
                continue
            output = {
                key: assignment[key]
                for key in (
                    "provider_id",
                    "capability_id",
                    "role",
                    "resource_id",
                    "resource_name",
                    "href",
                )
                if key in assignment
            }
            output["device_path"] = match.get("path", path)
            matched.append(output)

        smart_data = smart.get(path, {})
        health = str(smart_data.get("health_status", "unknown")).lower()
        if health not in HEALTH_STATES:
            health = "unknown"
        flattened = _flatten(device)
        capacity = _device_capacity(device)
        return {
            "name": str(device.get("name", ""))[:128],
            "path": path[:256],
            "health": health,
            "temperature_c": _number(smart_data.get("temperature_c")),
            "mounted": any(_is_mounted(record) for record in flattened),
            "mounted_capacity": capacity,
            "assignments": matched[:MAX_ASSIGNMENTS],
        }

    @staticmethod
    def _capacity(devices: list[dict]) -> dict:
        total = sum(item["mounted_capacity"]["mounted_total_bytes"] for item in devices)
        used = sum(item["mounted_capacity"]["mounted_used_bytes"] for item in devices)
        available = sum(
            item["mounted_capacity"]["mounted_available_bytes"] for item in devices
        )
        return {
            "mounted_total_bytes": total,
            "mounted_used_bytes": used,
            "mounted_available_bytes": available,
            "mounted_percent": round((used / total) * 100, 1) if total else None,
        }

    def _empty(self, warnings: list[dict]) -> dict:
        return {
            "state": "unavailable",
            "counts": {
                "total": 0,
                "healthy": 0,
                "warning": 0,
                "failing": 0,
                "unknown": 0,
                "mounted": 0,
                "unmounted": 0,
                "assigned": None,
                "unassigned": None,
                "unused": None,
            },
            "capacity": {
                "mounted_total_bytes": 0,
                "mounted_used_bytes": 0,
                "mounted_available_bytes": 0,
                "mounted_percent": None,
            },
            "sources": {
                "inventory": "unavailable",
                "smart": "not_checked",
                "assignments": "not_checked",
            },
            "devices": [],
            "warnings": warnings[:MAX_WARNINGS],
            "collected_at": _timestamp(self._clock()),
        }
