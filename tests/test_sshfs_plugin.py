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


class TestSSHFSImport:
    """Tests for SSHFS mount detection and import."""

    def test_parse_sshfs_source_basic(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        result = plugin._parse_sshfs_source("user@server.com:/data/files", "/mnt/remote")

        assert result is not None
        assert result["username"] == "user"
        assert result["host"] == "server.com"
        assert result["remote_path"] == "/data/files"
        assert result["mount_point"] == "/mnt/remote"
        assert result["port"] == 22
        assert result["auth_type"] == "key"

    def test_parse_sshfs_source_with_port(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        result = plugin._parse_sshfs_source("admin@192.168.1.100:2222:/home", "/mnt/nas")

        assert result is not None
        assert result["username"] == "admin"
        assert result["host"] == "192.168.1.100"
        assert result["port"] == 2222
        assert result["remote_path"] == "/home"

    def test_parse_sshfs_source_invalid(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)

        assert plugin._parse_sshfs_source("invalid", "/mnt/test") is None
        assert plugin._parse_sshfs_source("/local/path", "/mnt/test") is None
        assert plugin._parse_sshfs_source("noat:path", "/mnt/test") is None

    def test_parse_sshfs_source_generates_valid_id(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        result = plugin._parse_sshfs_source("user@host:/path", "/mnt/My Data")

        assert result is not None
        # ID should be lowercase, no spaces
        assert result["id"] == "mnt-my-data"

    def test_detect_sshfs_mounts_parses_proc_mounts(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        proc_mounts_content = """
/dev/sda1 / ext4 rw,relatime 0 0
user@server.com:/files /mnt/seedbox fuse.sshfs rw,nosuid,nodev 0 0
tmpfs /tmp tmpfs rw,nosuid 0 0
admin@nas.local:/share /mnt/nas fuse.sshfs rw,nosuid,nodev 0 0
"""
        with patch("builtins.open", MagicMock(return_value=proc_mounts_content.strip().split('\n'))):
            with patch("builtins.open") as mock_open:
                mock_open.return_value.__enter__.return_value = proc_mounts_content.strip().split('\n')
                mounts = plugin._detect_sshfs_mounts()

        assert len(mounts) == 2
        assert mounts[0]["host"] == "server.com"
        assert mounts[1]["host"] == "nas.local"

    def test_detect_sshfs_mounts_empty(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        proc_mounts_content = "/dev/sda1 / ext4 rw,relatime 0 0\n"

        with patch("builtins.open", MagicMock(return_value=iter(proc_mounts_content.split('\n')))):
            mounts = plugin._detect_sshfs_mounts()

        assert mounts == []

    def test_import_existing_mounts_no_mounts(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)

        with patch.object(plugin, "_detect_sshfs_mounts", return_value=[]):
            result = plugin.import_existing_mounts()

        assert result.success is True
        assert result.data["imported"] == 0
        assert "No existing" in result.message

    def test_import_existing_mounts_imports_new(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        detected = [{
            "id": "seedbox",
            "name": "user@server:/files",
            "host": "server",
            "port": 22,
            "username": "user",
            "remote_path": "/files",
            "mount_point": "/mnt/seedbox",
            "auth_type": "key",
            "enabled": True,
            "imported": True,
            "options": {"reconnect": True, "allow_other": True}
        }]

        with patch.object(plugin, "_detect_sshfs_mounts", return_value=detected):
            result = plugin.import_existing_mounts()

        assert result.success is True
        assert result.data["imported"] == 1
        mounts = plugin.load_mounts()
        assert len(mounts) == 1
        assert mounts[0]["id"] == "seedbox"

    def test_import_existing_mounts_skips_existing(self, temp_config_dir):
        plugin = SSHFSPlugin(temp_config_dir)
        # Pre-existing mount
        plugin.save_mounts([{
            "id": "existing",
            "mount_point": "/mnt/seedbox"
        }])

        detected = [{
            "id": "seedbox",
            "name": "user@server:/files",
            "host": "server",
            "port": 22,
            "username": "user",
            "remote_path": "/files",
            "mount_point": "/mnt/seedbox",  # Same mount point
            "auth_type": "key",
            "enabled": True,
            "imported": True,
            "options": {}
        }]

        with patch.object(plugin, "_detect_sshfs_mounts", return_value=detected):
            result = plugin.import_existing_mounts()

        assert result.success is True
        assert result.data["imported"] == 0
        assert "No new mounts" in result.message
