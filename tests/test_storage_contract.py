"""OB-000: versioned guided-onboarding storage contract."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from storage_contract import (
    CONFIG_CONTAINER_PATH,
    DEVICE_ROLES,
    DOWNLOADS_CONTAINER_PATH,
    MEDIA_CONTAINER_PATH,
    STORAGE_PROFILES,
    SUPPORTED_FILESYSTEMS,
    StorageContractError,
    parse_storage_contract,
)


SCHEMA_PATH = Path("config/schemas/storage-contract.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def device(
    device_id,
    role,
    mountpoint,
    *,
    filesystem_uuid=None,
    serial=None,
    filesystem="ext4",
):
    value = {
        "id": device_id,
        "role": role,
        "filesystem_uuid": filesystem_uuid or f"uuid-{device_id}",
        "filesystem": filesystem,
        "mountpoint": mountpoint,
    }
    if serial is not None:
        value["serial"] = serial
    return value


def contract(profile="single_disk", *, devices=None, locations=None):
    if devices is None:
        devices = [device("storage", "data", "/mnt/storage")]
    if locations is None:
        locations = {
            "media_host": "/mnt/storage/media",
            "downloads_host": (
                "/mnt/storage/downloads"
                if profile == "single_disk"
                else "/mnt/downloads"
            ),
            "application_config_host": "/var/lib/limeos/apps",
            "backup_host": "/mnt/backup/limeos",
            "media_container": "/data/media",
            "downloads_container": "/data/downloads",
            "config_container": "/config",
        }
    return {
        "schema_version": "1",
        "profile": profile,
        "media_identity": {"uid": 1000, "gid": 1000},
        "locations": locations,
        "devices": devices,
    }


def schema_errors(payload):
    return sorted(
        (error.message for error in Draft7Validator(SCHEMA).iter_errors(payload))
    )


def test_published_schema_is_valid_and_matches_closed_python_enums():
    Draft7Validator.check_schema(SCHEMA)

    properties = SCHEMA["properties"]
    device_properties = SCHEMA["definitions"]["device"]["properties"]
    assert set(properties["profile"]["enum"]) == STORAGE_PROFILES
    assert set(device_properties["role"]["enum"]) == DEVICE_ROLES
    assert set(device_properties["filesystem"]["enum"]) == SUPPORTED_FILESYSTEMS


def test_single_disk_contract_keeps_media_and_downloads_on_one_filesystem():
    raw = contract()

    parsed = parse_storage_contract(raw)

    assert parsed.profile == "single_disk"
    assert parsed.locations.media_host == "/mnt/storage/media"
    assert parsed.locations.downloads_host == "/mnt/storage/downloads"
    assert parsed.locations.media_container == MEDIA_CONTAINER_PATH
    assert parsed.locations.downloads_container == DOWNLOADS_CONTAINER_PATH
    assert parsed.locations.config_container == CONFIG_CONTAINER_PATH
    assert parsed.as_dict() == raw
    assert schema_errors(raw) == []


def test_separate_downloads_contract_assigns_one_drive_to_each_endpoint():
    raw = contract(
        "separate_downloads",
        devices=[
            device("storage", "data", "/mnt/storage", serial="DAS-A-01"),
            device("downloads", "downloads", "/mnt/downloads", serial="SSD-01"),
            device("backup", "config_backup", "/mnt/backup", serial="USB-STICK"),
        ],
    )

    parsed = parse_storage_contract(raw)

    assert [entry.role for entry in parsed.devices] == [
        "data",
        "downloads",
        "config_backup",
    ]
    assert parsed.locations.backup_host == "/mnt/backup/limeos"
    assert schema_errors(raw) == []


def test_protected_pool_represents_three_five_bay_enclosures():
    devices = [
        device(
            f"data-{index:02}",
            "data",
            f"/mnt/disks/data-{index:02}",
            serial=f"DAS-{((index - 1) // 5) + 1}-BAY-{((index - 1) % 5) + 1}",
        )
        for index in range(1, 15)
    ]
    devices.append(
        device("parity-01", "parity", "/mnt/parity/parity-01", serial="DAS-3-BAY-5")
    )
    raw = contract(
        "protected_pool",
        devices=devices,
        locations={
            **contract("protected_pool")["locations"],
            "downloads_host": "/mnt/storage/downloads",
        },
    )

    parsed = parse_storage_contract(raw)

    assert len(parsed.devices) == 15
    assert len([entry for entry in parsed.devices if entry.role == "data"]) == 14
    assert schema_errors(raw) == []


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(schema_version="2"),
        lambda value: value.update(profile="custom"),
        lambda value: value.update(extra=True),
        lambda value: value["media_identity"].update(uid=0),
        lambda value: value["media_identity"].update(gid=True),
        lambda value: value["locations"].update(media_container="/movies"),
        lambda value: value["locations"].update(media_host="/srv/media"),
        lambda value: value["locations"].update(downloads_host="/mnt/storage/../tmp"),
        lambda value: value["devices"][0].update(filesystem="zfs"),
        lambda value: value["devices"][0].update(mountpoint="/media/storage"),
    ],
)
def test_contract_rejects_unsupported_or_unsafe_values(change):
    raw = contract()
    change(raw)

    with pytest.raises(StorageContractError):
        parse_storage_contract(raw)


@pytest.mark.parametrize("field", ["id", "filesystem_uuid", "mountpoint"])
def test_contract_rejects_duplicate_device_identity(field):
    first = device("first", "data", "/mnt/storage")
    second = device("second", "config_backup", "/mnt/backup")
    second[field] = first[field]
    raw = contract(devices=[first, second])

    with pytest.raises(StorageContractError, match="duplicate"):
        parse_storage_contract(raw)


def test_single_disk_requires_one_data_device_and_nested_paths():
    wrong_role = contract(
        devices=[device("downloads", "downloads", "/mnt/downloads")]
    )
    outside_drive = contract()
    outside_drive["locations"]["downloads_host"] = "/mnt/downloads"

    with pytest.raises(StorageContractError, match="data"):
        parse_storage_contract(wrong_role)
    with pytest.raises(StorageContractError, match="downloads_host"):
        parse_storage_contract(outside_drive)


def test_separate_downloads_requires_distinct_data_and_download_devices():
    raw = contract("separate_downloads")

    with pytest.raises(StorageContractError, match="downloads"):
        parse_storage_contract(raw)


def test_protected_pool_requires_data_and_parity_roles():
    raw = contract(
        "protected_pool",
        devices=[device("storage", "data", "/mnt/disks/data-01")],
    )

    with pytest.raises(StorageContractError, match="data and one parity"):
        parse_storage_contract(raw)


def test_backup_location_must_be_below_assigned_backup_mount():
    raw = contract(
        devices=[
            device("storage", "data", "/mnt/storage"),
            device("backup", "config_backup", "/mnt/archive"),
        ]
    )

    with pytest.raises(StorageContractError, match="backup_host"):
        parse_storage_contract(raw)


def test_contract_rejects_more_than_one_configuration_backup_device():
    raw = contract(
        devices=[
            device("storage", "data", "/mnt/storage"),
            device("backup-a", "config_backup", "/mnt/backup-a"),
            device("backup-b", "config_backup", "/mnt/backup-b"),
        ]
    )

    with pytest.raises(StorageContractError, match="only one"):
        parse_storage_contract(raw)


def test_contract_and_schema_reject_unknown_nested_fields():
    raw = contract()
    raw["devices"][0]["kernel_name"] = "/dev/sdb1"

    with pytest.raises(StorageContractError, match="unknown"):
        parse_storage_contract(raw)
    assert schema_errors(raw)


def test_as_dict_returns_mutable_data_without_mutating_the_model():
    parsed = parse_storage_contract(contract())

    serialized = parsed.as_dict()
    serialized["devices"][0]["role"] = "parity"

    assert parsed.devices[0].role == "data"


def test_schema_rejects_the_same_structural_failures_as_the_parser():
    unsupported = contract()
    unsupported["locations"]["config_container"] = "/settings"
    unknown = copy.deepcopy(unsupported)
    unknown["surprise"] = True

    assert schema_errors(unsupported)
    assert schema_errors(unknown)
