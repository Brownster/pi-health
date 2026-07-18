"""Framework-neutral disk inventory read model."""

from __future__ import annotations

from ports import HelperPort


def process_device(device, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map, parent=None):
    """Build a structured disk record from an lsblk device and its children.

    Pure transform over the helper's block-device, blkid, mount, fstab, and usage
    maps; recurses into partitions. Loop and rom devices are skipped.
    """
    name = device.get('name', '')
    dev_path = f"/dev/{name}"
    dev_type = device.get('type', '')

    # Skip loop devices and other virtual devices
    if dev_type in ['loop', 'rom']:
        return None

    disk_info = {
        'name': name,
        'path': dev_path,
        'type': dev_type,
        'size': device.get('size', ''),
        'model': device.get('model', ''),
        'serial': device.get('serial', ''),
        'transport': device.get('tran', ''),
        'hotplug': device.get('hotplug', False),
        'fstype': device.get('fstype', ''),
        'mountpoint': device.get('mountpoint', ''),
        'partitions': []
    }

    # Add blkid info
    if dev_path in blkid_map:
        blk = blkid_map[dev_path]
        disk_info['uuid'] = blk.get('UUID', '')
        disk_info['label'] = blk.get('LABEL', '')
        if not disk_info['fstype']:
            disk_info['fstype'] = blk.get('TYPE', '')

    # Check mount status
    disk_info['mounted'] = dev_path in mounts_map
    if disk_info['mounted']:
        mount_info = mounts_map[dev_path]
        disk_info['mountpoint'] = mount_info['mountpoint']
        disk_info['mount_options'] = mount_info['options']

    # Check fstab status
    mountpoint = disk_info.get('mountpoint', '')
    fstab_entry = fstab_map.get(mountpoint)
    if fstab_entry is None and disk_info.get('uuid'):
        fstab_entry = fstab_uuid_map.get(disk_info['uuid'])
    disk_info['in_fstab'] = fstab_entry is not None
    disk_info['configured_mountpoint'] = (
        fstab_entry.get('mountpoint', '') if fstab_entry else ''
    )

    # Add usage info if mounted
    if disk_info.get('mountpoint') and disk_info['mountpoint'] in df_map:
        usage = df_map[disk_info['mountpoint']]
        disk_info['usage'] = {
            'total': int(usage.get('size', 0)),
            'used': int(usage.get('used', 0)),
            'available': int(usage.get('avail', 0)),
            'percent': usage.get('pcent', '0%').rstrip('%')
        }

    # Process children (partitions)
    children = device.get('children', [])
    for child in children:
        part = process_device(child, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map, parent=name)
        if part:
            disk_info['partitions'].append(part)

    return disk_info


class DiskInventoryService:
    """Assemble the block-device inventory from privileged helper reads."""

    def __init__(self, *, helper: HelperPort):
        self._helper = helper

    def inventory(self) -> dict:
        """Return a structured view of all block devices with mount and usage status."""
        result = {
            'disks': [],
            'helper_available': self._helper.available(),
        }

        if not result['helper_available']:
            return result

        # Get block devices
        lsblk_result = self._helper.call('lsblk')
        if not lsblk_result.get('success'):
            result['error'] = lsblk_result.get('error', 'Failed to get block devices')
            return result

        # Get blkid info for UUIDs
        blkid_result = self._helper.call('blkid')
        blkid_map = {}
        if blkid_result.get('success'):
            for dev in blkid_result.get('data', []):
                devname = dev.get('DEVNAME', '')
                if devname:
                    blkid_map[devname] = dev

        # Get current mounts
        mounts_result = self._helper.call('mounts_read')
        mounts_map = {}
        if mounts_result.get('success'):
            for mount in mounts_result.get('data', []):
                mounts_map[mount['device']] = mount

        # Get fstab entries
        fstab_result = self._helper.call('fstab_read')
        fstab_map = {}
        fstab_uuid_map = {}
        if fstab_result.get('success'):
            for entry in fstab_result.get('data', []):
                # Map by mountpoint for easy lookup
                fstab_map[entry['mountpoint']] = entry
                device = entry.get('device', '')
                if device.startswith('UUID='):
                    fstab_uuid_map[device.replace('UUID=', '')] = entry

        # Get disk usage
        df_result = self._helper.call('df')
        df_map = {}
        if df_result.get('success'):
            for entry in df_result.get('data', []):
                df_map[entry.get('target', '')] = entry

        # Process lsblk output
        blockdevices = lsblk_result.get('data', {}).get('blockdevices', [])
        for device in blockdevices:
            disk = process_device(device, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map)
            if disk:
                result['disks'].append(disk)

        return result
