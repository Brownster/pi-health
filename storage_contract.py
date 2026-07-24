"""Pure, versioned storage contract for guided media-stack onboarding."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from typing import Any

from fstab_presets import FSTAB_PRESETS


SCHEMA_VERSION = "1"
STORAGE_PROFILES = frozenset(
    {"single_disk", "separate_downloads", "protected_pool"}
)
DEVICE_ROLES = frozenset({"data", "downloads", "parity", "config_backup"})
SUPPORTED_FILESYSTEMS = frozenset(FSTAB_PRESETS)
MAX_DEVICES = 32

MEDIA_CONTAINER_PATH = "/data/media"
DOWNLOADS_CONTAINER_PATH = "/data/downloads"
CONFIG_CONTAINER_PATH = "/config"

DEFAULT_MEDIA_HOST_PATH = "/mnt/storage/media"
DEFAULT_DOWNLOADS_HOST_PATH = "/mnt/downloads"
DEFAULT_CONFIG_HOST_PATH = "/var/lib/limeos/apps"
DEFAULT_BACKUP_HOST_PATH = "/mnt/backup/limeos"

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SAFE_UUID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class StorageContractError(ValueError):
    """Raised when persisted onboarding storage data violates the contract."""


@dataclass(frozen=True)
class MediaIdentity:
    """Numeric ownership used by media containers and provisioned content."""

    uid: int
    gid: int


@dataclass(frozen=True)
class StorageLocations:
    """Stable host endpoints and their fixed managed-container paths."""

    media_host: str
    downloads_host: str
    application_config_host: str
    backup_host: str
    media_container: str = MEDIA_CONTAINER_PATH
    downloads_container: str = DOWNLOADS_CONTAINER_PATH
    config_container: str = CONFIG_CONTAINER_PATH


@dataclass(frozen=True)
class StorageDevice:
    """One filesystem assignment identified independently of its kernel name."""

    id: str
    role: str
    filesystem_uuid: str
    filesystem: str
    mountpoint: str
    serial: str | None = None


@dataclass(frozen=True)
class StorageContract:
    """Validated storage configuration shared by onboarding consumers."""

    schema_version: str
    profile: str
    media_identity: MediaIdentity
    locations: StorageLocations
    devices: tuple[StorageDevice, ...]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["devices"] = []
        for device in self.devices:
            serialized = asdict(device)
            if serialized["serial"] is None:
                serialized.pop("serial")
            value["devices"].append(serialized)
        return value


def parse_storage_contract(raw: object) -> StorageContract:
    """Validate and model one storage contract without filesystem access."""
    if not isinstance(raw, dict):
        raise StorageContractError("storage contract must be an object")
    _reject_unknown(
        raw,
        {"schema_version", "profile", "media_identity", "locations", "devices"},
        "storage contract",
    )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise StorageContractError("unsupported storage contract schema version")

    profile = raw.get("profile")
    if profile not in STORAGE_PROFILES:
        raise StorageContractError(f"unsupported storage profile: {profile!r}")

    identity = _parse_identity(raw.get("media_identity"))
    locations = _parse_locations(raw.get("locations"))
    devices = _parse_devices(raw.get("devices"))
    _validate_profile(profile, locations, devices)
    return StorageContract(
        schema_version=SCHEMA_VERSION,
        profile=profile,
        media_identity=identity,
        locations=locations,
        devices=devices,
    )


def _parse_identity(raw: object) -> MediaIdentity:
    if not isinstance(raw, dict):
        raise StorageContractError("media_identity must be an object")
    _reject_unknown(raw, {"uid", "gid"}, "media_identity")
    uid = raw.get("uid")
    gid = raw.get("gid")
    if not _is_unprivileged_id(uid):
        raise StorageContractError("media_identity.uid must be an unprivileged numeric ID")
    if not _is_unprivileged_id(gid):
        raise StorageContractError("media_identity.gid must be an unprivileged numeric ID")
    return MediaIdentity(uid=uid, gid=gid)


def _parse_locations(raw: object) -> StorageLocations:
    if not isinstance(raw, dict):
        raise StorageContractError("locations must be an object")
    allowed = {
        "media_host",
        "downloads_host",
        "application_config_host",
        "backup_host",
        "media_container",
        "downloads_container",
        "config_container",
    }
    _reject_unknown(raw, allowed, "locations")
    required = allowed
    missing = sorted(required - set(raw))
    if missing:
        raise StorageContractError(f"locations is missing fields: {missing}")

    media_host = _canonical_path(raw["media_host"], "locations.media_host", under_mnt=True)
    downloads_host = _canonical_path(
        raw["downloads_host"], "locations.downloads_host", under_mnt=True
    )
    config_host = _canonical_path(
        raw["application_config_host"],
        "locations.application_config_host",
        under_mnt=False,
    )
    backup_host = _canonical_path(
        raw["backup_host"], "locations.backup_host", under_mnt=True
    )

    constants = {
        "media_container": MEDIA_CONTAINER_PATH,
        "downloads_container": DOWNLOADS_CONTAINER_PATH,
        "config_container": CONFIG_CONTAINER_PATH,
    }
    for key, expected in constants.items():
        if raw.get(key) != expected:
            raise StorageContractError(f"locations.{key} must be {expected}")

    return StorageLocations(
        media_host=media_host,
        downloads_host=downloads_host,
        application_config_host=config_host,
        backup_host=backup_host,
    )


def _parse_devices(raw: object) -> tuple[StorageDevice, ...]:
    if not isinstance(raw, list) or not raw:
        raise StorageContractError("devices must be a non-empty list")
    if len(raw) > MAX_DEVICES:
        raise StorageContractError(f"devices cannot contain more than {MAX_DEVICES} entries")

    devices = tuple(_parse_device(item, index) for index, item in enumerate(raw))
    _reject_duplicates(devices, "id", "device IDs")
    _reject_duplicates(devices, "filesystem_uuid", "filesystem UUIDs")
    _reject_duplicates(devices, "mountpoint", "device mountpoints")
    return devices


def _parse_device(raw: object, index: int) -> StorageDevice:
    if not isinstance(raw, dict):
        raise StorageContractError(f"devices[{index}] must be an object")
    allowed = {"id", "role", "filesystem_uuid", "filesystem", "mountpoint", "serial"}
    _reject_unknown(raw, allowed, f"devices[{index}]")
    missing = sorted((allowed - {"serial"}) - set(raw))
    if missing:
        raise StorageContractError(f"devices[{index}] is missing fields: {missing}")

    device_id = raw["id"]
    if not isinstance(device_id, str) or not _SAFE_ID.fullmatch(device_id):
        raise StorageContractError(f"devices[{index}].id is invalid")
    role = raw["role"]
    if role not in DEVICE_ROLES:
        raise StorageContractError(f"devices[{index}].role is invalid")
    filesystem_uuid = raw["filesystem_uuid"]
    if not isinstance(filesystem_uuid, str) or not _SAFE_UUID.fullmatch(
        filesystem_uuid
    ):
        raise StorageContractError(f"devices[{index}].filesystem_uuid is invalid")
    filesystem = raw["filesystem"]
    if filesystem not in SUPPORTED_FILESYSTEMS:
        raise StorageContractError(f"devices[{index}].filesystem is unsupported")
    mountpoint = _canonical_path(
        raw["mountpoint"], f"devices[{index}].mountpoint", under_mnt=True
    )
    serial = raw.get("serial")
    if serial is not None:
        if (
            not isinstance(serial, str)
            or not serial.strip()
            or serial != serial.strip()
            or len(serial) > 128
            or any(ord(character) < 32 for character in serial)
        ):
            raise StorageContractError(f"devices[{index}].serial is invalid")

    return StorageDevice(
        id=device_id,
        role=role,
        filesystem_uuid=filesystem_uuid,
        filesystem=filesystem,
        mountpoint=mountpoint,
        serial=serial,
    )


def _validate_profile(
    profile: str,
    locations: StorageLocations,
    devices: tuple[StorageDevice, ...],
) -> None:
    by_role = {
        role: tuple(device for device in devices if device.role == role)
        for role in DEVICE_ROLES
    }
    if len(by_role["config_backup"]) > 1:
        raise StorageContractError("only one configuration backup device is supported")

    if profile == "single_disk":
        _require_role_count(by_role, data=1, downloads=0, parity=0)
        data_mount = by_role["data"][0].mountpoint
        _require_descendant(locations.media_host, data_mount, "media_host")
        _require_descendant(locations.downloads_host, data_mount, "downloads_host")
    elif profile == "separate_downloads":
        _require_role_count(by_role, data=1, downloads=1, parity=0)
        _require_descendant(
            locations.media_host,
            by_role["data"][0].mountpoint,
            "media_host",
            allow_root=True,
        )
        _require_descendant(
            locations.downloads_host,
            by_role["downloads"][0].mountpoint,
            "downloads_host",
            allow_root=True,
        )
    else:
        if not by_role["data"] or not by_role["parity"]:
            raise StorageContractError(
                "protected_pool requires at least one data and one parity device"
            )
        if len(by_role["downloads"]) > 1:
            raise StorageContractError(
                "protected_pool supports at most one downloads device"
            )
        _require_descendant(locations.media_host, "/mnt/storage", "media_host")
        if by_role["downloads"]:
            _require_descendant(
                locations.downloads_host,
                by_role["downloads"][0].mountpoint,
                "downloads_host",
                allow_root=True,
            )
        else:
            _require_descendant(
                locations.downloads_host, "/mnt/storage", "downloads_host"
            )

    if by_role["config_backup"]:
        _require_descendant(
            locations.backup_host,
            by_role["config_backup"][0].mountpoint,
            "backup_host",
        )


def _require_role_count(
    by_role: dict[str, tuple[StorageDevice, ...]],
    *,
    data: int,
    downloads: int,
    parity: int,
) -> None:
    expected = {"data": data, "downloads": downloads, "parity": parity}
    for role, count in expected.items():
        if len(by_role[role]) != count:
            raise StorageContractError(
                f"storage profile requires exactly {count} {role} device(s)"
            )


def _require_descendant(
    path: str, root: str, field: str, *, allow_root: bool = False
) -> None:
    try:
        common = os.path.commonpath((path, root))
    except ValueError as exc:
        raise StorageContractError(f"locations.{field} is outside {root}") from exc
    if common != root or (path == root and not allow_root):
        raise StorageContractError(f"locations.{field} must be below {root}")


def _canonical_path(value: object, field: str, *, under_mnt: bool) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise StorageContractError(f"{field} must be an absolute path")
    normalized = os.path.normpath(value)
    if value != normalized or normalized == "/":
        raise StorageContractError(f"{field} must be a canonical absolute path")
    if under_mnt and not normalized.startswith("/mnt/"):
        raise StorageContractError(f"{field} must be below /mnt")
    return normalized


def _reject_unknown(raw: dict, allowed: set[str], label: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise StorageContractError(f"{label} has unknown fields: {unknown}")


def _reject_duplicates(
    devices: tuple[StorageDevice, ...], field: str, label: str
) -> None:
    values = [getattr(device, field) for device in devices]
    if len(values) != len(set(values)):
        raise StorageContractError(f"duplicate {label} are not allowed")


def _is_unprivileged_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 2**31 - 1
