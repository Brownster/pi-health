"""Framework-neutral storage-plugin read operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class StoragePluginNotFoundError(Exception):
    """Raised when a requested storage plugin is not registered."""


class StoragePluginCapabilityError(Exception):
    """Raised when a plugin does not expose an optional read capability."""


class StoragePluginDataNotFoundError(Exception):
    """Raised when an optional plugin read has no current data."""


class StorageReadService:
    """Build storage-plugin read models from an injected registry."""

    def __init__(
        self,
        *,
        registry_provider: Callable[[], Any],
        managed_list_reader: Callable[[Any], list[dict]],
    ) -> None:
        self._registry_provider = registry_provider
        self._managed_list_reader = managed_list_reader

    def list_plugins(self) -> dict:
        registry = self._registry_provider()
        try:
            plugins = self._managed_list_reader(registry)
        except Exception:
            plugins = registry.list_plugins()
        return {"plugins": plugins}

    def details(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        return {
            "id": plugin.PLUGIN_ID,
            "name": plugin.PLUGIN_NAME,
            "description": plugin.PLUGIN_DESCRIPTION,
            "version": plugin.PLUGIN_VERSION,
            "installed": plugin.is_installed(),
            "install_instructions": plugin.get_install_instructions(),
            "schema": plugin.get_schema(),
            "config": plugin.get_config(),
            "status": plugin.get_status(),
            "commands": plugin.get_commands(),
        }

    def status(self, plugin_id: str) -> dict:
        return self._plugin(plugin_id).get_status()

    def recovery(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        if not hasattr(plugin, "get_recovery_status"):
            raise StoragePluginCapabilityError("Recovery not supported")
        return plugin.get_recovery_status()

    def latest_log(self, plugin_id: str) -> dict:
        plugin = self._plugin(plugin_id)
        if not hasattr(plugin, "get_latest_log"):
            raise StoragePluginCapabilityError("Logs not supported")
        result = plugin.get_latest_log()
        if not result:
            raise StoragePluginDataNotFoundError("No logs available")
        return result

    def _plugin(self, plugin_id: str):
        plugin = self._registry_provider().get(plugin_id)
        if not plugin:
            raise StoragePluginNotFoundError(f"Plugin not found: {plugin_id}")
        return plugin
