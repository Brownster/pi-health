"""Tests for MergerFS plugin."""
import os
import shutil
import tempfile
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.mergerfs_plugin import MergerFSPlugin, POLICIES


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mergerfs_plugin(temp_config_dir):
    return MergerFSPlugin(temp_config_dir)


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
