"""Bounded read adapter for existing storage-provider disk assignments."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


MAX_CONFIG_BYTES = 1_048_576
MAX_ASSIGNMENTS = 256
MAX_RESOURCES = 128
MAX_TEXT = 128
SAFE_UUID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _text(value, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    return value.strip()[:MAX_TEXT]


def _mount_path(value) -> str | None:
    if not isinstance(value, str) or not value.startswith("/mnt/"):
        return None
    normalized = os.path.normpath(value)
    if not normalized.startswith("/mnt/") or normalized == "/mnt":
        return None
    return normalized[:512]


class StorageProviderAssignmentReader:
    """Read MergerFS and SnapRAID assignments without loading provider code."""

    def __init__(self, config_dir: str | Path) -> None:
        self._config_dir = Path(config_dir)

    def read(self) -> dict:
        assignments: list[dict] = []
        warnings: list[dict] = []
        self._read_provider(
            "mergerfs",
            "MergerFS assignments are unavailable",
            self._mergerfs_assignments,
            assignments,
            warnings,
        )
        self._read_provider(
            "snapraid",
            "SnapRAID assignments are unavailable",
            self._snapraid_assignments,
            assignments,
            warnings,
        )
        return {
            "assignments": assignments[:MAX_ASSIGNMENTS],
            "warnings": warnings,
        }

    def _read_provider(self, provider_id, message, parser, assignments, warnings) -> None:
        path = self._config_dir / f"{provider_id}.json"
        if not path.exists():
            return
        try:
            config = self._load(path)
            assignments.extend(parser(config, MAX_ASSIGNMENTS - len(assignments)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            warnings.append(
                {
                    "code": "provider_config_invalid",
                    "source": provider_id,
                    "message": message,
                }
            )

    @staticmethod
    def _load(path: Path) -> dict:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError("provider configuration is too large")
        with path.open() as handle:
            config = json.load(handle)
        if not isinstance(config, dict):
            raise ValueError("provider configuration must be an object")
        return config

    @staticmethod
    def _mergerfs_assignments(config: dict, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        pools = config.get("pools", [])
        if not isinstance(pools, list):
            raise ValueError("pools must be a list")
        assignments = []
        for index, pool in enumerate(pools[:MAX_RESOURCES]):
            if not isinstance(pool, dict):
                continue
            resource_id = _text(pool.get("id") or pool.get("name"), f"pool-{index + 1}")
            resource_name = _text(pool.get("name"), resource_id)
            branches = pool.get("branches", [])
            if not isinstance(branches, list):
                continue
            for branch in branches[:MAX_RESOURCES]:
                target_path = _mount_path(branch)
                if not target_path:
                    continue
                assignments.append(
                    {
                        "provider_id": "mergerfs",
                        "capability_id": "storage.pooling",
                        "role": "branch",
                        "resource_id": resource_id,
                        "resource_name": resource_name,
                        "target_path": target_path,
                        "href": "/pools/mergerfs",
                    }
                )
                if len(assignments) >= limit:
                    return assignments
        return assignments

    @staticmethod
    def _snapraid_assignments(config: dict, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        drives = config.get("drives", [])
        if not isinstance(drives, list):
            raise ValueError("drives must be a list")
        assignments = []
        for index, drive in enumerate(drives[:MAX_RESOURCES]):
            if not isinstance(drive, dict):
                continue
            role = _text(drive.get("role")).lower()
            if role not in {"data", "parity"}:
                continue
            target_path = _mount_path(drive.get("path"))
            target_uuid = _text(drive.get("uuid"))
            if target_uuid and not SAFE_UUID.fullmatch(target_uuid):
                target_uuid = ""
            if not target_path and not target_uuid:
                continue
            resource_id = _text(drive.get("name"), f"drive-{index + 1}")
            assignment = {
                "provider_id": "snapraid",
                "capability_id": "storage.protection",
                "role": role,
                "resource_id": resource_id,
                "resource_name": resource_id,
                "href": "/protection/snapraid",
            }
            if target_path:
                assignment["target_path"] = target_path
            if target_uuid:
                assignment["target_uuid"] = target_uuid
            assignments.append(assignment)
            if len(assignments) >= limit:
                return assignments
        return assignments
