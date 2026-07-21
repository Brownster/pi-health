"""Unprivileged fixed repair jobs for installed LimeOS extensions and integrations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_EXTENSION_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FAILED_PROVIDER_STATES = {"error", "incompatible", "missing", "unknown"}


def _extension_entry(name: str) -> dict[str, Any]:
    if len(name) > 64 or not _EXTENSION_ID.fullmatch(name):
        raise ValueError("Extension ID is invalid")

    import plugin_manager

    try:
        config = json.loads(Path(plugin_manager.CONFIG_FILE).read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError("Extension configuration is unavailable") from exc
    plugins = config.get("plugins") if isinstance(config, Mapping) else None
    for item in plugins if isinstance(plugins, list) else []:
        if isinstance(item, Mapping) and item.get("id") == name:
            return dict(item)
    raise RuntimeError("Extension is not installed")


def inspect_extension(name: str) -> dict[str, Any]:
    """Import one configured third-party extension as the dashboard user."""
    import plugin_manager
    from storage_plugins.base import StoragePlugin
    from storage_plugins.registry import PluginRegistry
    from storage_plugins.remote_base import RemoteMountPlugin
    from runtime_paths import STORAGE_PLUGIN_CONFIG_DIR

    entry = _extension_entry(name)
    source_type = str(entry.get("type") or "")
    enabled = entry.get("enabled") is True
    source = entry.get("source")
    source_configured = isinstance(source, str) and bool(source.strip())
    plugin_path = Path(plugin_manager.PLUGIN_DIR) / name
    installed = plugin_path.is_dir() and not plugin_path.is_symlink()
    base = {
        "name": name,
        "type": source_type,
        "enabled": enabled,
        "installed": installed,
        "source_configured": source_configured,
        "repairable": (source_type == "github" and enabled and source_configured),
    }
    if not base["repairable"]:
        return {**base, "registered": False, "status": "unavailable"}
    if not installed:
        return {**base, "registered": False, "status": "missing"}

    entry_path = entry.get("entry")
    class_name = entry.get("class_name")
    if not isinstance(entry_path, str) or not isinstance(class_name, str):
        return {**base, "registered": False, "status": "missing"}
    module_candidate = plugin_path / entry_path
    module_path = module_candidate.resolve()
    try:
        plugin_root = plugin_path.resolve()
        if (
            plugin_root not in module_path.parents
            or module_candidate.is_symlink()
            or not module_path.is_file()
        ):
            raise RuntimeError
        spec = importlib.util.spec_from_file_location(
            f"limeos_repair_check_{name}", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        plugin_class = getattr(module, class_name)
        if not issubclass(plugin_class, (StoragePlugin, RemoteMountPlugin)):
            raise RuntimeError
        registry = PluginRegistry(str(STORAGE_PLUGIN_CONFIG_DIR))
        registry.register(plugin_class)
        observed = next(
            item for item in registry.list_plugins() if item.get("id") == name
        )
    except Exception:
        return {**base, "registered": False, "status": "error"}

    state = str(observed.get("status") or "unknown").lower()
    return {
        **base,
        "registered": True,
        "configured": observed.get("configured") is True,
        "status": state,
        "healthy": state not in _FAILED_PROVIDER_STATES,
    }


def repair_extension(name: str) -> dict[str, Any]:
    """Repair one configured extension through its existing lifecycle service."""
    from capability_lifecycle_service import ExtensionLifecycleService

    before = inspect_extension(name)
    if before.get("repairable") is not True:
        raise RuntimeError("Extension is not eligible for repair")
    ExtensionLifecycleService().transition(
        name,
        "repair",
        {},
        username="limeos-action",
    )
    after = inspect_extension(name)
    if after.get("registered") is not True or after.get("healthy") is not True:
        raise RuntimeError("Extension health verification failed")
    return after


def _mattermost_service():
    from app import create_app

    application = create_app({"INIT_PLUGINS": False, "START_SCHEDULERS": False})
    return application.extensions["mattermost_integration_service"]


def inspect_mattermost() -> dict[str, Any]:
    """Return bounded Mattermost lifecycle and service health."""
    status = _mattermost_service().status()
    raw_services = status.get("services")
    services = [
        {
            "name": str(name),
            "state": str(value.get("state") or "unknown").lower(),
            "health": str(value.get("health") or "").lower(),
        }
        for name, value in (
            raw_services.items() if isinstance(raw_services, Mapping) else []
        )
        if isinstance(value, Mapping)
    ]
    return {
        "name": "mattermost",
        "state": str(status.get("state") or "unknown").lower(),
        "installed": status.get("installed") is True,
        "stack_name": str(status.get("stack_name") or ""),
        "webhook_configured": status.get("webhook_configured") is True,
        "services": sorted(services, key=lambda item: item["name"]),
    }


def repair_mattermost() -> dict[str, Any]:
    """Repair Mattermost through its existing integration service."""
    service = _mattermost_service()
    service.repair()
    return inspect_mattermost()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one fixed LimeOS integration repair job."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("extension-status", "extension-repair"):
        child = subparsers.add_parser(command)
        child.add_argument("--name", required=True)
    subparsers.add_parser("mattermost-status")
    subparsers.add_parser("mattermost-repair")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extension-status":
            result = inspect_extension(args.name)
        elif args.command == "extension-repair":
            result = repair_extension(args.name)
        elif args.command == "mattermost-status":
            result = inspect_mattermost()
        else:
            result = repair_mattermost()
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - systemd entry point
    raise SystemExit(main())
