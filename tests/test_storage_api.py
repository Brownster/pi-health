#!/usr/bin/env python3
"""
Tests for storage plugin API endpoints.
"""
import json
import os
import sys
from unittest.mock import Mock


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.base import CommandResult



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


class DummySharePlugin(DummyPlugin):
    def __init__(self):
        super().__init__()
        self.shares = [{"name": "media", "enabled": True}]

    def get_status(self):
        return {
            "status": "healthy",
            "message": "ok",
            "service_running": True,
            "details": {"shares": self.shares},
        }

    def add_share(self, share):
        self.shares.append(share)
        return CommandResult(success=True, message="added")

    def update_share(self, share_name, share):
        return CommandResult(success=True, message=f"updated {share_name}")

    def remove_share(self, share_name):
        return CommandResult(success=True, message=f"removed {share_name}")

    def toggle_share(self, share_name, enabled):
        return CommandResult(success=True, message=f"toggled {share_name}={enabled}")


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
        if plugin_id == "share":
            return self._plugin
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


def test_storage_read_routes_delegate_to_injected_service(authenticated_client, app):
    service = Mock()
    service.list_plugins.return_value = {"plugins": []}
    service.details.return_value = {"id": "dummy"}
    service.status.return_value = {"status": "healthy"}
    service.recovery.return_value = {"recoverable": True}
    service.latest_log.return_value = {
        "content": "latest",
        "path": "/tmp/latest.log",
        "truncated": False,
    }
    app.extensions["storage_read_service"] = service

    assert authenticated_client.get("/api/storage/plugins").status_code == 200
    assert authenticated_client.get("/api/storage/plugins/dummy").status_code == 200
    assert authenticated_client.get(
        "/api/storage/plugins/dummy/status"
    ).status_code == 200
    assert authenticated_client.get(
        "/api/storage/plugins/dummy/recovery"
    ).status_code == 200
    log_response = authenticated_client.get(
        "/api/storage/plugins/dummy/logs/latest"
    )

    assert log_response.status_code == 200
    assert log_response.get_data(as_text=True) == "latest"
    service.list_plugins.assert_called_once_with()
    service.details.assert_called_once_with("dummy")
    service.status.assert_called_once_with("dummy")
    service.recovery.assert_called_once_with("dummy")
    service.latest_log.assert_called_once_with("dummy")


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


def test_run_plugin_command_adds_authenticated_audit_user(authenticated_client, monkeypatch):
    class AuditPlugin(DummyPlugin):
        PLUGIN_ID = "snapraid"

        def __init__(self):
            super().__init__()
            self.params = None

        def run_command(self, command_id, params=None):
            self.params = params
            yield "running"
            return CommandResult(success=True, message="done")

    plugin = AuditPlugin()
    plugin.get_commands = lambda: [{"id": "sync"}]
    registry = DummyRegistry(plugin=plugin)
    registry.get = lambda plugin_id: plugin if plugin_id == "snapraid" else None
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/snapraid/commands/sync",
        json={"force_reason": "confirmed"},
    )

    assert response.status_code == 200
    assert plugin.params == {
        "force_reason": "confirmed",
        "_audit_user": "testuser",
        "stream_tags": True,
    }


def test_run_plugin_command_stream_includes_output(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/commands/status",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 200
    events = []
    for line in response.data.decode("utf-8").splitlines():
        if line.startswith("data: "):
            payload = json.loads(line.replace("data: ", "", 1))
            events.append(payload)
    assert any(event.get("type") == "output" and "running" in event.get("line", "") for event in events)
    assert any(event.get("type") == "complete" and event.get("success") is True for event in events)


def test_run_plugin_command_stream_includes_failure_error(authenticated_client, monkeypatch):
    class FailedPlugin(DummyPlugin):
        def run_command(self, command_id, params=None):
            yield "failed"
            return CommandResult(success=False, message="", error="mount failed")

    registry = DummyRegistry(plugin=FailedPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)
    response = authenticated_client.post(
        "/api/storage/plugins/dummy/commands/status",
        json={},
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.data.decode("utf-8").splitlines()
        if line.startswith("data: ")
    ]
    completion = next(event for event in events if event.get("type") == "complete")
    assert completion["success"] is False
    assert completion["error"] == "mount failed"


def test_run_plugin_command_unknown(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/commands/unknown",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 404


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


def test_validate_plugin_config(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/dummy/validate",
        data=json.dumps({"invalid": True}),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["valid"] is False
    assert "invalid config" in data["errors"][0]


def test_apply_plugin_config_success(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post("/api/storage/plugins/dummy/apply")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "applied"


def test_apply_plugin_config_failure(authenticated_client, monkeypatch):
    class FailingPlugin(DummyPlugin):
        def apply_config(self):
            return CommandResult(success=False, message="nope", error="apply failed")

    registry = DummyRegistry(plugin=FailingPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post("/api/storage/plugins/dummy/apply")
    assert response.status_code == 400
    assert response.get_json()["error"] == "apply failed"


def test_get_plugin_status(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/plugins/dummy/status")
    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_get_plugin_recovery_not_supported(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummyPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/plugins/dummy/recovery")
    assert response.status_code == 404


def test_get_plugin_recovery_supported(authenticated_client, monkeypatch):
    class RecoverablePlugin(DummyPlugin):
        def get_recovery_status(self):
            return {"recoverable": True}

    registry = DummyRegistry(plugin=RecoverablePlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/plugins/dummy/recovery")
    assert response.status_code == 200
    assert response.get_json()["recoverable"] is True


def test_get_plugin_latest_log(authenticated_client, monkeypatch):
    class LogPlugin(DummyPlugin):
        def get_latest_log(self):
            return {"content": "hello\n", "path": "/tmp/test.log", "truncated": False}

    registry = DummyRegistry(plugin=LogPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/plugins/dummy/logs/latest")
    assert response.status_code == 200
    assert "hello" in response.get_data(as_text=True)
    assert response.headers["X-Log-Path"] == "/tmp/test.log"
    assert response.headers["X-Log-Truncated"] == "false"


def test_detect_mounts_success(authenticated_client, monkeypatch):
    class DetectingMountPlugin(DummyMountPlugin):
        def import_existing_mounts(self):
            return CommandResult(success=True, message="Imported", data={"imported": 1})

    registry = DummyRegistry(mount_plugin=DetectingMountPlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post("/api/storage/mounts/mount/detect")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["imported"] == 1


def test_share_endpoints(authenticated_client, monkeypatch):
    registry = DummyRegistry(plugin=DummySharePlugin())
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.get("/api/storage/shares/share")
    assert response.status_code == 200
    shares_payload = response.get_json()
    assert shares_payload["service_running"] is True
    assert shares_payload["shares"][0]["name"] == "media"

    response = authenticated_client.post(
        "/api/storage/shares/share",
        data=json.dumps({"name": "downloads", "path": "/mnt/downloads"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "created"

    response = authenticated_client.put(
        "/api/storage/shares/share/media",
        data=json.dumps({"path": "/mnt/media"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "updated"

    response = authenticated_client.post(
        "/api/storage/shares/share/media/toggle",
        data=json.dumps({"enabled": False}),
        content_type="application/json",
    )
    assert response.status_code == 200
    toggle_data = response.get_json()
    assert toggle_data["status"] == "toggled"
    assert toggle_data["enabled"] is False

    response = authenticated_client.delete("/api/storage/shares/share/media")
    assert response.status_code == 200
    assert response.get_json()["status"] == "deleted"


def test_config_preview_returns_generated_text(authenticated_client, monkeypatch):
    plugin = Mock()
    plugin.preview_config.return_value = "parity /mnt/parity/snapraid.parity\n"
    registry = Mock()
    registry.get.return_value = plugin
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/snapraid/config-preview",
        data=json.dumps({"enabled": True, "drives": []}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert "parity" in response.get_json()["preview"]
    plugin.preview_config.assert_called_once_with({"enabled": True, "drives": []})
    plugin.set_config.assert_not_called()  # preview must not write


def test_config_preview_unsupported_plugin_returns_400(authenticated_client, monkeypatch):
    plugin = Mock()
    plugin.preview_config.return_value = None
    registry = Mock()
    registry.get.return_value = plugin
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/rclone/config-preview",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_snapraid_command_defaults_stream_tags_and_audit(authenticated_client, monkeypatch):
    recorded = {}

    class FakePlugin:
        def get_commands(self):
            return [{"id": "sync"}]

        def run_command(self, command_id, params):
            recorded["params"] = dict(params)
            if False:  # make this a generator
                yield ""
            return CommandResult(success=True, message="ok")

    registry = Mock()
    registry.get.return_value = FakePlugin()
    monkeypatch.setattr("storage_plugins.get_registry", lambda: registry)

    response = authenticated_client.post(
        "/api/storage/plugins/snapraid/commands/sync",
        data=json.dumps({}),
        content_type="application/json",
    )
    response.get_data()  # drain the SSE generator so run_command executes

    assert recorded["params"]["stream_tags"] is True
    assert recorded["params"]["_audit_user"]
