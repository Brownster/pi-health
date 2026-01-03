"""Tests for SnapRAID plugin."""
import os
import shutil
import tempfile
import sys

import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.snapraid_plugin import SnapRAIDPlugin


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def snapraid_plugin(temp_config_dir):
    return SnapRAIDPlugin(temp_config_dir)


@pytest.fixture
def valid_config():
    return {
        "enabled": True,
        "drives": [
            {
                "id": "d1",
                "name": "d1",
                "path": "/mnt/disk1",
                "role": "data",
                "content": True
            },
            {
                "id": "d2",
                "name": "d2",
                "path": "/mnt/disk2",
                "role": "data",
                "content": True
            },
            {
                "id": "parity1",
                "name": "parity",
                "path": "/mnt/parity",
                "role": "parity",
                "parity_level": 1,
                "content": False
            }
        ],
        "excludes": ["*.tmp", "/lost+found/"],
        "settings": {
            "blocksize": 256,
            "prehash": True
        }
    }


class TestSnapRAIDValidation:
    def test_valid_config_passes(self, snapraid_plugin, valid_config):
        errors = snapraid_plugin.validate_config(valid_config)
        assert errors == []

    def test_empty_drives_fails(self, snapraid_plugin):
        errors = snapraid_plugin.validate_config({"drives": []})
        assert len(errors) > 0
        assert any("drive" in e.lower() for e in errors)

    def test_no_data_drive_fails(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity", "content": True}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("data drive" in e.lower() for e in errors)

    def test_no_parity_drive_fails(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": True}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("parity drive" in e.lower() for e in errors)

    def test_no_content_drive_fails(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": False},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity", "content": False}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("content" in e.lower() for e in errors)

    def test_duplicate_names_fails(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "d1", "name": "disk", "path": "/mnt/disk1", "role": "data", "content": True},
                {"id": "d2", "name": "disk", "path": "/mnt/disk2", "role": "data", "content": True},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity"}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("unique" in e.lower() for e in errors)

    def test_invalid_path_fails(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/home/data", "role": "data", "content": True},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity"}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("/mnt" in e for e in errors)


class TestSnapRAIDConfigGeneration:
    def test_generate_basic_config(self, snapraid_plugin, valid_config):
        content = snapraid_plugin._generate_config(valid_config)

        assert "parity /mnt/parity/snapraid.parity" in content
        assert "data d1 /mnt/disk1" in content
        assert "data d2 /mnt/disk2" in content
        assert "content /mnt/disk1/snapraid.content" in content
        assert "exclude *.tmp" in content

    def test_generate_multi_parity_config(self, snapraid_plugin):
        config = {
            "drives": [
                {"id": "p1", "name": "parity", "path": "/mnt/parity1", "role": "parity", "parity_level": 1},
                {"id": "p2", "name": "parity2", "path": "/mnt/parity2", "role": "parity", "parity_level": 2},
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": True}
            ],
            "excludes": []
        }

        content = snapraid_plugin._generate_config(config)

        assert "parity /mnt/parity1/snapraid.parity" in content
        assert "2-parity /mnt/parity2/snapraid.2-parity" in content


class TestSnapRAIDRecoveryStatus:
    def test_recovery_status_no_issues(self, snapraid_plugin):
        with patch("storage_plugins.snapraid_plugin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="No error detected\n", stderr="")
            status = snapraid_plugin.get_recovery_status()

        assert status["recoverable"] is True
        assert status["missing_files"] == 0
        assert status["damaged_files"] == 0
        assert status["recovery_options"] == []

    def test_recovery_status_missing_and_damaged(self, snapraid_plugin):
        output = "Missing file 3\nDamaged file 2\nMissing disk d1\n"
        with patch("storage_plugins.snapraid_plugin.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=output, stderr="")
            status = snapraid_plugin.get_recovery_status()

        assert status["missing_files"] == 3
        assert status["damaged_files"] == 2
        assert "d1" in status["failed_drives"]
        assert any(opt["id"] == "fix_missing" for opt in status["recovery_options"])
        assert any(opt["id"] == "fix_damaged" for opt in status["recovery_options"])

    def test_recovery_status_uses_helper(self, snapraid_plugin):
        output = "Missing file 1\n"
        with patch("storage_plugins.snapraid_plugin.helper_available", return_value=True):
            with patch("storage_plugins.snapraid_plugin.helper_call") as mock_call:
                mock_call.return_value = {"success": True, "stdout": output, "stderr": ""}
                status = snapraid_plugin.get_recovery_status()

        assert status["missing_files"] == 1


class TestSnapRAIDScheduling:
    def test_cron_to_oncalendar_daily(self, snapraid_plugin):
        assert snapraid_plugin._cron_to_oncalendar("0 3 * * *") == "*-*-* 3:0:00"

    def test_cron_to_oncalendar_weekly(self, snapraid_plugin):
        assert snapraid_plugin._cron_to_oncalendar("30 4 * * 0") == "Sun *-*-* 4:30:00"

    def test_generate_systemd_timer(self, snapraid_plugin):
        service, timer = snapraid_plugin.generate_systemd_timer("sync")
        assert "ExecStart=/usr/bin/snapraid sync" in service
        assert "OnCalendar=" in timer
