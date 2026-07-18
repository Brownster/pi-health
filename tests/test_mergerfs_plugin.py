"""Tests for MergerFS plugin."""
import os
import shutil
import subprocess
import tempfile
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.mergerfs_plugin import MergerFSPlugin


def consume_command(generator):
    output = []
    while True:
        try:
            output.append(next(generator))
        except StopIteration as exc:
            return output, exc.value


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mergerfs_plugin(temp_config_dir):
    return MergerFSPlugin(temp_config_dir)

@pytest.fixture(autouse=True)
def mock_mnt_paths(monkeypatch):
    real_exists = os.path.exists
    real_isdir = os.path.isdir

    def fake_exists(path):
        path_str = os.fspath(path)
        if path_str.startswith("/mnt/"):
            return True
        return real_exists(path)

    def fake_isdir(path):
        path_str = os.fspath(path)
        if path_str.startswith("/mnt/"):
            return True
        return real_isdir(path)

    monkeypatch.setattr(os.path, "exists", fake_exists)
    monkeypatch.setattr(os.path, "isdir", fake_isdir)


@pytest.fixture
def valid_config():
    return {
        "pools": [
            {
                "id": "pool1",
                "name": "storage",
                "branches": ["/mnt/disk1", "/mnt/disk2", "/mnt/disk3"],
                "mount_point": "/mnt/storage",
                "create_policy": "epmfs",
                "min_free_space": "4G",
                "enabled": True
            }
        ]
    }


class TestMergerFSValidation:
    def test_valid_config_passes(self, mergerfs_plugin, valid_config):
        errors = mergerfs_plugin.validate_config(valid_config)
        assert errors == []

    def test_empty_pools_passes(self, mergerfs_plugin):
        errors = mergerfs_plugin.validate_config({"pools": []})
        assert errors == []

    def test_duplicate_pool_names_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/s1"},
                {"id": "p2", "name": "storage", "branches": ["/mnt/d3", "/mnt/d4"], "mount_point": "/mnt/s2"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("duplicate" in e.lower() for e in errors)

    def test_insufficient_branches_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1"], "mount_point": "/mnt/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("2 branches" in e for e in errors)

    def test_duplicate_mount_points_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "pool1", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/storage"},
                {"id": "p2", "name": "pool2", "branches": ["/mnt/d3", "/mnt/d4"], "mount_point": "/mnt/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("mount point" in e.lower() for e in errors)

    def test_overlapping_branches_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "pool1", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/s1"},
                {"id": "p2", "name": "pool2", "branches": ["/mnt/d2", "/mnt/d3"], "mount_point": "/mnt/s2"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("multiple pools" in e.lower() for e in errors)

    def test_invalid_mount_path_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/home/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("/mnt" in e for e in errors)

    def test_invalid_policy_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"],
                 "mount_point": "/mnt/storage", "create_policy": "invalid_policy"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("policy" in e.lower() for e in errors)

    def test_invalid_min_free_space_fails(self, mergerfs_plugin):
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"],
                 "mount_point": "/mnt/storage", "min_free_space": "4Z"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("min_free_space" in e for e in errors)

    def test_branch_must_exist_fails(self, mergerfs_plugin, monkeypatch):
        def fake_exists(path):
            if path == "/mnt/missing":
                return False
            return path.startswith("/mnt/")

        monkeypatch.setattr(os.path, "exists", fake_exists)
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/missing", "/mnt/d2"],
                 "mount_point": "/mnt/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("not found" in e.lower() for e in errors)


class TestMergerFSFstabGeneration:
    def test_generate_basic_fstab(self, mergerfs_plugin, valid_config):
        pool = valid_config["pools"][0]
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "/mnt/disk1:/mnt/disk2:/mnt/disk3" in entry
        assert "/mnt/storage" in entry
        assert "fuse.mergerfs" in entry
        assert "category.create=epmfs" in entry

    def test_fstab_includes_min_free_space(self, mergerfs_plugin, valid_config):
        pool = valid_config["pools"][0]
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "minfreespace=4G" in entry

    def test_fstab_with_custom_policy(self, mergerfs_plugin):
        pool = {
            "name": "test",
            "branches": ["/mnt/d1", "/mnt/d2"],
            "mount_point": "/mnt/test",
            "create_policy": "lfs",
            "min_free_space": "1G"
        }
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "category.create=lfs" in entry

    def test_preset_defaults_applied(self, mergerfs_plugin):
        pool = {
            "name": "test",
            "branches": ["/mnt/d1", "/mnt/d2"],
            "mount_point": "/mnt/test",
            "preset": "linux_6_6_plus",
            "create_policy": "epmfs",
            "min_free_space": "1G"
        }
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "func.getattr=newest" in entry
        assert "dropcacheonclose=false" in entry

    def test_options_override_defaults(self, mergerfs_plugin):
        pool = {
            "name": "test",
            "branches": ["/mnt/d1", "/mnt/d2"],
            "mount_point": "/mnt/test",
            "create_policy": "epmfs",
            "min_free_space": "1G",
            "options": "category.create=lus,cache.files=auto-full"
        }
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "category.create=lus" in entry
        assert "cache.files=auto-full" in entry


class TestMergerFSStatus:
    def test_unconfigured_status(self, mergerfs_plugin):
        status = mergerfs_plugin.get_status()
        assert status["status"] == "unconfigured"

    def test_status_with_pools(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)

        with patch("os.path.ismount", return_value=True):
            with patch("os.statvfs") as mock_statvfs:
                mock_statvfs.return_value = MagicMock(
                    f_blocks=1000000,
                    f_bavail=500000,
                    f_frsize=4096
                )
                status = mergerfs_plugin.get_status()

        assert status["status"] == "healthy"
        assert len(status["details"]["pools"]) == 1


class TestMergerFSCommands:
    def test_status_command(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)
        outputs = list(mergerfs_plugin.run_command("status"))
        assert any("Pool" in line for line in outputs)

    def test_mount_helper_failure_returns_failed_result(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)
        with patch("storage_plugins.mergerfs_plugin.os.path.ismount", return_value=False):
            with patch("storage_plugins.mergerfs_plugin.helper_available", return_value=True):
                with patch(
                    "storage_plugins.mergerfs_plugin.helper_call",
                    return_value={"success": False, "error": "helper mount failed"},
                ):
                    output, result = consume_command(
                        mergerfs_plugin.run_command("mount", {"pool_name": "storage"})
                    )
        assert result.success is False
        assert "helper mount failed" in result.error
        assert any("helper mount failed" in line for line in output)

    def test_mount_nonzero_exit_returns_failed_result(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)
        process_result = MagicMock(returncode=1, stdout="", stderr="invalid option")
        with patch("storage_plugins.mergerfs_plugin.os.path.ismount", return_value=False):
            with patch("storage_plugins.mergerfs_plugin.helper_available", return_value=False):
                with patch("storage_plugins.mergerfs_plugin.subprocess.run", return_value=process_result):
                    _, result = consume_command(
                        mergerfs_plugin.run_command("mount", {"pool_name": "storage"})
                    )
        assert result.success is False
        assert "invalid option" in result.error

    def test_unmount_timeout_returns_failed_result(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)
        timeout = subprocess.TimeoutExpired(["umount", "/mnt/storage"], 60)
        with patch("storage_plugins.mergerfs_plugin.os.path.ismount", return_value=True):
            with patch("storage_plugins.mergerfs_plugin.helper_available", return_value=False):
                with patch("storage_plugins.mergerfs_plugin.subprocess.run", side_effect=timeout):
                    _, result = consume_command(
                        mergerfs_plugin.run_command("unmount", {"pool_name": "storage"})
                    )
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_balance_missing_binary_returns_failed_result(self, mergerfs_plugin, valid_config):
        mergerfs_plugin.set_config(valid_config)
        with patch("storage_plugins.mergerfs_plugin.subprocess.run", side_effect=FileNotFoundError):
            _, result = consume_command(
                mergerfs_plugin.run_command("balance", {"pool_name": "storage"})
            )
        assert result.success is False
        assert "not found" in result.error.lower()


class TestMergerFSApplyConfig:
    def test_preview_config_renders_managed_section_without_writing(
        self, mergerfs_plugin, valid_config
    ):
        preview = mergerfs_plugin.preview_config(valid_config)

        assert "# pi-health mergerfs start" in preview
        assert "/mnt/disk1:/mnt/disk2:/mnt/disk3" in preview
        assert "category.create=epmfs" in preview
        assert not os.path.exists(mergerfs_plugin.config_path)

    def test_preview_config_rejects_invalid_candidate(
        self, mergerfs_plugin, valid_config
    ):
        invalid = dict(valid_config)
        invalid["pools"] = [dict(valid_config["pools"][0], branches=["/mnt/disk1"])]

        with pytest.raises(ValueError, match="at least 2 branches"):
            mergerfs_plugin.preview_config(invalid)

    def test_preview_config_explains_empty_managed_section(self, mergerfs_plugin):
        preview = mergerfs_plugin.preview_config({"pools": []})

        assert "managed fstab section will be removed" in preview

    def test_apply_config_writes_fstab_section(self, mergerfs_plugin, valid_config, tmp_path, monkeypatch):
        fstab_path = tmp_path / "fstab"
        fstab_path.write_text("UUID=abc /mnt/data ext4 defaults 0 2\n")
        monkeypatch.setattr(mergerfs_plugin, "FSTAB_PATH", str(fstab_path))
        mergerfs_plugin.set_config(valid_config)

        with patch("storage_plugins.mergerfs_plugin.helper_available", return_value=False):
            result = mergerfs_plugin.apply_config()

        assert result.success is True
        content = fstab_path.read_text()
        assert "# pi-health mergerfs start" in content
        assert "fuse.mergerfs" in content

    def test_apply_config_removes_section_when_disabled(self, mergerfs_plugin, valid_config, tmp_path, monkeypatch):
        fstab_path = tmp_path / "fstab"
        fstab_path.write_text(
            "UUID=abc /mnt/data ext4 defaults 0 2\n"
            "# pi-health mergerfs start\n"
            "# mergerfs pool: storage\n"
            "/mnt/a:/mnt/b /mnt/storage fuse.mergerfs defaults 0 0\n"
            "# pi-health mergerfs end\n"
        )
        monkeypatch.setattr(mergerfs_plugin, "FSTAB_PATH", str(fstab_path))
        disabled = dict(valid_config)
        disabled["pools"] = [dict(valid_config["pools"][0], enabled=False)]
        mergerfs_plugin.set_config(disabled)

        with patch("storage_plugins.mergerfs_plugin.helper_available", return_value=False):
            result = mergerfs_plugin.apply_config()

        assert result.success is True
        content = fstab_path.read_text()
        assert "# pi-health mergerfs start" not in content
        assert "fuse.mergerfs" not in content


class TestPoolSurfacePH4001:
    """PH4-001 additive surface: pool kind + param schema for pool commands."""

    def test_plugin_kind_is_pool(self, mergerfs_plugin):
        assert mergerfs_plugin.PLUGIN_KIND == "pool"

    def test_pool_commands_declare_pool_name_param_schema(self, mergerfs_plugin):
        commands = {c["id"]: c for c in mergerfs_plugin.get_commands()}
        for command_id in ("mount", "unmount", "balance"):
            schema = commands[command_id]["param_schema"]
            assert schema[0]["name"] == "pool_name"
            assert schema[0]["type"] == "select"
            assert schema[0]["source"] == "status.details.pools[].name"

    def test_unmount_is_flagged_dangerous(self, mergerfs_plugin):
        commands = {c["id"]: c for c in mergerfs_plugin.get_commands()}
        assert commands["unmount"]["dangerous"] is True
