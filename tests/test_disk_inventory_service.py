"""BF-003: framework-neutral disk inventory service."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from disk_inventory_service import DiskInventoryService, process_device  # noqa: E402


class FakeHelper:
    """A HelperPort fake that returns canned responses keyed by command."""

    def __init__(self, responses, *, available=True):
        self._responses = responses
        self._available = available
        self.calls = []

    def available(self):
        return self._available

    def call(self, command, params=None):
        self.calls.append((command, params))
        return self._responses.get(command, {"success": False})


def test_inventory_unavailable_helper_returns_no_disks():
    helper = FakeHelper({}, available=False)
    result = DiskInventoryService(helper=helper).inventory()
    assert result == {"disks": [], "helper_available": False}
    assert helper.calls == []  # no privileged reads attempted


def test_inventory_lsblk_failure_surfaces_error():
    helper = FakeHelper({"lsblk": {"success": False, "error": "boom"}})
    result = DiskInventoryService(helper=helper).inventory()
    assert result["helper_available"] is True
    assert result["disks"] == []
    assert result["error"] == "boom"


def test_inventory_composes_helper_reads():
    helper = FakeHelper(
        {
            "lsblk": {
                "success": True,
                "data": {
                    "blockdevices": [
                        {
                            "name": "sda",
                            "type": "disk",
                            "size": "1T",
                            "children": [
                                {"name": "sda1", "type": "part"},
                            ],
                        },
                        {"name": "loop0", "type": "loop"},
                    ]
                },
            },
            "blkid": {
                "success": True,
                "data": [
                    {"DEVNAME": "/dev/sda1", "UUID": "u-1", "LABEL": "data", "TYPE": "ext4"},
                ],
            },
            "mounts_read": {
                "success": True,
                "data": [
                    {"device": "/dev/sda1", "mountpoint": "/mnt/storage", "options": "rw"},
                ],
            },
            "fstab_read": {
                "success": True,
                "data": [
                    {"mountpoint": "/mnt/storage", "device": "UUID=u-1"},
                ],
            },
            "df": {
                "success": True,
                "data": [
                    {"target": "/mnt/storage", "size": "100", "used": "40", "avail": "60", "pcent": "40%"},
                ],
            },
        }
    )

    result = DiskInventoryService(helper=helper).inventory()

    assert result["helper_available"] is True
    # loop device skipped; only sda remains
    assert len(result["disks"]) == 1
    disk = result["disks"][0]
    assert disk["name"] == "sda"
    partition = disk["partitions"][0]
    assert partition["uuid"] == "u-1"
    assert partition["label"] == "data"
    assert partition["fstype"] == "ext4"
    assert partition["mounted"] is True
    assert partition["mountpoint"] == "/mnt/storage"
    assert partition["in_fstab"] is True
    assert partition["usage"] == {
        "total": 100,
        "used": 40,
        "available": 60,
        "percent": "40",
    }


def test_process_device_skips_virtual_devices():
    assert process_device({"name": "loop0", "type": "loop"}, {}, {}, {}, {}, {}) is None
    assert process_device({"name": "sr0", "type": "rom"}, {}, {}, {}, {}, {}) is None


def test_process_device_matches_fstab_by_uuid_when_unmounted():
    device = {"name": "sdb1", "type": "part"}
    blkid_map = {"/dev/sdb1": {"UUID": "u-2"}}
    fstab_uuid_map = {"u-2": {"mountpoint": "/mnt/backup", "device": "UUID=u-2"}}
    disk = process_device(device, blkid_map, {}, {}, fstab_uuid_map, {})
    assert disk["mounted"] is False
    assert disk["in_fstab"] is True
