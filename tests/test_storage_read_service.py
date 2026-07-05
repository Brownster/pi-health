"""Tests for framework-neutral storage-plugin reads."""

from unittest.mock import Mock

import pytest

from storage_read_service import (
    StoragePluginCapabilityError,
    StoragePluginDataNotFoundError,
    StoragePluginNotFoundError,
    StorageReadService,
)


def service(*, plugin=None, registry=None, managed_list_reader=None):
    if registry is None:
        registry = Mock()
        registry.get.return_value = plugin
    return StorageReadService(
        registry_provider=Mock(return_value=registry),
        managed_list_reader=(
            managed_list_reader
            if managed_list_reader is not None
            else Mock(return_value=[{"id": "managed"}])
        ),
    )


def test_list_prefers_managed_plugin_inventory():
    registry = Mock()
    managed = Mock(return_value=[{"id": "managed"}])

    result = service(registry=registry, managed_list_reader=managed).list_plugins()

    assert result == {"plugins": [{"id": "managed"}]}
    managed.assert_called_once_with(registry)
    registry.list_plugins.assert_not_called()


def test_list_falls_back_to_registry_after_manager_failure():
    registry = Mock()
    registry.list_plugins.return_value = [{"id": "builtin"}]

    result = service(
        registry=registry,
        managed_list_reader=Mock(side_effect=RuntimeError("manager unavailable")),
    ).list_plugins()

    assert result == {"plugins": [{"id": "builtin"}]}


def test_details_composes_plugin_metadata_and_live_reads():
    plugin = Mock()
    plugin.PLUGIN_ID = "snapraid"
    plugin.PLUGIN_NAME = "SnapRAID"
    plugin.PLUGIN_DESCRIPTION = "Parity"
    plugin.PLUGIN_VERSION = "1.0"
    plugin.is_installed.return_value = True
    plugin.get_install_instructions.return_value = ""
    plugin.get_schema.return_value = {"type": "object"}
    plugin.get_config.return_value = {"enabled": True}
    plugin.get_status.return_value = {"status": "healthy"}
    plugin.get_commands.return_value = [{"id": "sync"}]
    plugin.PLUGIN_KIND = "pool"

    result = service(plugin=plugin).details("snapraid")

    assert result == {
        "id": "snapraid",
        "name": "SnapRAID",
        "description": "Parity",
        "version": "1.0",
        "kind": "pool",
        "installed": True,
        "install_instructions": "",
        "schema": {"type": "object"},
        "config": {"enabled": True},
        "status": {"status": "healthy"},
        "commands": [{"id": "sync"}],
    }


def test_missing_plugin_is_classified_for_every_read():
    subject = service(plugin=None)

    for operation in (
        lambda: subject.details("missing"),
        lambda: subject.status("missing"),
        lambda: subject.recovery("missing"),
        lambda: subject.latest_log("missing"),
    ):
        with pytest.raises(
            StoragePluginNotFoundError, match="Plugin not found: missing"
        ):
            operation()


def test_status_delegates_to_plugin():
    plugin = Mock()
    plugin.get_status.return_value = {"status": "degraded"}

    assert service(plugin=plugin).status("dummy") == {"status": "degraded"}


def test_optional_recovery_capability_and_result():
    unsupported = object()
    with pytest.raises(StoragePluginCapabilityError, match="Recovery not supported"):
        service(plugin=unsupported).recovery("dummy")

    supported = Mock()
    supported.get_recovery_status.return_value = {"recoverable": True}
    assert service(plugin=supported).recovery("dummy") == {"recoverable": True}


def test_latest_log_classifies_capability_and_empty_result():
    with pytest.raises(StoragePluginCapabilityError, match="Logs not supported"):
        service(plugin=object()).latest_log("dummy")

    plugin = Mock()
    plugin.get_latest_log.return_value = None
    with pytest.raises(StoragePluginDataNotFoundError, match="No logs available"):
        service(plugin=plugin).latest_log("dummy")


def test_latest_log_returns_transport_neutral_record():
    plugin = Mock()
    record = {"content": "line", "path": "/log", "truncated": False}
    plugin.get_latest_log.return_value = record

    assert service(plugin=plugin).latest_log("dummy") == record
