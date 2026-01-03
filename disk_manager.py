"""
Disk Manager Module

Provides disk inventory, mount management, and storage configuration.
Communicates with the privileged helper service over Unix socket.
"""

import os
import json
from flask import Blueprint, jsonify, request
from auth_utils import login_required
from helper_client import helper_call, helper_available, HelperError, HELPER_SOCKET

disk_manager = Blueprint('disk_manager', __name__)

# Media paths config file
MEDIA_PATHS_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'config',
    'media_paths.json'
)

# Default media paths
DEFAULT_MEDIA_PATHS = {
    'downloads': '/mnt/downloads',
    'storage': '/mnt/storage',
    'backup': '/mnt/backup',
    'config': '/home/pi/docker'
}




def load_media_paths():
    """Load media paths configuration."""
    try:
        if os.path.exists(MEDIA_PATHS_CONFIG):
            with open(MEDIA_PATHS_CONFIG, 'r') as f:
                config = json.load(f)
                # Merge with defaults
                merged = DEFAULT_MEDIA_PATHS.copy()
                merged.update(config)
                return merged
    except Exception:
        pass
    return DEFAULT_MEDIA_PATHS.copy()


def save_media_paths(paths):
    """Save media paths configuration."""
    os.makedirs(os.path.dirname(MEDIA_PATHS_CONFIG), exist_ok=True)
    with open(MEDIA_PATHS_CONFIG, 'w') as f:
        json.dump(paths, f, indent=2)


def get_disk_inventory():
    """
    Get complete disk inventory with mount status.

    Returns a structured view of all block devices with:
    - Device info (name, size, model, serial)
    - Partition info (uuid, fstype)
    - Mount status (mounted, mountpoint)
    - Usage stats (for mounted partitions)
    """
    result = {
        'disks': [],
        'helper_available': helper_available()
    }

    if not result['helper_available']:
        return result

    # Get block devices
    lsblk_result = helper_call('lsblk')
    if not lsblk_result.get('success'):
        result['error'] = lsblk_result.get('error', 'Failed to get block devices')
        return result

    # Get blkid info for UUIDs
    blkid_result = helper_call('blkid')
    blkid_map = {}
    if blkid_result.get('success'):
        for dev in blkid_result.get('data', []):
            devname = dev.get('DEVNAME', '')
            if devname:
                blkid_map[devname] = dev

    # Get current mounts
    mounts_result = helper_call('mounts_read')
    mounts_map = {}
    if mounts_result.get('success'):
        for mount in mounts_result.get('data', []):
            mounts_map[mount['device']] = mount

    # Get fstab entries
    fstab_result = helper_call('fstab_read')
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
    df_result = helper_call('df')
    df_map = {}
    if df_result.get('success'):
        for entry in df_result.get('data', []):
            df_map[entry.get('target', '')] = entry

    # Process lsblk output
    blockdevices = lsblk_result.get('data', {}).get('blockdevices', [])

    for device in blockdevices:
        disk = _process_device(device, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map)
        if disk:
            result['disks'].append(disk)

    return result


def _process_device(device, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map, parent=None):
    """Process a block device and its children."""
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
    disk_info['in_fstab'] = mountpoint in fstab_map
    if not disk_info['in_fstab'] and disk_info.get('uuid'):
        disk_info['in_fstab'] = disk_info['uuid'] in fstab_uuid_map

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
        part = _process_device(child, blkid_map, mounts_map, fstab_map, fstab_uuid_map, df_map, parent=name)
        if part:
            disk_info['partitions'].append(part)

    return disk_info


# =============================================================================
# API Endpoints
# =============================================================================

@disk_manager.route('/api/disks', methods=['GET'])
@login_required
def api_disk_list():
    """Get disk inventory."""
    try:
        inventory = get_disk_inventory()
        return jsonify(inventory)
    except HelperError as e:
        return jsonify({'error': str(e), 'helper_available': False}), 503


@disk_manager.route('/api/disks/helper-status', methods=['GET'])
@login_required
def api_helper_status():
    """Check if helper service is running."""
    available = helper_available()
    return jsonify({
        'available': available,
        'socket_path': HELPER_SOCKET
    })


@disk_manager.route('/api/disks/mount', methods=['POST'])
@login_required
def api_mount():
    """
    Mount a partition.

    Request body:
    {
        "uuid": "abc-123-...",
        "mountpoint": "/mnt/storage",
        "fstype": "ext4",
        "options": "defaults,nofail",
        "add_to_fstab": true
    }
    """
    data = request.get_json() or {}

    uuid = data.get('uuid', '')
    mountpoint = data.get('mountpoint', '')
    fstype = data.get('fstype', 'ext4')
    options = data.get('options', 'defaults,nofail')
    add_to_fstab = data.get('add_to_fstab', True)

    if not uuid:
        return jsonify({'error': 'UUID is required'}), 400
    if not mountpoint:
        return jsonify({'error': 'Mountpoint is required'}), 400
    if not mountpoint.startswith('/mnt/'):
        return jsonify({'error': 'Mountpoint must be under /mnt/'}), 400

    try:
        # Add to fstab if requested
        if add_to_fstab:
            fstab_result = helper_call('fstab_add', {
                'uuid': uuid,
                'mountpoint': mountpoint,
                'fstype': fstype,
                'options': options
            })
            if not fstab_result.get('success'):
                return jsonify({'error': fstab_result.get('error', 'Failed to add fstab entry')}), 400

        mount_params = {'mountpoint': mountpoint}
        if not add_to_fstab:
            # Resolve device from UUID for direct mount
            blkid_result = helper_call('blkid')
            if not blkid_result.get('success'):
                return jsonify({'error': blkid_result.get('error', 'Failed to resolve device')}), 400
            device = None
            for dev in blkid_result.get('data', []):
                if dev.get('UUID') == uuid:
                    device = dev.get('DEVNAME')
                    break
            if not device:
                return jsonify({'error': 'Device not found for UUID'}), 400
            mount_params['device'] = device

        # Mount the filesystem
        mount_result = helper_call('mount', mount_params)
        if not mount_result.get('success'):
            return jsonify({
                'error': mount_result.get('error', 'Mount failed'),
                'fstab_added': add_to_fstab
            }), 400

        return jsonify({
            'status': 'mounted',
            'mountpoint': mountpoint,
            'fstab_added': add_to_fstab
        })
    except HelperError as e:
        return jsonify({'error': str(e)}), 503


@disk_manager.route('/api/disks/unmount', methods=['POST'])
@login_required
def api_unmount():
    """
    Unmount a partition.

    Request body:
    {
        "mountpoint": "/mnt/storage",
        "remove_from_fstab": false
    }
    """
    data = request.get_json() or {}

    mountpoint = data.get('mountpoint', '')
    remove_from_fstab = data.get('remove_from_fstab', False)

    if not mountpoint:
        return jsonify({'error': 'Mountpoint is required'}), 400
    if not mountpoint.startswith('/mnt/'):
        return jsonify({'error': 'Mountpoint must be under /mnt/'}), 400

    try:
        # Unmount first
        umount_result = helper_call('umount', {'mountpoint': mountpoint})
        if not umount_result.get('success'):
            return jsonify({'error': umount_result.get('error', 'Unmount failed')}), 400

        # Remove from fstab if requested
        if remove_from_fstab:
            fstab_result = helper_call('fstab_remove', {'mountpoint': mountpoint})
            # Don't fail if fstab removal fails, just note it
            if not fstab_result.get('success'):
                return jsonify({
                    'status': 'unmounted',
                    'warning': 'Unmounted but failed to remove fstab entry',
                    'fstab_error': fstab_result.get('error')
                })

        return jsonify({
            'status': 'unmounted',
            'mountpoint': mountpoint,
            'fstab_removed': remove_from_fstab
        })
    except HelperError as e:
        return jsonify({'error': str(e)}), 503


@disk_manager.route('/api/disks/media-paths', methods=['GET'])
@login_required
def api_get_media_paths():
    """Get configured media paths."""
    paths = load_media_paths()
    return jsonify({'paths': paths})


@disk_manager.route('/api/disks/media-paths', methods=['POST'])
@login_required
def api_set_media_paths():
    """
    Set media paths configuration.

    Request body:
    {
        "downloads": "/mnt/downloads",
        "storage": "/mnt/storage",
        "backup": "/mnt/backup",
        "config": "/home/pi/docker"
    }
    """
    data = request.get_json() or {}

    paths = load_media_paths()

    # Update only provided paths
    for key in ['downloads', 'storage', 'backup', 'config']:
        if key in data:
            path = data[key]
            if not isinstance(path, str) or not path.startswith('/'):
                return jsonify({'error': f'Invalid path for {key}'}), 400
            paths[key] = path

    try:
        save_media_paths(paths)
        return jsonify({'status': 'updated', 'paths': paths})
    except Exception as e:
        return jsonify({'error': f'Failed to save paths: {str(e)}'}), 500


@disk_manager.route('/api/disks/suggested-mounts', methods=['GET'])
@login_required
def api_suggested_mounts():
    """
    Get suggested mount configurations based on detected drives.

    Returns mount suggestions for Setup 1 (NVMe + USB HDD + USB stick).
    """
    try:
        inventory = get_disk_inventory()
    except HelperError as e:
        return jsonify({'error': str(e)}), 503

    suggestions = []
    disks = inventory.get('disks', [])

    for disk in disks:
        # Check disk type and suggest mounts
        transport = disk.get('transport', '')
        is_nvme = 'nvme' in disk.get('name', '')
        is_usb = transport == 'usb'
        size_str = disk.get('size', '')

        # Process partitions
        partitions = disk.get('partitions', []) or [disk]
        for part in partitions:
            if part.get('mounted') or not part.get('uuid'):
                continue

            fstype = part.get('fstype', '')
            if fstype not in ['ext4', 'ext3', 'xfs', 'btrfs', 'ntfs', 'exfat', 'vfat']:
                continue

            suggestion = {
                'device': part.get('path', ''),
                'uuid': part.get('uuid', ''),
                'size': part.get('size', ''),
                'fstype': fstype,
                'label': part.get('label', ''),
                'suggested_mount': None,
                'reason': ''
            }

            # Suggest mount based on device characteristics
            if is_nvme:
                suggestion['suggested_mount'] = '/mnt/downloads'
                suggestion['reason'] = 'NVMe drive - fast storage for downloads'
            elif is_usb:
                # Parse size to determine suggestion
                size_gb = _parse_size_to_gb(size_str)
                if size_gb and size_gb < 64:
                    suggestion['suggested_mount'] = '/mnt/backup'
                    suggestion['reason'] = 'Small USB device - suitable for backups'
                else:
                    suggestion['suggested_mount'] = '/mnt/storage'
                    suggestion['reason'] = 'USB storage device - suitable for media'

            if suggestion['suggested_mount']:
                suggestions.append(suggestion)

    return jsonify({'suggestions': suggestions})


def _parse_size_to_gb(size_str):
    """Parse a size string like '500G' or '1T' to gigabytes."""
    if not size_str:
        return None

    size_str = size_str.upper().strip()
    try:
        if size_str.endswith('T'):
            return float(size_str[:-1]) * 1024
        elif size_str.endswith('G'):
            return float(size_str[:-1])
        elif size_str.endswith('M'):
            return float(size_str[:-1]) / 1024
        elif size_str.endswith('K'):
            return float(size_str[:-1]) / (1024 * 1024)
        else:
            # Assume bytes
            return float(size_str) / (1024 * 1024 * 1024)
    except ValueError:
        return None
