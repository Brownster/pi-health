import threading

import pytest

from capability_api import CapabilityLifecycleError
from capability_lifecycle_service import ExtensionLifecycleService


class Manager:
    def __init__(self):
        self.entries = {
            "thirdparty": {
                "id": "thirdparty",
                "type": "github",
                "enabled": False,
            },
            "enabled-provider": {
                "id": "enabled-provider",
                "type": "github",
                "enabled": True,
            },
        }
        self.calls = []
        self.result = {"success": True, "plugin": {"id": "thirdparty"}}

    def get_plugin_entry(self, provider_id):
        return self.entries.get(provider_id)

    def install_plugin(self, *args):
        self.calls.append(("install", *args))
        return self.result

    def set_enabled(self, provider_id, enabled):
        self.calls.append(("set_enabled", provider_id, enabled))

    def update_plugin(self, provider_id):
        self.calls.append(("update", provider_id))
        return self.result

    def repair_plugin(self, provider_id):
        self.calls.append(("repair", provider_id))
        return self.result

    def remove_plugin(self, provider_id):
        self.calls.append(("remove", provider_id))
        return self.result


def test_install_uses_existing_plugin_manager_contract():
    manager = Manager()
    service = ExtensionLifecycleService(manager=manager)

    result, status = service.install(
        {"type": "github", "source": "owner/repo", "id": "thirdparty"},
        username="admin",
    )

    assert status == 201
    assert result == {
        "status": "installed",
        "id": "thirdparty",
        "restart_required": True,
    }
    assert manager.calls == [
        ("install", "github", "owner/repo", "thirdparty", None, None)
    ]


@pytest.mark.parametrize("action", ["update", "repair"])
def test_sync_actions_delegate_without_replacing_configuration(action):
    manager = Manager()
    service = ExtensionLifecycleService(manager=manager)

    result = service.transition("thirdparty", action, {}, username="admin")

    assert result == {
        "status": action,
        "id": "thirdparty",
        "restart_required": True,
    }
    assert manager.calls == [(action, "thirdparty")]


def test_enablement_uses_existing_plugin_state_store():
    manager = Manager()
    service = ExtensionLifecycleService(manager=manager)

    result = service.transition("thirdparty", "enable", {}, username="admin")

    assert result["enabled"] is True
    assert result["restart_required"] is True
    assert manager.calls == [("set_enabled", "thirdparty", True)]


def test_remove_requires_disabled_extension():
    manager = Manager()
    service = ExtensionLifecycleService(manager=manager)

    with pytest.raises(CapabilityLifecycleError) as error:
        service.transition("enabled-provider", "remove", {}, username="admin")

    assert error.value.code == "extension_must_be_disabled"
    assert manager.calls == []


def test_missing_and_failed_extensions_return_bounded_errors():
    manager = Manager()
    service = ExtensionLifecycleService(manager=manager)

    with pytest.raises(CapabilityLifecycleError) as missing:
        service.transition("missing", "repair", {}, username="admin")
    assert missing.value.code == "extension_not_found"

    manager.result = {"success": False, "error": "token=must-not-leak"}
    with pytest.raises(CapabilityLifecycleError) as failed:
        service.transition("thirdparty", "repair", {}, username="admin")
    assert failed.value.code == "extension_repair_failed"
    assert "must-not-leak" not in failed.value.message


def test_concurrent_lifecycle_operations_fail_fast():
    manager = Manager()
    lock = threading.Lock()
    lock.acquire()
    service = ExtensionLifecycleService(manager=manager, operation_lock=lock)

    with pytest.raises(CapabilityLifecycleError) as error:
        service.transition("thirdparty", "enable", {}, username="admin")

    assert error.value.code == "extension_busy"
    assert manager.calls == []
    lock.release()
