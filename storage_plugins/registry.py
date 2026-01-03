"""
Plugin registry for discovering and managing storage plugins.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional

from storage_plugins.base import StoragePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for storage plugins."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._plugins: Dict[str, StoragePlugin] = {}
        os.makedirs(config_dir, exist_ok=True)

    def register(self, plugin_class: type) -> None:
        required_attrs = ["PLUGIN_ID", "PLUGIN_NAME"]
        for attr in required_attrs:
            if not getattr(plugin_class, attr, None):
                raise ValueError(f"Plugin missing required attribute: {attr}")

        plugin = plugin_class(self.config_dir)

        required_methods = [
            "get_schema", "get_config", "set_config",
            "validate_config", "apply_config", "get_status",
            "get_commands", "run_command"
        ]
        for method in required_methods:
            if not callable(getattr(plugin, method, None)):
                raise ValueError(f"Plugin missing required method: {method}")

        self._plugins[plugin.PLUGIN_ID] = plugin
        logger.info("Registered plugin: %s", plugin.PLUGIN_ID)

    def get(self, plugin_id: str) -> Optional[StoragePlugin]:
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[dict]:
        result = []
        for plugin_id, plugin in self._plugins.items():
            status = plugin.get_status()
            result.append({
                "id": plugin_id,
                "name": plugin.PLUGIN_NAME,
                "description": plugin.PLUGIN_DESCRIPTION,
                "version": plugin.PLUGIN_VERSION,
                "installed": plugin.is_installed(),
                "configured": status.get("status") != "unconfigured",
                "status": status.get("status", "unknown"),
                "status_message": status.get("message", "")
            })
        return result

    def get_all(self) -> Dict[str, StoragePlugin]:
        return self._plugins.copy()


_registry: Optional[PluginRegistry] = None


def get_registry(config_dir: str = None) -> PluginRegistry:
    global _registry
    if _registry is None:
        if config_dir is None:
            raise ValueError("config_dir required for first initialization")
        _registry = PluginRegistry(config_dir)
    return _registry


def init_plugins(config_dir: str) -> PluginRegistry:
    registry = get_registry(config_dir)

    try:
        from storage_plugins.snapraid_plugin import SnapRAIDPlugin
        registry.register(SnapRAIDPlugin)
    except Exception:
        pass

    try:
        from storage_plugins.mergerfs_plugin import MergerFSPlugin
        registry.register(MergerFSPlugin)
    except Exception:
        pass

    return registry
