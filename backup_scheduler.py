"""Backup Scheduler transport.

Creates compressed backups of docker config + stacks on a schedule and restores
them. Domain behavior lives in :mod:`backup_service`; this module wires the Flask
blueprint, supplies environment-specific providers, and preserves the historical
module-level functions used by internal callers and tests.
"""

from flask import Blueprint, current_app, has_app_context, jsonify, request

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from auth_utils import login_required
from disk_manager import load_media_paths
from helper_client import HelperError, helper_available, helper_call
from ports import ApschedulerAdapter, JsonFileRepository
from runtime_paths import (
    CONFIG_DIR as RUNTIME_CONFIG_DIR,
    CREDENTIALS_FILE,
    SNAPRAID_LOG_DIR,
    STATE_DIR as RUNTIME_STATE_DIR,
    STORAGE_PLUGIN_CONFIG_DIR,
    STORAGE_PLUGIN_STATE_DIR,
)
from backup_service import (  # noqa: F401  (re-exported for compatibility)
    DEFAULT_CONFIG,
    DEFAULT_EXCLUDES,
    SCHEDULE_PRESETS,
    BackupConfigError,
    BackupHelperUnavailable,
    BackupNotFound,
    BackupOperationError,
    BackupService,
    list_backups,
)

backup_scheduler = Blueprint('backup_scheduler', __name__)

CONFIG_DIR = str(RUNTIME_STATE_DIR)
CONFIG_FILE = str(RUNTIME_STATE_DIR / 'backup_config.json')
MEDIA_LAYOUT_CONFIG = RUNTIME_CONFIG_DIR / "media_layout.json"
MEDIA_PROFILE_CONFIG = RUNTIME_CONFIG_DIR / "media_profile.json"

# Dedicated background scheduler for backup jobs (separate from other schedulers).
scheduler = BackgroundScheduler(daemon=True)


# =============================================================================
# Environment-specific providers (kept out of the neutral service)
# =============================================================================

def _default_config():
    """Build defaults, overriding backup/config dirs from configured media paths."""
    defaults = DEFAULT_CONFIG.copy()
    paths = load_media_paths()
    defaults['dest_dir'] = paths.get('backup', defaults['dest_dir'])
    defaults['config_dir'] = paths.get('config', defaults['config_dir'])
    return defaults


def _get_sources(config):
    """Assemble the primary backup source paths for a config."""
    sources = []
    config_dir = config.get('config_dir', '').strip()
    stacks_path = config.get('stacks_path', '').strip()
    if config_dir:
        sources.append(config_dir)
    if stacks_path:
        sources.append(stacks_path)
    sources.extend([str(RUNTIME_CONFIG_DIR), str(RUNTIME_STATE_DIR)])
    sources.extend([str(MEDIA_LAYOUT_CONFIG), str(MEDIA_PROFILE_CONFIG)])
    if config.get('include_env', True):
        sources.append(str(CREDENTIALS_FILE))
    return list(dict.fromkeys(sources))


def _plugin_sources():
    return [
        str(STORAGE_PLUGIN_CONFIG_DIR),
        str(STORAGE_PLUGIN_STATE_DIR),
        str(SNAPRAID_LOG_DIR),
    ]


def _list_stacks():
    from stack_manager import list_stacks
    return list_stacks()


def _run_compose(name, command):
    from stack_manager import run_compose_command
    return run_compose_command(name, command)


class _ModuleHelperAdapter:
    """Helper port delegating to this module's ``helper_*`` names (test-patchable)."""

    def available(self):
        return helper_available()

    def call(self, command, params=None):
        return helper_call(command, params or {})


# =============================================================================
# Service construction and resolution
# =============================================================================

def default_backup_service(repository=None, scheduler_port=None, helper=None):
    """Build a BackupService bound to this module's paths, scheduler, and helper."""
    return BackupService(
        repository=repository if repository is not None else JsonFileRepository(),
        scheduler=(
            scheduler_port if scheduler_port is not None else ApschedulerAdapter(scheduler)
        ),
        helper=helper if helper is not None else _ModuleHelperAdapter(),
        config_path_provider=lambda: CONFIG_FILE,
        default_config_provider=_default_config,
        sources_provider=_get_sources,
        plugin_sources_provider=_plugin_sources,
        stack_lister=_list_stacks,
        compose_runner=_run_compose,
        trigger_factory=CronTrigger.from_crontab,
        excludes=DEFAULT_EXCLUDES,
    )


def _backup_service():
    if has_app_context():
        service = current_app.extensions.get("backup_service")
        if service is not None:
            return service
    return default_backup_service()


# =============================================================================
# Compatibility shims (module-level functions preserved for internal callers)
# =============================================================================

def load_config():
    return _backup_service().load_config()


def save_config(config):
    _backup_service().save_config(config)


def _update_schedule(preset):
    _backup_service().apply_schedule(preset)


def get_next_run_time():
    return _backup_service().next_run_time()


def run_backup_job():
    return _backup_service().run_backup()


def init_backup_scheduler(app=None):
    service = None
    if app is not None:
        service = getattr(app, "extensions", {}).get("backup_service")
    if service is None:
        service = _backup_service()
    service.init_scheduler()


# =============================================================================
# API Endpoints
# =============================================================================

@backup_scheduler.route('/api/backups/config', methods=['GET'])
@login_required
def api_backup_config():
    return jsonify(_backup_service().load_config())


@backup_scheduler.route('/api/backups/config', methods=['POST'])
@login_required
def api_backup_config_update():
    data = request.get_json() or {}
    try:
        config = _backup_service().update_config(data)
    except BackupConfigError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'status': 'ok', 'config': config})


@backup_scheduler.route('/api/backups/status', methods=['GET'])
@login_required
def api_backup_status():
    return jsonify(_backup_service().status())


@backup_scheduler.route('/api/backups/run', methods=['POST'])
@login_required
def api_backup_run():
    result = _backup_service().run_backup()
    if not result:
        return jsonify({'error': 'Backup failed'}), 500

    primary = result.get('primary', result)
    if not primary.get('success'):
        return jsonify({'error': primary.get('error', 'Backup failed'), 'result': result}), 500

    return jsonify({'status': 'ok', 'result': result})


@backup_scheduler.route('/api/backups/list', methods=['GET'])
@login_required
def api_backup_list():
    return jsonify({'backups': _backup_service().list_backups()})


@backup_scheduler.route('/api/backups/restore', methods=['POST'])
@login_required
def api_backup_restore():
    data = request.get_json() or {}
    try:
        result = _backup_service().restore(
            data.get('archive_name', ''),
            stop_stacks=bool(data.get('stop_stacks', True)),
            start_stacks=bool(data.get('start_stacks', True)),
        )
    except BackupConfigError as exc:
        return jsonify({'error': str(exc)}), 400
    except BackupNotFound as exc:
        return jsonify({'error': str(exc)}), 404
    except BackupHelperUnavailable as exc:
        return jsonify({'error': str(exc)}), 503
    except BackupOperationError as exc:
        return jsonify({'error': str(exc)}), 500
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503

    return jsonify({'status': 'ok', 'result': result})


@backup_scheduler.route('/api/backups/restore-plugins', methods=['POST'])
@login_required
def api_backup_restore_plugins():
    data = request.get_json() or {}
    try:
        result = _backup_service().restore_plugins(data.get('archive_name', ''))
    except BackupConfigError as exc:
        return jsonify({'error': str(exc)}), 400
    except BackupNotFound as exc:
        return jsonify({'error': str(exc)}), 404
    except BackupHelperUnavailable as exc:
        return jsonify({'error': str(exc)}), 503
    except BackupOperationError as exc:
        return jsonify({'error': str(exc)}), 500
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503

    return jsonify({'status': 'ok', 'result': result})
