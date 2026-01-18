#!/usr/bin/env python3
"""
Tests for storage plugin API endpoints.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from storage_plugins.base import CommandResult


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["username"] = "testuser"
    return client


class DummyPlugin:
    PLUGIN_ID = "dummy"
    PLUGIN_NAME = "Dummy Plugin"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Test plugin"

    def __init__(self):
        self.saved_config = {}

    def get_schema(self):
        return {"type": "object"}

    def get_config(self):
        return {"enabled": True}

    def set_config(self, config):
        self.saved_config = config
        return CommandResult(success=True, message="saved")

    def validate_config(self, config):
        if config.get("invalid"):
            return ["invalid config"]
        return []

    def apply_config(self):
        return CommandResult(success=True, message="applied")

    def get_status(self):
        return {"status": "healthy", "message": "ok"}

    def get_commands(self):
        return [{"id": "status"}]

    def run_command(self, command_id, params=None):
        yield "running\n"
        return CommandResult(success=True, message="done")

    def is_installed(self):
        return True

    def get_install_instructions(self):
        return ""


class DummyMountPlugin:
    def list_mounts_with_status(self):
        return [{"id": "m1", "mounted": False}]

    def add_mount(self, config):
        return CommandResult(success=True, message="added")

    def update_mount(self, mount_id, config):
        return CommandResult(success=True, message="updated")

    def remove_mount(self, mount_id):
        return CommandResult(success=True, message="removed")

    def mount(self, mount_id):
        return CommandResult(success=True, message="mounted")

    def unmount(self, mount_id):
        return CommandResult(success=True, message="unmounted")

    def get_mount_status(self, mount_id):
        return {"status": "connected"}


class DummyRegistry:
    def __init__(self, plugin=None, mount_plugin=None):
        self._plugin = plugin
        self._mount_plugin = mount_plugin

    def list_plugins(self):
        return [{"id": "dummy", "name": "Dummy Plugin"}]

    def get(self, plugin_id):
        if plugin_id == "dummy":
            return self._plugin
        if plugin_id == "mount":
            return self._mount_plugin
        return None

    def set_plugin_enabled(self, plugin_id, enabled):
        return True


def test_list_plugins_uses_plugin_manager(authenticated_client, monkeypatch):
    registry = DummyRegistry()
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)
    monkeypatch.setattr("plugin_manager.list_plugins", lambda _reg: [{"id": "dummy"}])

    response = authenticated_client.get("/api/storage/plugins")
    assert response.status_code == 200
    data = response.get_json()
    assert data["plugins"][0]["id"] == "dummy"


def test_toggle_plugin_imports_existing_shares(authenticated_client, monkeypatch):
    class ImportingPlugin(DummyPlugin):
        def import_existing_shares(self):
            return CommandResult(success=True, message="Imported", data={"imported": 2})

    registry = DummyRegistry(plugin=ImportingPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)
    monkeypatch.setattr("plugin_manager.set_enabled", lambda *_args, **_kwargs: None)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/toggle",
        data=json.dumps({"enabled": True}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["enabled"] is True
    assert data["imported"] == 2
    assert data["import_message"] == "Imported"


def test_toggle_plugin_falls_back_to_registry(authenticated_client, monkeypatch):
    class FallbackRegistry(DummyRegistry):
        def set_plugin_enabled(self, plugin_id, enabled):
            return plugin_id == "dummy" and enabled is True

    registry = FallbackRegistry()
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("plugin_manager.set_enabled", raise_error)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/toggle",
        data=json.dumps({"enabled": True}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["enabled"] is True


def test_install_plugin_requires_type_and_source(authenticated_client):
    response = authenticated_client.post(
        "/api/storage/plugins/install",
        data=json.dumps({"type": "", "source": ""}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_install_plugin_failure(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        "plugin_manager.install_plugin",
        lambda *_args, **_kwargs: {"success": False, "error": "Install failed"},
    )
    response = authenticated_client.post(
        "/api/storage/plugins/install",
        data=json.dumps({"type": "github", "source": "https://example.com/repo"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "Install failed"


def test_remove_plugin_failure(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        "plugin_manager.remove_plugin",
        lambda *_args, **_kwargs: {"success": False, "error": "Remove failed"},
    )
    response = authenticated_client.delete("/api/storage/plugins/dummy/remove")
    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "Remove failed"


def test_get_plugin_details(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/plugins/dummy")
    assert response.status_code == 200
    data = response.get_json()
    assert data["id"] == "dummy"
    assert "schema" in data
    assert "config" in data


def test_set_plugin_config_validation_error(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/config",
        data=json.dumps({"invalid": True}),
        content_type="application/json",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["error"] == "Validation failed"


def test_set_plugin_config_success(authenticated_client, monkeypatch):
    plugin = DummyPlugin()
    registry = DummyRegistry(plugin=plugin)
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/config",
        data=json.dumps({"name": "ok"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert plugin.saved_config == {"name": "ok"}


def test_run_plugin_command_stream(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/commands/status",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "complete" in body


def test_mount_endpoints(authenticated_client, monkeypatch):
    registry = DummyRegistry(mount_plugin=DummyMountPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/mounts/mount")
    assert response.status_code == 200

    response = authenticated_client.post(
        "/api/storage/mounts/mount",
        data=json.dumps({"id": "m1"}),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = authenticated_client.put(
        "/api/storage/mounts/mount/m1",
        data=json.dumps({"enabled": True}),
        content_type="application/json",
    )
    assert response.status_code == 200

    response = authenticated_client.post("/api/storage/mounts/mount/m1/mount")
    assert response.status_code == 200

    response = authenticated_client.post("/api/storage/mounts/mount/m1/unmount")
    assert response.status_code == 200

    response = authenticated_client.get("/api/storage/mounts/mount/m1/status")
    assert response.status_code == 200

    response = authenticated_client.delete("/api/storage/mounts/mount/m1")
    assert response.status_code == 200
