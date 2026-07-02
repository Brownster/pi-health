"""
Disk Manager Module

Provides disk inventory, mount management, and storage configuration.
Communicates with the privileged helper service over Unix socket.
"""

import os
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
from seedbox_service import (
    SeedboxOperationError,
    SeedboxService,
    SeedboxUnavailableError,
    SeedboxValidationError,
)
from disk_suggestion_service import DiskSuggestionService, parse_size_to_gb
from smart_service import SmartOperationError, SmartService, SmartValidationError
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
SEEDBOX_MOUNT_POINT = '/mnt/seedbox'




def load_media_paths():
    """Load media paths configuration."""
    return _media_paths().paths()


def save_media_paths(paths):
    """Save media paths configuration."""
    _media_paths().save(paths)


def load_seedbox_config():
    """Load seedbox mount configuration."""
    return _seedbox().config()


def save_seedbox_config(config):
    """Save seedbox mount configuration."""
    _seedbox().save(config)


def _seedbox_is_mounted():
    return _seedbox().is_mounted()


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


def default_seedbox_service(helper=None, repository=None):
    return SeedboxService(
        helper=helper if helper is not None else HelperClientAdapter(),
        repository=repository if repository is not None else JsonFileRepository(),
        config_path_provider=lambda: SEEDBOX_CONFIG,
        mount_point_provider=lambda: SEEDBOX_MOUNT_POINT,
        mounted_reader=os.path.ismount,
    )


def default_disk_suggestion_service(inventory_service=None):
    if inventory_service is None:
        inventory_service = default_disk_inventory_service()
    return DiskSuggestionService(
        inventory_reader=inventory_service.inventory,
        supported_filesystems=FSTAB_PRESETS,
    )


def default_smart_service(helper=None):
    return SmartService(
        helper=helper if helper is not None else HelperClientAdapter(),
        parser=parse_smartctl_json,
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


def _seedbox():
    if has_app_context():
        service = current_app.extensions.get("seedbox_service")
        if service is not None:
            return service
    return default_seedbox_service()


def _disk_suggestions():
    if has_app_context():
        service = current_app.extensions.get("disk_suggestion_service")
        if service is not None:
            return service
    return default_disk_suggestion_service(_disk_inventory())


def _smart():
    if has_app_context():
        service = current_app.extensions.get("smart_service")
        if service is not None:
            return service
    return default_smart_service()


def get_disk_inventory():
    """Get complete disk inventory with mount status via the inventory service."""
    return _disk_inventory().inventory()


@disk_manager.route('/api/disks/seedbox', methods=['GET'])
@login_required
def api_seedbox_get():
    return jsonify(_seedbox().state())


@disk_manager.route('/api/disks/seedbox', methods=['POST'])
@login_required
def api_seedbox_set():
    data = request.get_json() or {}
    try:
        return jsonify(_seedbox().configure(data))
    except SeedboxValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except SeedboxUnavailableError as exc:
        return jsonify({'error': str(exc)}), 503
    except SeedboxOperationError as exc:
        return jsonify({'error': str(exc)}), 500
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503


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
        return jsonify(_disk_suggestions().suggestions())
    except HelperError as e:
        return jsonify({'error': str(e)}), 503


def _parse_size_to_gb(size_str):
    """Parse a size string like '500G' or '1T' to gigabytes."""
    return parse_size_to_gb(size_str)


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
        return jsonify(_smart().all_devices())
    except SmartOperationError as exc:
        return jsonify({'error': str(exc)}), 503
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
    use_sat = request.args.get('use_sat', 'false').lower() == 'true'

    try:
        return jsonify(_smart().device(device, use_sat=use_sat))
    except SmartValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except SmartOperationError as exc:
        return jsonify({'error': str(exc)}), 503
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
    data = request.get_json() or {}
    test_type = data.get('test_type', 'short')
    use_sat = data.get('use_sat', False)

    try:
        return jsonify(_smart().start_test(
            device,
            test_type=test_type,
            use_sat=use_sat,
        ))
    except SmartValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except SmartOperationError as exc:
        return jsonify({'error': str(exc)}), 503
    except HelperError as e:
        return jsonify({'error': str(e), 'helper_available': False}), 503
