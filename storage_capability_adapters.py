"""Read-only capability adapters for the built-in storage plugins."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import plugin_manager
from capability_registry_service import ProviderCandidate
from storage_plugins.base import StoragePlugin
from storage_plugins.mergerfs_plugin import MergerFSPlugin
from storage_plugins.snapraid_plugin import SnapRAIDPlugin


DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parent / "config" / "capability_providers"


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _health_state(value: Any) -> str:
    state = str(value or "unknown").lower()
    if state in {"ok", "active", "healthy", "mounted", "ready", "protected"}:
        return "healthy"
    if state in {"warning", "degraded", "unmounted", "sync_required"}:
        return "warning"
    if state in {"error", "failed"}:
        return "error"
    if state == "unconfigured":
        return "unconfigured"
    return "unknown"


def _tone(state: str) -> str:
    if state == "healthy":
        return "success"
    if state in {"warning", "unconfigured"}:
        return "warning"
    if state == "error":
        return "danger"
    return "neutral"


def _schedule_value(
    schedule: Mapping[str, Any],
    job: str,
    key: str,
    default: Any = None,
) -> Any:
    nested = _record(schedule.get(job))
    return schedule.get(f"{job}_{key}", nested.get(key, default))


def read_builtin_plugin_entry(provider_id: str) -> dict[str, Any]:
    """Read built-in enablement without normalizing or writing plugins.json."""
    default = next(
        (
            _record(item)
            for item in plugin_manager.BUILTIN_DEFAULTS
            if item.get("id") == provider_id
        ),
        {},
    )
    try:
        payload = json.loads(Path(plugin_manager.CONFIG_FILE).read_text())
        stored = next(
            (
                _record(item)
                for item in _items(_record(payload).get("plugins"))
                if item.get("id") == provider_id
            ),
            {},
        )
    except (OSError, ValueError, TypeError):
        stored = {}
    return {**default, **stored}


class LegacyStorageCapabilityAdapter:
    """Expose MergerFS and SnapRAID through the capability registry.

    The adapter reads the existing plugin configuration and runtime status in place. It
    does not write configuration or invoke plugin commands.
    """

    def __init__(
        self,
        config_dir: str | Path,
        *,
        manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
        plugin_entry_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
        installed_reader: Callable[[StoragePlugin], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifest_dir = Path(manifest_dir)
        self._plugin_entry_reader = plugin_entry_reader or read_builtin_plugin_entry
        self._installed_reader = installed_reader or (lambda plugin: plugin.is_installed())
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        config_path = str(config_dir)
        self._plugins: dict[str, StoragePlugin] = {
            "mergerfs": MergerFSPlugin(config_path),
            "snapraid": SnapRAIDPlugin(config_path),
        }

    def candidates(self) -> list[ProviderCandidate]:
        """Return isolated registry candidates for the built-in storage providers."""
        return [self._candidate(provider_id) for provider_id in ("mergerfs", "snapraid")]

    def _candidate(self, provider_id: str) -> ProviderCandidate:
        plugin = self._plugins[provider_id]
        entry = self._read_entry(provider_id)
        enabled = bool(entry.get("enabled", True))
        configured = self._configured(provider_id, self._read_config(plugin))
        try:
            installed = bool(self._installed_reader(plugin))
        except Exception:
            installed = False
        capability_id = (
            "storage.pooling"
            if provider_id == "mergerfs"
            else "storage.protection"
        )
        return ProviderCandidate(
            manifest=lambda: self._read_manifest(provider_id),
            installed=installed,
            enabled=enabled,
            configured={capability_id: configured},
            status_reader=lambda requested, current=provider_id: self._status(
                current, requested
            ),
            source="builtin",
            provider_id_hint=provider_id,
        )

    def _read_entry(self, provider_id: str) -> dict[str, Any]:
        try:
            return _record(self._plugin_entry_reader(provider_id))
        except Exception:
            return {"enabled": False}

    @staticmethod
    def _read_config(plugin: StoragePlugin) -> dict[str, Any]:
        try:
            return _record(plugin.get_config())
        except Exception:
            return {}

    def _read_manifest(self, provider_id: str) -> dict[str, Any]:
        path = self._manifest_dir / f"{provider_id}.manifest.json"
        return json.loads(path.read_text())

    @staticmethod
    def _configured(provider_id: str, config: Mapping[str, Any]) -> bool:
        if provider_id == "mergerfs":
            return bool(_items(config.get("pools")))
        return bool(config.get("enabled") and _items(config.get("drives")))

    def _status(self, provider_id: str, capability_id: str) -> dict[str, Any]:
        expected = (
            "storage.pooling"
            if provider_id == "mergerfs"
            else "storage.protection"
        )
        if capability_id != expected:
            raise ValueError("unsupported capability")
        plugin = self._plugins[provider_id]
        raw_status = _record(plugin.get_status())
        config = _record(plugin.get_config())
        state = _health_state(raw_status.get("status"))
        message = str(raw_status.get("message") or "Provider status is available.")[:240]
        configured = self._configured(provider_id, config)
        details = (
            self._mergerfs_details(raw_status, config, state)
            if provider_id == "mergerfs"
            else self._snapraid_details(raw_status, config, state)
        )
        summary = self._summary(provider_id, details, state)
        issues = []
        if provider_id == "snapraid" and details.get("sync_required") is True:
            issues.append({
                "code": "sync_required",
                "severity": "warning",
                "message": "Parity must be synchronized with the current data.",
            })
        elif state == "error":
            issues.append({
                "code": "provider_error",
                "severity": "error",
                "message": message,
            })
        return {
            "schema_version": "1",
            "provider_id": provider_id,
            "capability_id": capability_id,
            "observed_at": self._clock().astimezone(timezone.utc).isoformat(),
            "lifecycle": {
                "installed": True,
                "enabled": True,
                "configured": configured,
                "compatibility": "compatible",
                "availability": "available",
            },
            "health": {"state": state, "message": message, "issues": issues},
            "summary": summary,
            "metrics": [],
            "recent_activity": [],
            "details": details,
        }

    @staticmethod
    def _mergerfs_details(
        raw_status: Mapping[str, Any],
        config: Mapping[str, Any],
        state: str,
    ) -> dict[str, Any]:
        status_details = _record(raw_status.get("details"))
        configured = {
            str(pool.get("name")): pool for pool in _items(config.get("pools"))
        }
        pools = []
        for pool in _items(status_details.get("pools")):
            saved = configured.get(str(pool.get("name")), {})
            mounted = bool(pool.get("mounted"))
            pools.append({
                **copy.deepcopy(pool),
                "policy": saved.get("create_policy", saved.get("policy")),
                "health": "healthy" if mounted else "warning",
            })
        return {**copy.deepcopy(status_details), "pools": pools, "provider_health": state}

    @staticmethod
    def _snapraid_details(
        raw_status: Mapping[str, Any],
        config: Mapping[str, Any],
        state: str,
    ) -> dict[str, Any]:
        status_details = _record(raw_status.get("details"))
        drives = _items(config.get("drives"))
        data_drives = sum(drive.get("role") == "data" for drive in drives)
        parity_drives = sum(drive.get("role") == "parity" for drive in drives)
        schedule = _record(config.get("schedule"))
        schedule_label = None
        if _schedule_value(schedule, "sync", "enabled", False):
            schedule_label = str(
                _schedule_value(schedule, "sync", "cron", "Scheduled sync")
            )
        elif _schedule_value(schedule, "scrub", "enabled", False):
            schedule_label = str(
                _schedule_value(schedule, "scrub", "cron", "Scheduled scrub")
            )
        sync_required = status_details.get("sync_required") is True
        set_health = "warning" if sync_required and state == "healthy" else state
        protection_sets = []
        if config.get("enabled") and drives:
            protection_sets.append({
                "name": "SnapRAID parity",
                "kind": "parity",
                "health": set_health,
                "protected_targets": status_details.get("data_drives", data_drives),
                "unprotected_targets": None,
                "parity_targets": status_details.get("parity_drives", parity_drives),
                "last_run_at": status_details.get("last_run_at"),
                "next_run_at": None,
                "schedule": schedule_label,
                "sync_required": sync_required,
                "required_action": "Sync required" if sync_required else None,
            })
        return {
            **copy.deepcopy(status_details),
            "data_drives": status_details.get("data_drives", data_drives),
            "parity_drives": status_details.get("parity_drives", parity_drives),
            "protection_sets": protection_sets,
        }

    @staticmethod
    def _summary(
        provider_id: str,
        details: Mapping[str, Any],
        state: str,
    ) -> list[dict[str, Any]]:
        if provider_id == "mergerfs":
            pools = _items(details.get("pools"))
            return [
                {"id": "pools", "label": "Pools", "value": len(pools), "tone": _tone(state)},
                {
                    "id": "mounted",
                    "label": "Mounted",
                    "value": sum(bool(pool.get("mounted")) for pool in pools),
                    "tone": _tone(state),
                },
            ]
        return [
            {
                "id": "data",
                "label": "Data drives",
                "value": details.get("data_drives", 0),
                "tone": _tone(state),
            },
            {
                "id": "parity",
                "label": "Parity drives",
                "value": details.get("parity_drives", 0),
                "tone": _tone(state),
            },
        ]
