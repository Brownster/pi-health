"""
Auto-Update Scheduler Module

Provides automatic image pulling and stack updates on a configurable schedule.
Replaces Watchtower functionality with a lightweight, integrated solution.
"""

import os
import json
import tempfile
import threading
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from auth_utils import login_required
from stack_manager import list_stacks, run_compose_command

# APScheduler imports
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Blueprint for API endpoints
update_scheduler_bp = Blueprint('update_scheduler', __name__)

# Config file location
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'auto_update.json')

# Default configuration
DEFAULT_CONFIG = {
    'version': 1,
    'enabled': False,
    'schedule_preset': 'disabled',
    'excluded_stacks': [],
    'notify_on_update': True,
    'last_run': None,
    'last_run_result': None
}

# Schedule presets to cron expressions
SCHEDULE_PRESETS = {
    'disabled': None,
    'daily_4am': '0 4 * * *',
    'weekly_sunday_4am': '0 4 * * 0'
}

# Global scheduler instance
scheduler = BackgroundScheduler(daemon=True)

# Lock to prevent concurrent updates
_update_lock = threading.Lock()
_update_running = False


# =============================================================================
# Config Management
# =============================================================================

def load_config():
    """Load configuration from JSON file with defaults fallback."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Merge with defaults for any missing keys
                merged = DEFAULT_CONFIG.copy()
                merged.update(config)
                return merged
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading auto-update config: {e}")

    return DEFAULT_CONFIG.copy()


def save_config(config):
    """Save configuration to JSON file with atomic write."""
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)

    # Atomic write: write to temp file, then rename
    try:
        fd, temp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(config, f, indent=2)
            os.replace(temp_path, CONFIG_FILE)
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise
    except Exception as e:
        print(f"Error saving auto-update config: {e}")
        raise


def get_schedule_cron(preset):
    """Convert schedule preset to cron expression."""
    return SCHEDULE_PRESETS.get(preset)


# =============================================================================
# Scheduler Management
# =============================================================================

def init_scheduler(app=None):
    """Initialize the scheduler with current config."""
    config = load_config()

    # Update schedule based on config
    if config['enabled'] and config['schedule_preset'] != 'disabled':
        update_schedule(config['schedule_preset'])

    # Start scheduler if not already running
    if not scheduler.running:
        scheduler.start()

    print(f"Auto-update scheduler initialized (enabled: {config['enabled']})")


def update_schedule(preset):
    """Update or remove the scheduled job."""
    # Remove existing job if any
    try:
        scheduler.remove_job('auto_update')
    except Exception:
        pass  # Job doesn't exist, that's fine

    # Add new job if preset is not disabled
    cron = get_schedule_cron(preset)
    if cron:
        scheduler.add_job(
            run_auto_update,
            CronTrigger.from_crontab(cron),
            id='auto_update',
            name='Auto-Update Stacks',
            replace_existing=True
        )
        print(f"Auto-update scheduled: {preset} ({cron})")
    else:
        print("Auto-update disabled")


def get_next_run_time():
    """Get the next scheduled run time."""
    try:
        job = scheduler.get_job('auto_update')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    except Exception:
        pass
    return None


# =============================================================================
# Update Logic
# =============================================================================

def has_new_images(pull_output):
    """
    Check if docker compose pull downloaded new images.

    Looks for indicators that new layers were pulled.
    """
    if not pull_output:
        return False

    # Indicators that new images were downloaded
    new_image_indicators = [
        'Downloaded newer image',
        'Pull complete',
        'Downloading',
        'Extracting',
        'Download complete',
        'Status: Downloaded'
    ]

    # Indicators that images are already up to date
    up_to_date_indicators = [
        'Image is up to date',
        'Status: Image is up to date'
    ]

    output_lower = pull_output.lower()

    # If we see "downloaded" or "extracting", new images were pulled
    for indicator in new_image_indicators:
        if indicator.lower() in output_lower:
            # But make sure it's not just "already downloaded"
            return True

    return False


def run_auto_update():
    """
    Main update job - runs on schedule or manually triggered.

    For each stack (not excluded):
    1. Pull images
    2. Check if images changed
    3. If changed, recreate services with `docker compose up -d`
    """
    global _update_running

    # Prevent concurrent updates
    if not _update_lock.acquire(blocking=False):
        print("Auto-update already running, skipping")
        return {'error': 'Update already in progress'}

    try:
        _update_running = True
        config = load_config()

        results = {
            'updated': [],
            'failed': [],
            'skipped': [],
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        # Get all stacks
        try:
            stacks = list_stacks()
        except Exception as e:
            results['failed'].append({'name': '_system', 'error': f'Failed to list stacks: {str(e)}'})
            return results

        print(f"Auto-update starting: {len(stacks)} stacks found")

        for stack in stacks:
            stack_name = stack.get('name', 'unknown')

            # Skip excluded stacks
            if stack_name in config.get('excluded_stacks', []):
                results['skipped'].append(stack_name)
                print(f"  Skipping {stack_name} (excluded)")
                continue

            try:
                print(f"  Processing {stack_name}...")

                # 1. Pull images
                pull_result = run_compose_command(stack_name, 'pull')

                if not pull_result or not pull_result.get('success'):
                    error_msg = pull_result.get('stderr', 'Unknown error') if pull_result else 'No result'
                    results['failed'].append({
                        'name': stack_name,
                        'error': f'Pull failed: {error_msg}'
                    })
                    print(f"    Pull failed: {error_msg[:100]}")
                    continue

                # 2. Check if images changed
                pull_stdout = pull_result.get('stdout', '')
                if has_new_images(pull_stdout):
                    print(f"    New images detected, recreating services...")

                    # 3. Recreate services
                    up_result = run_compose_command(stack_name, 'up')

                    if up_result and up_result.get('success'):
                        results['updated'].append(stack_name)
                        print(f"    Updated successfully")
                    else:
                        error_msg = up_result.get('stderr', 'Unknown error') if up_result else 'No result'
                        results['failed'].append({
                            'name': stack_name,
                            'error': f'Up failed: {error_msg}'
                        })
                        print(f"    Up failed: {error_msg[:100]}")
                else:
                    results['skipped'].append(stack_name)
                    print(f"    No new images, skipping")

            except Exception as e:
                results['failed'].append({
                    'name': stack_name,
                    'error': str(e)
                })
                print(f"    Error: {str(e)}")

        # Save results to config
        config['last_run'] = results['timestamp']
        config['last_run_result'] = results
        save_config(config)

        print(f"Auto-update complete: {len(results['updated'])} updated, "
              f"{len(results['failed'])} failed, {len(results['skipped'])} skipped")

        return results

    finally:
        _update_running = False
        _update_lock.release()


def is_update_running():
    """Check if an update is currently in progress."""
    return _update_running


# =============================================================================
# API Endpoints
# =============================================================================

@update_scheduler_bp.route('/api/auto-update/config', methods=['GET'])
@login_required
def api_get_config():
    """Get current auto-update configuration."""
    config = load_config()
    return jsonify(config)


@update_scheduler_bp.route('/api/auto-update/config', methods=['POST'])
@login_required
def api_set_config():
    """Update auto-update configuration."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    config = load_config()

    # Update allowed fields
    if 'enabled' in data:
        config['enabled'] = bool(data['enabled'])

    if 'schedule_preset' in data:
        preset = data['schedule_preset']
        if preset not in SCHEDULE_PRESETS:
            return jsonify({'error': f'Invalid schedule preset: {preset}'}), 400
        config['schedule_preset'] = preset

    if 'excluded_stacks' in data:
        if not isinstance(data['excluded_stacks'], list):
            return jsonify({'error': 'excluded_stacks must be a list'}), 400
        config['excluded_stacks'] = list(data['excluded_stacks'])

    if 'notify_on_update' in data:
        config['notify_on_update'] = bool(data['notify_on_update'])

    # Save config
    try:
        save_config(config)
    except Exception as e:
        return jsonify({'error': f'Failed to save config: {str(e)}'}), 500

    # Update scheduler
    if config['enabled']:
        update_schedule(config['schedule_preset'])
    else:
        update_schedule('disabled')

    return jsonify({'status': 'updated', 'config': config})


@update_scheduler_bp.route('/api/auto-update/status', methods=['GET'])
@login_required
def api_get_status():
    """Get scheduler status and next run time."""
    config = load_config()

    return jsonify({
        'enabled': config['enabled'],
        'schedule_preset': config['schedule_preset'],
        'next_run': get_next_run_time(),
        'last_run': config.get('last_run'),
        'last_run_result': config.get('last_run_result'),
        'update_running': is_update_running()
    })


@update_scheduler_bp.route('/api/auto-update/run-now', methods=['POST'])
@login_required
def api_run_now():
    """Trigger immediate update check."""
    if is_update_running():
        return jsonify({'error': 'Update already in progress'}), 409

    results = run_auto_update()

    if 'error' in results:
        return jsonify({'status': 'error', 'error': results['error']}), 409

    return jsonify({'status': 'completed', 'results': results})


@update_scheduler_bp.route('/api/auto-update/logs', methods=['GET'])
@login_required
def api_get_logs():
    """Get update history/logs."""
    config = load_config()
    return jsonify({
        'last_run': config.get('last_run'),
        'last_run_result': config.get('last_run_result')
    })


# Expose the blueprint and init function
update_scheduler = update_scheduler_bp
