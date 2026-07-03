"""Auto-Update Scheduler transport.

Provides automatic image pulling and stack updates on a configurable schedule.
Domain behavior lives in :mod:`update_service`; this module wires the Flask
blueprint and preserves the historical module-level functions used by internal
callers and tests.
"""

from flask import Blueprint, current_app, has_app_context, jsonify, request

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from auth_utils import login_required
from ports import ApschedulerAdapter, JsonFileRepository
from runtime_paths import STATE_DIR as RUNTIME_STATE_DIR
from stack_manager import list_stacks, run_compose_command
from update_service import (  # noqa: F401  (re-exported for compatibility)
    DEFAULT_CONFIG,
    SCHEDULE_PRESETS,
    AutoUpdateService,
    UpdateConfigError,
    get_schedule_cron,
    has_new_images,
)

# Blueprint for API endpoints
update_scheduler_bp = Blueprint('update_scheduler', __name__)

# Config file location
CONFIG_DIR = str(RUNTIME_STATE_DIR)
CONFIG_FILE = str(RUNTIME_STATE_DIR / 'auto_update.json')

# Dedicated background scheduler for auto-update jobs (separate from other schedulers).
scheduler = BackgroundScheduler(daemon=True)


# =============================================================================
# Service construction and resolution
# =============================================================================

def default_update_service(repository=None, scheduler_port=None):
    """Build an AutoUpdateService bound to this module's paths and scheduler."""
    return AutoUpdateService(
        repository=repository if repository is not None else JsonFileRepository(),
        scheduler=(
            scheduler_port if scheduler_port is not None else ApschedulerAdapter(scheduler)
        ),
        config_path_provider=lambda: CONFIG_FILE,
        stack_lister=lambda: list_stacks(),
        compose_runner=lambda name, command: run_compose_command(name, command),
        trigger_factory=CronTrigger.from_crontab,
    )


def _update_service():
    if has_app_context():
        service = current_app.extensions.get("update_service")
        if service is not None:
            return service
    return default_update_service()


# =============================================================================
# Compatibility shims (module-level functions preserved for internal callers)
# =============================================================================

def load_config():
    """Load configuration from JSON file with defaults fallback."""
    return _update_service().load_config()


def save_config(config):
    """Save configuration to JSON file with atomic write."""
    _update_service().save_config(config)


def update_schedule(preset):
    """Update or remove the scheduled job."""
    _update_service().apply_schedule(preset)


def get_next_run_time():
    """Get the next scheduled run time."""
    return _update_service().next_run_time()


def is_update_running():
    """Check if an update is currently in progress."""
    return _update_service().is_running()


def run_auto_update():
    """Run the update job (schedule or manual trigger)."""
    return _update_service().run()


def init_scheduler(app=None):
    """Initialize the scheduler with current config."""
    service = None
    if app is not None:
        service = getattr(app, "extensions", {}).get("update_service")
    if service is None:
        service = _update_service()
    service.init_scheduler()


# =============================================================================
# API Endpoints
# =============================================================================

@update_scheduler_bp.route('/api/auto-update/config', methods=['GET'])
@login_required
def api_get_config():
    """Get current auto-update configuration."""
    return jsonify(_update_service().load_config())


@update_scheduler_bp.route('/api/auto-update/config', methods=['POST'])
@login_required
def api_set_config():
    """Update auto-update configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    try:
        config = _update_service().update_config(data)
    except UpdateConfigError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': f'Failed to save config: {exc}'}), 500

    return jsonify({'status': 'updated', 'config': config})


@update_scheduler_bp.route('/api/auto-update/status', methods=['GET'])
@login_required
def api_get_status():
    """Get scheduler status and next run time."""
    return jsonify(_update_service().status())


@update_scheduler_bp.route('/api/auto-update/run-now', methods=['POST'])
@login_required
def api_run_now():
    """Trigger immediate update check."""
    service = _update_service()
    if service.is_running():
        return jsonify({'error': 'Update already in progress'}), 409

    results = service.run()
    if 'error' in results:
        return jsonify({'status': 'error', 'error': results['error']}), 409

    return jsonify({'status': 'completed', 'results': results})


@update_scheduler_bp.route('/api/auto-update/logs', methods=['GET'])
@login_required
def api_get_logs():
    """Get update history/logs."""
    return jsonify(_update_service().logs())


# Expose the blueprint and init function
update_scheduler = update_scheduler_bp
