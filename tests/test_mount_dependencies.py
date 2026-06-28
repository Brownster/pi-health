import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mount_dependencies import (
    DependencyInspectionError,
    find_mount_dependencies,
    normalize_managed_mountpoint,
)


class FakeContainer:
    def __init__(self, name, mounts):
        self.name = name
        self.attrs = {"Mounts": mounts}


class FakeContainers:
    def __init__(self, containers):
        self._containers = containers

    def list(self, all=False):
        assert all is True
        return self._containers


class FakeDockerClient:
    def __init__(self, containers):
        self.containers = FakeContainers(containers)


def _write_json(path, payload):
    path.write_text(json.dumps(payload))


def test_find_mount_dependencies_covers_all_consumers(tmp_path):
    media_config = tmp_path / "media_paths.json"
    plugin_dir = tmp_path / "storage_plugins"
    plugin_dir.mkdir()
    _write_json(
        media_config,
        {
            "downloads": "/mnt/storage/downloads",
            "storage": "/mnt/elsewhere",
            "backup": "/mnt/backup",
            "config": "/srv/config",
        },
    )
    _write_json(
        plugin_dir / "samba.json",
        {
            "shares": [
                {"name": "media", "path": "/mnt/storage/shared", "enabled": True},
                {"name": "disabled", "path": "/mnt/storage/disabled", "enabled": False},
            ]
        },
    )
    _write_json(
        plugin_dir / "mergerfs.json",
        {
            "pools": [
                {
                    "name": "archive",
                    "branches": ["/mnt/storage/disk1", "/mnt/other"],
                    "mount_point": "/mnt/pool",
                    "enabled": True,
                }
            ]
        },
    )
    _write_json(
        plugin_dir / "snapraid.json",
        {"drives": [{"name": "data1", "path": "/mnt/storage/disk1", "role": "data"}]},
    )
    docker_client = FakeDockerClient(
        [
            FakeContainer(
                "jellyfin",
                [{"Type": "bind", "Source": "/mnt/storage/media", "Destination": "/media"}],
            )
        ]
    )

    dependencies = find_mount_dependencies(
        "/mnt/storage",
        docker_client=docker_client,
        media_paths_config=str(media_config),
        storage_plugin_config_dir=str(plugin_dir),
    )

    assert {(item.kind, item.name, item.path) for item in dependencies} == {
        ("container", "jellyfin", "/mnt/storage/media"),
        ("media_path", "downloads", "/mnt/storage/downloads"),
        ("mergerfs_branch", "archive", "/mnt/storage/disk1"),
        ("share", "disabled", "/mnt/storage/disabled"),
        ("share", "media", "/mnt/storage/shared"),
        ("snapraid", "data1", "/mnt/storage/disk1"),
    }


def test_find_mount_dependencies_protects_mergerfs_pool_mount(tmp_path):
    plugin_dir = tmp_path / "storage_plugins"
    plugin_dir.mkdir()
    _write_json(
        plugin_dir / "mergerfs.json",
        {
            "pools": [
                {
                    "name": "archive",
                    "branches": ["/mnt/disk1", "/mnt/disk2"],
                    "mount_point": "/mnt/pool",
                }
            ]
        },
    )

    dependencies = find_mount_dependencies(
        "/mnt/pool",
        docker_client=FakeDockerClient([]),
        media_paths_config=str(tmp_path / "missing-media-paths.json"),
        storage_plugin_config_dir=str(plugin_dir),
        default_media_paths={"storage": "/mnt/storage"},
    )

    assert [(item.kind, item.name, item.path) for item in dependencies] == [
        ("mergerfs_pool", "archive", "/mnt/pool")
    ]


@pytest.mark.parametrize("filename", ["media_paths.json", "storage_plugins/snapraid.json"])
def test_find_mount_dependencies_fails_closed_on_malformed_config(tmp_path, filename):
    config_path = tmp_path / filename
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{not-json")

    with pytest.raises(DependencyInspectionError, match="Unable to read"):
        find_mount_dependencies(
            "/mnt/storage",
            docker_client=FakeDockerClient([]),
            media_paths_config=str(tmp_path / "media_paths.json"),
            storage_plugin_config_dir=str(tmp_path / "storage_plugins"),
        )


def test_find_mount_dependencies_fails_closed_without_docker(tmp_path):
    with pytest.raises(DependencyInspectionError, match="Docker service unavailable"):
        find_mount_dependencies(
            "/mnt/storage",
            docker_client=None,
            media_paths_config=str(tmp_path / "media_paths.json"),
            storage_plugin_config_dir=str(tmp_path / "storage_plugins"),
        )


def test_normalize_managed_mountpoint_rejects_path_escape():
    with pytest.raises(ValueError, match="under /mnt"):
        normalize_managed_mountpoint("/mnt/../etc")
