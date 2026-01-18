#!/usr/bin/env python3
"""
Tests for Rclone remote mount plugin.
"""
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.rclone_plugin import RclonePlugin


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def sample_config():
    return {
        "id": "s3-backup",
        "name": "S3 Backup",
        "backend": "s3",
        "provider": "AWS",
        "access_key_id": "key",
        "secret_access_key": "secret",
        "region": "us-east-1",
        "bucket": "my-bucket",
        "mount_point": "/mnt/s3",
        "enabled": False
    }


def test_validate_mount_config_ok(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    errors = plugin.validate_mount_config(sample_config())
    assert errors == []


def test_validate_mount_config_missing_secret(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    config = sample_config()
    config.pop("secret_access_key")
    errors = plugin.validate_mount_config(config)
    assert errors


def test_add_mount_saves_without_secret(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    config = sample_config()

    with patch("storage_plugins.rclone_plugin.helper_call", return_value={"success": True}):
        result = plugin.add_mount(config)

    assert result.success is True
    mounts = plugin.load_mounts()
    assert mounts[0]["id"] == "s3-backup"
    assert "secret_access_key" not in mounts[0]


def test_update_mount_toggle_enabled(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    config = sample_config()
    config.pop("secret_access_key")
    plugin.save_mounts([config])

    with patch("storage_plugins.rclone_plugin.helper_call", return_value={"success": True}):
        result = plugin.update_mount("s3-backup", {"enabled": True})

    assert result.success is True
    mounts = plugin.load_mounts()
    assert mounts[0]["enabled"] is True


def test_mount_unmount_calls_helper(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    with patch("storage_plugins.rclone_plugin.helper_call", return_value={"success": True}) as helper:
        mount_result = plugin.mount("s3-backup")
        unmount_result = plugin.unmount("s3-backup")

    assert mount_result.success is True
    assert unmount_result.success is True
    assert helper.call_count == 2


def test_get_mount_status_not_configured(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    status = plugin.get_mount_status("missing")
    assert status["status"] == "error"


def test_get_mount_status_connected(temp_config_dir):
    plugin = RclonePlugin(temp_config_dir)
    plugin.save_mounts([{
        "id": "s3-backup",
        "mount_point": "/mnt/s3"
    }])

    mock_run = MagicMock(returncode=0)
    with patch("storage_plugins.rclone_plugin.subprocess.run", return_value=mock_run):
        status = plugin.get_mount_status("s3-backup")

    assert status["status"] == "connected"
