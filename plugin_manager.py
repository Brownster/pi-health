"""
Plugin manager for built-in and third-party plugins.
Handles enable/disable state and third-party installation metadata.
"""
import importlib
import importlib.util
import json
import os
from typing import Optional

from helper_client import helper_call, HelperError
from storage_plugins.base import StoragePlugin
from storage_plugins.remote_base import RemoteMountPlugin


CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "plugins.json")
PLUGIN_DIR = os.getenv("PIHEALTH_PLUGIN_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins"))

BUILTIN_DEFAULTS = [
    {
        "id": "snapraid",
        "name": "SnapRAID",
        "type": "builtin",
        "enabled": True,
        "category": "storage"
    },
    {
        "id": "mergerfs",
        "name": "MergerFS",
        "type": "builtin",
        "enabled": True,
        "category": "storage"
    },
    {
        "id": "sshfs",
        "name": "SSHFS",
        "type": "builtin",
        "enabled": True,
        "category": "mount"
    },
    {
        "id": "rclone",
        "name": "Rclone",
        "type": "builtin",
        "enabled": False,
        "category": "mount"
    }
]


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"plugins": []}


def _save_config(config: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def _merge_defaults(config: dict) -> dict:
    existing = {p.get("id"): p for p in config.get("plugins", []) if p.get("id")}
    merged = []
    for default in BUILTIN_DEFAULTS:
        entry = {**default, **existing.get(default["id"], {})}
        merged.append(entry)
    for plugin_id, entry in existing.items():
        if plugin_id not in {p["id"] for p in BUILTIN_DEFAULTS}:
            merged.append(entry)
    return {"plugins": merged}


def load_plugins_config() -> dict:
    config = _merge_defaults(_load_config())
    _save_config(config)
    return config


def get_plugin_entry(plugin_id: str) -> Optional[dict]:
    config = load_plugins_config()
    for plugin in config.get("plugins", []):
        if plugin.get("id") == plugin_id:
            return plugin
    return None


def is_enabled(plugin_id: str) -> bool:
    entry = get_plugin_entry(plugin_id)
    if not entry:
        return False
    return bool(entry.get("enabled", False))


def set_enabled(plugin_id: str, enabled: bool) -> None:
    config = load_plugins_config()
    updated = []
    found = False
    for plugin in config.get("plugins", []):
        if plugin.get("id") == plugin_id:
            plugin = {**plugin, "enabled": bool(enabled)}
            found = True
        updated.append(plugin)
    if not found:
        updated.append({"id": plugin_id, "enabled": bool(enabled)})
    config["plugins"] = updated
    _save_config(config)


def list_plugins(registry) -> list[dict]:
    config = load_plugins_config()
    registered = {p["id"]: p for p in registry.list_plugins()}
    results = []

    for plugin in config.get("plugins", []):
        plugin_id = plugin.get("id")
        info = registered.get(plugin_id)
        enabled = bool(plugin.get("enabled", False))
        if info:
            entry = {**info, **plugin, "enabled": enabled}
        else:
            installed = False
            if plugin.get("type") == "github" and plugin_id:
                installed = os.path.exists(os.path.join(PLUGIN_DIR, plugin_id))
            elif plugin.get("type") == "pip":
                module_name = plugin.get("entry") or ""
                if module_name:
                    installed = importlib.util.find_spec(module_name) is not None
            entry = {
                "id": plugin_id,
                "name": plugin.get("name", plugin_id),
                "description": plugin.get("description", ""),
                "version": plugin.get("version", ""),
                "installed": installed,
                "configured": False,
                "status": "disabled" if not enabled else "missing",
                "status_message": "Disabled" if not enabled else "Not loaded",
                "category": plugin.get("category", "storage"),
                "enabled": enabled,
                "type": plugin.get("type", "builtin"),
                "source": plugin.get("source", "")
            }
        results.append(entry)

    # Include any registered plugins not in config
    for plugin_id, info in registered.items():
        if not any(p.get("id") == plugin_id for p in results):
            results.append({**info, "enabled": True})

    return results


def _load_manifest(plugin_path: str) -> dict:
    manifest_path = os.path.join(plugin_path, "pihealth_plugin.json")
    with open(manifest_path, "r") as f:
        return json.load(f)


def install_plugin(
    source_type: str,
    source: str,
    plugin_id: Optional[str] = None,
    entry: Optional[str] = None,
    class_name: Optional[str] = None,
) -> dict:
    payload = {
        "type": source_type,
        "source": source,
        "id": plugin_id or "",
        "entry": entry or "",
        "class_name": class_name or ""
    }
    try:
        result = helper_call("plugin_install", payload)
    except HelperError as exc:
        return {"success": False, "error": str(exc)}

    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Install failed")}

    if source_type == "github":
        plugin_id = result.get("id") or plugin_id
        if not plugin_id:
            return {"success": False, "error": "Missing plugin ID"}
        plugin_path = os.path.join(PLUGIN_DIR, plugin_id)
        try:
            manifest = _load_manifest(plugin_path)
        except Exception as exc:
            return {"success": False, "error": f"Failed to read manifest: {exc}"}

        entry = {
            "id": manifest.get("id", plugin_id),
            "name": manifest.get("name", plugin_id),
            "type": "github",
            "source": source,
            "entry": manifest.get("entry"),
            "class_name": manifest.get("class"),
            "category": manifest.get("category", "storage"),
            "enabled": False,
            "description": manifest.get("description", ""),
            "version": manifest.get("version", "")
        }
    else:
        if not entry or not class_name:
            return {"success": False, "error": "Pip plugins require entry module and class name"}
        entry = {
            "id": plugin_id or source,
            "name": plugin_id or source,
            "type": "pip",
            "source": source,
            "entry": entry,
            "class_name": class_name,
            "category": "storage",
            "enabled": False
        }

    config = load_plugins_config()
    config["plugins"] = [p for p in config.get("plugins", []) if p.get("id") != entry["id"]]
    config["plugins"].append(entry)
    _save_config(config)
    return {"success": True, "plugin": entry}


def remove_plugin(plugin_id: str) -> dict:
    entry = get_plugin_entry(plugin_id)
    if not entry or entry.get("type") == "builtin":
        return {"success": False, "error": "Builtin plugins cannot be removed"}

    try:
        result = helper_call("plugin_remove", {"id": plugin_id, "type": entry.get("type"), "source": entry.get("source", "")})
    except HelperError as exc:
        return {"success": False, "error": str(exc)}

    if not result.get("success"):
        return {"success": False, "error": result.get("error", "Remove failed")}

    config = load_plugins_config()
    config["plugins"] = [p for p in config.get("plugins", []) if p.get("id") != plugin_id]
    _save_config(config)
    return {"success": True}


def register_third_party_plugins(registry) -> None:
    config = load_plugins_config()
    for plugin in config.get("plugins", []):
        if not plugin.get("enabled"):
            continue
        plugin_type = plugin.get("type")
        if plugin_type not in ("github", "pip"):
            continue

        try:
            plugin_class = None
            if plugin_type == "github":
                entry = plugin.get("entry")
                class_name = plugin.get("class_name")
                if not entry or not class_name:
                    continue
                plugin_path = os.path.join(PLUGIN_DIR, plugin.get("id", ""))
                module_path = os.path.join(plugin_path, entry)
                if not os.path.exists(module_path):
                    continue
                spec = importlib.util.spec_from_file_location(f"pihealth_plugin_{plugin.get('id')}", module_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    plugin_class = getattr(module, class_name, None)
            else:
                module_name = plugin.get("entry")
                class_name = plugin.get("class_name")
                if not module_name or not class_name:
                    continue
                module = importlib.import_module(module_name)
                plugin_class = getattr(module, class_name, None)

            if plugin_class and issubclass(plugin_class, (StoragePlugin, RemoteMountPlugin)):
                registry.register(plugin_class)
        except Exception:
            continue
