"""CP-010 disk summary contract and provider-assignment coverage."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from disk_summary_service import DiskSummaryService


FIXED_TIME = datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc)


def _inventory():
    return {
        "helper_available": True,
        "disks": [
            {
                "name": "sda",
                "path": "/dev/sda",
                "type": "disk",
                "partitions": [
                    {
                        "name": "sda1",
                        "path": "/dev/sda1",
                        "type": "part",
                        "uuid": "data-1",
                        "mounted": True,
                        "mountpoint": "/mnt/data1",
                        "usage": {
                            "total": 1_000,
                            "used": 400,
                            "available": 600,
                            "percent": "40",
                        },
                        "partitions": [],
                    }
                ],
            },
            {
                "name": "sdb",
                "path": "/dev/sdb",
                "type": "disk",
                "partitions": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "uuid": "parity-1",
                        "mounted": False,
                        "mountpoint": "",
                        "configured_mountpoint": "/mnt/parity",
                        "partitions": [],
                    }
                ],
            },
            {
                "name": "sdc",
                "path": "/dev/sdc",
                "type": "disk",
                "mounted": False,
                "mountpoint": "",
                "partitions": [],
            },
        ],
    }


def _smart():
    return {
        "disks": [
            {"device": "/dev/sda", "data": {"health_status": "healthy", "temperature_c": 34}},
            {"device": "/dev/sdb", "data": {"health_status": "warning", "temperature_c": 57}},
            {"device": "/dev/sdc", "data": {"health_status": "failing", "temperature_c": 40}},
        ]
    }


def _assignments():
    return {
        "assignments": [
            {
                "provider_id": "mergerfs",
                "capability_id": "storage.pooling",
                "role": "branch",
                "resource_id": "media",
                "resource_name": "Media",
                "target_path": "/mnt/data1",
                "href": "/pools/mergerfs",
            },
            {
                "provider_id": "snapraid",
                "capability_id": "storage.protection",
                "role": "parity",
                "resource_id": "parity",
                "resource_name": "Parity",
                "target_uuid": "parity-1",
                "href": "/protection/snapraid",
            },
            {
                "provider_id": "mergerfs",
                "capability_id": "storage.pooling",
                "role": "branch",
                "resource_id": "archive",
                "resource_name": "Archive",
                "target_path": "/mnt/parity",
                "href": "/pools/mergerfs",
            },
        ],
        "warnings": [],
    }


def _service(*, inventory_provider=_inventory, smart_provider=_smart, assignment_provider=_assignments):
    return DiskSummaryService(
        inventory_provider=inventory_provider,
        smart_provider=smart_provider,
        assignment_provider=assignment_provider,
        clock=lambda: FIXED_TIME,
    )


def test_summary_composes_health_capacity_allocation_and_assignments():
    result = _service().snapshot()

    assert result["state"] == "attention"
    assert result["counts"] == {
        "total": 3,
        "healthy": 1,
        "warning": 1,
        "failing": 1,
        "unknown": 0,
        "mounted": 1,
        "unmounted": 2,
        "assigned": 2,
        "unassigned": 1,
        "unused": 1,
    }
    assert result["capacity"] == {
        "mounted_total_bytes": 1_000,
        "mounted_used_bytes": 400,
        "mounted_available_bytes": 600,
        "mounted_percent": 40.0,
    }
    assert result["sources"] == {
        "inventory": "available",
        "smart": "available",
        "assignments": "available",
    }
    assert result["warnings"] == []
    assert result["collected_at"] == "2026-07-18T12:30:00Z"

    devices = {item["path"]: item for item in result["devices"]}
    assert devices["/dev/sda"]["health"] == "healthy"
    assert devices["/dev/sda"]["mounted"] is True
    assert devices["/dev/sda"]["assignments"][0]["provider_id"] == "mergerfs"
    assert devices["/dev/sda"]["assignments"][0]["device_path"] == "/dev/sda1"
    assert devices["/dev/sdb"]["assignments"][0]["role"] == "parity"
    assert len(devices["/dev/sdb"]["assignments"]) == 2
    assert devices["/dev/sdc"]["assignments"] == []


def test_optional_source_failures_are_degraded_without_false_unassigned_counts():
    def unavailable():
        raise RuntimeError("private source detail")

    result = _service(smart_provider=unavailable, assignment_provider=unavailable).snapshot()

    assert result["state"] == "attention"
    assert result["counts"]["unknown"] == 3
    assert result["counts"]["assigned"] is None
    assert result["counts"]["unassigned"] is None
    assert result["counts"]["unused"] is None
    assert result["sources"]["inventory"] == "available"
    assert result["sources"]["smart"] == "unavailable"
    assert result["sources"]["assignments"] == "unavailable"
    assert result["warnings"] == [
        {
            "code": "source_unavailable",
            "source": "smart",
            "message": "SMART health is unavailable",
        },
        {
            "code": "source_unavailable",
            "source": "assignments",
            "message": "Provider assignments are unavailable",
        },
    ]
    assert "private source detail" not in str(result)


def test_embedded_summary_reuses_inventory_without_reading_smart():
    inventory_provider = Mock()
    smart_provider = Mock()
    service = _service(
        inventory_provider=inventory_provider,
        smart_provider=smart_provider,
    )

    result = service.snapshot(inventory=_inventory(), include_smart=False)

    inventory_provider.assert_not_called()
    smart_provider.assert_not_called()
    assert result["sources"]["smart"] == "not_checked"
    assert result["counts"]["unknown"] == 3
    assert result["counts"]["assigned"] == 2
    assert result["devices"][0]["assignments"][0]["provider_id"] == "mergerfs"


@pytest.mark.parametrize(
    ("inventory", "expected_source"),
    [
        ({"helper_available": False, "disks": []}, "unavailable"),
        ({"helper_available": True, "disks": [], "error": "lsblk failed"}, "unavailable"),
    ],
)
def test_inventory_unavailable_returns_bounded_empty_contract(inventory, expected_source):
    result = _service(inventory_provider=lambda: inventory).snapshot()

    assert result["state"] == "unavailable"
    assert result["counts"]["total"] == 0
    assert result["counts"]["assigned"] is None
    assert result["devices"] == []
    assert result["sources"]["inventory"] == expected_source
    assert result["warnings"][0]["source"] == "inventory"


def test_malformed_records_are_ignored_and_results_are_bounded():
    inventory = _inventory()
    inventory["disks"] = inventory["disks"] * 100
    assignments = _assignments()
    assignments["assignments"] = assignments["assignments"] * 200
    assignments["warnings"] = [{"source": "provider", "message": "bad"}] * 100

    result = _service(
        inventory_provider=lambda: inventory,
        assignment_provider=lambda: assignments,
    ).snapshot()

    assert len(result["devices"]) == 128
    assert len(result["warnings"]) <= 20
