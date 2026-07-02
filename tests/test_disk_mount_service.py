"""Tests for framework-neutral disk mount operations."""

from unittest.mock import Mock, call

import pytest

from disk_mount_service import (
    DiskMountService,
    MountDependencyCheckError,
    MountInUseError,
    MountOperationError,
    MountValidationError,
)
from mount_dependencies import DependencyInspectionError, MountDependency


def service(helper=None, dependency_inspector=None):
    return DiskMountService(
        helper=helper or Mock(),
        dependency_inspector=dependency_inspector or Mock(return_value=[]),
    )


def test_mount_adds_fstab_before_mounting():
    helper = Mock()
    helper.call.side_effect = [{"success": True}, {"success": True}]

    result = service(helper).mount(
        uuid="abc-123", mountpoint="/mnt/storage", fstype="ext4"
    )

    assert result == {
        "status": "mounted",
        "mountpoint": "/mnt/storage",
        "fstab_added": True,
    }
    assert helper.call.call_args_list == [
        call(
            "fstab_add",
            {"uuid": "abc-123", "mountpoint": "/mnt/storage", "fstype": "ext4"},
        ),
        call("mount", {"mountpoint": "/mnt/storage"}),
    ]


def test_direct_mount_resolves_uuid_to_device():
    helper = Mock()
    helper.call.side_effect = [
        {"success": True, "data": [{"UUID": "abc-123", "DEVNAME": "/dev/sda1"}]},
        {"success": True},
    ]

    service(helper).mount(
        uuid="abc-123",
        mountpoint="/mnt/storage",
        fstype="ext4",
        add_to_fstab=False,
    )

    assert helper.call.call_args_list == [
        call("blkid"),
        call("mount", {"mountpoint": "/mnt/storage", "device": "/dev/sda1"}),
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"uuid": "", "mountpoint": "/mnt/x", "fstype": "ext4"}, "UUID is required"),
        ({"uuid": "x", "mountpoint": "", "fstype": "ext4"}, "Mountpoint is required"),
        (
            {"uuid": "x", "mountpoint": "/tmp/x", "fstype": "ext4"},
            "Mountpoint must be under /mnt/",
        ),
    ],
)
def test_mount_rejects_invalid_identity_or_path(kwargs, message):
    with pytest.raises(MountValidationError, match=message):
        service().mount(**kwargs)


def test_mount_rejects_custom_options_before_helper_call():
    helper = Mock()
    with pytest.raises(MountValidationError) as caught:
        service(helper).mount(
            uuid="x",
            mountpoint="/mnt/x",
            fstype="ext4",
            custom_options_supplied=True,
        )

    assert caught.value.code == "mount_options_not_allowed"
    helper.call.assert_not_called()


def test_mount_reports_fstab_side_effect_when_mount_fails():
    helper = Mock()
    helper.call.side_effect = [{"success": True}, {"success": False, "error": "busy"}]

    with pytest.raises(MountOperationError, match="busy") as caught:
        service(helper).mount(uuid="x", mountpoint="/mnt/x", fstype="ext4")

    assert caught.value.fstab_added is True


def test_unmount_blocks_known_dependencies_before_helper_call():
    helper = Mock()
    dependency = MountDependency("container", "media", "/mnt/storage/media")

    with pytest.raises(MountInUseError) as caught:
        service(helper, Mock(return_value=[dependency])).unmount(
            mountpoint="/mnt/storage"
        )

    assert caught.value.dependencies == [dependency]
    helper.call.assert_not_called()


def test_unmount_fails_closed_when_dependency_inspection_fails():
    inspector = Mock(side_effect=DependencyInspectionError(["Docker unavailable"]))

    with pytest.raises(MountDependencyCheckError) as caught:
        service(dependency_inspector=inspector).unmount(mountpoint="/mnt/storage")

    assert caught.value.details == ["Docker unavailable"]


def test_unmount_preserves_fstab_removal_warning():
    helper = Mock()
    helper.call.side_effect = [
        {"success": True},
        {"success": False, "error": "read only"},
    ]

    result = service(helper).unmount(mountpoint="/mnt/storage", remove_from_fstab=True)

    assert result == {
        "status": "unmounted",
        "warning": "Unmounted but failed to remove fstab entry",
        "fstab_error": "read only",
    }
