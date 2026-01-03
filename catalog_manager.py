"""
App Catalog Manager

Provides an app-store style experience for managing Docker services.
Templates are stored in catalog/ as YAML files.
"""
import os
import re
import shutil
import tempfile
import json
import yaml
from datetime import datetime
from flask import Blueprint, jsonify, request
from auth_utils import login_required

catalog_manager = Blueprint('catalog_manager', __name__)

# Media paths config (shared with disk_manager)
MEDIA_PATHS_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'config',
    'media_paths.json'
)


def _load_media_paths():
    """Load configured media paths for template defaults."""
    defaults = {
        'downloads': '/mnt/downloads',
        'storage': '/mnt/storage',
        'backup': '/mnt/backup',
        'config': '/home/pi/docker'
    }
    try:
        if os.path.exists(MEDIA_PATHS_CONFIG):
            with open(MEDIA_PATHS_CONFIG, 'r') as f:
                config = json.load(f)
                defaults.update(config)
    except Exception:
        pass
    return defaults

CATALOG_DIR = os.getenv('CATALOG_DIR', 'catalog')
DOCKER_COMPOSE_PATH = os.getenv('DOCKER_COMPOSE_PATH', './docker-compose.yml')
BACKUP_DIR = os.getenv('CATALOG_BACKUP_DIR', './backups')

# Template variable pattern: {{KEY}}
TEMPLATE_VAR_PATTERN = re.compile(r'\{\{(\w+)\}\}')


def _catalog_path():
    return os.path.abspath(CATALOG_DIR)


def _load_catalog_items():
    """Load all catalog items from YAML files."""
    items = []
    catalog_dir = _catalog_path()
    if not os.path.isdir(catalog_dir):
        return items

    for filename in os.listdir(catalog_dir):
        if not (filename.endswith('.yaml') or filename.endswith('.yml')):
            continue
        path = os.path.join(catalog_dir, filename)
        try:
            with open(path, 'r') as f:
                data = yaml.safe_load(f)
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        item_id = data.get('id')
        if not item_id:
            continue

        data['_source'] = filename
        items.append(data)

    return items


def _get_catalog_item(item_id):
    """Get a specific catalog item by ID."""
    items = _load_catalog_items()
    for item in items:
        if item.get('id') == item_id:
            return item
    return None


def _summarize_item(item):
    """Create a summary of a catalog item for listing."""
    return {
        'id': item.get('id'),
        'name': item.get('name') or item.get('id'),
        'description': item.get('description', ''),
        'requires': item.get('requires', []) or [],
        'disabled_by_default': bool(item.get('disabled_by_default', False)),
        'source': item.get('_source', ''),
    }


def _load_compose_file():
    """Load the Docker Compose file as a dict."""
    if not os.path.exists(DOCKER_COMPOSE_PATH):
        return None

    try:
        with open(DOCKER_COMPOSE_PATH, 'r') as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _load_compose_services():
    """Get list of service names from compose file."""
    data = _load_compose_file()
    if not data:
        return []

    services = data.get('services', {})
    if isinstance(services, dict):
        return list(services.keys())
    return []


def _ensure_backup_directory():
    """Ensure the backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _backup_compose_file():
    """Create a timestamped backup of the compose file."""
    if not os.path.exists(DOCKER_COMPOSE_PATH):
        return None

    _ensure_backup_directory()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BACKUP_DIR, f"docker-compose-{timestamp}.yml")
    shutil.copy(DOCKER_COMPOSE_PATH, backup_file)

    # Keep only the 10 most recent backups
    backups = sorted([
        f for f in os.listdir(BACKUP_DIR)
        if f.startswith('docker-compose-') and f.endswith('.yml')
    ])
    if len(backups) > 10:
        for old_backup in backups[:-10]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old_backup))
            except Exception:
                pass

    return backup_file


def _save_compose_file(data):
    """Save compose data to file with atomic write."""
    # Ensure parent directory exists
    compose_dir = os.path.dirname(os.path.abspath(DOCKER_COMPOSE_PATH))
    os.makedirs(compose_dir, exist_ok=True)

    # Atomic write: temp file + rename
    fd, temp_path = tempfile.mkstemp(dir=compose_dir, suffix='.yml')
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(temp_path, DOCKER_COMPOSE_PATH)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _render_template(service_dict, values):
    """
    Render a service template by replacing {{KEY}} placeholders with values.
    Returns a deep copy with substitutions applied.
    """
    def substitute(obj):
        if isinstance(obj, str):
            # Replace all {{KEY}} patterns
            def replacer(match):
                key = match.group(1)
                return str(values.get(key, match.group(0)))
            return TEMPLATE_VAR_PATTERN.sub(replacer, obj)
        elif isinstance(obj, dict):
            return {k: substitute(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [substitute(item) for item in obj]
        else:
            return obj

    return substitute(service_dict)


def _find_unresolved_placeholders(obj, path=""):
    """Find unresolved {{KEY}} placeholders in rendered template."""
    unresolved = []

    if isinstance(obj, str):
        for match in TEMPLATE_VAR_PATTERN.finditer(obj):
            unresolved.append(f"{path}{match.group(0)}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}{key}."
            unresolved.extend(_find_unresolved_placeholders(value, next_path))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            next_path = f"{path}[{idx}]."
            unresolved.extend(_find_unresolved_placeholders(value, next_path))

    return unresolved


def _merge_compose_section(compose_data, section, section_data):
    """Merge a top-level compose section like networks/volumes."""
    if not section_data:
        return

    if section not in compose_data or not isinstance(compose_data.get(section), dict):
        compose_data[section] = {}

    for key, value in section_data.items():
        if key not in compose_data[section]:
            compose_data[section][key] = value


def _validate_install_request(item, values):
    """
    Validate install request.
    Returns (is_valid, error_message).
    """
    fields = item.get('fields', [])

    # Check all required fields have values
    for field in fields:
        key = field.get('key')
        if not key:
            continue
        required = field.get('required', True)
        # Use default if no value provided
        if key not in values or values[key] == '':
            default = field.get('default', '')
            if default == '' and required:
                return False, f"Missing required field: {field.get('label', key)}"
            if default != '':
                values[key] = default

    return True, None


def _check_dependencies(item, installed_services):
    """
    Check if all dependencies are satisfied.
    Returns (satisfied, missing_deps).
    """
    requires = item.get('requires', []) or []
    missing = [dep for dep in requires if dep not in installed_services]
    return len(missing) == 0, missing


# =============================================================================
# API Endpoints
# =============================================================================

@catalog_manager.route('/api/catalog', methods=['GET'])
@login_required
def api_catalog_list():
    """List all catalog items."""
    items = _load_catalog_items()
    return jsonify({'items': [_summarize_item(item) for item in items]})


@catalog_manager.route('/api/catalog/<item_id>', methods=['GET'])
@login_required
def api_catalog_get(item_id):
    """Get a specific catalog item with full details.

    Query params:
        apply_media_paths: If 'true', apply configured media paths to field defaults
    """
    item = _get_catalog_item(item_id)
    if not item:
        return jsonify({'error': 'Catalog item not found'}), 404

    # Optionally apply media paths to field defaults
    apply_paths = request.args.get('apply_media_paths', 'false').lower() == 'true'
    if apply_paths:
        media_paths = _load_media_paths()
        # Map common field keys to media path keys
        path_mapping = {
            'CONFIG_DIR': 'config',
            'DOWNLOADS_DIR': 'downloads',
            'MEDIA_DIR': 'storage',
            'STORAGE_DIR': 'storage',
            'BACKUP_DIR': 'backup'
        }
        # Create a copy with updated defaults
        item = dict(item)
        if 'fields' in item:
            item['fields'] = []
            for field in _get_catalog_item(item_id).get('fields', []):
                field_copy = dict(field)
                key = field_copy.get('key', '')
                if key in path_mapping:
                    path_key = path_mapping[key]
                    if path_key in media_paths:
                        field_copy['default'] = media_paths[path_key]
                item['fields'].append(field_copy)

    return jsonify({'item': item})


@catalog_manager.route('/api/catalog/status', methods=['GET'])
@login_required
def api_catalog_status():
    """Get list of installed services from compose file."""
    services = _load_compose_services()
    return jsonify({'services': services})


@catalog_manager.route('/api/catalog/install', methods=['POST'])
@login_required
def api_catalog_install():
    """
    Install an app from the catalog.

    Request body:
    {
        "id": "sonarr",
        "values": {
            "TZ": "Europe/London",
            "CONFIG_DIR": "/home/pi/docker",
            ...
        },
        "skip_dependency_check": false,
        "start_service": true
    }
    """
    data = request.get_json() or {}

    item_id = data.get('id')
    if not item_id:
        return jsonify({'error': 'Missing app id'}), 400

    # Load catalog item
    item = _get_catalog_item(item_id)
    if not item:
        return jsonify({'error': f'Catalog item not found: {item_id}'}), 404

    # Get values (with defaults filled in)
    values = dict(data.get('values', {}))

    # Validate required fields
    valid, error = _validate_install_request(item, values)
    if not valid:
        return jsonify({'error': error}), 400

    # Check dependencies
    installed_services = _load_compose_services()
    skip_dep_check = data.get('skip_dependency_check', False)

    if not skip_dep_check:
        satisfied, missing = _check_dependencies(item, installed_services)
        if not satisfied:
            return jsonify({
                'error': 'Missing dependencies',
                'missing_dependencies': missing,
                'message': f'Install these first: {", ".join(missing)}'
            }), 400

    # Check if already installed
    if item_id in installed_services:
        return jsonify({'error': f'Service already installed: {item_id}'}), 409

    # Render the service template
    service_template = item.get('service', {})
    rendered_service = _render_template(service_template, values)

    unresolved = _find_unresolved_placeholders(rendered_service)
    if unresolved:
        return jsonify({
            'error': 'Template has unresolved variables',
            'unresolved': unresolved
        }), 400

    # Load or create compose file
    compose_data = _load_compose_file()
    if compose_data is None:
        # Create new compose file structure
        compose_data = {
            'version': '3.8',
            'services': {}
        }

    # Ensure services dict exists
    if 'services' not in compose_data:
        compose_data['services'] = {}

    # Backup before modifying
    backup_file = _backup_compose_file()

    # Add the new service
    compose_data['services'][item_id] = rendered_service

    # Merge required top-level sections
    for section in ('networks', 'volumes'):
        section_data = item.get(section)
        if not section_data:
            continue
        rendered_section = _render_template(section_data, values)
        unresolved_section = _find_unresolved_placeholders(rendered_section)
        if unresolved_section:
            return jsonify({
                'error': 'Template has unresolved variables',
                'unresolved': unresolved_section
            }), 400
        _merge_compose_section(compose_data, section, rendered_section)

    # Save compose file
    try:
        _save_compose_file(compose_data)
    except Exception as e:
        return jsonify({
            'error': f'Failed to save compose file: {str(e)}',
            'backup': backup_file
        }), 500

    result = {
        'status': 'installed',
        'id': item_id,
        'name': item.get('name', item_id),
        'backup': backup_file
    }

    # Optionally start the service
    start_service = data.get('start_service', False)
    if start_service:
        try:
            import subprocess
            compose_dir = os.path.dirname(os.path.abspath(DOCKER_COMPOSE_PATH))
            proc = subprocess.run(
                ['docker', 'compose', 'up', '-d', item_id],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            result['started'] = proc.returncode == 0
            if proc.returncode != 0:
                result['start_error'] = proc.stderr
        except Exception as e:
            result['started'] = False
            result['start_error'] = str(e)

    return jsonify(result)


@catalog_manager.route('/api/catalog/remove', methods=['POST'])
@login_required
def api_catalog_remove():
    """
    Remove an installed app.

    Request body:
    {
        "id": "sonarr",
        "stop_service": true,
        "check_dependents": true
    }
    """
    data = request.get_json() or {}

    item_id = data.get('id')
    if not item_id:
        return jsonify({'error': 'Missing app id'}), 400

    # Check if service exists
    installed_services = _load_compose_services()
    if item_id not in installed_services:
        return jsonify({'error': f'Service not installed: {item_id}'}), 404

    # Check for dependent services (services that require this one)
    check_dependents = data.get('check_dependents', True)
    if check_dependents:
        dependents = []
        items = _load_catalog_items()
        for installed_id in installed_services:
            if installed_id == item_id:
                continue
            # Find the catalog item for this installed service
            for cat_item in items:
                if cat_item.get('id') == installed_id:
                    requires = cat_item.get('requires', []) or []
                    if item_id in requires:
                        dependents.append(installed_id)
                    break

        if dependents:
            return jsonify({
                'error': 'Cannot remove: other services depend on this',
                'dependents': dependents,
                'message': f'Remove these first: {", ".join(dependents)}'
            }), 400

    # Load compose file
    compose_data = _load_compose_file()
    if compose_data is None:
        return jsonify({'error': 'Compose file not found'}), 404

    # Optionally stop the service first
    stop_service = data.get('stop_service', True)
    stop_result = None
    if stop_service:
        try:
            import subprocess
            compose_dir = os.path.dirname(os.path.abspath(DOCKER_COMPOSE_PATH))
            proc = subprocess.run(
                ['docker', 'compose', 'stop', item_id],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            stop_result = {
                'stopped': proc.returncode == 0,
                'output': proc.stdout if proc.returncode == 0 else proc.stderr
            }
            # Also remove the container
            subprocess.run(
                ['docker', 'compose', 'rm', '-f', item_id],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as e:
            stop_result = {'stopped': False, 'error': str(e)}

    # Backup before modifying
    backup_file = _backup_compose_file()

    # Remove the service from compose
    if 'services' in compose_data and item_id in compose_data['services']:
        del compose_data['services'][item_id]

    # Save compose file
    try:
        _save_compose_file(compose_data)
    except Exception as e:
        return jsonify({
            'error': f'Failed to save compose file: {str(e)}',
            'backup': backup_file
        }), 500

    result = {
        'status': 'removed',
        'id': item_id,
        'backup': backup_file
    }

    if stop_result:
        result['stop_result'] = stop_result

    return jsonify(result)


@catalog_manager.route('/api/catalog/check-dependencies', methods=['POST'])
@login_required
def api_check_dependencies():
    """
    Check if dependencies are satisfied for an app.

    Request body:
    {
        "id": "sonarr"
    }
    """
    data = request.get_json() or {}

    item_id = data.get('id')
    if not item_id:
        return jsonify({'error': 'Missing app id'}), 400

    item = _get_catalog_item(item_id)
    if not item:
        return jsonify({'error': f'Catalog item not found: {item_id}'}), 404

    installed_services = _load_compose_services()
    satisfied, missing = _check_dependencies(item, installed_services)

    return jsonify({
        'id': item_id,
        'requires': item.get('requires', []) or [],
        'satisfied': satisfied,
        'missing': missing,
        'installed_services': installed_services
    })
