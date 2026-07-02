"""Tests for framework-neutral seedbox configuration."""

from unittest.mock import Mock, call

import pytest

from seedbox_service import (
    SeedboxOperationError,
    SeedboxService,
    SeedboxUnavailableError,
    SeedboxValidationError,
)


def make_service(*, helper=None, repository=None, mounted_reader=None):
    if helper is None:
        helper = Mock()
        helper.available.return_value = True
        helper.call.return_value = {"success": True}
    if repository is None:
        repository = Mock()
        repository.read_json.return_value = None
    return SeedboxService(
        helper=helper,
        repository=repository,
        config_path_provider=lambda: "/config/seedbox.json",
        mount_point_provider=lambda: "/mnt/seedbox",
        mounted_reader=(
            mounted_reader if mounted_reader is not None else Mock(return_value=False)
        ),
    )


def enabled_payload(**overrides):
    return {
        "enabled": True,
        "host": " seedbox.example ",
        "username": " user ",
        "password": "secret",
        "remote_path": " /downloads ",
        "port": "2222",
        **overrides,
    }


def test_state_returns_defaults_and_current_mount_status():
    mounted_reader = Mock(return_value=True)

    result = make_service(mounted_reader=mounted_reader).state()

    assert result == {
        "config": {
            "enabled": False,
            "host": "",
            "username": "",
            "port": 22,
            "remote_path": "",
            "mount_point": "/mnt/seedbox",
        },
        "mounted": True,
    }
    mounted_reader.assert_called_once_with("/mnt/seedbox")


def test_config_falls_back_after_repository_failure():
    repository = Mock()
    repository.read_json.side_effect = PermissionError

    assert make_service(repository=repository).config()["enabled"] is False


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"host": ""}, "host, username, and remote_path required"),
        ({"remote_path": "relative"}, "Invalid remote_path"),
        ({"remote_path": "/data/../secret"}, "Invalid remote_path"),
        ({"password": ""}, "Password required"),
        ({"port": "invalid"}, "Invalid port"),
        ({"port": 65536}, "Invalid port"),
    ],
)
def test_configure_validates_before_helper_call(overrides, message):
    helper = Mock()
    helper.available.return_value = True

    with pytest.raises(SeedboxValidationError, match=message):
        make_service(helper=helper).configure(enabled_payload(**overrides))

    helper.call.assert_not_called()


def test_configure_requires_available_helper():
    helper = Mock()
    helper.available.return_value = False

    with pytest.raises(SeedboxUnavailableError, match="Helper service unavailable"):
        make_service(helper=helper).configure(enabled_payload())


def test_configure_sends_password_but_never_persists_it():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {"success": True}
    repository = Mock()
    mounted_reader = Mock(return_value=True)

    result = make_service(
        helper=helper, repository=repository, mounted_reader=mounted_reader
    ).configure(enabled_payload())

    helper.call.assert_called_once_with(
        "seedbox_configure",
        {
            "host": "seedbox.example",
            "username": "user",
            "password": "secret",
            "remote_path": "/downloads",
            "port": 2222,
        },
    )
    persisted = repository.write_json.call_args.args[1]
    assert "password" not in persisted
    assert result == {"status": "ok", "config": persisted, "mounted": True}


def test_disable_calls_helper_before_persisting_disabled_state():
    events = []
    helper = Mock()
    helper.available.return_value = True
    helper.call.side_effect = lambda *args: events.append("helper") or {"success": True}
    repository = Mock()
    repository.write_json.side_effect = lambda *args: events.append("write")

    result = make_service(helper=helper, repository=repository).configure(
        {"enabled": False, "host": "old", "username": "user", "port": 22}
    )

    assert events == ["helper", "write"]
    assert helper.call.call_args_list == [call("seedbox_disable", {})]
    assert result["config"]["enabled"] is False


def test_helper_rejection_does_not_persist_config():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {"success": False, "error": "sshfs unavailable"}
    repository = Mock()

    with pytest.raises(SeedboxOperationError, match="sshfs unavailable"):
        make_service(helper=helper, repository=repository).configure(enabled_payload())

    repository.write_json.assert_not_called()


def test_mount_reader_failure_is_reported_as_unmounted():
    assert (
        make_service(mounted_reader=Mock(side_effect=PermissionError)).is_mounted()
        is False
    )
