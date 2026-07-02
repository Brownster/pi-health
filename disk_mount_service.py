"""Framework-neutral disk mount and unmount operations."""

from __future__ import annotations

from collections.abc import Callable

from fstab_presets import FSTAB_PRESETS, normalize_fstype
from mount_dependencies import (
    DependencyInspectionError,
    MountDependency,
    normalize_managed_mountpoint,
)
from ports import HelperPort


class MountValidationError(Exception):
    """Raised when a mount request is invalid."""

    def __init__(self, message: str, *, code: str | None = None, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


class MountDependencyCheckError(Exception):
    """Raised when unmount safety dependencies cannot be inspected."""

    def __init__(self, details: list[str]):
        super().__init__("Unable to verify mount dependencies")
        self.details = details


class MountInUseError(Exception):
    """Raised when an unmount would disrupt known dependants."""

    def __init__(self, dependencies: list[MountDependency]):
        super().__init__("Unmount blocked")
        self.dependencies = dependencies


class MountOperationError(Exception):
    """Raised when the helper rejects a mount operation."""

    def __init__(self, message: str, *, fstab_added: bool | None = None):
        super().__init__(message)
        self.fstab_added = fstab_added


class DiskMountService:
    """Coordinate validated mount mutations through the privileged helper."""

    def __init__(
        self,
        *,
        helper: HelperPort,
        dependency_inspector: Callable[[str], list[MountDependency]],
    ) -> None:
        self._helper = helper
        self._dependency_inspector = dependency_inspector

    def mount(
        self,
        *,
        uuid: str,
        mountpoint: str,
        fstype: str | None,
        add_to_fstab: bool = True,
        custom_options_supplied: bool = False,
    ) -> dict:
        if not uuid:
            raise MountValidationError("UUID is required")
        if not mountpoint:
            raise MountValidationError("Mountpoint is required")
        if not mountpoint.startswith("/mnt/"):
            raise MountValidationError("Mountpoint must be under /mnt/")
        if custom_options_supplied:
            raise MountValidationError(
                "Custom mount options are not allowed",
                code="mount_options_not_allowed",
            )
        try:
            normalized_fstype = normalize_fstype(fstype)
        except ValueError as exc:
            raise MountValidationError(
                str(exc),
                code="unsupported_filesystem",
                details=sorted(FSTAB_PRESETS),
            ) from exc

        if add_to_fstab:
            result = self._helper.call(
                "fstab_add",
                {"uuid": uuid, "mountpoint": mountpoint, "fstype": normalized_fstype},
            )
            if not result.get("success"):
                raise MountOperationError(
                    result.get("error", "Failed to add fstab entry")
                )
            mount_params = {"mountpoint": mountpoint}
        else:
            result = self._helper.call("blkid")
            if not result.get("success"):
                raise MountOperationError(
                    result.get("error", "Failed to resolve device")
                )
            device = next(
                (
                    item.get("DEVNAME")
                    for item in result.get("data", [])
                    if item.get("UUID") == uuid
                ),
                None,
            )
            if not device:
                raise MountOperationError("Device not found for UUID")
            mount_params = {"mountpoint": mountpoint, "device": device}

        result = self._helper.call("mount", mount_params)
        if not result.get("success"):
            raise MountOperationError(
                result.get("error", "Mount failed"),
                fstab_added=add_to_fstab,
            )
        return {
            "status": "mounted",
            "mountpoint": mountpoint,
            "fstab_added": add_to_fstab,
        }

    def unmount(self, *, mountpoint: str, remove_from_fstab: bool = False) -> dict:
        if not mountpoint:
            raise MountValidationError("Mountpoint is required")
        try:
            mountpoint = normalize_managed_mountpoint(mountpoint)
        except ValueError as exc:
            raise MountValidationError(str(exc)) from exc

        try:
            dependencies = self._dependency_inspector(mountpoint)
        except DependencyInspectionError as exc:
            raise MountDependencyCheckError(exc.details) from exc
        if dependencies:
            raise MountInUseError(dependencies)

        result = self._helper.call("umount", {"mountpoint": mountpoint})
        if not result.get("success"):
            raise MountOperationError(result.get("error", "Unmount failed"))

        if remove_from_fstab:
            result = self._helper.call("fstab_remove", {"mountpoint": mountpoint})
            if not result.get("success"):
                return {
                    "status": "unmounted",
                    "warning": "Unmounted but failed to remove fstab entry",
                    "fstab_error": result.get("error"),
                }

        return {
            "status": "unmounted",
            "mountpoint": mountpoint,
            "fstab_removed": remove_from_fstab,
        }
