import json
from datetime import datetime, timezone

from flask import Flask

import app as app_module
from capability_registry_service import CapabilityRegistryService
import storage_capability_adapters
from storage_capability_adapters import (
    LegacyStorageCapabilityAdapter,
    read_builtin_plugin_entry,
)


NOW = datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc)


def registry(adapter):
    return CapabilityRegistryService(
        candidate_reader=adapter.candidates,
        limeos_version="1.0.0",
        clock=lambda: NOW,
    )


def write_config(path, name, payload):
    (path / f"{name}.json").write_text(json.dumps(payload, indent=2))


def status(snapshot, capability_id):
    capability = next(
        item for item in snapshot["capabilities"] if item["id"] == capability_id
    )
    return capability["providers"][0]["status"]


def test_adapter_maps_existing_configs_without_rewriting_them(tmp_path, monkeypatch):
    mergerfs_config = {
        "pools": [{
            "name": "media",
            "branches": ["/mnt/data1", "/mnt/data2"],
            "mount_point": "/mnt/media",
            "create_policy": "epmfs",
        }],
    }
    snapraid_config = {
        "enabled": True,
        "drives": [
            {"name": "d1", "path": "/mnt/data1", "role": "data", "content": True},
            {"name": "p1", "path": "/mnt/parity1", "role": "parity", "content": True},
        ],
        "schedule": {
            "sync_enabled": True,
            "sync_cron": "0 2 * * *",
            "scrub_enabled": False,
            "scrub_cron": "0 3 * * 0",
        },
    }
    write_config(tmp_path, "mergerfs", mergerfs_config)
    write_config(tmp_path, "snapraid", snapraid_config)
    before = {
        name: (tmp_path / f"{name}.json").read_text()
        for name in ("mergerfs", "snapraid")
    }
    entries = {
        "mergerfs": {"enabled": True},
        "snapraid": {"enabled": True},
    }
    adapter = LegacyStorageCapabilityAdapter(
        tmp_path,
        plugin_entry_reader=entries.get,
        installed_reader=lambda _plugin: True,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        adapter._plugins["mergerfs"],
        "get_status",
        lambda: {
            "status": "healthy",
            "message": "1 pool(s) configured",
            "details": {"pools": [{
                "name": "media", "mount_point": "/mnt/media", "mounted": True,
                "branches": 2, "total_bytes": 4_000, "free_bytes": 2_500,
            }]},
        },
    )
    monkeypatch.setattr(
        adapter._plugins["snapraid"],
        "get_status",
        lambda: {
            "status": "degraded",
            "message": "Sync required",
            "details": {
                "data_drives": 1,
                "parity_drives": 1,
                "sync_required": True,
                "last_run_at": "2026-07-18T20:00:00+00:00",
            },
        },
    )

    snapshot = registry(adapter).snapshot()

    assert snapshot["errors"] == []
    pool_status = status(snapshot, "storage.pooling")
    pool = pool_status["details"]["pools"][0]
    assert pool_status["lifecycle"]["configured"] is True
    assert pool == {
        "name": "media",
        "mount_point": "/mnt/media",
        "mounted": True,
        "branches": 2,
        "total_bytes": 4_000,
        "free_bytes": 2_500,
        "policy": "epmfs",
        "health": "healthy",
    }
    protection_status = status(snapshot, "storage.protection")
    protection_set = protection_status["details"]["protection_sets"][0]
    assert protection_status["health"]["state"] == "warning"
    assert protection_status["health"]["issues"][0]["code"] == "sync_required"
    assert protection_set["protected_targets"] == 1
    assert protection_set["parity_targets"] == 1
    assert protection_set["schedule"] == "0 2 * * *"
    assert protection_set["required_action"] == "Sync required"
    assert {
        name: (tmp_path / f"{name}.json").read_text()
        for name in ("mergerfs", "snapraid")
    } == before


def test_disabled_provider_is_discoverable_without_status_execution(tmp_path, monkeypatch):
    write_config(tmp_path, "mergerfs", {"pools": []})
    write_config(tmp_path, "snapraid", {
        "enabled": True,
        "drives": [{"name": "d1", "path": "/mnt/data1", "role": "data"}],
    })
    entries = {
        "mergerfs": {"enabled": True},
        "snapraid": {"enabled": False},
    }
    adapter = LegacyStorageCapabilityAdapter(
        tmp_path,
        plugin_entry_reader=entries.get,
        installed_reader=lambda _plugin: True,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        adapter._plugins["mergerfs"],
        "get_status",
        lambda: {"status": "unconfigured", "message": "No pools", "details": {"pools": []}},
    )
    monkeypatch.setattr(
        adapter._plugins["snapraid"],
        "get_status",
        lambda: (_ for _ in ()).throw(AssertionError("disabled status read")),
    )

    snapshot = registry(adapter).snapshot()
    providers = {provider["id"]: provider for provider in snapshot["providers"]}
    snapraid = providers["snapraid"]

    assert snapshot["errors"] == []
    assert snapraid["installed"] is True
    assert snapraid["enabled"] is False
    assert snapraid["capabilities"][0]["status"]["health"]["state"] == "disabled"
    assert snapraid["capabilities"][0]["status"]["lifecycle"]["configured"] is True


def test_corrupt_provider_config_is_isolated(tmp_path, monkeypatch):
    (tmp_path / "mergerfs.json").write_text("{not-json")
    write_config(tmp_path, "snapraid", {
        "enabled": True,
        "drives": [
            {"name": "d1", "path": "/mnt/data1", "role": "data"},
            {"name": "p1", "path": "/mnt/parity1", "role": "parity"},
        ],
    })
    adapter = LegacyStorageCapabilityAdapter(
        tmp_path,
        plugin_entry_reader=lambda _provider_id: {"enabled": True},
        installed_reader=lambda _plugin: True,
        clock=lambda: NOW,
    )
    monkeypatch.setattr(
        adapter._plugins["snapraid"],
        "get_status",
        lambda: {
            "status": "healthy",
            "message": "All data protected",
            "details": {"data_drives": 1, "parity_drives": 1, "sync_required": False},
        },
    )

    snapshot = registry(adapter).snapshot()
    providers = {provider["id"]: provider for provider in snapshot["providers"]}

    assert providers["mergerfs"]["health"]["state"] == "unavailable"
    assert providers["snapraid"]["health"]["state"] == "healthy"
    assert snapshot["errors"] == [{
        "code": "provider_status_unavailable",
        "message": "Provider status is unavailable.",
        "provider_id": "mergerfs",
    }]


def test_production_manifest_actions_match_plugin_commands(tmp_path):
    adapter = LegacyStorageCapabilityAdapter(
        tmp_path,
        plugin_entry_reader=lambda _provider_id: {"enabled": False},
        installed_reader=lambda _plugin: True,
    )

    for provider_id, candidate in zip(("mergerfs", "snapraid"), adapter.candidates()):
        manifest = candidate.manifest()
        declared = {action["id"] for action in manifest["capabilities"][0]["actions"]}
        implemented = {command["id"] for command in adapter._plugins[provider_id].get_commands()}
        assert declared == implemented


def test_builtin_enablement_read_does_not_create_or_normalize_config(tmp_path, monkeypatch):
    config_path = tmp_path / "plugins.json"
    monkeypatch.setattr(storage_capability_adapters.plugin_manager, "CONFIG_FILE", str(config_path))

    assert read_builtin_plugin_entry("snapraid")["enabled"] is True
    assert not config_path.exists()

    original = '{"plugins":[{"id":"snapraid","enabled":false,"custom":"keep"}]}'
    config_path.write_text(original)
    entry = read_builtin_plugin_entry("snapraid")

    assert entry["enabled"] is False
    assert entry["custom"] == "keep"
    assert config_path.read_text() == original


def test_production_registry_uses_storage_adapter(monkeypatch):
    calls = []

    class Adapter:
        def __init__(self, config_dir):
            calls.append(("init", config_dir))

        def candidates(self):
            calls.append(("candidates",))
            return []

    monkeypatch.setattr(app_module, "LegacyStorageCapabilityAdapter", Adapter)
    application = Flask(__name__)
    application.config.update(INIT_PLUGINS=True, LIMEOS_VERSION="1.0.0")

    service = app_module._default_capability_registry_service(application)

    assert service.snapshot()["providers"] == []
    assert calls == [("init", app_module.STORAGE_PLUGIN_CONFIG_DIR), ("candidates",)]
    assert application.extensions["storage_capability_adapter"].__class__ is Adapter
