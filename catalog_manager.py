"""App Catalog Manager transport.

Provides an app-store style experience for managing Docker services. Domain
behavior lives in :mod:`catalog_service`; this module wires the Flask blueprint,
supplies environment-specific providers (catalog dir, media paths, compose I/O),
and preserves the historical module-level functions used by internal callers and
tests.
"""
import os
import json
from flask import Blueprint, current_app, has_app_context, jsonify, request, session
from auth_utils import csrf_protect, login_required
from compose_yaml import ComposeYamlError, dump_compose_yaml, load_compose_yaml
from runtime_paths import CONFIG_DIR as RUNTIME_CONFIG_DIR, STATIC_CATALOG_DIR
from stack_manager import (
    ComposeFileConflictError,
    atomic_write_text,
    backup_stack,
    find_compose_file,
    get_stack_path,
    list_stacks,
    run_compose_command,
    stack_lock,
    stream_compose_command,
    validate_stack_name,
)
from catalog_service import (  # noqa: F401  (re-exported for compatibility)
    CATALOG_COMPOSE_SECTIONS,
    TEMPLATE_VAR_PATTERN,
    CatalogComposeSectionError,
    CatalogError,
    CatalogService,
    _check_dependencies,
    _find_unresolved_placeholders,
    _merge_compose_section,
    _render_template,
    _summarize_item,
    _validate_install_request,
)

catalog_manager = Blueprint('catalog_manager', __name__)

# Media paths config (shared with disk_manager)
MEDIA_PATHS_CONFIG = str(RUNTIME_CONFIG_DIR / 'media_paths.json')

CATALOG_DIR = os.getenv('CATALOG_DIR', str(STATIC_CATALOG_DIR))
STACKS_PATH = os.getenv('STACKS_PATH', '/opt/stacks')


def _load_media_paths():
    """Load configured media paths for template defaults."""
    defaults = {
        'downloads': '/mnt/downloads',
        'storage': '/mnt/storage',
        'backup': '/mnt/backup',
        'config': '/home/pi/docker',
    }
    try:
        if os.path.exists(MEDIA_PATHS_CONFIG):
            with open(MEDIA_PATHS_CONFIG) as f:
                defaults.update(json.load(f))
    except Exception:
        pass
    return defaults


def _load_stack_compose(stack_dir):
    """Load a stack compose file with round-trip presentation metadata."""
    compose_path = find_compose_file(stack_dir)
    if not compose_path or not os.path.exists(compose_path):
        return None, None
    try:
        with open(compose_path) as f:
            data = load_compose_yaml(f.read())
        return data, compose_path
    except OSError as exc:
        raise ComposeYamlError(f'Unable to read compose file: {exc}') from exc


def _save_stack_compose(stack_dir, data, filename=None):
    """Save compose data atomically without discarding YAML presentation."""
    os.makedirs(stack_dir, exist_ok=True)
    compose_path = filename or os.path.join(stack_dir, 'compose.yaml')
    atomic_write_text(compose_path, dump_compose_yaml(data))
    return compose_path


# =============================================================================
# Service construction and resolution
# =============================================================================

def default_catalog_service():
    """Build a CatalogService bound to this module's providers and stack ops."""
    return CatalogService(
        catalog_dir_provider=lambda: CATALOG_DIR,
        media_paths_loader=_load_media_paths,
        load_stack_compose=lambda stack_dir: _load_stack_compose(stack_dir),
        save_stack_compose=lambda stack_dir, data, filename=None: _save_stack_compose(
            stack_dir, data, filename
        ),
        list_stacks=list_stacks,
        get_stack_path=get_stack_path,
        validate_stack_name=validate_stack_name,
        backup_stack=backup_stack,
        run_compose_command=lambda *args, **kwargs: run_compose_command(*args, **kwargs),
        stream_compose_command=lambda stack, command: stream_compose_command(stack, command),
        stack_lock=stack_lock,
        compose_conflict_error=ComposeFileConflictError,
    )


def _catalog_service():
    if has_app_context():
        service = current_app.extensions.get("catalog_service")
        if service is not None:
            return service
    return default_catalog_service()


# =============================================================================
# API Endpoints
# =============================================================================

@catalog_manager.route('/api/catalog', methods=['GET'])
@login_required
def api_catalog_list():
    return jsonify(_catalog_service().list_items())


@catalog_manager.route('/api/catalog/<item_id>', methods=['GET'])
@login_required
def api_catalog_get(item_id):
    apply_paths = request.args.get('apply_media_paths', 'false').lower() == 'true'
    try:
        return jsonify(_catalog_service().get_item(item_id, apply_media_paths=apply_paths))
    except CatalogError as exc:
        return jsonify(exc.payload), exc.status_code


@catalog_manager.route('/api/catalog/status', methods=['GET'])
@login_required
def api_catalog_status():
    return jsonify(_catalog_service().status())


@catalog_manager.route('/api/catalog/install', methods=['POST'])
@login_required
@csrf_protect
def api_catalog_install():
    data = request.get_json() or {}
    try:
        result, status = _catalog_service().install(
            data,
            operation_registry=current_app.extensions["operation_registry"],
            owner=session['csrf_token'],
            username=session.get('username', 'unknown'),
        )
    except CatalogError as exc:
        return jsonify(exc.payload), exc.status_code
    return jsonify(result), status


@catalog_manager.route('/api/catalog/operations/<operation_id>/stream', methods=['GET'])
@login_required
def api_stream_catalog_operation(operation_id):
    from operation_sse import stream_operation_response

    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind='catalog-install',
    )


@catalog_manager.route('/api/catalog/remove', methods=['POST'])
@login_required
def api_catalog_remove():
    data = request.get_json() or {}
    try:
        return jsonify(_catalog_service().remove(data))
    except CatalogError as exc:
        return jsonify(exc.payload), exc.status_code


@catalog_manager.route('/api/catalog/check-dependencies', methods=['POST'])
@login_required
def api_check_dependencies():
    data = request.get_json() or {}
    try:
        return jsonify(_catalog_service().check_dependencies(data))
    except CatalogError as exc:
        return jsonify(exc.payload), exc.status_code
