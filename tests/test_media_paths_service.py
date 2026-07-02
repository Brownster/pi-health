"""Tests for framework-neutral media-path management."""

import os

from unittest.mock import Mock, call

import pytest

from media_paths_service import MediaPathValidationError, MediaPathsService


DEFAULTS = {
    "downloads": "/mnt/downloads",
    "storage": "/mnt/storage",
    "backup": "/mnt/backup",
    "config": "/home/pi/docker",
}


def make_service(
    *, helper=None, repository=None, renderer=None, file_exists=None, file_reader=None
):
    if helper is None:
        helper = Mock()
        helper.available.return_value = False
    if repository is None:
        repository = Mock()
        repository.read_json.return_value = {}
    return MediaPathsService(
        helper=helper,
        repository=repository,
        config_path_provider=lambda: "/config/media_paths.json",
        compose_path_provider=lambda: "./docker-compose.yml",
        defaults=DEFAULTS,
        startup_renderer=(
            renderer
            if renderer is not None
            else Mock(return_value=("script", "service"))
        ),
        file_exists=file_exists
        if file_exists is not None
        else Mock(return_value=False),
        file_reader=(
            file_reader
            if file_reader is not None
            else Mock(side_effect=FileNotFoundError)
        ),
    )


def test_paths_merges_configured_values_over_defaults():
    repository = Mock()
    repository.read_json.return_value = {"storage": "/mnt/media"}

    paths = make_service(repository=repository).paths()

    assert paths == {**DEFAULTS, "storage": "/mnt/media"}
    repository.read_json.assert_called_once_with("/config/media_paths.json", default={})


def test_paths_falls_back_after_repository_failure():
    repository = Mock()
    repository.read_json.side_effect = PermissionError

    assert make_service(repository=repository).paths() == DEFAULTS


def test_update_validates_before_write():
    repository = Mock()
    repository.read_json.return_value = {}

    with pytest.raises(MediaPathValidationError, match="Invalid path for storage"):
        make_service(repository=repository).update({"storage": "relative/path"})

    repository.write_json.assert_not_called()


def test_update_writes_merged_paths_and_reports_startup_warning():
    repository = Mock()
    repository.read_json.return_value = {"backup": "/mnt/archive"}
    helper = Mock()
    helper.available.return_value = False

    result = make_service(helper=helper, repository=repository).update(
        {"storage": "/mnt/media", "ignored": "/mnt/ignored"}
    )

    expected = {**DEFAULTS, "backup": "/mnt/archive", "storage": "/mnt/media"}
    repository.write_json.assert_called_once_with("/config/media_paths.json", expected)
    assert result == {
        "status": "updated",
        "paths": expected,
        "startup_warning": "Helper service unavailable",
    }


def test_apply_startup_service_preserves_helper_sequence():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {"success": True}

    result = make_service(helper=helper).apply_startup_service(DEFAULTS)

    assert result == {"success": True}
    assert helper.call.call_args_list == [
        call(
            "configure_startup_service",
            {
                "mount_points": [
                    "/mnt/storage",
                    "/mnt/downloads",
                    "/mnt/backup",
                ],
                "compose_file": os.path.abspath("./docker-compose.yml"),
            },
        ),
        call("systemctl", {"action": "daemon-reload"}),
        call(
            "systemctl",
            {"action": "enable", "unit": "docker-compose-start.service"},
        ),
    ]


def test_apply_startup_service_stops_after_configure_failure():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {"success": False, "error": "denied"}

    assert make_service(helper=helper).apply_startup_service(DEFAULTS) == {
        "success": False,
        "error": "denied",
    }
    assert helper.call.call_count == 1


def test_preview_prefers_privileged_helper_result():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {
        "success": True,
        "script": {"proposed": "helper script"},
        "service": {"proposed": "helper service"},
    }
    renderer = Mock()

    result = make_service(helper=helper, renderer=renderer).preview_startup_service()

    assert result["script"]["proposed"] == "helper script"
    renderer.assert_not_called()


def test_preview_falls_back_to_local_files_after_helper_failure():
    helper = Mock()
    helper.available.return_value = True
    helper.call.side_effect = RuntimeError("offline")
    renderer = Mock(return_value=("new script", "new service"))
    current = {
        "/usr/local/bin/check_mount_and_start.sh": "old script",
        "/etc/systemd/system/docker-compose-start.service": "new service",
    }

    result = make_service(
        helper=helper,
        renderer=renderer,
        file_exists=lambda path: path in current,
        file_reader=lambda path: current[path],
    ).preview_startup_service()

    assert result["script"]["changed"] is True
    assert result["service"]["changed"] is False
