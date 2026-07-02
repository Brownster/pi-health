"""
Disk Manager Module

Provides disk inventory, mount management, and storage configuration.
Communicates with the privileged helper service over Unix socket.
"""

import os
import json
from flask import Blueprint, current_app, has_app_context, jsonify, request
from auth_utils import login_required
from helper_client import helper_call, helper_available, HelperError, HELPER_SOCKET
from disk_inventory_service import DiskInventoryService
from ports import HelperClientAdapter, JsonFileRepository
from helper_templates import render_startup_files
from fstab_presets import FSTAB_PRESETS
from mount_dependencies import find_mount_dependencies
from disk_mount_service import (
    DiskMountService,
    MountDependencyCheckError,
    MountInUseError,
    MountOperationError,
    MountValidationError,
)
from media_paths_service import (
    MediaPathValidationError,
    MediaPathsService,
    startup_service_params,
)
from smart_monitor import parse_smartctl_json
from runtime_paths import CONFIG_DIR as RUNTIME_CONFIG_DIR, STORAGE_PLUGIN_CONFIG_DIR as RUNTIME_STORAGE_PLUGIN_CONFIG_DIR

disk_manager = Blueprint('disk_manager', __name__)

# Media paths config file
MEDIA_PATHS_CONFIG = str(RUNTIME_CONFIG_DIR / 'media_paths.json')

SEEDBOX_CONFIG = str(RUNTIME_CONFIG_DIR / 'seedbox_mount.json')

STORAGE_PLUGIN_CONFIG_DIR = str(RUNTIME_STORAGE_PLUGIN_CONFIG_DIR)

# Default media paths
DEFAULT_MEDIA_PATHS = {
    'downloads': '/mnt/downloads',
    'storage': '/mnt/storage',
    'backup': '/mnt/backup',
    'config': '/home/pi/docker'
}

DOCKER_COMPOSE_PATH = os.getenv('DOCKER_COMPOSE_PATH', './docker-compose.yml')
STARTUP_SERVICE_NAME = 'docker-compose-start.service'
SEEDBOX_MOUNT_POINT = '/mnt/seedbox'




def load_media_paths():
    """Load media paths configuration."""
    return _media_paths().paths()


def save_media_paths(paths):
    """Save media paths configuration."""
    _media_paths().save(paths)


def load_seedbox_config():
    """Load seedbox mount configuration."""
    try:
        if os.path.exists(SEEDBOX_CONFIG):
            with open(SEEDBOX_CONFIG, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {
        'enabled': False,
        'host': '',
        'username': '',
        'port': 22,
        'remote_path': '',
        'mount_point': SEEDBOX_MOUNT_POINT
    }


def save_seedbox_config(config):
    """Save seedbox mount configuration."""
    os.makedirs(os.path.dirname(SEEDBOX_CONFIG), exist_ok=True)
    with open(SEEDBOX_CONFIG, 'w') as f:
        json.dump(config, f, indent=2)


def _seedbox_is_mounted():
    try:
        return os.path.ismount(SEEDBOX_MOUNT_POINT)
    except Exception:
        return False


def _startup_service_params(paths):
    return startup_service_params(paths, DOCKER_COMPOSE_PATH)


def update_startup_service(paths):
    return _media_paths().apply_startup_service(paths)


def default_disk_inventory_service():
    return DiskInventoryService(helper=HelperClientAdapter())


def default_disk_mount_service(helper=None, docker_client=None):
    helper = helper or HelperClientAdapter()
    return DiskMountService(
        helper=helper,
        dependency_inspector=lambda mountpoint: find_mount_dependencies(
            mountpoint,
            docker_client=docker_client,
            media_paths_config=MEDIA_PATHS_CONFIG,
            storage_plugin_config_dir=STORAGE_PLUGIN_CONFIG_DIR,
            default_media_paths=DEFAULT_MEDIA_PATHS,
        ),
    )


def default_media_paths_service(helper=None, repository=None):
    return MediaPathsService(
        helper=helper if helper is not None else HelperClientAdapter(),
        repository=repository if repository is not None else JsonFileRepository(),
        config_path_provider=lambda: MEDIA_PATHS_CONFIG,
        compose_path_provider=lambda: DOCKER_COMPOSE_PATH,
        defaults=DEFAULT_MEDIA_PATHS,
        startup_renderer=render_startup_files,
    )


def _disk_inventory():
    if has_app_context():
        service = current_app.extensions.get("disk_inventory_service")
        if service is not None:
            return service
    return default_disk_inventory_service()


def _disk_mounts():
    if has_app_context():
        service = current_app.extensions.get("disk_mount_service")
        if service is not None:
            return service
    return default_disk_mount_service()


def _media_paths():
    if has_app_context():
        service = current_app.extensions.get("media_paths_service")
        if service is not None:
            return service
    return default_media_paths_service()


def get_disk_inventory():
    """Get complete disk inventory with mount status via the inventory service."""
    return _disk_inventory().inventory()


@disk_manager.route('/api/disks/seedbox', methods=['GET'])
@login_required
def api_seedbox_get():
    config = load_seedbox_config()
    return jsonify({
        'config': config,
        'mounted': _seedbox_is_mounted()
    })


@disk_manager.route('/api/disks/seedbox', methods=['POST'])
@login_required
def api_seedbox_set():
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    data = request.get_json() or {}
    enabled = bool(data.get('enabled', False))
    host = str(data.get('host', '')).strip()
    username = str(data.get('username', '')).strip()
    remote_path = str(data.get('remote_path', '')).strip()
    port = data.get('port', 22)
    password = data.get('password', '')

    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid port'}), 400

    if enabled:
        if not host or not username or not remote_path:
            return jsonify({'error': 'host, username, and remote_path required'}), 400
        if not remote_path.startswith('/') or '..' in remote_path:
            return jsonify({'error': 'Invalid remote_path'}), 400
        if not password:
            return jsonify({'error': 'Password required'}), 400
        if port < 1 or port > 65535:
            return jsonify({'error': 'Invalid port'}), 400

        try:
            result = helper_call('seedbox_configure', {
                'host': host,
                'username': username,
                'password': password,
                'remote_path': remote_path,
                'port': port
            })
            if not result.get('success'):
                return jsonify({'error': result.get('error', 'Failed to configure seedbox')}), 500
        except HelperError as exc:
            return jsonify({'error': str(exc)}), 503
    else:
        try:
            result = helper_call('seedbox_disable', {})
            if not result.get('success'):
                return jsonify({'error': result.get('error', 'Failed to disable seedbox')}), 500
        except HelperError as exc:
            return jsonify({'error': str(exc)}), 503

    config = {
        'enabled': enabled,
        'host': host,
        'username': username,
        'port': port,
        'remote_path': remote_path,
        'mount_point': SEEDBOX_MOUNT_POINT
    }
    save_seedbox_config(config)
    return jsonify({'status': 'ok', 'config': config, 'mounted': _seedbox_is_mounted()})


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
        "add_to_fstab": true
    }
    """
    data = request.get_json() or {}

    uuid = data.get('uuid', '')
    mountpoint = data.get('mountpoint', '')
    fstype = data.get('fstype')
    add_to_fstab = data.get('add_to_fstab', True)

    try:
        return jsonify(_disk_mounts().mount(
            uuid=uuid,
            mountpoint=mountpoint,
            fstype=fstype,
            add_to_fstab=add_to_fstab,
            custom_options_supplied='options' in data,
        ))
    except MountValidationError as exc:
        payload = {'error': str(exc)}
        if exc.code:
            payload['code'] = exc.code
        if exc.code == 'mount_options_not_allowed':
            payload['message'] = 'Remove options and use the filesystem preset'
        if exc.details is not None:
            payload['details'] = exc.details
        return jsonify(payload), 400
    except MountOperationError as exc:
        payload = {'error': str(exc)}
        if exc.fstab_added is not None:
            payload['fstab_added'] = exc.fstab_added
        return jsonify(payload), 400
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

    try:
        return jsonify(_disk_mounts().unmount(
            mountpoint=mountpoint,
            remove_from_fstab=remove_from_fstab,
        ))
    except MountValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except MountDependencyCheckError as exc:
        return jsonify({
            'code': 'dependency_check_failed',
            'error': 'Unable to verify mount dependencies',
            'message': 'Restore dependency checks and retry',
            'details': exc.details,
        }), 503

    except MountInUseError as exc:
        dependencies = exc.dependencies
        return jsonify({
            'code': 'mount_in_use',
            'error': 'Unmount blocked',
            'message': 'Stop or reconfigure dependent services and retry',
            'details': [dependency.detail() for dependency in dependencies],
            'dependencies': [dependency.as_dict() for dependency in dependencies],
        }), 409

    except MountOperationError as exc:
        return jsonify({'error': str(exc)}), 400
    except HelperError as e:
        return jsonify({'error': str(e)}), 503


@disk_manager.route('/api/disks/media-paths', methods=['GET'])
@login_required
def api_get_media_paths():
    """Get configured media paths."""
    return jsonify({'paths': _media_paths().paths()})


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

    try:
        return jsonify(_media_paths().update(data))
    except MediaPathValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as e:
        return jsonify({'error': f'Failed to save paths: {str(e)}'}), 500


@disk_manager.route('/api/disks/startup-service/preview', methods=['GET'])
@login_required
def api_preview_startup_service():
    """Preview changes to startup service before applying."""
    return jsonify(_media_paths().preview_startup_service())


@disk_manager.route('/api/disks/startup-service', methods=['POST'])
@login_required
def api_regenerate_startup_service():
    """Regenerate mount-wait startup service."""
    result = _media_paths().apply_startup_service()
    if result.get('success'):
        return jsonify({'status': 'updated'})
    return jsonify({'error': result.get('error', 'Failed to update startup service')}), 503


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
            if fstype not in FSTAB_PRESETS:
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


# =============================================================================
# SMART Health API Endpoints
# =============================================================================

@disk_manager.route('/api/disks/smart', methods=['GET'])
@login_required
def api_smart_all():
    """
    Get SMART health data for all disks.

    Returns:
        {
            "disks": [
                {
                    "device": "/dev/sda",
                    "data": { ... SMART health data ... }
                },
                ...
            ]
        }
    """
    try:
        result = helper_call('smart_all_devices', {})
        if result.get('success'):
            # Process each device's raw smartctl data through parser
            processed_disks = []
            for disk in result.get('devices', []):
                device = disk.get('device', 'unknown')
                raw_data = disk.get('data', {})
                if raw_data:
                    parsed = parse_smartctl_json(raw_data)
                    processed_disks.append({
                        'device': device,
                        'data': parsed.to_dict()
                    })
                else:
                    processed_disks.append({
                        'device': device,
                        'data': {'device': device, 'error_message': disk.get('error', 'No SMART data')}
                    })
            return jsonify({'disks': processed_disks})
        return jsonify({'error': result.get('error', 'Failed to get SMART data')}), 503
    except HelperError as e:
        return jsonify({'error': str(e), 'helper_available': False}), 503


@disk_manager.route('/api/disks/<path:device>/smart', methods=['GET'])
@login_required
def api_smart_device(device):
    """
    Get SMART health data for a specific device.

    Args:
        device: Device path (e.g., sda or nvme0n1). Will be prefixed with /dev/.

    Query params:
        use_sat: Set to 'true' to use SAT passthrough for USB drives

    Returns:
        SMART health data for the device
    """
    # Sanitize device name - only allow alphanumeric and common device name chars
    if not device or not all(c.isalnum() or c in '-_' for c in device):
        return jsonify({'error': 'Invalid device name'}), 400

    device_path = f'/dev/{device}'
    use_sat = request.args.get('use_sat', 'false').lower() == 'true'

    try:
        result = helper_call('smart_info', {
            'device': device_path,
            'use_sat': use_sat
        })
        if result.get('success'):
            # Parse raw smartctl JSON into SmartHealth format
            raw_data = result.get('data', {})
            parsed = parse_smartctl_json(raw_data)
            return jsonify(parsed.to_dict())
        return jsonify({'error': result.get('error', 'Failed to get SMART data')}), 503
    except HelperError as e:
        return jsonify({'error': str(e), 'helper_available': False}), 503


@disk_manager.route('/api/disks/<path:device>/smart-test', methods=['POST'])
@login_required
def api_smart_test(device):
    """
    Run a SMART self-test on a device.

    Args:
        device: Device path (e.g., sda or nvme0n1). Will be prefixed with /dev/.

    Request body:
        {
            "test_type": "short" | "long" | "conveyance"
        }

    Returns:
        Result of starting the test
    """
    # Sanitize device name
    if not device or not all(c.isalnum() or c in '-_' for c in device):
        return jsonify({'error': 'Invalid device name'}), 400

    data = request.get_json() or {}
    test_type = data.get('test_type', 'short')

    if test_type not in ['short', 'long', 'conveyance']:
        return jsonify({'error': 'Invalid test type. Use: short, long, or conveyance'}), 400

    device_path = f'/dev/{device}'
    use_sat = data.get('use_sat', False)

    try:
        result = helper_call('smart_test', {
            'device': device_path,
            'test_type': test_type,
            'use_sat': use_sat
        })
        if result.get('success'):
            return jsonify({
                'status': 'started',
                'test_type': test_type,
                'message': result.get('message', 'SMART test started')
            })
        return jsonify({'error': result.get('error', 'Failed to start SMART test')}), 503
    except HelperError as e:
        return jsonify({'error': str(e), 'helper_available': False}), 503
