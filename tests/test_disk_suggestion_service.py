"""Tests for framework-neutral mount suggestions."""

from unittest.mock import Mock

import pytest

from disk_suggestion_service import DiskSuggestionService, parse_size_to_gb


def service(inventory):
    reader = Mock(return_value=inventory)
    return DiskSuggestionService(
        inventory_reader=reader,
        supported_filesystems={"ext4", "xfs", "btrfs"},
    ), reader


def partition(**overrides):
    return {
        "path": "/dev/sda1",
        "uuid": "abc",
        "fstype": "ext4",
        "size": "500G",
        "mounted": False,
        **overrides,
    }


def test_nvme_partition_is_recommended_for_downloads():
    subject, reader = service(
        {
            "disks": [
                {
                    "name": "nvme0n1",
                    "transport": "nvme",
                    "size": "500G",
                    "partitions": [partition(path="/dev/nvme0n1p1")],
                }
            ]
        }
    )

    result = subject.suggestions()

    assert result["suggestions"][0]["suggested_mount"] == "/mnt/downloads"
    reader.assert_called_once_with()


@pytest.mark.parametrize(
    ("size", "expected"),
    [("32G", "/mnt/backup"), ("64G", "/mnt/storage"), ("2T", "/mnt/storage")],
)
def test_usb_recommendation_uses_whole_disk_size(size, expected):
    subject, _ = service(
        {
            "disks": [
                {
                    "name": "sda",
                    "transport": "usb",
                    "size": size,
                    "partitions": [partition()],
                }
            ]
        }
    )

    assert subject.suggestions()["suggestions"][0]["suggested_mount"] == expected


def test_filters_mounted_missing_uuid_and_unsupported_filesystems():
    subject, _ = service(
        {
            "disks": [
                {
                    "name": "sda",
                    "transport": "usb",
                    "size": "500G",
                    "partitions": [
                        partition(mounted=True),
                        partition(uuid=""),
                        partition(fstype="ntfs"),
                    ],
                }
            ]
        }
    )

    assert subject.suggestions() == {"suggestions": []}


def test_unpartitioned_disk_is_considered_and_non_storage_transport_is_skipped():
    usb = partition(path="/dev/sda", size="16G") | {
        "name": "sda",
        "transport": "usb",
        "partitions": [],
    }
    sata = partition(path="/dev/sdb") | {
        "name": "sdb",
        "transport": "sata",
        "partitions": [],
    }
    subject, _ = service({"disks": [usb, sata]})

    result = subject.suggestions()["suggestions"]

    assert len(result) == 1
    assert result[0]["device"] == "/dev/sda"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1T", 1024.0), ("500G", 500.0), ("512M", 0.5), ("invalid", None)],
)
def test_parse_size_to_gb(value, expected):
    assert parse_size_to_gb(value) == expected
