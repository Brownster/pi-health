#!/usr/bin/env python3
"""
Tests for pihealth_helper module
"""
import sys
import os
from unittest.mock import patch, MagicMock, mock_open

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import importlib


with patch("logging.FileHandler", return_value=logging.StreamHandler()):
    helper = importlib.import_module("pihealth_helper")


class TestRunCommand:
    @patch("pihealth_helper.subprocess.run")
    def test_run_command_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        result = helper.run_command(["echo", "ok"])
        assert result["stdout"] == "ok"
        assert result["returncode"] == 0


class TestCommandParsing:
    @patch("pihealth_helper.run_command")
    def test_cmd_lsblk_invalid_json(self, mock_run):
        mock_run.return_value = {"returncode": 0, "stdout": "not-json"}
        result = helper.cmd_lsblk({})
        assert result["success"] is False

    @patch("pihealth_helper.run_command")
    def test_cmd_blkid_parsing(self, mock_run):
        mock_run.return_value = {
            "returncode": 0,
            "stdout": "DEVNAME=/dev/sda1\nUUID=abc\n\nDEVNAME=/dev/sdb1\nUUID=def\n",
        }
        result = helper.cmd_blkid({})
        assert result["success"] is True
        assert len(result["data"]) == 2

    def test_cmd_fstab_read_missing_file(self):
        with patch("pihealth_helper.os.path.exists", return_value=False):
            result = helper.cmd_fstab_read({})
        assert result["success"] is True
        assert result["data"] == []

    def test_cmd_fstab_read_parses_entries(self):
        content = "# comment\nUUID=abc /mnt/storage ext4 defaults 0 2\n"
        with patch("pihealth_helper.os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=content)):
                result = helper.cmd_fstab_read({})
        assert result["success"] is True
        assert result["data"][0]["mountpoint"] == "/mnt/storage"

    def test_cmd_mounts_read_parses(self):
        content = "/dev/sda1 /mnt/storage ext4 rw,relatime 0 0\n"
        with patch("builtins.open", mock_open(read_data=content)):
            result = helper.cmd_mounts_read({})
        assert result["success"] is True
        assert result["data"][0]["device"] == "/dev/sda1"

    @patch("pihealth_helper.run_command")
    def test_cmd_df_parses(self, mock_run):
        mock_run.return_value = {
            "returncode": 0,
            "stdout": "source target fstype size used avail pcent\n/dev/sda1 / ext4 100 50 50 50%\n",
        }
        result = helper.cmd_df({})
        assert result["success"] is True
        assert result["data"][0]["source"] == "/dev/sda1"


class TestValidationFailures:
    def test_cmd_fstab_add_invalid_uuid(self):
        result = helper.cmd_fstab_add({"uuid": "bad!", "mountpoint": "/mnt/data"})
        assert result["success"] is False

    def test_cmd_fstab_add_invalid_mount(self):
        result = helper.cmd_fstab_add({"uuid": "abc-123", "mountpoint": "/tmp"})
        assert result["success"] is False

    def test_cmd_fstab_add_invalid_fstype(self):
        result = helper.cmd_fstab_add({"uuid": "abc-123", "mountpoint": "/mnt/data", "fstype": "weird"})
        assert result["success"] is False

    def test_cmd_mount_invalid_mountpoint(self):
        result = helper.cmd_mount({"mountpoint": "/tmp"})
        assert result["success"] is False

    def test_cmd_umount_invalid_mountpoint(self):
        result = helper.cmd_umount({"mountpoint": "/tmp"})
        assert result["success"] is False

    def test_cmd_smart_info_invalid_device(self):
        result = helper.cmd_smart_info({"device": "notdev"})
        assert result["success"] is False

    def test_cmd_snapraid_invalid_command(self):
        result = helper.cmd_snapraid({"command": "rm"})
        assert result["success"] is False

    def test_cmd_mergerfs_mount_invalid(self):
        result = helper.cmd_mergerfs_mount({"branches": "/mnt/a", "mount_point": "/bad"})
        assert result["success"] is False

    def test_cmd_mergerfs_umount_invalid(self):
        result = helper.cmd_mergerfs_umount({"mount_point": "/bad"})
        assert result["success"] is False

    def test_cmd_write_snapraid_conf_invalid_path(self):
        result = helper.cmd_write_snapraid_conf({"path": "/tmp/snapraid.conf"})
        assert result["success"] is False

    def test_cmd_write_systemd_unit_invalid(self):
        result = helper.cmd_write_systemd_unit({"unit_name": "bad.service"})
        assert result["success"] is False

    def test_cmd_write_startup_script_invalid(self):
        result = helper.cmd_write_startup_script({"path": "/tmp/script.sh"})
        assert result["success"] is False

    def test_cmd_systemctl_invalid_action(self):
        result = helper.cmd_systemctl({"action": "reboot"})
        assert result["success"] is False

    def test_cmd_tailscale_up_invalid_auth(self):
        result = helper.cmd_tailscale_up({"auth_key": "bad key"})
        assert result["success"] is False

    def test_cmd_docker_network_create_invalid_name(self):
        result = helper.cmd_docker_network_create({"name": "bad name"})
        assert result["success"] is False

    def test_cmd_write_vpn_env_invalid_path(self):
        result = helper.cmd_write_vpn_env({"path": "/etc/passwd"})
        assert result["success"] is False

    def test_cmd_backup_create_invalid_sources(self):
        result = helper.cmd_backup_create({"sources": [], "dest_dir": "/mnt/backups"})
        assert result["success"] is False

    def test_cmd_backup_create_invalid_dest(self):
        result = helper.cmd_backup_create({"sources": ["/home/pi"], "dest_dir": "/tmp"})
        assert result["success"] is False

    def test_cmd_backup_create_no_valid_sources(self):
        with patch("pihealth_helper.os.path.exists", return_value=False):
            result = helper.cmd_backup_create(
                {"sources": ["/home/pi"], "dest_dir": "/mnt/backups"}
            )
        assert result["success"] is False

    def test_cmd_backup_restore_invalid_archive(self):
        result = helper.cmd_backup_restore({"archive_path": "/tmp/file.txt"})
        assert result["success"] is False

    def test_cmd_seedbox_configure_missing(self):
        result = helper.cmd_seedbox_configure({"host": "", "username": "", "remote_path": ""})
        assert result["success"] is False


class TestRequestHandling:
    def test_handle_request_invalid_json(self):
        result = helper.handle_request("not json")
        assert result["success"] is False

    def test_handle_request_missing_command(self):
        result = helper.handle_request("{}")
        assert result["success"] is False

    def test_handle_request_unknown_command(self):
        result = helper.handle_request('{"command":"nope"}')
        assert result["success"] is False

    def test_handle_request_ping(self):
        result = helper.handle_request('{"command":"ping"}')
        assert result["success"] is True
