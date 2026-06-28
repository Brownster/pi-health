"""Fail-closed dependency inspection for managed disk unmounts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class MountDependency:
    kind: str
    name: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.kind, "name": self.name, "path": self.path}

    def detail(self) -> str:
        return f"{self.kind}: {self.name} ({self.path})"


class DependencyInspectionError(RuntimeError):
    def __init__(self, details: list[str]):
        self.details = details
        super().__init__("; ".join(details))


def normalize_managed_mountpoint(path: str) -> str:
    """Normalize a mountpoint and ensure it cannot escape /mnt."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("Mountpoint must be an absolute path under /mnt/")
    normalized = os.path.normpath(path)
    if normalized == "/mnt" or os.path.commonpath([normalized, "/mnt"]) != "/mnt":
        raise ValueError("Mountpoint must be under /mnt/")
    resolved = os.path.realpath(normalized)
    if resolved == "/mnt" or os.path.commonpath([resolved, "/mnt"]) != "/mnt":
        raise ValueError("Mountpoint must resolve under /mnt/")
    return resolved


def _read_json_object(path: str, label: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Unable to read {label}: configuration must be an object")
    return payload


def _object_list(config: dict, key: str, label: str) -> list[dict]:
    values = config.get(key, [])
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        raise ValueError(f"Unable to read {label}: {key} must be a list of objects")
    return values


def _normalize_dependency_path(path: object, label: str) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise ValueError(f"Unable to read {label}: dependency path must be absolute")
    return os.path.realpath(os.path.normpath(path))


def _uses_mount(path: str, mountpoint: str) -> bool:
    try:
        return os.path.commonpath([path, mountpoint]) == mountpoint
    except ValueError:
        return False


def _container_dependencies(docker_client, mountpoint: str) -> list[MountDependency]:
    if docker_client is None:
        raise ValueError("Docker service unavailable")
    try:
        containers = docker_client.containers.list(all=True)
    except Exception as exc:
        raise ValueError(f"Unable to inspect containers: {exc}") from exc

    dependencies = []
    for container in containers:
        try:
            attrs = container.attrs
            mounts = attrs.get("Mounts") if isinstance(attrs, dict) else None
            if not isinstance(mounts, list):
                raise ValueError("mount metadata is unavailable")
            name = str(getattr(container, "name", "") or attrs.get("Name", "unknown")).lstrip("/")
            for mount in mounts:
                if not isinstance(mount, dict):
                    raise ValueError("mount metadata is malformed")
                source = mount.get("Source")
                if not isinstance(source, str) or not os.path.isabs(source):
                    continue
                normalized = os.path.realpath(os.path.normpath(source))
                if _uses_mount(normalized, mountpoint):
                    dependencies.append(MountDependency("container", name, normalized))
        except ValueError as exc:
            name = str(getattr(container, "name", "unknown"))
            raise ValueError(f"Unable to inspect container {name}: {exc}") from exc
        except Exception as exc:
            name = str(getattr(container, "name", "unknown"))
            raise ValueError(f"Unable to inspect container {name}: {exc}") from exc
    return dependencies


def _media_dependencies(
    config_path: str,
    defaults: dict[str, str],
    mountpoint: str,
) -> list[MountDependency]:
    config = {**defaults, **_read_json_object(config_path, "media paths configuration")}
    dependencies = []
    for name in ("downloads", "storage", "backup", "config"):
        if name not in config:
            continue
        path = _normalize_dependency_path(config[name], f"media path {name}")
        if _uses_mount(path, mountpoint):
            dependencies.append(MountDependency("media_path", name, path))
    return dependencies


def _share_dependencies(config_dir: str, mountpoint: str) -> list[MountDependency]:
    path = os.path.join(config_dir, "samba.json")
    shares = _object_list(_read_json_object(path, "Samba configuration"), "shares", "Samba configuration")
    dependencies = []
    for share in shares:
        name = str(share.get("name") or "unnamed")
        source = _normalize_dependency_path(share.get("path"), f"Samba share {name}")
        if _uses_mount(source, mountpoint):
            dependencies.append(MountDependency("share", name, source))
    return dependencies


def _mergerfs_dependencies(config_dir: str, mountpoint: str) -> list[MountDependency]:
    path = os.path.join(config_dir, "mergerfs.json")
    pools = _object_list(
        _read_json_object(path, "MergerFS configuration"),
        "pools",
        "MergerFS configuration",
    )
    dependencies = []
    for pool in pools:
        name = str(pool.get("name") or "unnamed")
        branches = pool.get("branches", [])
        if not isinstance(branches, list):
            raise ValueError(f"Unable to read MergerFS pool {name}: branches must be a list")
        for branch in branches:
            source = _normalize_dependency_path(branch, f"MergerFS pool {name}")
            if _uses_mount(source, mountpoint):
                dependencies.append(MountDependency("mergerfs_branch", name, source))
        pool_mount = _normalize_dependency_path(pool.get("mount_point"), f"MergerFS pool {name}")
        if _uses_mount(pool_mount, mountpoint):
            dependencies.append(MountDependency("mergerfs_pool", name, pool_mount))
    return dependencies


def _snapraid_dependencies(config_dir: str, mountpoint: str) -> list[MountDependency]:
    path = os.path.join(config_dir, "snapraid.json")
    drives = _object_list(
        _read_json_object(path, "SnapRAID configuration"),
        "drives",
        "SnapRAID configuration",
    )
    dependencies = []
    for drive in drives:
        name = str(drive.get("name") or drive.get("role") or "unnamed")
        source = _normalize_dependency_path(drive.get("path"), f"SnapRAID drive {name}")
        if _uses_mount(source, mountpoint):
            dependencies.append(MountDependency("snapraid", name, source))
    return dependencies


def find_mount_dependencies(
    mountpoint: str,
    *,
    docker_client,
    media_paths_config: str,
    storage_plugin_config_dir: str,
    default_media_paths: dict[str, str] | None = None,
) -> list[MountDependency]:
    """Return every configured consumer below a mountpoint, or fail closed."""
    normalized_mountpoint = normalize_managed_mountpoint(mountpoint)
    defaults = default_media_paths or {}
    dependencies = []
    errors = []
    inspectors = (
        lambda: _container_dependencies(docker_client, normalized_mountpoint),
        lambda: _media_dependencies(media_paths_config, defaults, normalized_mountpoint),
        lambda: _share_dependencies(storage_plugin_config_dir, normalized_mountpoint),
        lambda: _mergerfs_dependencies(storage_plugin_config_dir, normalized_mountpoint),
        lambda: _snapraid_dependencies(storage_plugin_config_dir, normalized_mountpoint),
    )
    for inspect in inspectors:
        try:
            dependencies.extend(inspect())
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise DependencyInspectionError(errors)
    return sorted(set(dependencies))
