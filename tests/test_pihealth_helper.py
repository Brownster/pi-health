#!/usr/bin/env python3
"""
Tests for pihealth_helper module
"""
import sys
import os
import json
import socket
import stat
import struct
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

    def test_cmd_fstab_set_section_writes(self, tmp_path):
        path = tmp_path / "fstab"
        path.write_text("UUID=abc /mnt/data ext4 defaults 0 2\n")
        result = helper.cmd_fstab_set_section({
            "marker": "mergerfs",
            "lines": [
                "# mergerfs pool: storage",
                "/mnt/a:/mnt/b /mnt/storage fuse.mergerfs defaults 0 0"
            ],
            "path": str(path)
        })
        assert result["success"] is True
        content = path.read_text()
        assert "# pi-health mergerfs start" in content
        assert "fuse.mergerfs" in content

    def test_cmd_fstab_set_section_removes(self, tmp_path):
        path = tmp_path / "fstab"
        path.write_text(
            "UUID=abc /mnt/data ext4 defaults 0 2\n"
            "# pi-health mergerfs start\n"
            "# mergerfs pool: storage\n"
            "/mnt/a:/mnt/b /mnt/storage fuse.mergerfs defaults 0 0\n"
            "# pi-health mergerfs end\n"
        )
        result = helper.cmd_fstab_set_section({
            "marker": "mergerfs",
            "lines": [],
            "path": str(path)
        })
        assert result["success"] is True
        content = path.read_text()
        assert "# pi-health mergerfs start" not in content
        assert "fuse.mergerfs" not in content

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

    def test_cmd_fstab_add_rejects_raw_options(self):
        result = helper.cmd_fstab_add({
            "uuid": "abc-123",
            "mountpoint": "/mnt/data",
            "fstype": "ext4",
            "options": "defaults,nofail",
        })
        assert result == {"success": False, "error": "Custom mount options are not allowed"}

    @pytest.mark.parametrize(
        ("fstype", "expected_entry"),
        [
            ("ext4", "UUID=abc-123 /mnt/data ext4 defaults,nofail 0 2\n"),
            ("xfs", "UUID=abc-123 /mnt/data xfs defaults,nofail 0 0\n"),
            (
                "exfat",
                "UUID=abc-123 /mnt/data exfat defaults,nofail,uid=1000,gid=1000,umask=0022 0 0\n",
            ),
        ],
    )
    def test_cmd_fstab_add_uses_filesystem_preset(self, fstype, expected_entry):
        opened = mock_open(read_data="")
        with patch("pihealth_helper.shutil.copy"):
            with patch("pihealth_helper.os.makedirs"):
                with patch("builtins.open", opened):
                    result = helper.cmd_fstab_add({
                        "uuid": "abc-123",
                        "mountpoint": "/mnt/data",
                        "fstype": fstype,
                    })

        assert result["success"] is True
        opened().write.assert_any_call(expected_entry)

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

    def test_cmd_configure_startup_service_invalid_mount(self):
        result = helper.cmd_configure_startup_service({
            "mount_points": ["/mnt/data\nExecStart=/bin/sh"],
            "compose_file": "/opt/stacks/docker-compose.yml",
        })
        assert result["success"] is False

    def test_cmd_configure_startup_service_invalid_compose_path(self):
        result = helper.cmd_configure_startup_service({
            "mount_points": ["/mnt/data"],
            "compose_file": "/tmp/compose.yml",
        })
        assert result["success"] is False

    def test_cmd_preview_startup_service(self):
        with patch("pihealth_helper.os.path.exists", return_value=False):
            result = helper.cmd_preview_startup_service({
                "mount_points": ["/mnt/data"],
                "compose_file": "/opt/stacks/docker-compose.yml",
            })
        assert result["success"] is True
        assert "script" in result
        assert "service" in result
        assert "path" in result["script"]
        assert "/mnt/data" in result["script"]["proposed"]
        assert "exists" in result["script"]

    def test_cmd_configure_snapraid_schedule_rejects_injection(self):
        result = helper.cmd_configure_snapraid_schedule({
            "job_type": "sync\nExecStart=/bin/sh",
            "cron": "0 3 * * *",
        })
        assert result["success"] is False

        result = helper.cmd_configure_snapraid_schedule({
            "job_type": "sync",
            "cron": "0 3 * * *\nExecStart=/bin/sh",
        })
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

    def test_cmd_backup_create_accepts_runtime_roots(self):
        sources = ["/etc/limeos", "/var/lib/limeos", "/var/log/limeos"]
        with (
            patch("pihealth_helper.os.path.exists", return_value=True),
            patch("pihealth_helper.os.makedirs"),
            patch("pihealth_helper.os.listdir", return_value=[]),
            patch(
                "pihealth_helper.run_command",
                return_value={"returncode": 0, "stdout": "", "stderr": ""},
            ),
        ):
            result = helper.cmd_backup_create(
                {"sources": sources, "dest_dir": "/mnt/backups"}
            )
        assert result["success"] is True

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

    def test_handle_request_requires_object_params(self):
        result = helper.handle_request('[]')
        assert result == {"success": False, "error": "Request must be an object"}

        result = helper.handle_request('{"command":"ping","params":[]}')
        assert result == {"success": False, "error": "Invalid command or parameters"}

    def test_handle_request_unknown_command(self):
        result = helper.handle_request('{"command":"nope"}')
        assert result["success"] is False

    def test_handle_request_ping(self):
        result = helper.handle_request('{"command":"ping"}')
        assert result["success"] is True

    def test_raw_file_write_commands_are_not_exposed(self):
        for command in ("write_systemd_unit", "write_startup_script"):
            request = json.dumps({"command": command, "params": {"content": "#!/bin/sh"}})
            result = helper.handle_request(request)
            assert result["success"] is False
            assert "Unknown command" in result["error"]


class TestManagedTemplates:
    def test_startup_template_ignores_raw_content(self, tmp_path):
        script_path = tmp_path / "check_mount_and_start.sh"
        service_path = tmp_path / "docker-compose-start.service"
        params = {
            "mount_points": ["/mnt/data"],
            "compose_file": "/opt/stacks/docker-compose.yml",
            "content": "ExecStart=/bin/sh",
        }
        with patch.object(helper, "STARTUP_SCRIPT_PATH", str(script_path)):
            with patch.object(helper, "STARTUP_SERVICE_PATH", str(service_path)):
                result = helper.cmd_configure_startup_service(params)

        assert result["success"] is True
        assert "ExecStart=/bin/sh" not in script_path.read_text()
        assert "ExecStart=/bin/sh" not in service_path.read_text()
        assert "/mnt/data" in script_path.read_text()
        assert stat.S_IMODE(script_path.stat().st_mode) == 0o755

    def test_snapraid_template_uses_only_validated_job_and_cron(self, tmp_path):
        def write_to_tmp(path, content, mode=0o644):
            target = tmp_path / os.path.basename(path)
            target.write_text(content)
            return {"success": True, "path": str(target)}

        with patch.object(helper, "_write_managed_file", side_effect=write_to_tmp):
            result = helper.cmd_configure_snapraid_schedule({
                "job_type": "sync",
                "cron": "30 4 * * 0",
                "content": "ExecStart=/bin/sh",
            })

        assert result["success"] is True
        service = (tmp_path / "pihealth-snapraid-sync.service").read_text()
        timer = (tmp_path / "pihealth-snapraid-sync.timer").read_text()
        assert "ExecStart=/usr/bin/snapraid sync" in service
        assert "ExecStart=/bin/sh" not in service
        assert "OnCalendar=Sun *-*-* 4:30:00" in timer


class TestSocketSecurity:
    @staticmethod
    def _decode_sent_response(conn):
        frame = conn.sendall.call_args.args[0]
        size = struct.unpack('!I', frame[:4])[0]
        return json.loads(frame[4:4 + size])

    def test_authorized_group_peer(self):
        conn = MagicMock()
        conn.getsockopt.return_value = struct.pack('3i', 123, 1000, 1000)
        with patch.object(helper, "_get_process_group_ids", return_value={1000, 1234}):
            authorized, credentials = helper._peer_is_authorized(conn, 1234)
        assert authorized is True
        assert credentials == (123, 1000, 1000)

    def test_framed_ping_over_unix_socket(self):
        conn = MagicMock()
        request = b'{"command":"ping","params":{}}'
        conn.recv.side_effect = [struct.pack('!I', len(request)), request]
        with patch.object(helper, "_peer_is_authorized", return_value=(True, (123, 1000, 1000))):
            helper._serve_connection(conn, 1234)
        assert self._decode_sent_response(conn)["success"] is True

    def test_unauthorized_peer_is_rejected_before_dispatch(self):
        conn = MagicMock()
        with patch.object(helper, "_peer_is_authorized", return_value=(False, (123, 1000, 1000))):
            with patch.object(helper, "handle_request") as handle_request:
                helper._serve_connection(conn, 1234)
        handle_request.assert_not_called()
        response = self._decode_sent_response(conn)
        assert response == {"success": False, "error": "Unauthorized helper peer"}

    def test_oversized_frame_is_rejected_before_dispatch(self):
        conn = MagicMock()
        conn.recv.return_value = struct.pack('!I', helper.MAX_MESSAGE_SIZE + 1)
        with patch.object(helper, "_peer_is_authorized", return_value=(True, (123, 1000, 1000))):
            with patch.object(helper, "handle_request") as handle_request:
                helper._serve_connection(conn, 1234)
        handle_request.assert_not_called()
        assert "Invalid request size" in self._decode_sent_response(conn)["error"]

    def test_truncated_frame_is_rejected_before_dispatch(self):
        conn = MagicMock()
        conn.recv.side_effect = [struct.pack('!I', 10), b"{}", b""]
        with patch.object(helper, "_peer_is_authorized", return_value=(True, (123, 1000, 1000))):
            with patch.object(helper, "handle_request") as handle_request:
                helper._serve_connection(conn, 1234)
        handle_request.assert_not_called()
        assert "Incomplete request frame" in self._decode_sent_response(conn)["error"]

    def test_timed_out_frame_is_rejected_before_dispatch(self):
        conn = MagicMock()
        conn.recv.side_effect = socket.timeout
        with patch.object(helper, "_peer_is_authorized", return_value=(True, (123, 1000, 1000))):
            with patch.object(helper, "handle_request") as handle_request:
                helper._serve_connection(conn, 1234)
        handle_request.assert_not_called()
        assert "Request frame timed out" in self._decode_sent_response(conn)["error"]

    def test_socket_permissions(self, tmp_path):
        socket_dir = tmp_path / "run"
        socket_dir.mkdir()
        socket_path = socket_dir / "helper.sock"
        socket_path.touch()
        with patch.object(helper.os, "chown") as chown:
            helper._secure_socket_directory(str(socket_dir), 1234)
            helper._secure_socket_file(str(socket_path), 1234)
        assert stat.S_IMODE(socket_dir.stat().st_mode) == 0o750
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660
        assert chown.call_count == 2


class TestNetworkInfo:
    @patch("pihealth_helper.run_command")
    def test_cmd_network_info_parses_interfaces(self, mock_run):
        mock_run.side_effect = [
            {
                "returncode": 0,
                "stdout": '[{"ifname":"eth0","operstate":"UP","address":"00:11",'
                          '"mtu":1500,"addr_info":[{"family":"inet","local":"192.168.1.2","prefixlen":24}]}]'
            },
            {
                "returncode": 0,
                "stdout": '[{"gateway":"192.168.1.1","dev":"eth0"}]'
            },
            {
                "returncode": 0,
                "stdout": "1.2.3.4"
            }
        ]

        with patch("builtins.open", mock_open(read_data="nameserver 8.8.8.8\n")):
            result = helper.cmd_network_info({})

        assert result["success"] is True
        assert result["interfaces"]
        assert result["default_gateway"]["ip"] == "192.168.1.1"
        assert "8.8.8.8" in result["dns_servers"]
