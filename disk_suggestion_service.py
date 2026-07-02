"""Framework-neutral suggested mount read model."""

from __future__ import annotations

from collections.abc import Callable, Collection
from typing import Any


def parse_size_to_gb(size: Any) -> float | None:
    """Parse a human-readable block-device size into gigabytes."""
    if not size:
        return None

    value = str(size).upper().strip()
    try:
        if value.endswith("T"):
            return float(value[:-1]) * 1024
        if value.endswith("G"):
            return float(value[:-1])
        if value.endswith("M"):
            return float(value[:-1]) / 1024
        if value.endswith("K"):
            return float(value[:-1]) / (1024 * 1024)
        return float(value) / (1024 * 1024 * 1024)
    except ValueError:
        return None


class DiskSuggestionService:
    """Derive mount recommendations from one disk-inventory snapshot."""

    def __init__(
        self,
        *,
        inventory_reader: Callable[[], dict],
        supported_filesystems: Collection[str],
    ) -> None:
        self._inventory_reader = inventory_reader
        self._supported_filesystems = frozenset(supported_filesystems)

    def suggestions(self) -> dict:
        inventory = self._inventory_reader()
        suggestions = []
        for disk in inventory.get("disks", []):
            suggestion = self._disk_suggestions(disk)
            suggestions.extend(suggestion)
        return {"suggestions": suggestions}

    def _disk_suggestions(self, disk: dict) -> list[dict]:
        is_nvme = "nvme" in disk.get("name", "")
        is_usb = disk.get("transport", "") == "usb"
        size_gb = parse_size_to_gb(disk.get("size", ""))
        suggestions = []

        for partition in disk.get("partitions", []) or [disk]:
            if partition.get("mounted") or not partition.get("uuid"):
                continue
            if partition.get("fstype", "") not in self._supported_filesystems:
                continue

            mountpoint, reason = self._recommendation(is_nvme, is_usb, size_gb)
            if not mountpoint:
                continue
            suggestions.append(
                {
                    "device": partition.get("path", ""),
                    "uuid": partition.get("uuid", ""),
                    "size": partition.get("size", ""),
                    "fstype": partition.get("fstype", ""),
                    "label": partition.get("label", ""),
                    "suggested_mount": mountpoint,
                    "reason": reason,
                }
            )
        return suggestions

    @staticmethod
    def _recommendation(
        is_nvme: bool, is_usb: bool, size_gb: float | None
    ) -> tuple[str | None, str]:
        if is_nvme:
            return "/mnt/downloads", "NVMe drive - fast storage for downloads"
        if not is_usb:
            return None, ""
        if size_gb and size_gb < 64:
            return "/mnt/backup", "Small USB device - suitable for backups"
        return "/mnt/storage", "USB storage device - suitable for media"
