"""Approved fstab settings for filesystems managed by Pi-Health."""

from __future__ import annotations


_LINUX_OPTIONS = "defaults,nofail"
_REMOVABLE_OPTIONS = "defaults,nofail,uid=1000,gid=1000,umask=0022"

FSTAB_PRESETS = {
    "ext2": {"options": _LINUX_OPTIONS, "dump": 0, "pass": 2},
    "ext3": {"options": _LINUX_OPTIONS, "dump": 0, "pass": 2},
    "ext4": {"options": _LINUX_OPTIONS, "dump": 0, "pass": 2},
    "xfs": {"options": _LINUX_OPTIONS, "dump": 0, "pass": 0},
    "btrfs": {"options": _LINUX_OPTIONS, "dump": 0, "pass": 0},
    "ntfs": {"options": _REMOVABLE_OPTIONS, "dump": 0, "pass": 0},
    "vfat": {"options": _REMOVABLE_OPTIONS, "dump": 0, "pass": 0},
    "exfat": {"options": _REMOVABLE_OPTIONS, "dump": 0, "pass": 0},
}


def normalize_fstype(fstype: object) -> str:
    normalized = fstype.strip().lower() if isinstance(fstype, str) else ""
    if normalized not in FSTAB_PRESETS:
        supported = ", ".join(sorted(FSTAB_PRESETS))
        raise ValueError(f"Unsupported filesystem type; supported types: {supported}")
    return normalized


def get_fstab_preset(fstype: object) -> dict[str, object]:
    """Return a copy of the approved preset for one filesystem."""
    return FSTAB_PRESETS[normalize_fstype(fstype)].copy()
