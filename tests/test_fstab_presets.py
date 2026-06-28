import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fstab_presets import FSTAB_PRESETS, get_fstab_preset


EXPECTED_PRESETS = {
    "ext2": {"options": "defaults,nofail", "dump": 0, "pass": 2},
    "ext3": {"options": "defaults,nofail", "dump": 0, "pass": 2},
    "ext4": {"options": "defaults,nofail", "dump": 0, "pass": 2},
    "xfs": {"options": "defaults,nofail", "dump": 0, "pass": 0},
    "btrfs": {"options": "defaults,nofail", "dump": 0, "pass": 0},
    "ntfs": {"options": "defaults,nofail,uid=1000,gid=1000,umask=0022", "dump": 0, "pass": 0},
    "vfat": {"options": "defaults,nofail,uid=1000,gid=1000,umask=0022", "dump": 0, "pass": 0},
    "exfat": {"options": "defaults,nofail,uid=1000,gid=1000,umask=0022", "dump": 0, "pass": 0},
}


def test_fstab_presets_are_explicit_and_complete():
    assert FSTAB_PRESETS == EXPECTED_PRESETS


@pytest.mark.parametrize("fstype", ["", "auto", "zfs", None])
def test_get_fstab_preset_rejects_unsupported_filesystem(fstype):
    with pytest.raises(ValueError, match="Unsupported filesystem type"):
        get_fstab_preset(fstype)


def test_get_fstab_preset_normalizes_case_and_whitespace():
    assert get_fstab_preset(" EXT4 ") == EXPECTED_PRESETS["ext4"]
