"""
Plugin registry for discovering and managing storage plugins.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, Optional, Union

from storage_plugins.base import StoragePlugin
from storage_plugins.remote_base import RemoteMountPlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Registry for storage plugins."""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self._plugins: Dict[str, Union[StoragePlugin, RemoteMountPlugin]] = {}
        os.makedirs(config_dir, exist_ok=True)

    def register(self, plugin_class: type) -> None:
        required_attrs = ["PLUGIN_ID", "PLUGIN_NAME"]
        for attr in required_attrs:
            if not getattr(plugin_class, attr, None):
                raise ValueError(f"Plugin missing required attribute: {attr}")

        plugin = plugin_class(self.config_dir)

        if issubclass(plugin_class, RemoteMountPlugin):
            required_methods = [
                "get_schema", "validate_mount_config", "mount",
                "unmount", "get_mount_status", "enable_automount",
                "disable_automount", "list_mounts_with_status"
            ]
        else:
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

    def get(self, plugin_id: str) -> Optional[Union[StoragePlugin, RemoteMountPlugin]]:
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[dict]:
        result = []
        for plugin_id, plugin in self._plugins.items():
            if isinstance(plugin, RemoteMountPlugin):
                mounts = plugin.list_mounts_with_status()
                mounted = sum(1 for m in mounts if m.get('mounted'))
                status = {
                    "status": "healthy" if mounts and mounted else "unconfigured",
                    "message": f"{mounted}/{len(mounts)} mounted" if mounts else "No mounts configured"
                }
                configured = len(mounts) > 0
                category = getattr(plugin, 'PLUGIN_CATEGORY', 'mount')
            else:
                status = plugin.get_status()
                configured = status.get("status") != "unconfigured"
                category = getattr(plugin, 'PLUGIN_CATEGORY', 'storage')

            # Get enabled state from plugin config
            enabled = self._get_plugin_enabled(plugin_id)

            result.append({
                "id": plugin_id,
                "name": plugin.PLUGIN_NAME,
                "description": plugin.PLUGIN_DESCRIPTION,
                "version": plugin.PLUGIN_VERSION,
                "category": category,
                "installed": plugin.is_installed(),
                "install_instructions": plugin.get_install_instructions(),
                "enabled": enabled,
                "configured": configured,
                "status": status.get("status", "unknown"),
                "status_message": status.get("message", "")
            })
        return result

    def _get_plugin_enabled(self, plugin_id: str) -> bool:
        """Get plugin enabled state from config."""
        try:
            import plugin_manager
            return plugin_manager.is_enabled(plugin_id)
        except Exception:
            pass
        return True

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Set plugin enabled state."""
        try:
            import plugin_manager
            plugin_manager.set_enabled(plugin_id, enabled)
            return True
        except Exception:
            return False

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        """Check if a plugin is enabled."""
        return self._get_plugin_enabled(plugin_id)

    def get_all(self) -> Dict[str, Union[StoragePlugin, RemoteMountPlugin]]:
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
        import plugin_manager
        enabled = plugin_manager.is_enabled
    except Exception:
        enabled = lambda _id: True

    try:
        from storage_plugins.snapraid_plugin import SnapRAIDPlugin
        if enabled("snapraid"):
            registry.register(SnapRAIDPlugin)
    except Exception:
        pass

    try:
        from storage_plugins.mergerfs_plugin import MergerFSPlugin
        if enabled("mergerfs"):
            registry.register(MergerFSPlugin)
    except Exception:
        pass

    try:
        from storage_plugins.sshfs_plugin import SSHFSPlugin
        if enabled("sshfs"):
            registry.register(SSHFSPlugin)
    except Exception:
        pass

    try:
        from storage_plugins.rclone_plugin import RclonePlugin
        if enabled("rclone"):
            registry.register(RclonePlugin)
    except Exception:
        pass

    try:
        import plugin_manager
        plugin_manager.register_third_party_plugins(registry)
    except Exception:
        pass

    return registry
