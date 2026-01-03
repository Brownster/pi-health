"""
Backup Scheduler Module

Creates compressed backups of docker config + stacks on a schedule.
Backups are written to a mounted USB path (default /mnt/backup).
"""

import os
import json
import tempfile
import threading
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from auth_utils import login_required
from helper_client import helper_call, helper_available, HelperError
from disk_manager import load_media_paths

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

backup_scheduler = Blueprint('backup_scheduler', __name__)

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'backup_config.json')

DEFAULT_CONFIG = {
    'version': 1,
    'enabled': False,
    'schedule_preset': 'disabled',
    'retention_count': 7,
    'dest_dir': '/mnt/backup',
    'config_dir': '/home/pi/docker',
    'stacks_path': '/opt/stacks',
    'include_env': True,
    'compression': 'zst',
    'last_run': None,
    'last_run_result': None,
    'last_restore': None,
    'last_restore_result': None
}

SCHEDULE_PRESETS = {
    'disabled': None,
    'daily_2am': '0 2 * * *',
    'weekly_sunday_2am': '0 2 * * 0'
}

scheduler = BackgroundScheduler(daemon=True)
_backup_lock = threading.Lock()
_backup_running = False


def _default_config():
    defaults = DEFAULT_CONFIG.copy()
    paths = load_media_paths()
    defaults['dest_dir'] = paths.get('backup', defaults['dest_dir'])
    defaults['config_dir'] = paths.get('config', defaults['config_dir'])
    return defaults


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                merged = _default_config()
                merged.update(config)
                return merged
    except (json.JSONDecodeError, IOError):
        pass
    return _default_config()


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
        os.replace(temp_path, CONFIG_FILE)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def _get_sources(config):
    sources = []
    config_dir = config.get('config_dir', '').strip()
    stacks_path = config.get('stacks_path', '').strip()
    if config_dir:
        sources.append(config_dir)
    if stacks_path:
        sources.append(stacks_path)
    if config.get('include_env', True):
        sources.append('/etc/pi-health.env')
    return sources


def _update_schedule(preset):
    try:
        scheduler.remove_job('pihealth_backup')
    except Exception:
        pass

    cron = SCHEDULE_PRESETS.get(preset)
    if cron:
        scheduler.add_job(
            run_backup_job,
            CronTrigger.from_crontab(cron),
            id='pihealth_backup',
            name='Pi-Health Backup',
            replace_existing=True
        )


def init_backup_scheduler(app=None):
    config = load_config()
    if config.get('enabled') and config.get('schedule_preset') != 'disabled':
        _update_schedule(config['schedule_preset'])

    if not scheduler.running:
        scheduler.start()


def run_backup_job():
    global _backup_running

    if not _backup_lock.acquire(blocking=False):
        return {'error': 'Backup already in progress'}

    try:
        _backup_running = True
        config = load_config()

        if not helper_available():
            result = {'success': False, 'error': 'Helper service unavailable'}
        else:
            try:
                result = helper_call('backup_create', {
                    'sources': _get_sources(config),
                    'dest_dir': config.get('dest_dir'),
                    'retention_count': config.get('retention_count', 7),
                    'compression': config.get('compression', 'zst')
                })
            except HelperError as exc:
                result = {'success': False, 'error': str(exc)}

        config['last_run'] = datetime.now(timezone.utc).isoformat()
        config['last_run_result'] = result
        save_config(config)
        return result
    finally:
        _backup_running = False
        _backup_lock.release()


def get_next_run_time():
    try:
        job = scheduler.get_job('pihealth_backup')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
    except Exception:
        pass
    return None


def list_backups(dest_dir):
    entries = []
    if not dest_dir or not os.path.isdir(dest_dir):
        return entries

    for name in sorted(os.listdir(dest_dir)):
        if not name.startswith('pi-health-backup-'):
            continue
        if not (name.endswith('.tar.zst') or name.endswith('.tar.gz')):
            continue
        path = os.path.join(dest_dir, name)
        try:
            stat = os.stat(path)
            entries.append({
                'name': name,
                'size': stat.st_size,
                'mtime': stat.st_mtime
            })
        except OSError:
            continue
    entries.sort(key=lambda item: item['mtime'], reverse=True)
    return entries


@backup_scheduler.route('/api/backups/config', methods=['GET'])
@login_required
def api_backup_config():
    return jsonify(load_config())


@backup_scheduler.route('/api/backups/config', methods=['POST'])
@login_required
def api_backup_config_update():
    data = request.get_json() or {}
    config = load_config()

    for key in ('enabled', 'schedule_preset', 'retention_count', 'dest_dir',
                'config_dir', 'stacks_path', 'include_env'):
        if key in data:
            config[key] = data[key]

    retention = config.get('retention_count', 7)
    try:
        retention = int(retention)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid retention_count'}), 400
    if retention < 1:
        return jsonify({'error': 'retention_count must be >= 1'}), 400
    config['retention_count'] = retention

    dest_dir = str(config.get('dest_dir', '')).strip()
    if not dest_dir.startswith('/'):
        return jsonify({'error': 'dest_dir must be absolute'}), 400
    if '..' in dest_dir:
        return jsonify({'error': 'dest_dir invalid'}), 400

    config_dir = str(config.get('config_dir', '')).strip()
    if config_dir and (not config_dir.startswith('/') or '..' in config_dir):
        return jsonify({'error': 'config_dir invalid'}), 400

    stacks_path = str(config.get('stacks_path', '')).strip()
    if stacks_path and (not stacks_path.startswith('/') or '..' in stacks_path):
        return jsonify({'error': 'stacks_path invalid'}), 400

    schedule = config.get('schedule_preset', 'disabled')
    if schedule not in SCHEDULE_PRESETS:
        return jsonify({'error': 'Invalid schedule_preset'}), 400

    save_config(config)

    if config.get('enabled') and schedule != 'disabled':
        _update_schedule(schedule)
    else:
        _update_schedule('disabled')

    return jsonify({'status': 'ok', 'config': config})


@backup_scheduler.route('/api/backups/status', methods=['GET'])
@login_required
def api_backup_status():
    config = load_config()
    return jsonify({
        'enabled': config.get('enabled', False),
        'next_run': get_next_run_time(),
        'backup_running': _backup_running,
        'last_run': config.get('last_run'),
        'last_run_result': config.get('last_run_result')
    })


@backup_scheduler.route('/api/backups/run', methods=['POST'])
@login_required
def api_backup_run():
    result = run_backup_job()
    if not result or not result.get('success'):
        return jsonify({'error': result.get('error', 'Backup failed'), 'result': result}), 500
    return jsonify({'status': 'ok', 'result': result})


@backup_scheduler.route('/api/backups/list', methods=['GET'])
@login_required
def api_backup_list():
    config = load_config()
    dest_dir = config.get('dest_dir')
    return jsonify({'backups': list_backups(dest_dir)})


@backup_scheduler.route('/api/backups/restore', methods=['POST'])
@login_required
def api_backup_restore():
    data = request.get_json() or {}
    archive_name = data.get('archive_name', '').strip()
    stop_stacks = bool(data.get('stop_stacks', True))
    start_stacks = bool(data.get('start_stacks', True))

    if not archive_name or '/' in archive_name or '..' in archive_name:
        return jsonify({'error': 'Invalid archive name'}), 400

    config = load_config()
    dest_dir = config.get('dest_dir', '')
    archive_path = os.path.join(dest_dir, archive_name)

    if not os.path.exists(archive_path):
        return jsonify({'error': 'Backup not found'}), 404

    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    stacks_stopped = []
    stacks_started = []
    try:
        if stop_stacks:
            from stack_manager import list_stacks, run_compose_command
            stacks, err = list_stacks()
            if err:
                return jsonify({'error': err}), 500
            for stack in stacks:
                name = stack.get('name')
                if not name:
                    continue
                result = run_compose_command(name, 'stop')
                if result and result.get('success'):
                    stacks_stopped.append(name)

        restore_result = helper_call('backup_restore', {
            'archive_path': archive_path
        })
        if not restore_result.get('success'):
            return jsonify({'error': restore_result.get('error', 'Restore failed')}), 500

        if start_stacks and stacks_stopped:
            from stack_manager import run_compose_command
            for name in stacks_stopped:
                result = run_compose_command(name, 'up')
                if result and result.get('success'):
                    stacks_started.append(name)

        config['last_restore'] = datetime.now(timezone.utc).isoformat()
        config['last_restore_result'] = {
            'restore': restore_result,
            'stopped': stacks_stopped,
            'started': stacks_started
        }
        save_config(config)

        return jsonify({
            'status': 'ok',
            'result': config['last_restore_result']
        })
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503
