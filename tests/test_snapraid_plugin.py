"""Tests for SnapRAID plugin."""
import os
import json
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
                "uuid": "uuid-disk1",
                "role": "data",
                "content": True
            },
            {
                "id": "d2",
                "name": "d2",
                "path": "/mnt/disk2",
                "uuid": "uuid-disk2",
                "role": "data",
                "content": True
            },
            {
                "id": "parity1",
                "name": "parity",
                "path": "/mnt/parity",
                "uuid": "uuid-parity",
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

    @pytest.mark.parametrize("path", ["/mnt/pool", "/mnt/pool/media"])
    def test_mergerfs_pool_path_fails(self, snapraid_plugin, valid_config, path):
        with open(os.path.join(snapraid_plugin.config_dir, "mergerfs.json"), "w") as handle:
            json.dump({"pools": [{"mount_point": "/mnt/pool", "enabled": True}]}, handle)
        valid_config["drives"][0]["path"] = path

        errors = snapraid_plugin.validate_config(valid_config)

        assert any("MergerFS pool" in error and path in error for error in errors)

    def test_disabled_mergerfs_pool_path_still_fails(
        self, snapraid_plugin, valid_config
    ):
        with open(os.path.join(snapraid_plugin.config_dir, "mergerfs.json"), "w") as handle:
            json.dump(
                {"pools": [{"mount_point": "/mnt/pool", "enabled": False}]},
                handle,
            )
        valid_config["drives"][0]["path"] = "/mnt/pool/media"

        errors = snapraid_plugin.validate_config(valid_config)

        assert any("MergerFS pool" in error for error in errors)

    def test_malformed_mergerfs_config_fails_closed(
        self, snapraid_plugin, valid_config
    ):
        with open(os.path.join(snapraid_plugin.config_dir, "mergerfs.json"), "w") as handle:
            json.dump([], handle)

        errors = snapraid_plugin.validate_config(valid_config)

        assert any("Unable to validate MergerFS" in error for error in errors)

    def test_missing_drive_uuid_fails(self, snapraid_plugin, valid_config):
        valid_config["drives"][0].pop("uuid")

        errors = snapraid_plugin.validate_config(valid_config)

        assert any("UUID" in error and "/mnt/disk1" in error for error in errors)


def consume_command(generator):
    output = []
    while True:
        try:
            output.append(next(generator))
        except StopIteration as exc:
            return output, exc.value


class TestSnapRAIDSafetyPreflight:
    def test_mounted_sources_pass_with_expected_device_identity(
        self, snapraid_plugin, valid_config
    ):
        mounts = {
            "/mnt/disk1": {"source": "/dev/sda1", "device_id": "8:1"},
            "/mnt/disk2": {"source": "/dev/sdb1", "device_id": "8:17"},
            "/mnt/parity": {"source": "/dev/sdc1", "device_id": "8:33"},
        }
        identities = {
            "uuid-disk1": {"source": "/dev/sda1", "device_id": "8:1"},
            "uuid-disk2": {"source": "/dev/sdb1", "device_id": "8:17"},
            "uuid-parity": {"source": "/dev/sdc1", "device_id": "8:33"},
        }
        with patch.object(snapraid_plugin, "_read_mount_sources", return_value=mounts):
            with patch.object(
                snapraid_plugin,
                "_resolve_uuid_identity",
                side_effect=lambda uuid: identities.get(uuid),
            ):
                errors = snapraid_plugin._check_mounted_sources(valid_config)

        assert errors == []

    def test_mounted_sources_reject_missing_mount(self, snapraid_plugin, valid_config):
        with patch.object(snapraid_plugin, "_read_mount_sources", return_value={}):
            errors = snapraid_plugin._check_mounted_sources(valid_config)

        assert any("not a mounted source" in error and "/mnt/disk1" in error for error in errors)

    def test_mounted_sources_reject_wrong_uuid(self, snapraid_plugin, valid_config):
        mounts = {
            drive["path"]: {"source": f"/dev/{drive['id']}", "device_id": "8:1"}
            for drive in valid_config["drives"]
        }
        with patch.object(snapraid_plugin, "_read_mount_sources", return_value=mounts):
            with patch.object(
                snapraid_plugin,
                "_resolve_uuid_identity",
                return_value={"source": "/dev/expected", "device_id": "8:99"},
            ):
                errors = snapraid_plugin._check_mounted_sources(valid_config)

        assert any("device identity mismatch" in error for error in errors)

    def test_sync_fails_closed_when_diff_fails(self, snapraid_plugin):
        with patch.object(snapraid_plugin, "_check_mounted_sources", return_value=[]):
            with patch(
                "storage_plugins.snapraid_plugin.subprocess.run",
                return_value=MagicMock(returncode=1, stdout="", stderr="diff failed"),
            ):
                output, result = consume_command(
                    snapraid_plugin.run_command(
                        "sync",
                        {"force": True, "force_reason": "operator reviewed changes"},
                    )
                )

        assert result.success is False
        assert "diff failed" in result.error.lower()
        assert any("WARNING" in str(line) for line in output)

    def test_threshold_force_requires_reason(self, snapraid_plugin):
        diff_output = "51 removed\n0 updated\n"
        with patch.object(snapraid_plugin, "_check_mounted_sources", return_value=[]):
            with patch(
                "storage_plugins.snapraid_plugin.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=diff_output, stderr=""),
            ):
                _, result = consume_command(
                    snapraid_plugin.run_command("sync", {"force": True})
                )

        assert result.success is False
        assert "reason" in result.error.lower()

    def test_threshold_force_is_audited(self, snapraid_plugin):
        diff_output = "51 removed\n0 updated\n"
        with patch.object(snapraid_plugin, "_check_mounted_sources", return_value=[]):
            with patch(
                "storage_plugins.snapraid_plugin.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=diff_output, stderr=""),
            ):
                with patch("storage_plugins.snapraid_plugin.helper_available", return_value=True):
                    with patch(
                        "storage_plugins.snapraid_plugin.helper_call",
                        return_value={"success": True, "stdout": "", "stderr": ""},
                    ):
                        _, result = consume_command(
                            snapraid_plugin.run_command(
                                "sync",
                                {
                                    "force": True,
                                    "force_reason": "operator confirmed threshold override",
                                    "_audit_user": "admin",
                                },
                            )
                        )

        state = snapraid_plugin._load_state()
        assert result.success is True
        assert state["force_overrides"][-1]["username"] == "admin"
        assert state["force_overrides"][-1]["reason"] == "operator confirmed threshold override"

    def test_threshold_force_aborts_when_audit_cannot_be_saved(self, snapraid_plugin):
        diff_output = "51 removed\n0 updated\n"
        with patch.object(snapraid_plugin, "_check_mounted_sources", return_value=[]):
            with patch(
                "storage_plugins.snapraid_plugin.subprocess.run",
                return_value=MagicMock(returncode=0, stdout=diff_output, stderr=""),
            ):
                with patch.object(
                    snapraid_plugin, "_record_force_override", return_value=False
                ):
                    with patch(
                        "storage_plugins.snapraid_plugin.helper_call"
                    ) as helper_call:
                        _, result = consume_command(
                            snapraid_plugin.run_command(
                                "sync",
                                {
                                    "force": True,
                                    "force_reason": "operator confirmed threshold override",
                                },
                            )
                        )

        assert result.success is False
        assert "audit" in result.error.lower()
        helper_call.assert_not_called()


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
    def test_apply_schedule_uses_typed_helper_command(self, snapraid_plugin):
        config = snapraid_plugin.get_config()
        config["schedule"] = {
            "sync_enabled": True,
            "sync_cron": "30 4 * * 0",
            "scrub_enabled": False,
            "scrub_cron": "0 4 * * 0",
        }
        with patch("storage_plugins.snapraid_plugin.helper_available", return_value=True):
            with patch("storage_plugins.snapraid_plugin.helper_call", return_value={"success": True}) as helper_call:
                result = snapraid_plugin.apply_schedule(config)

        assert result.success is True
        configure_call = next(
            call for call in helper_call.call_args_list
            if call.args[0] == "configure_snapraid_schedule"
        )
        assert configure_call.args[1] == {
            "job_type": "sync",
            "cron": "30 4 * * 0",
        }
        assert "content" not in configure_call.args[1]
