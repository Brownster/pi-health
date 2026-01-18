#!/usr/bin/env python3
"""
Tests for SSHFS remote mount plugin.
"""
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.sshfs_plugin import SSHFSPlugin


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def sample_config():
    return {
        "id": "seedbox",
        "name": "Seedbox",
        "host": "example.com",
        "port": 22,
        "username": "user",
        "password": "secret",
        "remote_path": "/data",
        "mount_point": "/mnt/seedbox",
        "enabled": True
    }


def test_validate_mount_config_ok(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    errors = plugin.validate_mount_config(sample_config())
    assert errors == []


def test_validate_mount_config_errors(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    errors = plugin.validate_mount_config({"id": "Bad Id"})
    assert errors


def test_add_mount_saves_without_password(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    config = sample_config()

    with patch("storage_plugins.sshfs_plugin.helper_call", return_value={"success": True}):
        result = plugin.add_mount(config)

    assert result.success is True
    mounts = plugin.load_mounts()
    assert mounts[0]["id"] == "seedbox"
    assert "password" not in mounts[0]


def test_add_mount_duplicate(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    config = sample_config()

    with patch("storage_plugins.sshfs_plugin.helper_call", return_value={"success": True}):
        plugin.add_mount(config)
        result = plugin.add_mount(config)

    assert result.success is False


def test_mount_unmount_calls_helper(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)

    with patch("storage_plugins.sshfs_plugin.helper_call", return_value={"success": True}) as helper:
        mount_result = plugin.mount("seedbox")
        unmount_result = plugin.unmount("seedbox")

    assert mount_result.success is True
    assert unmount_result.success is True
    assert helper.call_count == 2


def test_update_mount_enabled_toggle(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    base = sample_config()
    base.pop("password")
    plugin.save_mounts([base])

    with patch("storage_plugins.sshfs_plugin.helper_call", return_value={"success": True}) as helper:
        result = plugin.update_mount("seedbox", {"enabled": False})

    assert result.success is True
    mounts = plugin.load_mounts()
    assert mounts[0]["enabled"] is False
    helper.assert_called_once()


def test_get_mount_status_not_configured(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    status = plugin.get_mount_status("missing")
    assert status["status"] == "error"


def test_get_mount_status_connected(temp_config_dir):
    plugin = SSHFSPlugin(temp_config_dir)
    plugin.save_mounts([{
        "id": "seedbox",
        "mount_point": "/mnt/seedbox"
    }])

    mock_run = MagicMock(returncode=0)
    with patch("storage_plugins.sshfs_plugin.subprocess.run", return_value=mock_run):
        with patch("storage_plugins.sshfs_plugin.os.listdir", return_value=[]):
            status = plugin.get_mount_status("seedbox")

    assert status["status"] == "connected"
