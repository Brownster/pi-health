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
from stack_manager import list_stacks, validate_stack_name, get_stack_path, find_compose_file, backup_stack, run_compose_command

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
STACKS_PATH = os.getenv('STACKS_PATH', '/opt/stacks')

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


def _load_stack_compose(stack_dir):
    """Load a stack compose file as a dict."""
    compose_path = find_compose_file(stack_dir)
    if not compose_path or not os.path.exists(compose_path):
        return None, None
    try:
        with open(compose_path, 'r') as f:
            data = yaml.safe_load(f)
        return (data if isinstance(data, dict) else None), compose_path
    except Exception:
        return None, compose_path


def _save_stack_compose(stack_dir, data, filename=None):
    """Save compose data to a stack with atomic write."""
    os.makedirs(stack_dir, exist_ok=True)
    compose_path = filename or os.path.join(stack_dir, 'compose.yaml')
    compose_dir = os.path.dirname(os.path.abspath(compose_path))
    os.makedirs(compose_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=compose_dir, suffix='.yml')
    try:
        with os.fdopen(fd, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(temp_path, compose_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
    return compose_path


def _list_stack_services(stack_name=None):
    """Get service names across stacks or for a single stack."""
    services = []
    stacks, err = list_stacks()
    if err:
        return services
    for stack in stacks:
        name = stack.get('name')
        if stack_name and name != stack_name:
            continue
        stack_dir = get_stack_path(name)
        data, _ = _load_stack_compose(stack_dir)
        if not data:
            continue
        stack_services = data.get('services', {})
        if isinstance(stack_services, dict):
            services.extend(stack_services.keys())
    return services


def _find_service_stacks(service_name):
    """Find which stacks contain a given service."""
    stacks, err = list_stacks()
    if err:
        return []
    matches = []
    for stack in stacks:
        name = stack.get('name')
        stack_dir = get_stack_path(name)
        data, _ = _load_stack_compose(stack_dir)
        if not data:
            continue
        services = data.get('services', {})
        if isinstance(services, dict) and service_name in services:
            matches.append(name)
    return matches


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
    services = _list_stack_services()
    service_map = {}
    for svc in services:
        service_map.setdefault(svc, [])
        service_map[svc].extend(_find_service_stacks(svc))
    return jsonify({'services': sorted(set(services)), 'service_stacks': service_map})


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
        "target_stack": "media" | "new",
        "stack_name": "media",
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

    target_stack = data.get('target_stack')
    new_stack_name = data.get('stack_name') or item_id

    if target_stack and target_stack != 'new':
        valid, error = validate_stack_name(target_stack)
        if not valid:
            return jsonify({'error': error}), 400
        stack_dir = get_stack_path(target_stack)
        if not os.path.isdir(stack_dir):
            return jsonify({'error': f'Stack not found: {target_stack}'}), 404
        active_stack = target_stack
    else:
        valid, error = validate_stack_name(new_stack_name)
        if not valid:
            return jsonify({'error': error}), 400
        stack_dir = get_stack_path(new_stack_name)
        if os.path.exists(stack_dir):
            return jsonify({'error': f'Stack already exists: {new_stack_name}'}), 409
        active_stack = new_stack_name

    # Check dependencies within target stack
    installed_services = _list_stack_services(active_stack)
    skip_dep_check = data.get('skip_dependency_check', False)

    if not skip_dep_check:
        satisfied, missing = _check_dependencies(item, installed_services)
        if not satisfied:
            return jsonify({
                'error': 'Missing dependencies',
                'missing_dependencies': missing,
                'message': f'Install these first in stack {active_stack}: {", ".join(missing)}'
            }), 400

    if item_id in installed_services:
        return jsonify({'error': f'Service already installed in stack {active_stack}: {item_id}'}), 409

    # Render the service template
    service_template = item.get('service', {})
    rendered_service = _render_template(service_template, values)

    unresolved = _find_unresolved_placeholders(rendered_service)
    if unresolved:
        return jsonify({
            'error': 'Template has unresolved variables',
            'unresolved': unresolved
        }), 400

    # Load or create compose file in the stack
    compose_data, compose_path = _load_stack_compose(stack_dir)
    if compose_data is None:
        compose_data = {
            'version': '3.8',
            'services': {}
        }

    if 'services' not in compose_data:
        compose_data['services'] = {}

    backup_file = None
    if os.path.exists(stack_dir):
        backup_file = backup_stack(active_stack)

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

    try:
        _save_stack_compose(stack_dir, compose_data, compose_path)
    except Exception as e:
        return jsonify({
            'error': f'Failed to save compose file: {str(e)}',
            'backup': backup_file
        }), 500

    result = {
        'status': 'installed',
        'id': item_id,
        'name': item.get('name', item_id),
        'backup': backup_file,
        'stack': active_stack
    }

    start_service = data.get('start_service', False)
    if start_service:
        start_result, start_error = run_compose_command(active_stack, 'up')
        result['started'] = bool(start_result and start_result.get('success'))
        if start_error:
            result['start_error'] = start_error
        elif start_result and not start_result.get('success'):
            result['start_error'] = start_result.get('stderr', 'Failed to start service')

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
        "check_dependents": true,
        "target_stack": "media"
    }
    """
    data = request.get_json() or {}

    item_id = data.get('id')
    if not item_id:
        return jsonify({'error': 'Missing app id'}), 400

    target_stack = data.get('target_stack')
    stacks_with_service = _find_service_stacks(item_id)
    if not stacks_with_service:
        return jsonify({'error': f'Service not installed: {item_id}'}), 404
    if target_stack:
        if target_stack not in stacks_with_service:
            return jsonify({'error': f'Service not found in stack: {target_stack}'}), 404
        active_stack = target_stack
    else:
        if len(stacks_with_service) > 1:
            return jsonify({'error': 'Service exists in multiple stacks', 'stacks': stacks_with_service}), 409
        active_stack = stacks_with_service[0]

    # Check for dependent services (services that require this one)
    check_dependents = data.get('check_dependents', True)
    if check_dependents:
        dependents = []
        items = _load_catalog_items()
        stack_services = _list_stack_services(active_stack)
        for installed_id in stack_services:
            if installed_id == item_id:
                continue
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

    stack_dir = get_stack_path(active_stack)
    compose_data, compose_path = _load_stack_compose(stack_dir)
    if compose_data is None:
        return jsonify({'error': 'Compose file not found'}), 404

    # Optionally stop the service first
    stop_service = data.get('stop_service', True)
    stop_result = None
    if stop_service:
        stop_result, stop_error = run_compose_command(active_stack, 'stop')
        if stop_error:
            stop_result = {'stopped': False, 'error': stop_error}

    # Backup before modifying
    backup_file = backup_stack(active_stack)

    # Remove the service from compose
    if 'services' in compose_data and item_id in compose_data['services']:
        del compose_data['services'][item_id]

    try:
        _save_stack_compose(stack_dir, compose_data, compose_path)
    except Exception as e:
        return jsonify({
            'error': f'Failed to save compose file: {str(e)}',
            'backup': backup_file
        }), 500

    result = {
        'status': 'removed',
        'id': item_id,
        'backup': backup_file,
        'stack': active_stack
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
        "id": "sonarr",
        "target_stack": "media"
    }
    """
    data = request.get_json() or {}

    item_id = data.get('id')
    if not item_id:
        return jsonify({'error': 'Missing app id'}), 400

    item = _get_catalog_item(item_id)
    if not item:
        return jsonify({'error': f'Catalog item not found: {item_id}'}), 404

    target_stack = data.get('target_stack')
    if target_stack:
        installed_services = _list_stack_services(target_stack)
    else:
        installed_services = _list_stack_services()
    satisfied, missing = _check_dependencies(item, installed_services)

    return jsonify({
        'id': item_id,
        'requires': item.get('requires', []) or [],
        'satisfied': satisfied,
        'missing': missing,
        'installed_services': installed_services
    })
