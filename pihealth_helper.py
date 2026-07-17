#!/usr/bin/env python3
"""
Pi-Health Privileged Helper Service

A minimal systemd service that runs as root and exposes whitelisted
system commands over a Unix socket. This allows pi-health to perform
privileged operations (disk info, mount management) without running
the main Flask app as root.

Security:
- Only accepts connections from Unix socket (local only)
- Only executes whitelisted commands
- All operations are logged
- Input validation on all parameters
"""

import os
import sys
import json
import socket
import subprocess
import re
import logging
import signal
import shutil
import stat
import struct
import threading
import tempfile
from datetime import datetime, timezone
from typing import Optional
import urllib.request
import urllib.error
import shlex
from helper_templates import (
    cron_to_oncalendar,
    render_package_reconcile_schedule,
    render_snapraid_schedule,
    render_startup_files,
)
from fstab_presets import get_fstab_preset, normalize_fstype
from agent_provider.provisioning import (
    AGENT_CONFIG_PATH,
    AGENT_ENV_PATH,
    AGENT_LIB_DIR,
    AGENT_POLICY_PATH,
    AGENT_STATE_DIR,
    AGENT_UNIT_PATH,
    AGENT_VENV_DIR,
    CLAUDE_CONFIG_DIR,
    LIMEOPS_AUDIT_PATH,
    LIMEOPS_SOCKET_DIR,
    LIMEOPS_SOCKET_PATH,
    LIMEOPS_STATE_DIR,
    LIMEOPS_UNIT_PATH,
    render_agent_unit,
    render_limeops_unit,
)
from agent_provider.auth import (
    AuthBusyError,
    AuthInputError,
    AuthNotFoundError,
    GuidedAuthManager,
)

# Configuration
SOCKET_PATH = '/run/pihealth/helper.sock'
LOG_FILE = '/var/log/limeos/pihealth-helper.log'
MAX_MESSAGE_SIZE = 65536
FRAME_HEADER_SIZE = 4
COPY_PARTY_DIR = '/opt/copyparty'
COPY_PARTY_SHARE = '/srv/copyparty'
COPY_PARTY_UNIT = '/etc/systemd/system/copyparty.service'
COPY_PARTY_ASSET_KEYWORDS = ('copyparty-sfx', 'copyparty')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE) if os.path.exists(os.path.dirname(LOG_FILE)) else logging.StreamHandler(),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Valid mount point pattern (prevent path traversal)
MOUNT_POINT_PATTERN = re.compile(r'^/mnt(/[a-zA-Z0-9._-]+)+$')
# Valid device pattern
DEVICE_PATTERN = re.compile(r'^/dev/[a-zA-Z0-9_-]+$')
# Valid UUID pattern
UUID_PATTERN = re.compile(r'^[a-fA-F0-9-]+$')
BACKUP_DEST_PATTERN = re.compile(r'^/(mnt|backups)(/[a-zA-Z0-9._-]+)*$')
BACKUP_SOURCE_ALLOWED = (
    '/home/',
    '/opt/',
    '/etc/pi-health.env',
    '/etc/limeos/',
    '/var/lib/limeos/',
    '/var/log/limeos/',
)
SEEDBOX_MOUNT_POINT = '/mnt/seedbox'
SEEDBOX_PASSFILE = '/etc/sshfs/seedbox.pass'
SEEDBOX_MOUNT_UNIT = 'mnt-seedbox.mount'
SEEDBOX_AUTOMOUNT_UNIT = 'mnt-seedbox.automount'
RCLONE_CONFIG_DIR = '/etc/rclone'
RCLONE_CONFIG_FILE = '/etc/rclone/rclone.conf'
RCLONE_MOUNTS_CONFIG = '/etc/rclone/mounts.json'
STARTUP_SCRIPT_PATH = '/usr/local/bin/check_mount_and_start.sh'
STARTUP_SERVICE_PATH = '/etc/systemd/system/docker-compose-start.service'
SNAPRAID_JOB_TYPES = {'sync', 'scrub'}
MEDIA_LIBRARY_DIRS = ('movies', 'tv', 'music', 'books', 'audiobooks', 'podcasts')
MEDIA_DOWNLOAD_CATEGORIES = (
    'sonarr',
    'radarr',
    'lidarr',
    'readarr',
    'sabnzbd',
    'transmission',
    'rdtclient',
    'jackett',
    'get_iplayer',
)

# SSHFS multi-mount configuration
SSHFS_CONFIG_DIR = '/etc/sshfs'
SSHFS_MOUNTS_CONFIG = '/etc/sshfs/mounts.json'
PLUGIN_DIR = os.getenv("PIHEALTH_PLUGIN_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins"))
PIHEALTH_REPO_DIR = os.getenv("PIHEALTH_REPO_DIR")
PIHEALTH_SERVICE_NAME = os.getenv("PIHEALTH_SERVICE_NAME", "pi-health")
PIHEALTH_HELPER_SERVICE_NAME = "pihealth-helper.service"

CLAUDE_APT_KEY_URL = 'https://downloads.claude.ai/keys/claude-code.asc'
CLAUDE_APT_KEY_PATH = '/etc/apt/keyrings/claude-code.asc'
CLAUDE_APT_SOURCE_PATH = '/etc/apt/sources.list.d/claude-code.list'
CLAUDE_APT_SOURCE = (
    'deb [signed-by=/etc/apt/keyrings/claude-code.asc] '
    'https://downloads.claude.ai/claude-code/apt/latest latest main\n'
)
CLAUDE_SIGNING_FINGERPRINT = '31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE'

_agent_auth_manager = GuidedAuthManager(
    [
        '/usr/sbin/runuser', '-u', 'lime-agent', '--pty', '--', 'env', '-i',
        'HOME=/var/lib/lime-agent',
        'USER=lime-agent',
        'LOGNAME=lime-agent',
        'PATH=/usr/local/bin:/usr/bin:/bin',
        'LANG=C.UTF-8',
        f'CLAUDE_CONFIG_DIR={CLAUDE_CONFIG_DIR}',
        'DISABLE_AUTOUPDATER=1',
        '/usr/bin/claude', 'auth', 'login',
    ],
    cwd=AGENT_STATE_DIR,
    credential_path=os.path.join(CLAUDE_CONFIG_DIR, '.credentials.json'),
)

PLUGIN_ID_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
COMPOSE_FILE_NAMES = {'compose.yml', 'compose.yaml', 'docker-compose.yml', 'docker-compose.yaml'}
COMPOSE_ALLOWED_ROOTS = ('/home/', '/opt/', '/srv/')


def run_command(cmd, timeout=30, cwd=None):
    """Run a command and return stdout, stderr, returncode."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        return {
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'error': 'Command timed out', 'returncode': -1}
    except Exception as e:
        return {'error': str(e), 'returncode': -1}


def _write_managed_file(path, content, mode=0o644):
    """Back up and atomically replace one helper-managed file."""
    try:
        if os.path.exists(path):
            backup = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(path, backup)

        temp_path = f"{path}.tmp.{os.getpid()}"
        with open(temp_path, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        return {'success': True, 'path': path}
    except Exception as exc:
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        return {'success': False, 'error': str(exc)}


def _validate_compose_path(value):
    if not isinstance(value, str) or not value.startswith('/'):
        return None
    if any(character in value for character in ('\x00', '\n', '\r')):
        return None
    normalized = os.path.normpath(value)
    if normalized != value or os.path.basename(normalized) not in COMPOSE_FILE_NAMES:
        return None
    if not normalized.startswith(COMPOSE_ALLOWED_ROOTS):
        return None
    return normalized


def _validate_mount_points(values):
    if not isinstance(values, list) or len(values) > 32:
        return None
    mount_points = []
    for value in values:
        if not isinstance(value, str) or not MOUNT_POINT_PATTERN.fullmatch(value) or '..' in value:
            return None
        if value not in mount_points:
            mount_points.append(value)
    return mount_points


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _detect_pkg_manager():
    for manager in ('apt-get', 'dnf', 'pacman'):
        if _command_exists(manager):
            return manager
    return None


def _install_packages(packages):
    manager = _detect_pkg_manager()
    if not manager:
        return {'success': False, 'error': 'No supported package manager found'}

    if manager == 'apt-get':
        update = run_command(['apt-get', 'update', '-y'], timeout=600)
        if update.get('returncode') != 0:
            return {'success': False, 'error': update.get('stderr', 'apt-get update failed')}
        install_cmd = ['apt-get', 'install', '-y'] + packages
    elif manager == 'dnf':
        install_cmd = ['dnf', 'install', '-y'] + packages
    else:
        install_cmd = ['pacman', '-S', '--noconfirm'] + packages

    result = run_command(install_cmd, timeout=1200)
    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Package install failed')}
    return {'success': True}


def _ensure_dependencies(required_bins, package_map):
    missing = []
    for binary in required_bins:
        if binary in ('fusermount', 'fusermount3'):
            if _command_exists('fusermount') or _command_exists('fusermount3'):
                continue
        if not _command_exists(binary):
            missing.append(binary)

    if not missing:
        return {'success': True}

    manager = _detect_pkg_manager()
    if not manager:
        return {'success': False, 'error': 'Missing dependencies and no package manager found'}

    packages = package_map.get(manager, [])
    if not packages:
        return {'success': False, 'error': f'No package mapping for {manager}'}

    return _install_packages(packages)


def cmd_lsblk(params):
    """Get block device information as JSON."""
    result = run_command(['lsblk', '-J', '-o',
                         'NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,UUID,MODEL,SERIAL,TRAN,HOTPLUG'])
    if result.get('returncode') == 0:
        try:
            return {'success': True, 'data': json.loads(result['stdout'])}
        except json.JSONDecodeError:
            return {'success': False, 'error': 'Failed to parse lsblk output'}
    return {'success': False, 'error': result.get('stderr', result.get('error', 'Unknown error'))}


def cmd_blkid(params):
    """Get block device attributes."""
    result = run_command(['blkid', '-o', 'export'])
    if result.get('returncode') == 0:
        devices = []
        current = {}
        for line in result['stdout'].split('\n'):
            line = line.strip()
            if not line:
                if current:
                    devices.append(current)
                    current = {}
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                current[key] = value
        if current:
            devices.append(current)
        return {'success': True, 'data': devices}
    return {'success': False, 'error': result.get('stderr', result.get('error', 'Unknown error'))}


def cmd_fstab_read(params):
    """Read current fstab entries."""
    try:
        fstab_path = '/etc/fstab'
        if not os.path.exists(fstab_path):
            return {'success': True, 'data': []}

        entries = []
        with open(fstab_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    entries.append({
                        'line': line_num,
                        'device': parts[0],
                        'mountpoint': parts[1],
                        'fstype': parts[2],
                        'options': parts[3],
                        'dump': parts[4] if len(parts) > 4 else '0',
                        'pass': parts[5] if len(parts) > 5 else '0'
                    })
        return {'success': True, 'data': entries}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def cmd_mounts_read(params):
    """Read current mount status from /proc/mounts."""
    try:
        mounts = []
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    mounts.append({
                        'device': parts[0],
                        'mountpoint': parts[1],
                        'fstype': parts[2],
                        'options': parts[3]
                    })
        return {'success': True, 'data': mounts}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def cmd_fstab_add(params):
    """Add an entry to fstab."""
    uuid = params.get('uuid', '')
    mountpoint = params.get('mountpoint', '')
    fstype = params.get('fstype')

    # Validate inputs
    if not uuid or not UUID_PATTERN.match(uuid):
        return {'success': False, 'error': 'Invalid UUID format'}
    if not mountpoint or not MOUNT_POINT_PATTERN.match(mountpoint) or '..' in mountpoint:
        return {'success': False, 'error': 'Invalid mountpoint (must be /mnt/<name>)'}
    if 'options' in params:
        return {'success': False, 'error': 'Custom mount options are not allowed'}
    try:
        fstype = normalize_fstype(fstype)
        preset = get_fstab_preset(fstype)
    except ValueError:
        return {'success': False, 'error': 'Invalid filesystem type'}

    fstab_line = (
        f"UUID={uuid} {mountpoint} {fstype} {preset['options']} "
        f"{preset['dump']} {preset['pass']}\n"
    )

    try:
        # Backup fstab first
        import shutil
        from datetime import datetime
        backup_path = f"/etc/fstab.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy('/etc/fstab', backup_path)
        logger.info(f"Backed up fstab to {backup_path}")

        # Check if entry already exists
        with open('/etc/fstab', 'r') as f:
            content = f.read()
            if f"UUID={uuid}" in content:
                return {'success': False, 'error': 'UUID already in fstab'}
            if f" {mountpoint} " in content:
                return {'success': False, 'error': 'Mountpoint already in fstab'}

        # Create mount directory if needed
        os.makedirs(mountpoint, exist_ok=True)

        # Append to fstab
        with open('/etc/fstab', 'a') as f:
            f.write("# Added by pi-health\n")
            f.write(fstab_line)

        logger.info(f"Added fstab entry: {fstab_line.strip()}")
        return {'success': True, 'backup': backup_path, 'entry': fstab_line.strip()}
    except Exception as e:
        logger.error(f"Failed to add fstab entry: {e}")
        return {'success': False, 'error': str(e)}


def cmd_fstab_remove(params):
    """Remove an entry from fstab by mountpoint."""
    mountpoint = params.get('mountpoint', '')

    if not mountpoint or not MOUNT_POINT_PATTERN.match(mountpoint) or '..' in mountpoint:
        return {'success': False, 'error': 'Invalid mountpoint'}

    try:
        # Backup fstab first
        import shutil
        from datetime import datetime
        backup_path = f"/etc/fstab.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy('/etc/fstab', backup_path)

        # Read and filter fstab
        with open('/etc/fstab', 'r') as f:
            lines = f.readlines()

        new_lines = []
        removed = False
        skip_comment = False
        for line in lines:
            # Skip the "Added by pi-health" comment if the next line is the one we're removing
            if line.strip() == '# Added by pi-health':
                skip_comment = True
                continue
            if skip_comment:
                skip_comment = False
                if f" {mountpoint} " in line:
                    removed = True
                    continue
                else:
                    new_lines.append('# Added by pi-health\n')

            if f" {mountpoint} " in line:
                removed = True
                continue
            new_lines.append(line)

        if not removed:
            return {'success': False, 'error': 'Mountpoint not found in fstab'}

        with open('/etc/fstab', 'w') as f:
            f.writelines(new_lines)

        logger.info(f"Removed fstab entry for {mountpoint}")
        return {'success': True, 'backup': backup_path}
    except Exception as e:
        logger.error(f"Failed to remove fstab entry: {e}")
        return {'success': False, 'error': str(e)}


def cmd_fstab_set_section(params):
    """Replace a managed section in fstab."""
    marker = params.get('marker', '').strip()
    lines = params.get('lines', [])
    path = params.get('path', '/etc/fstab')

    allowed_markers = {'mergerfs'}
    if marker not in allowed_markers:
        return {'success': False, 'error': 'Invalid marker'}

    if path != '/etc/fstab' and not (path.startswith('/tmp/') or path.startswith('/var/tmp/')):
        return {'success': False, 'error': 'Path not allowed'}

    if not isinstance(lines, list):
        return {'success': False, 'error': 'lines must be a list'}

    start = f"# pi-health {marker} start"
    end = f"# pi-health {marker} end"

    try:
        existing = []
        if os.path.exists(path):
            with open(path, 'r') as handle:
                existing = handle.read().splitlines()

        updated = []
        in_section = False
        for line in existing:
            if line.strip() == start:
                in_section = True
                continue
            if in_section:
                if line.strip() == end:
                    in_section = False
                continue
            updated.append(line.rstrip('\n'))

        cleaned_lines = [line.rstrip('\n') for line in lines if str(line).strip()]
        if cleaned_lines:
            if updated and updated[-1].strip():
                updated.append('')
            updated.append(start)
            updated.extend(cleaned_lines)
            updated.append(end)
            updated.append('')

        # Refuse to operate through a symlink: a planted symlink at `path` would
        # otherwise let root back up (read) or overwrite an arbitrary target.
        if os.path.islink(path):
            return {'success': False, 'error': 'Path must not be a symlink'}

        if os.path.exists(path):
            backup_path = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(path, backup_path)
            logger.info(f"Backed up fstab to {backup_path}")
        else:
            backup_path = None

        content = "\n".join(updated).rstrip("\n") + "\n"
        # O_NOFOLLOW closes the TOCTOU window on the final path component.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)

        return {'success': True, 'backup': backup_path, 'path': path}
    except Exception as e:
        logger.error(f"Failed to update fstab section: {e}")
        return {'success': False, 'error': str(e)}


def cmd_mount(params):
    """Mount a filesystem."""
    mountpoint = params.get('mountpoint', '')
    device = params.get('device', '')

    if not mountpoint or not MOUNT_POINT_PATTERN.match(mountpoint) or '..' in mountpoint:
        return {'success': False, 'error': 'Invalid mountpoint'}
    if device and not DEVICE_PATTERN.match(device):
        return {'success': False, 'error': 'Invalid device path'}

    # Create directory if needed
    os.makedirs(mountpoint, exist_ok=True)

    cmd = ['mount', mountpoint]
    if device:
        cmd = ['mount', device, mountpoint]

    result = run_command(cmd)
    if result.get('returncode') == 0:
        logger.info(f"Mounted {mountpoint}")
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', result.get('error', 'Mount failed'))}


def cmd_umount(params):
    """Unmount a filesystem."""
    mountpoint = params.get('mountpoint', '')

    if not mountpoint or not MOUNT_POINT_PATTERN.match(mountpoint) or '..' in mountpoint:
        return {'success': False, 'error': 'Invalid mountpoint'}

    result = run_command(['umount', mountpoint])
    if result.get('returncode') == 0:
        logger.info(f"Unmounted {mountpoint}")
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', result.get('error', 'Unmount failed'))}


def cmd_smart_info(params):
    """Get full SMART info for a device (with USB drive support)."""
    device = params.get('device', '')
    use_sat = params.get('use_sat', False)

    if not device or not DEVICE_PATTERN.match(device):
        return {'success': False, 'error': 'Invalid device path'}

    # Check if smartctl is available
    result = run_command(['which', 'smartctl'])
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'smartctl not installed'}

    # Build command - use -a for full attributes, -j for JSON
    cmd = ['smartctl', '-a', '-j']
    if use_sat:
        cmd.extend(['-d', 'sat'])
    cmd.append(device)

    result = run_command(cmd)
    # smartctl returns various codes, but if we have stdout try to parse it
    if result.get('stdout'):
        try:
            data = json.loads(result['stdout'])
            return {'success': True, 'data': data}
        except json.JSONDecodeError:
            pass

    # If no SAT and failed, retry with SAT for USB drives
    if not use_sat and result.get('returncode') not in [0, 4]:
        return cmd_smart_info({'device': device, 'use_sat': True})

    return {'success': False, 'error': result.get('stderr', 'smartctl failed')}


def cmd_smart_test(params):
    """Run a SMART self-test on a device."""
    device = params.get('device', '')
    test_type = params.get('test_type', 'short')  # short, long, conveyance
    use_sat = params.get('use_sat', False)

    if not device or not DEVICE_PATTERN.match(device):
        return {'success': False, 'error': 'Invalid device path'}

    if test_type not in ['short', 'long', 'conveyance']:
        return {'success': False, 'error': 'Invalid test type. Use: short, long, or conveyance'}

    # Check if smartctl is available
    result = run_command(['which', 'smartctl'])
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'smartctl not installed'}

    # Build command
    cmd = ['smartctl', '-t', test_type]
    if use_sat:
        cmd.extend(['-d', 'sat'])
    cmd.append(device)

    result = run_command(cmd)
    if result.get('returncode') == 0:
        return {'success': True, 'message': f'{test_type.capitalize()} test started on {device}'}

    # Retry with SAT if needed
    if not use_sat:
        return cmd_smart_test({'device': device, 'test_type': test_type, 'use_sat': True})

    return {'success': False, 'error': result.get('stderr', 'Failed to start test')}


def cmd_smart_all_devices(params):
    """Get SMART info for all disk devices."""
    # Get list of block devices
    result = run_command(['lsblk', '-d', '-n', '-o', 'NAME,TYPE'])
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'Failed to list devices'}

    devices = []
    for line in result.get('stdout', '').strip().split('\n'):
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'disk':
            devices.append(f"/dev/{parts[0]}")

    # Get SMART info for each device
    results = []
    for device in devices:
        smart_result = cmd_smart_info({'device': device})
        if smart_result.get('success'):
            results.append({
                'device': device,
                'data': smart_result.get('data')
            })
        else:
            results.append({
                'device': device,
                'error': smart_result.get('error')
            })

    return {'success': True, 'devices': results}


def cmd_alert_health_snapshot(params):
    """Return read-only host health inputs used by the alert daemon."""
    smart = cmd_smart_all_devices({})
    mounts = cmd_mounts_read({})
    try:
        from storage_plugins.snapraid_plugin import SnapRAIDPlugin

        config_dir = os.path.join(
            os.getenv('LIMEOS_CONFIG_DIR', '/etc/limeos'),
            'storage_plugins',
        )
        snapraid = SnapRAIDPlugin(config_dir).get_status()
    except Exception as exc:
        snapraid = {'status': 'unavailable', 'message': str(exc), 'details': {}}
    return {
        'success': True,
        'smart': smart,
        'mounts': mounts,
        'snapraid': snapraid,
    }


def cmd_df(params):
    """Get disk space usage."""
    result = run_command(['df', '-B1', '--output=source,target,fstype,size,used,avail,pcent'])
    if result.get('returncode') == 0:
        lines = result['stdout'].strip().split('\n')
        if len(lines) < 2:
            return {'success': True, 'data': []}

        headers = lines[0].lower().split()
        data = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= len(headers):
                entry = dict(zip(headers, parts))
                data.append(entry)
        return {'success': True, 'data': data}
    return {'success': False, 'error': result.get('stderr', 'df failed')}


SNAPRAID_ALLOWED_CONF = frozenset({'/etc/snapraid.conf', '/etc/snapraid-diff.conf'})


def _snapraid_log_dir():
    return os.path.join(os.getenv("LIMEOS_LOG_DIR", "/var/log/limeos"), "snapraid")


def _snapraid_log_target_allowed(target):
    """Allow only stdout/stderr or a file under the managed snapraid log dir.

    A crafted target would otherwise let a caller redirect root-owned writes to
    an arbitrary path.
    """
    if target in ('>&1', '>&2'):
        return True
    candidate = target
    for prefix in ('>>', '>'):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    if not candidate or '..' in candidate:
        return False
    log_dir = os.path.realpath(_snapraid_log_dir())
    resolved = os.path.realpath(candidate)
    return resolved == log_dir or resolved.startswith(log_dir + os.sep)


def cmd_snapraid(params):
    """Run snapraid command."""
    allowed_cmds = ['status', 'diff', 'sync', 'scrub', 'check', 'fix']
    cmd = params.get('command', '')

    if cmd not in allowed_cmds:
        return {'success': False, 'error': f'Command not allowed: {cmd}'}

    conf_path = params.get('conf_path')
    if conf_path is not None and conf_path not in SNAPRAID_ALLOWED_CONF:
        return {'success': False, 'error': 'conf_path not allowed'}

    log_tags = params.get('log_tags', True)
    log_target = params.get('log_target', '>&2')
    if log_tags and not _snapraid_log_target_allowed(log_target):
        return {'success': False, 'error': 'log_target not allowed'}

    gui = params.get('gui', True)

    args = ['snapraid']
    if conf_path:
        args.extend(['-c', conf_path])
    if log_tags:
        args.extend(['--log', log_target])
        if gui:
            args.append('--gui')

    args.append(cmd)
    if cmd == 'scrub' and 'percent' in params:
        args.extend(['-p', str(params['percent'])])
    if cmd == 'scrub' and 'age_days' in params:
        args.extend(['-o', str(params['age_days'])])

    result = run_command(args, timeout=3600)
    return {
        'success': result.get('returncode') == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result.get('returncode')
    }


def _validate_branches(branches):
    for branch in branches:
        if not branch or not branch.startswith('/mnt/') or '..' in branch:
            return False
    return True


def cmd_mergerfs_mount(params):
    """Mount a MergerFS pool."""
    branches = params.get('branches', '')
    mount_point = params.get('mount_point', '')
    options = params.get('options', '')

    if not branches or not mount_point:
        return {'success': False, 'error': 'branches and mount_point required'}

    if not MOUNT_POINT_PATTERN.match(mount_point) or '..' in mount_point:
        return {'success': False, 'error': 'Invalid mount point'}

    branch_list = [b for b in branches.split(':') if b]
    if not branch_list or not _validate_branches(branch_list):
        return {'success': False, 'error': 'Invalid branches'}

    safe_options = re.sub(r'[^a-zA-Z0-9,_=:-]', '', options)

    os.makedirs(mount_point, exist_ok=True)
    cmd = ['mergerfs', '-o', safe_options, ':'.join(branch_list), mount_point]
    result = run_command(cmd)

    return {
        'success': result.get('returncode') == 0,
        'error': result.get('stderr', '') if result.get('returncode') != 0 else None
    }


def cmd_mergerfs_umount(params):
    """Unmount a MergerFS pool."""
    mount_point = params.get('mount_point', '')

    if not mount_point or not MOUNT_POINT_PATTERN.match(mount_point) or '..' in mount_point:
        return {'success': False, 'error': 'Invalid mount point'}

    result = run_command(['umount', mount_point])
    return {
        'success': result.get('returncode') == 0,
        'error': result.get('stderr', '') if result.get('returncode') != 0 else None
    }


def cmd_write_snapraid_conf(params):
    """Write snapraid.conf file."""
    content = params.get('content', '')
    path = params.get('path', '/etc/snapraid.conf')

    allowed_paths = ['/etc/snapraid.conf', '/etc/snapraid-diff.conf']
    if path not in allowed_paths:
        return {'success': False, 'error': 'Path not allowed'}

    try:
        import shutil
        from datetime import datetime
        if os.path.exists(path):
            backup = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(path, backup)

        with open(path, 'w') as f:
            f.write(content)

        return {'success': True, 'path': path}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _startup_parameters(params):
    mount_points = _validate_mount_points(params.get('mount_points'))
    compose_file = _validate_compose_path(params.get('compose_file'))
    if mount_points is None:
        return None, None, 'Invalid mount_points'
    if compose_file is None:
        return None, None, 'Invalid compose_file'
    return mount_points, compose_file, None


def _startup_file_state(script, service):
    """Read current helper-managed files and include fixed-template previews."""

    result = {
        'success': True,
        'script': {'path': STARTUP_SCRIPT_PATH, 'current': '', 'proposed': script, 'exists': False},
        'service': {'path': STARTUP_SERVICE_PATH, 'current': '', 'proposed': service, 'exists': False}
    }

    try:
        if os.path.exists(STARTUP_SCRIPT_PATH):
            with open(STARTUP_SCRIPT_PATH, 'r') as f:
                result['script']['current'] = f.read()
                result['script']['exists'] = True
    except Exception as e:
        result['script']['error'] = str(e)

    try:
        if os.path.exists(STARTUP_SERVICE_PATH):
            with open(STARTUP_SERVICE_PATH, 'r') as f:
                result['service']['current'] = f.read()
                result['service']['exists'] = True
    except Exception as e:
        result['service']['error'] = str(e)

    result['script']['changed'] = result['script']['current'] != script
    result['service']['changed'] = result['service']['current'] != service
    return result


def _validate_media_root(value):
    if not isinstance(value, str) or not MOUNT_POINT_PATTERN.match(value):
        return None
    return value.rstrip('/')


def _validate_uid_gid(value):
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,10}', value):
        return None
    number = int(value)
    if number < 0 or number > 60000:
        return None
    return number


def _chown_chmod_tree(path, uid, gid):
    os.chown(path, uid, gid)
    os.chmod(path, 0o775)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            target = os.path.join(root, name)
            if os.path.islink(target):
                continue
            os.chown(target, uid, gid)
            os.chmod(target, 0o775)
        for name in files:
            target = os.path.join(root, name)
            if os.path.islink(target):
                continue
            os.chown(target, uid, gid)


def cmd_media_layout_provision(params):
    storage_root = _validate_media_root(params.get('storage_root'))
    downloads_root = _validate_media_root(params.get('downloads_root'))
    puid = _validate_uid_gid(params.get('puid'))
    pgid = _validate_uid_gid(params.get('pgid'))
    if storage_root is None:
        return {'success': False, 'error': 'Invalid storage_root'}
    if downloads_root is None:
        return {'success': False, 'error': 'Invalid downloads_root'}
    if puid is None:
        return {'success': False, 'error': 'Invalid puid'}
    if pgid is None:
        return {'success': False, 'error': 'Invalid pgid'}

    directories = [os.path.join(storage_root, kind) for kind in MEDIA_LIBRARY_DIRS]
    directories.append(os.path.join(downloads_root, 'incomplete'))
    directories.extend(
        os.path.join(downloads_root, 'complete', category)
        for category in MEDIA_DOWNLOAD_CATEGORIES
    )

    created = []
    existing = []
    try:
        for path in directories:
            if os.path.isdir(path):
                existing.append(path)
            else:
                os.makedirs(path, exist_ok=True)
                created.append(path)
            _chown_chmod_tree(path, puid, pgid)
    except Exception as exc:
        return {'success': False, 'error': str(exc)}

    return {'success': True, 'created': created, 'existing': existing}


def cmd_preview_startup_service(params):
    mount_points, compose_file, error = _startup_parameters(params)
    if error:
        return {'success': False, 'error': error}
    script, service = render_startup_files(mount_points, compose_file)
    return _startup_file_state(script, service)


def cmd_configure_startup_service(params):
    mount_points, compose_file, error = _startup_parameters(params)
    if error:
        return {'success': False, 'error': error}
    script, service = render_startup_files(mount_points, compose_file)

    result = _write_managed_file(STARTUP_SCRIPT_PATH, script, mode=0o755)
    if not result.get('success'):
        return result
    result = _write_managed_file(STARTUP_SERVICE_PATH, service)
    if not result.get('success'):
        return result
    return {'success': True, 'script_path': STARTUP_SCRIPT_PATH, 'service_path': STARTUP_SERVICE_PATH}


def cmd_configure_snapraid_schedule(params):
    job_type = params.get('job_type')
    on_calendar = cron_to_oncalendar(params.get('cron'))
    if job_type not in SNAPRAID_JOB_TYPES:
        return {'success': False, 'error': 'Invalid SnapRAID job type'}
    if on_calendar is None:
        return {'success': False, 'error': 'Invalid cron schedule'}

    service, timer = render_snapraid_schedule(job_type, on_calendar)
    unit_base = f"pihealth-snapraid-{job_type}"
    service_path = f"/etc/systemd/system/{unit_base}.service"
    timer_path = f"/etc/systemd/system/{unit_base}.timer"
    result = _write_managed_file(service_path, service)
    if not result.get('success'):
        return result
    result = _write_managed_file(timer_path, timer)
    if not result.get('success'):
        return result
    return {'success': True, 'service_path': service_path, 'timer_path': timer_path}


def cmd_systemctl(params):
    """Run systemctl commands for SnapRAID timers."""
    action = params.get('action', '')
    unit = params.get('unit', '')

    allowed_actions = {'daemon-reload', 'enable', 'disable', 'start', 'stop'}
    allowed_units = {
        'pihealth-snapraid-sync.timer',
        'pihealth-snapraid-scrub.timer',
        'docker-compose-start.service'
    }

    if action not in allowed_actions:
        return {'success': False, 'error': 'Action not allowed'}

    if action != 'daemon-reload' and unit not in allowed_units:
        return {'success': False, 'error': 'Unit not allowed'}

    cmd = ['systemctl', action]
    if unit:
        cmd.append(unit)
    if action in ('enable', 'disable'):
        cmd.append('--now')

    result = run_command(cmd, timeout=60)
    return {
        'success': result.get('returncode') == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result.get('returncode')
    }


def _read_os_release():
    data = {}
    try:
        with open("/etc/os-release") as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep:
                    data[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return data


def cmd_tailscale_install(params):
    """Install Tailscale from its signed apt repository (no pipe-to-shell).

    Packages are gpg-verified by apt, which is the documented secure method and
    avoids running an unverified `curl | sh` script as root.
    """
    os_release = _read_os_release()
    distro = os_release.get("ID", "")
    codename = os_release.get("VERSION_CODENAME", "")
    if distro not in ("debian", "ubuntu", "raspbian") or not codename:
        return {
            'success': False,
            'error': 'Unsupported distribution for apt install; install Tailscale manually',
        }

    keyring = "/usr/share/keyrings/tailscale-archive-keyring.gpg"
    base = f"https://pkgs.tailscale.com/stable/{distro}/{codename}"
    steps = [
        ["curl", "-fsSL", f"{base}.noarmor.gpg", "-o", keyring],
        [
            "curl", "-fsSL", f"{base}.tailscale-keyring.list",
            "-o", "/etc/apt/sources.list.d/tailscale.list",
        ],
        ["apt-get", "update"],
        ["apt-get", "install", "-y", "tailscale"],
    ]
    for step in steps:
        result = run_command(step, timeout=600)
        if result.get('returncode') != 0:
            return {
                'success': False,
                'error': result.get('stderr', 'tailscale install step failed'),
                'stdout': result.get('stdout', ''),
                'returncode': result.get('returncode'),
                'step': step[0],
            }
    return {'success': True}


def cmd_tailscale_up(params):
    """Start Tailscale and authenticate."""
    auth_key = params.get('auth_key', '')
    allowed_key = re.compile(r'^[A-Za-z0-9._-]+$')
    cmd = ['tailscale', 'up', '--accept-routes=false']
    if auth_key:
        if not allowed_key.match(auth_key):
            return {'success': False, 'error': 'Invalid auth key format'}
        cmd.extend(['--authkey', auth_key])

    result = run_command(cmd, timeout=120)
    return {
        'success': result.get('returncode') == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result.get('returncode')
    }


def cmd_tailscale_status(params):
    """Get Tailscale status and network info."""
    import json as json_module
    import shutil

    # Check if tailscale binary exists
    if not shutil.which('tailscale'):
        return {
            'success': True,
            'installed': False,
            'status': None
        }

    # Get JSON status
    result = run_command(['tailscale', 'status', '--json'], timeout=30)
    if result.get('returncode') != 0:
        # Tailscale installed but not running or not configured
        return {
            'success': True,
            'installed': True,
            'running': False,
            'status': None,
            'error': result.get('stderr', 'Failed to get status')
        }

    try:
        status = json_module.loads(result.get('stdout', '{}'))
        # Extract useful info
        self_info = status.get('Self', {})
        return {
            'success': True,
            'installed': True,
            'running': True,
            'backend_state': status.get('BackendState', 'Unknown'),
            'tailnet_name': status.get('CurrentTailnet', {}).get('Name', ''),
            'hostname': self_info.get('HostName', ''),
            'dns_name': self_info.get('DNSName', ''),
            'tailscale_ips': self_info.get('TailscaleIPs', []),
            'online': self_info.get('Online', False),
            'os': self_info.get('OS', ''),
            'relay': self_info.get('Relay', ''),
            'rx_bytes': self_info.get('RxBytes', 0),
            'tx_bytes': self_info.get('TxBytes', 0),
            'created': self_info.get('Created', ''),
            'last_seen': self_info.get('LastSeen', ''),
            'peers': len(status.get('Peer', {})),
            'health': status.get('Health', []),
            'magic_dns_suffix': status.get('MagicDNSSuffix', ''),
            'raw_status': status
        }
    except json_module.JSONDecodeError:
        return {
            'success': False,
            'installed': True,
            'error': 'Failed to parse status JSON'
        }


def cmd_tailscale_logout(params):
    """Logout from Tailscale (for re-authentication)."""
    import shutil

    if not shutil.which('tailscale'):
        return {'success': False, 'error': 'Tailscale not installed'}

    result = run_command(['tailscale', 'logout'], timeout=30)
    return {
        'success': result.get('returncode') == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result.get('returncode')
    }


def cmd_network_info(params):
    """Get detailed host network information."""
    import json as json_module
    import socket

    info = {
        'hostname': socket.gethostname(),
        'fqdn': socket.getfqdn(),
        'interfaces': [],
        'dns_servers': [],
        'default_gateway': None,
        'public_ip': None
    }

    # Get interface info using ip command
    result = run_command(['ip', '-j', 'addr'], timeout=10)
    if result.get('returncode') == 0:
        try:
            interfaces = json_module.loads(result.get('stdout', '[]'))
            for iface in interfaces:
                iface_info = {
                    'name': iface.get('ifname', ''),
                    'state': iface.get('operstate', 'UNKNOWN'),
                    'mac': iface.get('address', ''),
                    'mtu': iface.get('mtu', 0),
                    'ipv4': [],
                    'ipv6': []
                }
                for addr in iface.get('addr_info', []):
                    if addr.get('family') == 'inet':
                        iface_info['ipv4'].append({
                            'address': addr.get('local', ''),
                            'prefix': addr.get('prefixlen', 0),
                            'broadcast': addr.get('broadcast', '')
                        })
                    elif addr.get('family') == 'inet6':
                        iface_info['ipv6'].append({
                            'address': addr.get('local', ''),
                            'prefix': addr.get('prefixlen', 0),
                            'scope': addr.get('scope', '')
                        })
                # Skip loopback from main list but include it
                if iface_info['name'] != 'lo' or params.get('include_loopback'):
                    info['interfaces'].append(iface_info)
        except json_module.JSONDecodeError:
            pass

    # Get default gateway
    result = run_command(['ip', '-j', 'route', 'show', 'default'], timeout=10)
    if result.get('returncode') == 0:
        try:
            routes = json_module.loads(result.get('stdout', '[]'))
            if routes:
                info['default_gateway'] = {
                    'ip': routes[0].get('gateway', ''),
                    'interface': routes[0].get('dev', '')
                }
        except json_module.JSONDecodeError:
            pass

    # Get DNS servers from /etc/resolv.conf
    try:
        with open('/etc/resolv.conf', 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('nameserver'):
                    parts = line.split()
                    if len(parts) >= 2:
                        info['dns_servers'].append(parts[1])
    except Exception:
        pass

    # Try to get public IP (optional, might fail)
    try:
        result = run_command(['curl', '-s', '--max-time', '5', 'https://api.ipify.org'], timeout=10)
        if result.get('returncode') == 0:
            ip = result.get('stdout', '').strip()
            if ip and re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
                info['public_ip'] = ip
    except Exception:
        pass

    return {
        'success': True,
        **info
    }


def cmd_docker_network_create(params):
    """Create Docker network if missing."""
    name = params.get('name', '').strip()
    if not name:
        return {'success': False, 'error': 'Network name required'}
    if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
        return {'success': False, 'error': 'Invalid network name'}

    list_result = run_command(['docker', 'network', 'ls', '--format', '{{.Name}}'])
    if list_result.get('returncode') != 0:
        return {'success': False, 'error': list_result.get('stderr', 'Failed to list networks')}
    if name in list_result.get('stdout', '').splitlines():
        return {'success': True, 'message': 'Network already exists'}

    result = run_command(['docker', 'network', 'create', name])
    return {
        'success': result.get('returncode') == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result.get('returncode')
    }


def cmd_write_vpn_env(params):
    """Write Gluetun VPN environment file."""
    path = params.get('path', '').strip()
    content = params.get('content', '')

    if not path or '..' in path:
        return {'success': False, 'error': 'Invalid path'}
    if not path.endswith('/vpn/.env'):
        return {'success': False, 'error': 'Path not allowed'}
    if not path.startswith('/home/') and not path.startswith('/config/'):
        return {'success': False, 'error': 'Path not allowed'}

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        os.chmod(path, 0o600)
        return {'success': True, 'path': path}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def cmd_backup_create(params):
    """Create a compressed backup archive."""
    sources = params.get('sources', [])
    dest_dir = params.get('dest_dir', '')
    retention_count = params.get('retention_count', 7)
    compression = params.get('compression', 'zst')
    archive_prefix = params.get('archive_prefix', 'pi-health-backup')
    excludes = params.get('excludes', [])

    if not isinstance(sources, list) or not sources:
        return {'success': False, 'error': 'sources required'}
    if not dest_dir or not BACKUP_DEST_PATTERN.match(dest_dir) or '..' in dest_dir:
        return {'success': False, 'error': 'Invalid dest_dir'}

    try:
        retention_count = int(retention_count)
    except (TypeError, ValueError):
        return {'success': False, 'error': 'Invalid retention_count'}
    if retention_count < 1:
        return {'success': False, 'error': 'retention_count must be >= 1'}

    valid_sources = []
    for source in sources:
        if not isinstance(source, str) or not source.startswith('/'):
            continue
        if '..' in source:
            continue
        if not any(
            source == prefix.rstrip('/') or source.startswith(prefix)
            for prefix in BACKUP_SOURCE_ALLOWED
        ):
            continue
        if os.path.exists(source):
            valid_sources.append(source)

    if not valid_sources:
        return {'success': False, 'error': 'No valid sources found'}

    # Validate and build exclude arguments
    exclude_args = []
    if isinstance(excludes, list):
        for pattern in excludes:
            if isinstance(pattern, str) and pattern and '..' not in pattern:
                exclude_args.extend(['--exclude', pattern])

    os.makedirs(dest_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_prefix = re.sub(r'[^a-zA-Z0-9._-]', '', archive_prefix) or 'pi-health-backup'
    archive_name = f"{safe_prefix}-{timestamp}.tar.zst" if compression == 'zst' else f"{safe_prefix}-{timestamp}.tar.gz"
    archive_path = os.path.join(dest_dir, archive_name)

    if compression == 'zst':
        cmd = ['tar', '-I', 'zstd', '-cf', archive_path] + exclude_args + valid_sources
    else:
        cmd = ['tar', '-czf', archive_path] + exclude_args + valid_sources

    result = run_command(cmd, timeout=3600)
    if result.get('returncode') != 0:
        return {
            'success': False,
            'error': result.get('stderr', 'Backup failed')
        }

    # Retention cleanup
    try:
        backups = []
        for name in os.listdir(dest_dir):
            if not name.startswith(f"{safe_prefix}-"):
                continue
            if not (name.endswith('.tar.zst') or name.endswith('.tar.gz')):
                continue
            path = os.path.join(dest_dir, name)
            try:
                stat = os.stat(path)
                backups.append((stat.st_mtime, path))
            except OSError:
                continue
        backups.sort(reverse=True)
        for _, path in backups[retention_count:]:
            try:
                os.remove(path)
            except OSError:
                continue
    except Exception:
        pass

    return {'success': True, 'archive': archive_path}


def cmd_backup_restore(params):
    """Restore from a compressed backup archive."""
    archive_path = params.get('archive_path', '').strip()

    if not archive_path or '..' in archive_path:
        return {'success': False, 'error': 'Invalid archive path'}
    if not (archive_path.endswith('.tar.zst') or archive_path.endswith('.tar.gz')):
        return {'success': False, 'error': 'Invalid archive type'}
    if not (archive_path.startswith('/mnt/') or archive_path.startswith('/backups/')):
        return {'success': False, 'error': 'Archive path not allowed'}
    if not os.path.exists(archive_path):
        return {'success': False, 'error': 'Archive not found'}

    if archive_path.endswith('.tar.zst'):
        cmd = ['tar', '-I', 'zstd', '-x', '--overwrite', '-f', archive_path, '-C', '/']
    else:
        cmd = ['tar', '-x', '--overwrite', '-zf', archive_path, '-C', '/']

    result = run_command(cmd, timeout=3600)
    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Restore failed')}

    return {'success': True, 'archive': archive_path}


def cmd_seedbox_configure(params):
    """Configure the seedbox SSHFS mount."""
    host = params.get('host', '').strip()
    username = params.get('username', '').strip()
    password = params.get('password', '')
    remote_path = params.get('remote_path', '').strip()
    port = str(params.get('port', '22')).strip()

    if not host or not username or not remote_path:
        return {'success': False, 'error': 'host, username, and remote_path required'}
    if not remote_path.startswith('/'):
        return {'success': False, 'error': 'remote_path must be absolute'}
    if '..' in remote_path:
        return {'success': False, 'error': 'remote_path invalid'}
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return {'success': False, 'error': 'Invalid port'}
    if not password:
        return {'success': False, 'error': 'Password required'}

    os.makedirs(os.path.dirname(SEEDBOX_PASSFILE), exist_ok=True)
    with open(SEEDBOX_PASSFILE, 'w') as f:
        f.write(password)
    os.chmod(SEEDBOX_PASSFILE, 0o600)

    os.makedirs(SEEDBOX_MOUNT_POINT, exist_ok=True)

    mount_unit = f"""[Unit]
Description=Seedbox SFTP Mount
After=network-online.target
Wants=network-online.target

[Mount]
What=sshfs#{username}@{host}:{remote_path}
Where={SEEDBOX_MOUNT_POINT}
Type=fuse.sshfs
Options=_netdev,users,allow_other,reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,StrictHostKeyChecking=accept-new,ssh_command=sshpass -f {SEEDBOX_PASSFILE} ssh,port={port}
TimeoutSec=30

[Install]
WantedBy=multi-user.target
"""

    automount_unit = f"""[Unit]
Description=Seedbox SFTP Automount
After=network-online.target
Wants=network-online.target

[Automount]
Where={SEEDBOX_MOUNT_POINT}

[Install]
WantedBy=multi-user.target
"""

    try:
        with open(f"/etc/systemd/system/{SEEDBOX_MOUNT_UNIT}", 'w') as f:
            f.write(mount_unit)
        with open(f"/etc/systemd/system/{SEEDBOX_AUTOMOUNT_UNIT}", 'w') as f:
            f.write(automount_unit)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    run_command(['systemctl', 'daemon-reload'])
    enable_result = run_command(['systemctl', 'enable', '--now', SEEDBOX_AUTOMOUNT_UNIT])
    if enable_result.get('returncode') != 0:
        return {'success': False, 'error': enable_result.get('stderr', 'Failed to enable automount')}

    return {'success': True}


def cmd_seedbox_disable(params):
    """Disable the seedbox SSHFS mount."""
    run_command(['systemctl', 'disable', '--now', SEEDBOX_AUTOMOUNT_UNIT])
    run_command(['systemctl', 'stop', SEEDBOX_MOUNT_UNIT])
    run_command(['systemctl', 'daemon-reload'])
    return {'success': True}


# =============================================================================
# Rclone Mount Commands
# =============================================================================

def _get_rclone_unit_name(mount_id: str) -> str:
    safe_id = re.sub(r'[^a-zA-Z0-9]', '-', mount_id)
    return f"rclone-{safe_id}.service"


def _load_rclone_mounts():
    try:
        if os.path.exists(RCLONE_MOUNTS_CONFIG):
            with open(RCLONE_MOUNTS_CONFIG, 'r') as f:
                return json.load(f).get('mounts', [])
    except Exception:
        pass
    return []


def _save_rclone_mounts(mounts):
    os.makedirs(RCLONE_CONFIG_DIR, exist_ok=True)
    with open(RCLONE_MOUNTS_CONFIG, 'w') as f:
        json.dump({'mounts': mounts}, f, indent=2)


def _write_rclone_remote(config):
    os.makedirs(RCLONE_CONFIG_DIR, exist_ok=True)
    remote_name = f"rclone-{config['id']}"
    backend = config.get('backend', 's3')
    provider = config.get('provider', 'AWS')
    region = config.get('region', 'us-east-1')
    endpoint = config.get('endpoint', '')
    access_key_id = config.get('access_key_id', '')
    secret_access_key = config.get('secret_access_key', '')

    lines = []
    if os.path.exists(RCLONE_CONFIG_FILE):
        with open(RCLONE_CONFIG_FILE, 'r') as f:
            lines = f.read().splitlines()

    # Remove existing section
    new_lines = []
    in_section = False
    for line in lines:
        if line.strip().startswith('[') and line.strip().endswith(']'):
            in_section = line.strip()[1:-1] == remote_name
            if in_section:
                continue
        if in_section:
            continue
        new_lines.append(line)

    new_lines.append(f"[{remote_name}]")
    new_lines.append("type = s3")
    new_lines.append(f"provider = {provider}")
    new_lines.append(f"access_key_id = {access_key_id}")
    new_lines.append(f"secret_access_key = {secret_access_key}")
    new_lines.append(f"region = {region}")
    if backend == 's3-compatible' and endpoint:
        new_lines.append(f"endpoint = {endpoint}")

    with open(RCLONE_CONFIG_FILE, 'w') as f:
        f.write("\n".join(new_lines) + "\n")


def _read_rclone_remote(remote_name: str) -> dict:
    result = {}
    if not os.path.exists(RCLONE_CONFIG_FILE):
        return result
    try:
        with open(RCLONE_CONFIG_FILE, 'r') as f:
            lines = f.read().splitlines()
    except Exception:
        return result

    in_section = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            in_section = line[1:-1] == remote_name
            continue
        if not in_section or '=' not in line:
            continue
        key, value = [part.strip() for part in line.split('=', 1)]
        result[key] = value
    return result


def cmd_rclone_list(params):
    mounts = _load_rclone_mounts()
    result = []
    for mount in mounts:
        mount_id = mount.get('id', '')
        mount_point = mount.get('mount_point', '')
        unit = _get_rclone_unit_name(mount_id)
        active = run_command(['systemctl', 'is-active', unit]).get('returncode') == 0
        mounted = run_command(['mountpoint', '-q', mount_point]).get('returncode') == 0
        result.append({
            **mount,
            'active': active,
            'mounted': mounted
        })
    return {'success': True, 'mounts': result}


def cmd_rclone_configure(params):
    mount_id = params.get('id', '').strip()
    name = params.get('name', '').strip()
    backend = params.get('backend', 's3')
    bucket = params.get('bucket', '').strip()
    mount_point = params.get('mount_point', '').strip()
    enabled = bool(params.get('enabled', False))

    if not mount_id or not name or not bucket or not mount_point:
        return {'success': False, 'error': 'id, name, bucket, mount_point required'}
    if not re.match(r'^[a-z0-9-]+$', mount_id):
        return {'success': False, 'error': 'ID must be lowercase alphanumeric with hyphens'}
    if not mount_point.startswith('/mnt/') or '..' in mount_point:
        return {'success': False, 'error': 'Mount point must be under /mnt/'}

    if backend not in ('s3', 's3-compatible'):
        return {'success': False, 'error': 'Unsupported backend'}

    access_key_id = params.get('access_key_id', '')
    secret_access_key = params.get('secret_access_key', '')
    if not access_key_id or not secret_access_key:
        existing = _read_rclone_remote(f"rclone-{mount_id}")
        access_key_id = access_key_id or existing.get('access_key_id', '')
        secret_access_key = secret_access_key or existing.get('secret_access_key', '')

    if not access_key_id and not secret_access_key:
        return {'success': False, 'error': 'Access key and secret key required'}
    if not access_key_id:
        return {'success': False, 'error': 'Access key required'}
    if not secret_access_key:
        return {'success': False, 'error': 'Secret key required'}
    if backend == 's3-compatible' and not params.get('endpoint'):
        return {'success': False, 'error': 'Endpoint required for S3-compatible'}

    os.makedirs(mount_point, exist_ok=True)
    params = {
        **params,
        'access_key_id': access_key_id,
        'secret_access_key': secret_access_key
    }
    _write_rclone_remote(params)

    unit = _get_rclone_unit_name(mount_id)
    remote_name = f"rclone-{mount_id}:{bucket}"
    options = params.get('options', {}) or {}
    vfs_cache_mode = options.get('vfs_cache_mode', 'writes')
    read_only = options.get('read_only', False)
    allow_other = options.get('allow_other', True)

    flags = [
        f"--config={RCLONE_CONFIG_FILE}",
        f"--vfs-cache-mode={vfs_cache_mode}",
        "--dir-cache-time=5m",
        "--poll-interval=1m"
    ]
    if read_only:
        flags.append("--read-only")
    if allow_other:
        flags.append("--allow-other")

    unit_body = f"""[Unit]
Description=Rclone Mount: {name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount {remote_name} {mount_point} {' '.join(flags)}
ExecStop=/bin/fusermount -u {mount_point}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

    try:
        with open(f"/etc/systemd/system/{unit}", 'w') as f:
            f.write(unit_body)
    except Exception as e:
        return {'success': False, 'error': f'Failed to write unit file: {e}'}

    run_command(['systemctl', 'daemon-reload'])

    if enabled and params.get('auto_install', True):
        deps = _ensure_dependencies(
            ['rclone', 'fusermount', 'fusermount3'],
            {
                'apt-get': ['rclone', 'fuse3'],
                'dnf': ['rclone', 'fuse3'],
                'pacman': ['rclone', 'fuse3']
            }
        )
        if not deps.get('success'):
            return {'success': False, 'error': deps.get('error', 'Dependency install failed')}

    if enabled:
        result = run_command(['systemctl', 'enable', '--now', unit])
        if result.get('returncode') != 0:
            return {'success': False, 'error': result.get('stderr', 'Failed to enable')}
    else:
        run_command(['systemctl', 'disable', '--now', unit])

    mounts = _load_rclone_mounts()
    mounts = [m for m in mounts if m.get('id') != mount_id]
    mounts.append({
        'id': mount_id,
        'name': name,
        'backend': backend,
        'provider': params.get('provider', 'AWS'),
        'region': params.get('region', 'us-east-1'),
        'endpoint': params.get('endpoint', ''),
        'bucket': bucket,
        'mount_point': mount_point,
        'enabled': enabled
    })
    _save_rclone_mounts(mounts)

    return {'success': True}


def cmd_rclone_remove(params):
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}
    unit = _get_rclone_unit_name(mount_id)
    run_command(['systemctl', 'disable', '--now', unit])
    if os.path.exists(f"/etc/systemd/system/{unit}"):
        os.remove(f"/etc/systemd/system/{unit}")
    run_command(['systemctl', 'daemon-reload'])

    mounts = _load_rclone_mounts()
    mounts = [m for m in mounts if m.get('id') != mount_id]
    _save_rclone_mounts(mounts)
    return {'success': True}


def cmd_rclone_mount(params):
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}
    unit = _get_rclone_unit_name(mount_id)
    result = run_command(['systemctl', 'start', unit])
    if result.get('returncode') == 0:
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', 'Mount failed')}


def cmd_rclone_unmount(params):
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}
    unit = _get_rclone_unit_name(mount_id)
    result = run_command(['systemctl', 'stop', unit])
    if result.get('returncode') == 0:
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', 'Unmount failed')}


# =============================================================================
# SSHFS Multi-Mount Commands
# =============================================================================

SSHFS_CONFIG_DIR = '/etc/sshfs'
SSHFS_MOUNTS_CONFIG = '/etc/sshfs/mounts.json'


# =============================================================================
# SSHFS Multi-Mount Commands
# =============================================================================

def _load_sshfs_mounts():
    """Load SSHFS mounts configuration."""
    try:
        if os.path.exists(SSHFS_MOUNTS_CONFIG):
            with open(SSHFS_MOUNTS_CONFIG, 'r') as f:
                return json.load(f).get('mounts', [])
    except Exception:
        pass
    return []


def _save_sshfs_mounts(mounts):
    """Save SSHFS mounts configuration."""
    os.makedirs(SSHFS_CONFIG_DIR, exist_ok=True)
    with open(SSHFS_MOUNTS_CONFIG, 'w') as f:
        json.dump({'mounts': mounts}, f, indent=2)
    os.chmod(SSHFS_MOUNTS_CONFIG, 0o600)


def _get_sshfs_unit_names(mount_id):
    """Get systemd unit names for a mount ID."""
    # Convert mount_id to a safe unit name
    safe_id = re.sub(r'[^a-zA-Z0-9]', '-', mount_id)
    return {
        'mount': f'sshfs-{safe_id}.mount',
        'automount': f'sshfs-{safe_id}.automount'
    }


def _is_sshfs_mounted(mount_point):
    """Check if an SSHFS mount point is currently mounted."""
    try:
        result = run_command(['mountpoint', '-q', mount_point])
        return result.get('returncode') == 0
    except Exception:
        return False


def cmd_sshfs_list(params):
    """List all configured SSHFS mounts with their status."""
    mounts = _load_sshfs_mounts()
    result = []

    for mount in mounts:
        mount_point = mount.get('mount_point', '')
        units = _get_sshfs_unit_names(mount.get('id', ''))

        # Check if mounted
        is_mounted = _is_sshfs_mounted(mount_point) if mount_point else False

        # Check if enabled (automount unit is enabled)
        enabled_check = run_command(['systemctl', 'is-enabled', units['automount']])
        is_enabled = enabled_check.get('returncode') == 0

        result.append({
            'id': mount.get('id'),
            'name': mount.get('name', ''),
            'host': mount.get('host', ''),
            'port': mount.get('port', 22),
            'username': mount.get('username', ''),
            'remote_path': mount.get('remote_path', ''),
            'mount_point': mount_point,
            'mounted': is_mounted,
            'enabled': is_enabled,
            'options': mount.get('options', {})
        })

    return {'success': True, 'mounts': result}


def cmd_sshfs_configure(params):
    """Configure an SSHFS mount (add or update)."""
    mount_id = params.get('id', '').strip()
    name = params.get('name', '').strip()
    host = params.get('host', '').strip()
    username = params.get('username', '').strip()
    password = params.get('password', '')
    remote_path = params.get('remote_path', '').strip()
    mount_point = params.get('mount_point', '').strip()
    port = str(params.get('port', '22')).strip()
    options = params.get('options', {})

    # Validation
    if not mount_id:
        return {'success': False, 'error': 'Mount ID required'}
    if not re.match(r'^[a-zA-Z0-9_-]+$', mount_id):
        return {'success': False, 'error': 'Invalid mount ID (use alphanumeric, dash, underscore)'}
    if not host or not username or not remote_path or not mount_point:
        return {'success': False, 'error': 'host, username, remote_path, and mount_point required'}
    if not remote_path.startswith('/'):
        return {'success': False, 'error': 'remote_path must be absolute'}
    if not mount_point.startswith('/mnt/'):
        return {'success': False, 'error': 'mount_point must be under /mnt/'}
    if '..' in remote_path or '..' in mount_point:
        return {'success': False, 'error': 'Path traversal not allowed'}
    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return {'success': False, 'error': 'Invalid port'}

    # Load existing mounts
    mounts = _load_sshfs_mounts()

    # Check if updating existing or adding new
    existing_idx = next((i for i, m in enumerate(mounts) if m.get('id') == mount_id), None)

    # If password provided, store it
    passfile = os.path.join(SSHFS_CONFIG_DIR, f'{mount_id}.pass')
    if password:
        os.makedirs(SSHFS_CONFIG_DIR, exist_ok=True)
        with open(passfile, 'w') as f:
            f.write(password)
        os.chmod(passfile, 0o600)
    elif existing_idx is None and not os.path.exists(passfile):
        return {'success': False, 'error': 'Password required for new mount'}

    # Create mount point directory
    os.makedirs(mount_point, exist_ok=True)

    # Build systemd units
    units = _get_sshfs_unit_names(mount_id)

    # Build mount options
    mount_opts = [
        '_netdev',
        'users',
        'allow_other',
        f'port={port}'
    ]
    if options.get('reconnect', True):
        mount_opts.extend(['reconnect', 'ServerAliveInterval=15', 'ServerAliveCountMax=3'])
    if options.get('compression', False):
        mount_opts.append('Compression=yes')
    mount_opts.append('StrictHostKeyChecking=accept-new')
    mount_opts.append(f'ssh_command=sshpass -f {passfile} ssh')


    mount_unit = f"""[Unit]
Description=SSHFS Mount - {name or mount_id}
After=network-online.target
Wants=network-online.target

[Mount]
What=sshfs#{username}@{host}:{remote_path}
Where={mount_point}
Type=fuse.sshfs
Options={','.join(mount_opts)}
TimeoutSec=30

[Install]
WantedBy=multi-user.target
"""

    automount_unit = f"""[Unit]
Description=SSHFS Automount - {name or mount_id}
After=network-online.target
Wants=network-online.target

[Automount]
Where={mount_point}
TimeoutIdleSec=300

[Install]
WantedBy=multi-user.target
"""

    try:
        # Write systemd units
        with open(f"/etc/systemd/system/{units['mount']}", 'w') as f:
            f.write(mount_unit)
        with open(f"/etc/systemd/system/{units['automount']}", 'w') as f:
            f.write(automount_unit)
    except Exception as e:
        return {'success': False, 'error': f'Failed to write systemd units: {e}'}

    # Reload systemd
    run_command(['systemctl', 'daemon-reload'])

    if params.get('enabled', True) and params.get('auto_install', True):
        deps = _ensure_dependencies(
            ['sshfs', 'sshpass'],
            {
                'apt-get': ['sshfs', 'sshpass'],
                'dnf': ['sshfs', 'sshpass'],
                'pacman': ['sshfs', 'sshpass']
            }
        )
        if not deps.get('success'):
            return {'success': False, 'error': deps.get('error', 'Dependency install failed')}

    # Enable automount
    if params.get('enabled', True):
        enable_result = run_command(['systemctl', 'enable', '--now', units['automount']])
        if enable_result.get('returncode') != 0:
            return {'success': False, 'error': enable_result.get('stderr', 'Failed to enable automount')}
    else:
        run_command(['systemctl', 'disable', '--now', units['automount']])
        run_command(['systemctl', 'stop', units['mount']])

    # Update config
    mount_config = {
        'id': mount_id,
        'name': name or mount_id,
        'host': host,
        'port': int(port),
        'username': username,
        'remote_path': remote_path,
        'mount_point': mount_point,
        'options': options,
        'enabled': bool(params.get('enabled', True))
    }

    if existing_idx is not None:
        mounts[existing_idx] = mount_config
    else:
        mounts.append(mount_config)

    _save_sshfs_mounts(mounts)

    return {'success': True, 'mount': mount_config}


def cmd_sshfs_remove(params):
    """Remove an SSHFS mount configuration."""
    mount_id = params.get('id', '').strip()

    if not mount_id:
        return {'success': False, 'error': 'Mount ID required'}

    mounts = _load_sshfs_mounts()
    mount = next((m for m in mounts if m.get('id') == mount_id), None)

    if not mount:
        return {'success': False, 'error': 'Mount not found'}

    units = _get_sshfs_unit_names(mount_id)

    # Stop and disable units
    run_command(['systemctl', 'disable', '--now', units['automount']])
    run_command(['systemctl', 'stop', units['mount']])

    # Remove unit files
    for unit in [units['mount'], units['automount']]:
        unit_path = f"/etc/systemd/system/{unit}"
        if os.path.exists(unit_path):
            os.remove(unit_path)

    # Remove password file
    passfile = os.path.join(SSHFS_CONFIG_DIR, f'{mount_id}.pass')
    if os.path.exists(passfile):
        os.remove(passfile)

    # Reload systemd
    run_command(['systemctl', 'daemon-reload'])

    # Remove from config
    mounts = [m for m in mounts if m.get('id') != mount_id]
    _save_sshfs_mounts(mounts)

    return {'success': True}


def cmd_sshfs_mount(params):
    """Manually mount an SSHFS mount."""
    mount_id = params.get('id', '').strip()

    if not mount_id:
        return {'success': False, 'error': 'Mount ID required'}

    mounts = _load_sshfs_mounts()
    mount = next((m for m in mounts if m.get('id') == mount_id), None)

    if not mount:
        return {'success': False, 'error': 'Mount not found'}

    units = _get_sshfs_unit_names(mount_id)
    result = run_command(['systemctl', 'start', units['mount']])

    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Failed to mount')}

    return {'success': True}


def cmd_sshfs_unmount(params):
    """Manually unmount an SSHFS mount."""
    mount_id = params.get('id', '').strip()

    if not mount_id:
        return {'success': False, 'error': 'Mount ID required'}

    mounts = _load_sshfs_mounts()
    mount = next((m for m in mounts if m.get('id') == mount_id), None)

    if not mount:
        return {'success': False, 'error': 'Mount not found'}

    units = _get_sshfs_unit_names(mount_id)
    result = run_command(['systemctl', 'stop', units['mount']])

    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Failed to unmount')}

    return {'success': True}


def _normalize_github_source(source: str) -> Optional[str]:
    if source.startswith(('http://', 'https://', 'git@')):
        return source
    if source.count('/') == 1:
        return f"https://github.com/{source}.git"
    return None


def _derive_plugin_id(source: str) -> str:
    cleaned = source.rstrip('/')
    name = cleaned.split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    return name


def _validate_plugin_id(plugin_id: str) -> bool:
    return bool(PLUGIN_ID_PATTERN.match(plugin_id))


def _fetch_latest_copyparty_asset() -> str:
    """Return the browser_download_url for the latest copyparty sfx asset."""
    url = "https://api.github.com/repos/9001/copyparty/releases/latest"
    request = urllib.request.Request(url, headers={"User-Agent": "pi-health"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    for asset in payload.get("assets", []):
        name = asset.get("name", "")
        if not name.endswith(".py"):
            continue
        lower = name.lower()
        if any(key in lower for key in COPY_PARTY_ASSET_KEYWORDS):
            return asset.get("browser_download_url", "")

    return ""


def _write_copyparty_unit(share_path: str, port: int, extra_args: str) -> dict:
    """Write systemd unit for CopyParty."""
    os.makedirs(os.path.dirname(COPY_PARTY_UNIT), exist_ok=True)
    os.makedirs(share_path, exist_ok=True)
    os.makedirs(COPY_PARTY_DIR, exist_ok=True)

    exec_start = ["/usr/bin/python3", os.path.join(COPY_PARTY_DIR, "copyparty-sfx.py")]
    if port:
        exec_start.extend(["--port", str(port)])
    if extra_args:
        exec_start.extend(shlex.split(extra_args))

    unit_contents = "\n".join([
        "[Unit]",
        "Description=CopyParty File Server",
        "After=network.target",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={share_path}",
        f"ExecStart={' '.join(exec_start)}",
        "Restart=on-failure",
        "Environment=PYTHONUNBUFFERED=1",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        ""
    ])

    with open(COPY_PARTY_UNIT, "w") as handle:
        handle.write(unit_contents)

    reload_result = run_command(["systemctl", "daemon-reload"])
    if reload_result.get("returncode") != 0:
        return {'success': False, 'error': reload_result.get('stderr', 'daemon-reload failed')}

    return {'success': True}


def cmd_copyparty_install(params):
    """Install CopyParty from the latest GitHub release."""
    share_path = params.get("share_path", COPY_PARTY_SHARE).strip() or COPY_PARTY_SHARE
    port = int(params.get("port", 3923) or 3923)
    extra_args = params.get("extra_args", "").strip()

    try:
        download_url = _fetch_latest_copyparty_asset()
    except (urllib.error.URLError, TimeoutError) as exc:
        return {'success': False, 'error': f'Failed to fetch release info: {exc}'}

    if not download_url:
        return {'success': False, 'error': 'No CopyParty release asset found'}

    os.makedirs(COPY_PARTY_DIR, exist_ok=True)
    target_path = os.path.join(COPY_PARTY_DIR, "copyparty-sfx.py")

    try:
        request = urllib.request.Request(download_url, headers={"User-Agent": "pi-health"})
        with urllib.request.urlopen(request, timeout=60) as response:
            with open(target_path, "wb") as handle:
                handle.write(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        return {'success': False, 'error': f'Failed to download CopyParty: {exc}'}

    os.chmod(target_path, 0o755)

    unit_result = _write_copyparty_unit(share_path, port, extra_args)
    if not unit_result.get('success'):
        return unit_result

    result = run_command(["systemctl", "enable", "--now", "copyparty.service"], timeout=60)
    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Failed to start CopyParty')}

    return {'success': True}


def cmd_copyparty_configure(params):
    """Update CopyParty configuration and restart."""
    share_path = params.get("share_path", COPY_PARTY_SHARE).strip() or COPY_PARTY_SHARE
    port = int(params.get("port", 3923) or 3923)
    extra_args = params.get("extra_args", "").strip()

    if not os.path.exists(os.path.join(COPY_PARTY_DIR, "copyparty-sfx.py")):
        return {'success': False, 'error': 'CopyParty is not installed'}

    unit_result = _write_copyparty_unit(share_path, port, extra_args)
    if not unit_result.get('success'):
        return unit_result

    result = run_command(["systemctl", "restart", "copyparty.service"], timeout=60)
    if result.get('returncode') != 0:
        return {'success': False, 'error': result.get('stderr', 'Failed to restart CopyParty')}

    return {'success': True}


def cmd_copyparty_status(params):
    """Return CopyParty status."""
    installed = os.path.exists(os.path.join(COPY_PARTY_DIR, "copyparty-sfx.py"))
    service_active = False
    service_status = "unknown"

    if os.path.exists(COPY_PARTY_UNIT):
        result = run_command(["systemctl", "is-active", "copyparty.service"], timeout=10)
        service_status = (result.get("stdout") or "").strip() or "unknown"
        service_active = service_status == "active"

    return {
        'success': True,
        'installed': installed,
        'service_active': service_active,
        'service_status': service_status
    }


def _validate_pihealth_update_params(params):
    """Return (context, error) for a Pi-Health self-update request.

    Shared by every update step so validation stays identical whether the
    orchestrator drives one step at a time or the legacy combined path runs.
    """
    user = params.get("user", "").strip()
    repo_path = params.get("repo_path", "").strip()
    service_name = params.get("service_name", "").strip() or PIHEALTH_SERVICE_NAME

    if not user or not re.match(r"^[a-z_][a-z0-9_-]*$", user):
        return None, 'Invalid user'

    if not repo_path:
        repo_path = PIHEALTH_REPO_DIR or f"/home/{user}/pi-health"

    if not repo_path.startswith(f"/home/{user}/") or ".." in repo_path:
        return None, 'repo_path must be under /home/<user>'

    if not os.path.isdir(repo_path):
        return None, 'repo_path not found'

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return None, 'repo_path is not a git repo'

    if not service_name.endswith(".service"):
        service_name = f"{service_name}.service"

    allowed_services = {PIHEALTH_SERVICE_NAME, f"{PIHEALTH_SERVICE_NAME}.service"}
    extra_allowed = os.getenv("PIHEALTH_UPDATE_SERVICES", "")
    if extra_allowed:
        for entry in extra_allowed.split(","):
            entry = entry.strip()
            if entry:
                allowed_services.add(entry)

    if service_name not in allowed_services:
        return None, 'service_name not allowed'

    return {"user": user, "repo_path": repo_path, "service_name": service_name}, None


def _git_as(user, repo_path, *args, timeout=30):
    """Run a git command in ``repo_path`` as ``user``."""
    return run_command(
        ["runuser", "-u", user, "--", "git", "-C", repo_path, *args],
        timeout=timeout,
    )


def _pihealth_update_pull(ctx):
    """Fast-forward the checkout and report the commit range and changed files."""
    user = ctx["user"]
    repo_path = ctx["repo_path"]

    head = _git_as(user, repo_path, "rev-parse", "HEAD")
    old_commit = (head.get("stdout") or "").strip() if head.get("returncode") == 0 else None

    pull = _git_as(user, repo_path, "pull", "--ff-only", timeout=180)
    stderr = pull.get("stderr", "") or pull.get("error", "") or ""
    if pull.get("returncode") != 0 and "static/v2" in stderr and (
        "would be overwritten by merge" in stderr
        or "untracked working tree files" in stderr
    ):
        # One-time transition: the committed static/v2 bundle collides with the
        # previously-gitignored local build. It is a generated artifact about to
        # arrive from git, so drop the untracked copy and retry the pull once.
        tracked = _git_as(user, repo_path, "ls-files", "--error-unmatch", "static/v2/index.html")
        bundle = os.path.join(repo_path, "static", "v2")
        if tracked.get("returncode") != 0 and os.path.isdir(bundle):
            shutil.rmtree(bundle, ignore_errors=True)
            pull = _git_as(user, repo_path, "pull", "--ff-only", timeout=180)

    if pull.get("returncode") != 0:
        return {
            'success': False,
            'error': pull.get("stderr") or pull.get("error") or 'git pull failed',
            'stdout': pull.get("stdout", ""),
        }

    head2 = _git_as(user, repo_path, "rev-parse", "HEAD")
    new_commit = (head2.get("stdout") or "").strip() if head2.get("returncode") == 0 else None

    changed_files = []
    if old_commit and new_commit and old_commit != new_commit:
        diff = _git_as(user, repo_path, "diff", "--name-only", f"{old_commit}..{new_commit}")
        if diff.get("returncode") == 0:
            changed_files = [line for line in (diff.get("stdout") or "").splitlines() if line.strip()]

    return {
        'success': True,
        'old_commit': old_commit,
        'new_commit': new_commit,
        'changed_files': changed_files,
        'stdout': pull.get("stdout", ""),
    }


def _pihealth_update_deps(ctx):
    """Install Python dependencies into the service virtualenv."""
    user = ctx["user"]
    repo_path = ctx["repo_path"]
    venv_py = os.path.join(repo_path, ".venv", "bin", "python")
    requirements = os.path.join(repo_path, "requirements.txt")

    if not os.path.isfile(venv_py):
        return {'success': True, 'skipped': True, 'reason': 'no virtualenv found'}
    if not os.path.isfile(requirements):
        return {'success': True, 'skipped': True, 'reason': 'no requirements.txt'}

    # Run as the service user (like the git/npm steps) so the venv doesn't end up
    # with root-owned files that later break manual pip runs as the user.
    result = run_command(
        ["runuser", "-u", user, "--", venv_py, "-m", "pip", "install", "-r", requirements],
        timeout=1200,
    )
    if result.get("returncode") != 0:
        return {
            'success': False,
            'error': result.get("stderr") or result.get("error") or 'pip install failed',
            'stdout': result.get("stdout", ""),
        }
    return {'success': True, 'stdout': result.get("stdout", "")}


def _pihealth_update_migrate(ctx):
    """Ensure LimeOS runtime directories exist and run the idempotent migration."""
    user = ctx["user"]
    repo_path = ctx["repo_path"]
    script = os.path.join(repo_path, "scripts", "migrate_runtime_state.py")
    if not os.path.isfile(script):
        return {'success': True, 'skipped': True, 'reason': 'no migration script'}

    config_dir = os.getenv("LIMEOS_CONFIG_DIR", "/etc/limeos")
    state_dir = os.getenv("LIMEOS_STATE_DIR", "/var/lib/limeos")
    log_dir = os.getenv("LIMEOS_LOG_DIR", "/var/log/limeos")
    credentials_file = os.getenv("LIMEOS_CREDENTIALS_FILE", os.path.join(config_dir, "credentials.env"))

    if run_command(["getent", "group", "pihealth"]).get("returncode") != 0:
        run_command(["groupadd", "pihealth"])

    directory_layout = (
        (config_dir, ["storage_plugins"]),
        (state_dir, ["storage_plugins"]),
        (log_dir, ["snapraid"]),
    )
    for base, subdirs in directory_layout:
        run_command(["install", "-d", "-m", "0750", "-o", user, "-g", "pihealth", base])
        for subdir in subdirs:
            run_command(["install", "-d", "-m", "0750", "-o", user, "-g", "pihealth", os.path.join(base, subdir)])

    venv_py = os.path.join(repo_path, ".venv", "bin", "python")
    python_bin = venv_py if os.path.isfile(venv_py) else "python3"
    result = run_command(
        [
            python_bin, script,
            "--source-root", repo_path,
            "--config-dir", config_dir,
            "--state-dir", state_dir,
            "--log-dir", log_dir,
            "--legacy-credentials", "/etc/pi-health.env",
            "--credentials-file", credentials_file,
        ],
        timeout=300,
    )

    # Restore service ownership regardless of whether new files were copied.
    run_command(["chown", "-R", f"{user}:pihealth", config_dir, state_dir, log_dir])
    _restore_agent_runtime_ownership()

    if result.get("returncode") != 0:
        return {
            'success': False,
            'error': result.get("stderr") or result.get("error") or 'migration failed',
            'stdout': result.get("stdout", ""),
        }

    # Ensure the nightly package-baseline reconcile timer is installed (idempotent;
    # best-effort so a timer hiccup never blocks the update).
    try:
        cmd_configure_package_reconcile_schedule({"app_dir": repo_path, "user": user})
    except Exception:
        pass

    return {'success': True, 'stdout': result.get("stdout", "")}


def _bundle_is_fresh(repo_path):
    """True when the committed static/v2 bundle matches the frontend source.

    Uses the digest marker written by build:publish. Missing tool/marker (older checkout)
    is treated as fresh so it never blocks an update.
    """
    script = os.path.join(repo_path, "scripts", "bundle_source_digest.py")
    if not os.path.isfile(script):
        return True
    proc = run_command([sys.executable, script, "--check"], timeout=60, cwd=repo_path)
    return proc.get("returncode") == 0


def _pihealth_update_build(ctx):
    """Rebuild the web UI when it is stale and a toolchain is available; else flag staleness."""
    user = ctx["user"]
    repo_path = ctx["repo_path"]
    frontend = os.path.join(repo_path, "frontend")

    if not os.path.isdir(frontend):
        return {'success': True, 'skipped': True, 'reason': 'no frontend directory'}

    fresh = _bundle_is_fresh(repo_path)

    if not shutil.which("npm"):
        # No toolchain: the committed bundle is all we can serve. Surface staleness rather
        # than silently serving old UI (it must be rebuilt and committed upstream).
        if fresh:
            return {'success': True, 'skipped': True,
                    'reason': 'npm not installed; committed bundle is current'}
        return {'success': True, 'skipped': True, 'stale': True,
                'reason': 'npm not installed and the committed web UI bundle is stale; '
                          'rebuild and commit static/v2 upstream'}

    if fresh:
        return {'success': True, 'skipped': True, 'reason': 'web UI already up to date'}

    if not os.path.isdir(os.path.join(frontend, "node_modules")):
        install = run_command(
            ["runuser", "-u", user, "--", "npm", "ci"], timeout=1800, cwd=frontend
        )
        if install.get("returncode") != 0:
            return {
                'success': False,
                'error': install.get("stderr") or install.get("error") or 'npm ci failed',
                'stdout': install.get("stdout", ""),
            }

    result = run_command(
        ["runuser", "-u", user, "--", "npm", "run", "build:publish"], timeout=1800, cwd=frontend
    )
    if result.get("returncode") != 0:
        return {
            'success': False,
            'error': result.get("stderr") or result.get("error") or 'npm build failed',
            'stdout': result.get("stdout", ""),
        }
    return {'success': True, 'stdout': result.get("stdout", "")}


def _pihealth_update_restart(ctx):
    """Schedule delayed app and helper restarts after flushing the response."""
    service_name = ctx["service_name"]
    service_names = [service_name, PIHEALTH_HELPER_SERVICE_NAME]

    if shutil.which("systemd-run"):
        result = run_command([
            "systemd-run",
            "--on-active=2",
            "--timer-property=RemainAfterElapse=no",
            "systemctl", "restart", *service_names,
        ])
        if result.get("returncode") == 0:
            return {'success': True, 'scheduled': True}

    try:
        quoted_services = " ".join(shlex.quote(name) for name in service_names)
        subprocess.Popen(
            ["sh", "-c", f"sleep 2; systemctl restart {quoted_services}"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {'success': True, 'scheduled': True}
    except Exception as exc:
        return {'success': False, 'error': str(exc)}


def _migrate_agent_policy():
    """Converge the deployed broker policy to the current default operation set while
    preserving host-specific resource allowlists.

    The install/repair path preserves the on-disk policy, so an installation created
    before a new read operation existed would keep denying it. This merges the release's
    default operations (adding new ones) over the existing policy, carrying forward the
    per-operation resources that setup filled in, validates the result, and rewrites it.
    """
    if not os.path.exists(AGENT_POLICY_PATH):
        return {'success': True, 'skipped': True, 'reason': 'policy not installed'}
    repo_dir = _agent_repo_dir()
    try:
        with open(os.path.join(repo_dir, 'config', 'agent-policy.default.json')) as handle:
            default_policy = json.load(handle)
        with open(AGENT_POLICY_PATH) as handle:
            current = json.load(handle)
    except (OSError, ValueError):
        return {'success': False, 'error': 'Unable to read the broker policy'}
    current_ops = current.get('operations', {}) if isinstance(current, dict) else {}
    merged_ops = {}
    for name, spec in (default_policy.get('operations') or {}).items():
        op = dict(spec)
        previous = current_ops.get(name)
        if isinstance(previous, dict) and 'resources' in previous and 'resources' in op:
            op['resources'] = previous['resources']  # keep host-specific allowlists
        merged_ops[name] = op
    merged = dict(default_policy)
    merged['operations'] = merged_ops
    try:
        from limeops.policy import LimeOpsPolicy
        LimeOpsPolicy.from_mapping(merged)  # validate before writing
    except Exception:
        return {'success': False, 'error': 'Migrated broker policy failed validation'}
    written = _write_managed_file(
        AGENT_POLICY_PATH, json.dumps(merged, indent=2, sort_keys=True) + '\n', 0o640
    )
    if not written.get('success'):
        return {'success': False, 'error': 'Failed to write the broker policy'}
    if run_command(['chown', 'root:limeops', AGENT_POLICY_PATH]).get('returncode') != 0:
        return {'success': False, 'error': 'Failed to secure the broker policy'}
    added = sorted(set(merged_ops) - set(current_ops))
    return {'success': True, 'migrated': True, 'added_operations': added}


def _pihealth_update_agent(ctx):
    """Converge the deployed AI agent runtime to the pulled release.

    Only runs when the agent is already installed — a self-update never installs the
    agent on a host that never opted in. When installed, it migrates the broker policy to
    the release's operation set (preserving host resources), re-runs the idempotent
    runtime install (re-copies the agent packages + package module/manifest and re-renders
    the systemd unit templates so a deployed unit cannot drift), reconciles the package
    baseline, and restarts the agent. A failure at any step is reported, not swallowed.
    """
    if not os.path.exists(AGENT_UNIT_PATH):
        return {'success': True, 'skipped': True, 'reason': 'agent not installed'}
    policy = _migrate_agent_policy()
    if not policy.get('success'):
        return {'success': False, 'error': policy.get('error', 'broker policy migration failed')}
    install = cmd_agent_runtime_install({})  # restarts limeopsd -> loads the migrated policy
    if not install.get('success'):
        return {'success': False, 'error': install.get('error', 'agent runtime refresh failed')}
    reconcile = cmd_packages_reconcile({'mode': 'apply'})
    if not reconcile.get('success', True):
        return {
            'success': False,
            'error': 'Package baseline reconcile reported failures',
            'failed': reconcile.get('failed', []),
            'drift': reconcile.get('drift', []),
        }
    if run_command(['systemctl', 'restart', 'limeos-agent.service'], timeout=30).get(
        'returncode'
    ) != 0:
        return {'success': False, 'error': 'Failed to restart the agent runtime'}
    return {
        'success': True,
        'refreshed': True,
        'added_operations': policy.get('added_operations', []),
        'reconciled': reconcile.get('applied', []),
        'drift': reconcile.get('drift', []),
    }


def cmd_pihealth_update(params):
    """Run one Pi-Health self-update step, or the legacy combined pull+restart.

    The orchestrator (``pihealth_update_service``) drives the steps one at a
    time so it can stream progress; an empty/``all`` step keeps older callers
    working with the original pull-then-restart behaviour.
    """
    ctx, error = _validate_pihealth_update_params(params)
    if error:
        return {'success': False, 'error': error}

    step = (params.get("step") or "").strip().lower()
    step_handlers = {
        "pull": _pihealth_update_pull,
        "deps": _pihealth_update_deps,
        "migrate": _pihealth_update_migrate,
        "build": _pihealth_update_build,
        "agent": _pihealth_update_agent,
        "restart": _pihealth_update_restart,
    }
    if step in step_handlers:
        return step_handlers[step](ctx)

    if step in ("", "all", "legacy"):
        pull = _pihealth_update_pull(ctx)
        if not pull.get("success"):
            return pull
        restart = _pihealth_update_restart(ctx)
        if not restart.get("success"):
            return restart
        return {
            'success': True,
            'old_commit': pull.get("old_commit"),
            'new_commit': pull.get("new_commit"),
        }

    return {'success': False, 'error': f'unknown update step: {step}'}


def cmd_plugin_install(params):
    """Install a third-party plugin from GitHub or pip."""
    source_type = params.get('type', '').strip()
    source = params.get('source', '').strip()
    plugin_id = params.get('id', '').strip()

    if not source_type or not source:
        return {'success': False, 'error': 'type and source required'}

    if source_type == 'github':
        if not plugin_id:
            plugin_id = _derive_plugin_id(source)
        if not plugin_id or not _validate_plugin_id(plugin_id):
            return {'success': False, 'error': 'Invalid plugin ID'}

        normalized = _normalize_github_source(source)
        if not normalized:
            return {'success': False, 'error': 'Invalid GitHub source'}

        os.makedirs(PLUGIN_DIR, exist_ok=True)
        plugin_path = os.path.join(PLUGIN_DIR, plugin_id)
        if os.path.exists(plugin_path):
            return {'success': False, 'error': 'Plugin already installed'}

        deps = _ensure_dependencies(
            ['git'],
            {
                'apt-get': ['git'],
                'dnf': ['git'],
                'pacman': ['git']
            }
        )
        if not deps.get('success'):
            return deps

        result = run_command(['git', 'clone', '--depth', '1', normalized, plugin_path], timeout=600)
        if result.get('returncode') != 0:
            return {'success': False, 'error': result.get('stderr', 'Failed to clone repo')}

        return {'success': True, 'id': plugin_id}

    if source_type == 'pip':
        # Disabled: `pip install` runs arbitrary setup.py as root into the system
        # Python. Install from a GitHub source instead, or add a sandboxed installer.
        return {'success': False, 'error': 'pip plugins are not supported'}

    return {'success': False, 'error': 'Unsupported plugin type'}


def cmd_plugin_remove(params):
    """Remove a third-party plugin."""
    plugin_id = params.get('id', '').strip()
    source_type = params.get('type', '').strip()
    source = params.get('source', '').strip()

    if not plugin_id and source_type == 'github':
        return {'success': False, 'error': 'Plugin ID required'}

    if source_type == 'github':
        if not _validate_plugin_id(plugin_id):
            return {'success': False, 'error': 'Invalid plugin ID'}

        plugin_path = os.path.join(PLUGIN_DIR, plugin_id)
        if os.path.exists(plugin_path):
            shutil.rmtree(plugin_path)
        return {'success': True}

    if source_type == 'pip':
        package = source or plugin_id
        if not package:
            return {'success': False, 'error': 'Package name required'}
        result = run_command([sys.executable, '-m', 'pip', 'uninstall', '-y', package], timeout=600)
        if result.get('returncode') != 0:
            return {'success': False, 'error': result.get('stderr', 'pip uninstall failed')}
        return {'success': True}

    return {'success': False, 'error': 'Unsupported plugin type'}


def _agent_params_are_empty(params):
    return isinstance(params, dict) and not params


def _agent_reject_params(params):
    if _agent_params_are_empty(params):
        return None
    return {'success': False, 'error': 'Agent operation does not accept parameters'}


def _agent_repo_dir():
    repo_dir = PIHEALTH_REPO_DIR or os.path.dirname(os.path.realpath(__file__))
    repo_dir = os.path.realpath(repo_dir)
    if not os.path.isabs(repo_dir) or not os.path.isfile(
        os.path.join(repo_dir, 'config', 'agent-policy.default.json')
    ):
        return None
    return repo_dir


def _ensure_system_group(name):
    if run_command(['getent', 'group', name]).get('returncode') == 0:
        return True
    return _run_account_command(['/usr/sbin/groupadd', '--system', name]).get('returncode') == 0


def _ensure_system_user(name, group, home):
    if run_command(['getent', 'passwd', name]).get('returncode') == 0:
        return True
    return _run_account_command([
        '/usr/sbin/useradd', '--system', '--gid', group, '--home-dir', home,
        '--create-home', '--shell', '/usr/sbin/nologin', name,
    ]).get('returncode') == 0


def _run_account_command(argv):
    """Run one fixed shadow-utils command outside the helper mount sandbox."""
    return run_command(
        [
            'systemd-run', '--quiet', '--wait', '--pipe', '--collect',
            '--service-type=exec', *argv,
        ],
        timeout=60,
    )


def _agent_install_directory(path, mode, owner, group):
    result = run_command([
        'install', '-d', '-m', format(mode, '04o'), '-o', owner, '-g', group, path,
    ])
    return result.get('returncode') == 0


def _restore_agent_runtime_ownership():
    """Restore fixed agent paths after legacy state migration or helper restart."""
    if run_command(['getent', 'passwd', 'lime-agent']).get('returncode') != 0:
        return True
    for path, mode in (
        ('/var/lib/lime-agent', 0o700),
        (CLAUDE_CONFIG_DIR, 0o700),
        (AGENT_STATE_DIR, 0o750),
    ):
        if not os.path.isdir(path):
            continue
        if run_command(['chown', '-R', 'lime-agent:lime-agent', path]).get('returncode') != 0:
            return False
        if run_command(['chmod', format(mode, '04o'), path]).get('returncode') != 0:
            return False
    return True


def _ensure_agent_file(path, content, mode, ownership):
    """Create one fixed agent file once; preserve configured content on repair."""
    if os.path.lexists(path):
        if os.path.islink(path) or not os.path.isfile(path):
            return False
    else:
        written = _write_managed_file(path, content, mode)
        if not written.get('success'):
            return False
    if run_command(['chmod', format(mode, '04o'), path]).get('returncode') != 0:
        return False
    return run_command(['chown', ownership, path]).get('returncode') == 0


def cmd_agent_runtime_install(params):
    """Create the fixed LimeOps/agent identities, paths, policy, and units."""
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    repo_dir = _agent_repo_dir()
    if not repo_dir:
        return {'success': False, 'error': 'LimeOS repository is unavailable'}

    for group in ('limeops', 'lime-agent', 'limeops-client'):
        if not _ensure_system_group(group):
            return {'success': False, 'error': 'Failed to create agent identities'}
    if not _ensure_system_user('limeops', 'limeops', '/var/lib/limeops'):
        return {'success': False, 'error': 'Failed to create agent identities'}
    if not _ensure_system_user('lime-agent', 'lime-agent', '/var/lib/lime-agent'):
        return {'success': False, 'error': 'Failed to create agent identities'}

    if _run_account_command([
        '/usr/sbin/usermod', '-a', '-G', 'limeops-client', 'lime-agent'
    ]).get('returncode') != 0:
        return {'success': False, 'error': 'Failed to authorize the agent client'}
    privileged_groups = ('docker', 'pihealth')
    if any(
        run_command(['getent', 'group', group]).get('returncode') != 0
        for group in privileged_groups
    ):
        return {'success': False, 'error': 'Required LimeOps groups are unavailable'}
    result = _run_account_command([
        '/usr/sbin/usermod', '-a', '-G', ','.join(privileged_groups), 'limeops'
    ])
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'Failed to authorize the LimeOps broker'}

    integrations_config_dir = os.path.dirname(AGENT_CONFIG_PATH)
    if os.path.islink(integrations_config_dir) or not os.path.isdir(integrations_config_dir):
        return {'success': False, 'error': 'LimeOS integrations directory is unavailable'}

    directories = (
        (AGENT_STATE_DIR, 0o750, 'lime-agent', 'lime-agent'),
        ('/var/lib/lime-agent', 0o700, 'lime-agent', 'lime-agent'),
        (CLAUDE_CONFIG_DIR, 0o700, 'lime-agent', 'lime-agent'),
        (LIMEOPS_STATE_DIR, 0o750, 'limeops', 'limeops'),
        (LIMEOPS_SOCKET_DIR, 0o750, 'limeops', 'limeops-client'),
    )
    if not all(_agent_install_directory(*item) for item in directories):
        return {'success': False, 'error': 'Failed to create agent runtime directories'}

    python_bin = os.path.join(repo_dir, '.venv', 'bin', 'python')
    if not os.path.isfile(python_bin):
        return {'success': False, 'error': 'LimeOS virtual environment is unavailable'}
    if not _agent_install_directory(AGENT_LIB_DIR, 0o755, 'root', 'root'):
        return {'success': False, 'error': 'Failed to create the agent runtime library'}
    for package in ('agent_gateway', 'agent_provider', 'agent_runtime', 'agent_transport', 'limeops'):
        source = os.path.join(repo_dir, package)
        destination = os.path.join(AGENT_LIB_DIR, package)
        if not os.path.isdir(source):
            return {'success': False, 'error': 'Agent runtime package is unavailable'}
        try:
            shutil.copytree(source, destination, dirs_exist_ok=True)
        except OSError:
            return {'success': False, 'error': 'Failed to install the agent runtime package'}
    # Top-level module + its manifest so the broker can serve packages.status.
    try:
        module_source = os.path.join(repo_dir, 'limeos_packages.py')
        if os.path.isfile(module_source):
            shutil.copy2(module_source, os.path.join(AGENT_LIB_DIR, 'limeos_packages.py'))
        manifest_dir = os.path.join(AGENT_LIB_DIR, 'config')
        os.makedirs(manifest_dir, exist_ok=True)
        manifest_source = os.path.join(repo_dir, 'config', 'limeos-packages.json')
        if os.path.isfile(manifest_source):
            shutil.copy2(manifest_source, os.path.join(manifest_dir, 'limeos-packages.json'))
    except OSError:
        return {'success': False, 'error': 'Failed to install the package manifest'}
    for argv, timeout in (
        (['python3', '-m', 'venv', AGENT_VENV_DIR], 120),
        ([os.path.join(AGENT_VENV_DIR, 'bin', 'pip'), 'install', 'websocket-client>=1.8,<2'], 300),
        # The broker reads system status via psutil; guarantee it for the system
        # interpreter path so system.status cannot fail with upstream_failure.
        (['apt-get', 'install', '-y', 'python3-psutil'], 300),
        (['chmod', '-R', 'u=rwX,go=rX', AGENT_LIB_DIR], 60),
        (['chown', '-R', 'root:root', AGENT_LIB_DIR], 60),
        (['chown', '-R', 'lime-agent:lime-agent', AGENT_VENV_DIR], 60),
    ):
        if run_command(argv, timeout=timeout).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to prepare the isolated agent runtime'}
    policy_source = os.path.join(repo_dir, 'config', 'agent-policy.default.json')
    settings_source = os.path.join(repo_dir, 'config', 'agents.default.json')
    try:
        with open(policy_source) as handle:
            policy = handle.read()
        with open(settings_source) as handle:
            settings = handle.read()
    except OSError:
        return {'success': False, 'error': 'Default agent configuration is unavailable'}

    preserved_files = (
        (AGENT_POLICY_PATH, policy, 0o640, 'root:limeops'),
        (AGENT_CONFIG_PATH, settings, 0o640, 'root:limeops'),
        (AGENT_ENV_PATH, '', 0o640, 'root:lime-agent'),
    )
    if not all(_ensure_agent_file(*item) for item in preserved_files):
        return {'success': False, 'error': 'Failed to secure agent configuration files'}

    managed_files = (
        (LIMEOPS_UNIT_PATH, render_limeops_unit(repo_dir), 0o644, 'root:root'),
        (AGENT_UNIT_PATH, render_agent_unit(repo_dir, python_bin), 0o644, 'root:root'),
    )
    for path, content, mode, ownership in managed_files:
        written = _write_managed_file(path, content, mode)
        if not written.get('success'):
            return {'success': False, 'error': 'Failed to write agent runtime files'}
        if run_command(['chown', ownership, path]).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to secure agent runtime files'}

    if not os.path.exists(LIMEOPS_AUDIT_PATH):
        audit = _write_managed_file(LIMEOPS_AUDIT_PATH, '', 0o640)
        if not audit.get('success'):
            return {'success': False, 'error': 'Failed to create the agent audit log'}
    for argv in (
        ['chown', 'limeops:limeops', LIMEOPS_AUDIT_PATH],
        ['chmod', '0640', LIMEOPS_AUDIT_PATH],
    ):
        if run_command(argv).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to secure the agent audit log'}

    for argv in (
        ['systemctl', 'daemon-reload'],
        ['systemctl', 'enable', 'limeopsd.service'],
        ['systemctl', 'restart', 'limeopsd.service'],
        ['systemctl', 'enable', 'limeos-agent.service'],
    ):
        if run_command(argv, timeout=60).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to activate agent runtime units'}
    _write_agent_release_marker(repo_dir)
    return {'success': True, 'runtime_installed': True}


def _agent_repo_commit(repo_dir):
    result = run_command(['git', '-C', repo_dir, 'rev-parse', 'HEAD'])
    return (result.get('stdout') or '').strip() if result.get('returncode') == 0 else ''


def _write_agent_release_marker(repo_dir):
    """Record the deployed agent-runtime commit so startup can detect a stale deploy."""
    commit = _agent_repo_commit(repo_dir)
    if not commit:
        return
    try:
        with open(os.path.join(AGENT_LIB_DIR, '.release'), 'w') as handle:
            handle.write(commit + '\n')
    except OSError:
        pass


def cmd_agent_converge_if_stale(params):
    """Converge the agent runtime iff the deployed commit is behind the repo.

    This closes the first-release bootstrap gap: a self-update runs the pre-pull
    orchestrator/helper, so the release that introduces the agent step cannot run it in
    that same flow, and a subsequent update exits as already-current. The web service
    calls this on startup (after it has restarted on the new code), so the agent converges
    automatically on the next boot without a second update.
    """
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    if not os.path.exists(AGENT_UNIT_PATH):
        return {'success': True, 'skipped': True, 'reason': 'agent not installed'}
    repo_dir = _agent_repo_dir()
    if not repo_dir:
        return {'success': True, 'skipped': True, 'reason': 'repository unavailable'}
    head = _agent_repo_commit(repo_dir)
    try:
        with open(os.path.join(AGENT_LIB_DIR, '.release')) as handle:
            deployed = handle.read().strip()
    except OSError:
        deployed = ''
    if head and deployed == head:
        return {'success': True, 'skipped': True, 'reason': 'agent runtime is current'}
    return _pihealth_update_agent(ctx={})


def _unit_state(unit, action):
    result = run_command(['systemctl', action, unit], timeout=10)
    return (result.get('stdout') or '').strip() or 'unknown'


def _agent_broker_state():
    state = _unit_state('limeopsd.service', 'is-active')
    if state != 'active':
        return state
    try:
        socket_mode = os.stat(LIMEOPS_SOCKET_PATH, follow_symlinks=False).st_mode
    except OSError:
        return 'failed'
    return 'active' if stat.S_ISSOCK(socket_mode) else 'failed'


def cmd_agent_runtime_status(params):
    """Return a non-secret status snapshot for AA-006."""
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    version_result = run_command([
        'runuser', '-u', 'lime-agent', '--', '/usr/bin/claude', '--version'
    ], timeout=10)
    version_match = re.search(r'(?<!\d)\d+\.\d+\.\d+(?!\d)', version_result.get('stdout') or '')
    version_tuple = (
        tuple(int(part) for part in version_match.group(0).split('.'))
        if version_match else ()
    )
    auth_result = run_command([
        'runuser', '-u', 'lime-agent', '--', 'env', '-i',
        'HOME=/var/lib/lime-agent', 'USER=lime-agent', 'LOGNAME=lime-agent',
        'PATH=/usr/local/bin:/usr/bin:/bin', 'LANG=C.UTF-8',
        f'CLAUDE_CONFIG_DIR={CLAUDE_CONFIG_DIR}',
        '/usr/bin/claude', 'auth', 'status',
    ], timeout=10)
    try:
        auth = json.loads(auth_result.get('stdout') or '{}')
    except ValueError:
        auth = {}
    try:
        with open(AGENT_CONFIG_PATH) as handle:
            settings = json.load(handle)
        from agent_runtime.service import parse_config
        parsed_settings = parse_config(settings)
        configured = bool(
            parsed_settings.team_id
            and parsed_settings.channel_id
            and parsed_settings.bot_token_id
            and parsed_settings.allowed_channels
        )
    except (OSError, ValueError):
        settings, parsed_settings, configured = {}, None, False
    return {
        'success': True,
        'runtime_installed': os.path.isfile(AGENT_UNIT_PATH) and os.path.isfile(LIMEOPS_UNIT_PATH),
        'agent_active': _unit_state('limeos-agent.service', 'is-active'),
        'broker_active': _agent_broker_state(),
        'claude_installed': version_result.get('returncode') == 0,
        'claude_version': version_match.group(0) if version_match else None,
        'claude_compatible': bool(version_tuple and version_tuple >= (2, 1, 205)),
        'claude_credentials_present': os.path.isfile(
            os.path.join(CLAUDE_CONFIG_DIR, '.credentials.json')
        ),
        'claude_authenticated': bool(
            auth_result.get('returncode') == 0
            and isinstance(auth, dict)
            and auth.get('loggedIn') is True
        ),
        'configured': configured,
        'enabled': bool(parsed_settings.enabled) if parsed_settings else False,
        'team_id': parsed_settings.team_id if parsed_settings else None,
        'channel_id': parsed_settings.channel_id if parsed_settings else None,
        'bot_token_id': parsed_settings.bot_token_id if parsed_settings else None,
        'auth_state': _agent_auth_manager.current_state(),
    }


def cmd_agent_runtime_disable(params):
    """Stop the assistant without changing Mattermost, alerts, or retained state."""
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    try:
        with open(AGENT_CONFIG_PATH) as handle:
            settings = json.load(handle)
        if isinstance(settings, dict):
            settings['enabled'] = False
            written = _write_managed_file(
                AGENT_CONFIG_PATH, json.dumps(settings, indent=2) + '\n', 0o640
            )
            if not written.get('success'):
                return {'success': False, 'error': 'Failed to disable the agent runtime'}
            if run_command(['chown', 'root:limeops', AGENT_CONFIG_PATH]).get('returncode') != 0:
                return {'success': False, 'error': 'Failed to disable the agent runtime'}
    except (OSError, ValueError):
        pass
    result = run_command(['systemctl', 'disable', '--now', 'limeos-agent.service'], timeout=60)
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'Failed to disable the agent runtime'}
    return {'success': True, 'disabled': True}


def _install_claude_apt_repository():
    """Install Anthropic's fixed apt key after checking its published fingerprint."""
    try:
        with urllib.request.urlopen(CLAUDE_APT_KEY_URL, timeout=30) as response:
            key_data = response.read(256 * 1024 + 1)
    except (OSError, urllib.error.URLError):
        return {'success': False, 'error': 'Failed to download Claude signing key'}
    if not key_data or len(key_data) > 256 * 1024:
        return {'success': False, 'error': 'Invalid Claude signing key'}
    try:
        with tempfile.TemporaryDirectory(prefix='claude-code-gpg-') as gpg_home:
            temp_path = os.path.join(gpg_home, 'claude-code.asc')
            with open(temp_path, 'wb') as handle:
                handle.write(key_data)
            checked = run_command(
                ['gpg', '--homedir', gpg_home, '--show-keys', '--with-colons', temp_path],
                timeout=30,
            )
            fingerprints = [
                line.split(':')[9].upper()
                for line in (checked.get('stdout') or '').splitlines()
                if line.startswith('fpr:') and len(line.split(':')) > 9
            ]
            if (
                checked.get('returncode') != 0
                or CLAUDE_SIGNING_FINGERPRINT not in fingerprints
            ):
                return {'success': False, 'error': 'Claude signing key verification failed'}
            if run_command(
                ['install', '-d', '-m', '0755', '/etc/apt/keyrings']
            ).get('returncode') != 0:
                return {'success': False, 'error': 'Failed to create apt key directory'}
            key_text = key_data.decode('ascii')
            key_result = _write_managed_file(CLAUDE_APT_KEY_PATH, key_text, 0o644)
            source_result = _write_managed_file(
                CLAUDE_APT_SOURCE_PATH, CLAUDE_APT_SOURCE, 0o644
            )
            if not key_result.get('success') or not source_result.get('success'):
                return {'success': False, 'error': 'Failed to configure Claude apt repository'}
            return {'success': True}
    except (OSError, UnicodeDecodeError):
        return {'success': False, 'error': 'Failed to configure Claude apt repository'}


def _resolve_claude_apt_version(pinned_upstream):
    """Full apt version of claude-code whose upstream matches the pin, or None if the
    channel does not currently offer it."""
    from limeos_packages import upstream_version

    result = run_command(['apt-cache', 'madison', 'claude-code'], timeout=30)
    if result.get('returncode') != 0:
        return None
    for line in (result.get('stdout') or '').splitlines():
        parts = [part.strip() for part in line.split('|')]
        if len(parts) >= 2 and upstream_version(parts[1]) == pinned_upstream:
            return parts[1]
    return None


def cmd_agent_provider_install(params):
    """Install Claude Code from the fixed stable signed apt repository."""
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    repository = _install_claude_apt_repository()
    if not repository.get('success'):
        return repository
    # A missing or unreadable Claude pin is a hard error — never fall back to the rolling
    # latest, which would install and hold an untested version while reporting success.
    try:
        from limeos_packages import load_manifest, upstream_version
        pinned = next(
            (spec.version for spec in load_manifest()
             if spec.name == 'claude-code' and spec.policy == 'pinned' and spec.version),
            None,
        )
    except Exception:
        return {'success': False, 'error': 'Unable to read the Claude Code pin from the manifest'}
    if not pinned:
        return {'success': False, 'error': 'Claude Code pin missing from the package manifest'}
    if run_command(['apt-get', 'update'], timeout=300).get('returncode') != 0:
        return {'success': False, 'error': 'Failed to refresh the apt index'}
    # Resolve the full Debian version whose upstream matches the pin (the pin names an
    # upstream version like 2.1.207; the channel serves 2.1.207-1). If the pinned version
    # is no longer offered, fail cleanly — the signal to test + bump the manifest (or move
    # the entry to present-min for a rolling channel).
    full_version = _resolve_claude_apt_version(upstream_version(pinned))
    if not full_version:
        return {'success': False,
                'error': f'Pinned Claude Code {pinned} is not available in the apt channel'}
    install = run_command(
        ['apt-get', 'install', '-y', '--allow-downgrades', '--allow-change-held-packages',
         f'claude-code={full_version}'],
        timeout=600,
    )
    if install.get('returncode') != 0:
        return {'success': False, 'error': 'Failed to install Claude Code'}
    version = run_command(['/usr/bin/claude', '--version'], timeout=10)
    if version.get('returncode') != 0:
        return {'success': False, 'error': 'Claude Code verification failed'}
    match = re.search(r'(?<!\d)\d+\.\d+\.\d+(?!\d)', version.get('stdout') or '')
    if not match or tuple(int(part) for part in match.group(0).split('.')) < (2, 1, 205):
        return {'success': False, 'error': 'Installed Claude Code version is unsupported'}
    if upstream_version(match.group(0)) != upstream_version(pinned):
        return {'success': False,
                'error': f'Claude Code {match.group(0)} does not match the pinned {pinned}'}
    # Hold the version; the CLI's own auto-updater is disabled via DISABLE_AUTOUPDATER in the
    # agent environment. A failed hold means the pin isn't enforced, so fail the install.
    if run_command(['apt-mark', 'hold', 'claude-code'], timeout=30).get('returncode') != 0:
        return {'success': False, 'error': 'Failed to hold the Claude Code version'}
    return {'success': True, 'installed': True, 'version': match.group(0)}


def write_agent_bot_secret(token):
    """Write only the fixed Mattermost bot token destination; never return the token."""
    if (
        not isinstance(token, str)
        or not re.fullmatch(r'[A-Za-z0-9._-]{1,512}', token)
    ):
        return {'success': False, 'error': 'Invalid Mattermost bot token'}
    if os.path.lexists(AGENT_ENV_PATH) and (
        os.path.islink(AGENT_ENV_PATH) or not os.path.isfile(AGENT_ENV_PATH)
    ):
        return {'success': False, 'error': 'Failed to store Mattermost bot token'}
    directory = os.path.dirname(AGENT_ENV_PATH)
    try:
        fd, temp_path = tempfile.mkstemp(dir=directory, prefix='.agents.env.', suffix='.tmp')
        with os.fdopen(fd, 'w') as handle:
            handle.write(f'MATTERMOST_BOT_TOKEN={token}\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o640)
        os.replace(temp_path, AGENT_ENV_PATH)
    except OSError:
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        return {'success': False, 'error': 'Failed to store Mattermost bot token'}
    if run_command(['chown', 'root:lime-agent', AGENT_ENV_PATH]).get('returncode') != 0:
        return {'success': False, 'error': 'Failed to secure Mattermost bot token'}
    return {'success': True, 'stored': True}


def cmd_agent_provider_auth_start(params):
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    if not _restore_agent_runtime_ownership():
        return {'success': False, 'error': 'Claude authentication storage is unavailable'}
    try:
        operation_id = _agent_auth_manager.start()
        return {'success': True, 'operation_id': operation_id}
    except (AuthBusyError, OSError):
        return {'success': False, 'error': 'Claude authentication is already running or unavailable'}


def cmd_agent_provider_auth_status(params):
    if not isinstance(params, dict) or set(params) != {'operation_id', 'cursor'}:
        return {'success': False, 'error': 'Invalid Claude authentication status request'}
    try:
        status = _agent_auth_manager.status(params['operation_id'], cursor=params['cursor'])
        return {'success': True, **status}
    except (AuthNotFoundError, AuthInputError):
        return {'success': False, 'error': 'Claude authentication operation was not found'}


def cmd_agent_provider_auth_submit(params):
    if not isinstance(params, dict) or set(params) != {'operation_id', 'code'}:
        return {'success': False, 'error': 'Invalid Claude authentication response'}
    try:
        _agent_auth_manager.submit(params['operation_id'], params['code'])
        return {'success': True, 'accepted': True}
    except (AuthNotFoundError, AuthInputError):
        return {'success': False, 'error': 'Claude authentication response was rejected'}


def cmd_agent_provider_auth_cancel(params):
    if not isinstance(params, dict) or set(params) != {'operation_id'}:
        return {'success': False, 'error': 'Invalid Claude authentication cancellation'}
    try:
        _agent_auth_manager.cancel(params['operation_id'])
        return {'success': True, 'cancelled': True}
    except AuthNotFoundError:
        return {'success': False, 'error': 'Claude authentication operation was not found'}


def cmd_agent_bot_secret_write(params):
    if not isinstance(params, dict) or set(params) != {'token'}:
        return {'success': False, 'error': 'Invalid Mattermost bot credential request'}
    return write_agent_bot_secret(params.get('token'))


def cmd_agent_configure(params):
    if not isinstance(params, dict) or set(params) != {'settings', 'policy'}:
        return {'success': False, 'error': 'Invalid agent configuration request'}
    settings, policy = params.get('settings'), params.get('policy')
    try:
        from agent_runtime.service import parse_config
        from limeops.policy import LimeOpsPolicy

        parse_config(settings)
        LimeOpsPolicy.from_mapping(policy)
        with open(os.path.join(_agent_repo_dir(), 'config', 'agent-policy.default.json')) as handle:
            default_policy = json.load(handle)
        if set(policy.get('operations', {})) != set(default_policy.get('operations', {})):
            return {'success': False, 'error': 'Agent policy operations do not match the fixed profile'}
    except Exception:
        return {'success': False, 'error': 'Invalid agent configuration'}
    files = (
        (AGENT_POLICY_PATH, policy, 'root:limeops'),
        (AGENT_CONFIG_PATH, settings, 'root:limeops'),
    )
    for path, payload, ownership in files:
        written = _write_managed_file(
            path, json.dumps(payload, indent=2, sort_keys=True) + '\n', 0o640
        )
        if not written.get('success'):
            return {'success': False, 'error': 'Failed to write agent configuration'}
        if run_command(['chown', ownership, path]).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to secure agent configuration'}
    return {'success': True, 'configured': True}


def cmd_agent_runtime_start(params):
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    status = cmd_agent_runtime_status({})
    if not status.get('configured') or not status.get('claude_authenticated'):
        return {'success': False, 'error': 'Agent setup or Claude authentication is required'}
    if status.get('broker_active') != 'active':
        return {'success': False, 'error': 'LimeOps broker is unavailable'}
    try:
        with open(AGENT_CONFIG_PATH) as handle:
            settings = json.load(handle)
        settings['enabled'] = True
        written = _write_managed_file(
            AGENT_CONFIG_PATH, json.dumps(settings, indent=2) + '\n', 0o640
        )
        if not written.get('success'):
            return {'success': False, 'error': 'Failed to enable the agent runtime'}
        if run_command(['chown', 'root:limeops', AGENT_CONFIG_PATH]).get('returncode') != 0:
            return {'success': False, 'error': 'Failed to enable the agent runtime'}
    except (OSError, TypeError, ValueError):
        return {'success': False, 'error': 'Failed to enable the agent runtime'}
    result = run_command(['systemctl', 'enable', '--now', 'limeos-agent.service'], timeout=60)
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'Failed to start the agent runtime'}
    return {'success': True, 'started': True}


def _agent_read_json_lines(path, limit, allowed_fields):
    try:
        with open(path, 'rb') as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - 512 * 1024)
            handle.seek(start)
            data = handle.read(512 * 1024)
    except OSError:
        return []
    lines = data.splitlines()
    if start and lines:
        lines = lines[1:]
    lines = lines[-limit:]
    records = []
    output_bytes = 0
    for line in reversed(lines):
        try:
            record = json.loads(line.decode('utf-8'))
        except ValueError:
            continue
        if isinstance(record, dict):
            public = {key: record.get(key) for key in allowed_fields if key in record}
            size = len(json.dumps(public, separators=(',', ':')).encode('utf-8'))
            if output_bytes + size > 48 * 1024:
                break
            records.append(public)
            output_bytes += size
    records.reverse()
    return records


def _agent_limit_params(params):
    if not isinstance(params, dict) or set(params) != {'limit'}:
        return None
    limit = params.get('limit')
    return limit if isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 200 else None


def cmd_agent_usage_read(params):
    limit = _agent_limit_params(params)
    if limit is None:
        return {'success': False, 'error': 'Invalid agent usage limit'}
    counters_path = os.path.join(AGENT_STATE_DIR, 'usage-counters.json')
    try:
        with open(counters_path) as handle:
            counters = json.load(handle)
    except (OSError, ValueError):
        counters = {}
    today = datetime.now(timezone.utc).date().isoformat()
    def safe_count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    totals = {
        'total_turns': safe_count(counters.get('total_turns', 0)),
        'total_invocations': safe_count(counters.get('total_invocations', 0)),
        'invocations_today': (
            safe_count(counters.get('invocations', 0))
            if counters.get('invocation_date') == today else 0
        ),
    }
    fields = (
        'at', 'conversation_id', 'correlation_id', 'outcome', 'rounds',
        'duration_seconds', 'tool_operations', 'tool_audit_ids',
    )
    records = _agent_read_json_lines(
        os.path.join(AGENT_STATE_DIR, 'usage-records.jsonl'), limit, fields
    )
    return {'success': True, 'totals': totals, 'records': records}


def cmd_agent_audit_read(params):
    limit = _agent_limit_params(params)
    if limit is None:
        return {'success': False, 'error': 'Invalid agent audit limit'}
    fields = (
        'ts', 'phase', 'request_id', 'audit_id', 'operation', 'actor_type',
        'actor_id', 'actor_username', 'ok', 'error_code', 'duration_ms', 'output_bytes',
    )
    return {
        'success': True,
        'records': _agent_read_json_lines(LIMEOPS_AUDIT_PATH, limit, fields),
    }


def cmd_agent_delivery_test(params):
    rejected = _agent_reject_params(params)
    if rejected:
        return rejected
    try:
        from agent_runtime.service import parse_config
        from agent_transport.bot_client import MattermostBotApi
        from agent_transport.bot_setup import verify_threaded_delivery

        with open(AGENT_CONFIG_PATH) as handle:
            settings = parse_config(json.load(handle))
        token = None
        with open(AGENT_ENV_PATH) as handle:
            for line in handle:
                if line.startswith('MATTERMOST_BOT_TOKEN='):
                    token = line.partition('=')[2].strip()
                    break
        if not token or not settings.channel_id:
            return {'success': False, 'error': 'Agent delivery is not configured'}
        api = MattermostBotApi(settings.site_url)
        api.use_token(token)
        delivered = verify_threaded_delivery(api, channel_id=settings.channel_id)
        return {'success': bool(delivered), 'delivered': bool(delivered)}
    except Exception:
        return {'success': False, 'error': 'Agent delivery test failed'}


def _packages_apt_command(action):
    """Translate a manifest ReconcileAction into a fixed apt argv (names/versions come
    from the validated manifest, so no untrusted input reaches the shell)."""
    if action.action == 'install_version':
        # A pinned package is held; changing its version (up or down) needs both flags.
        return [
            'apt-get', 'install', '-y', '--allow-downgrades', '--allow-change-held-packages',
            f'{action.name}={action.version}',
        ]
    if action.action == 'hold':
        return ['apt-mark', 'hold', action.name]
    if action.action in ('install', 'upgrade_min'):
        return ['apt-get', 'install', '-y', action.name]
    if action.action == 'remove':
        return ['apt-get', 'remove', '-y', action.name]
    # disable_self_update is enforced by DISABLE_AUTOUPDATER in the agent environment.
    return None


def cmd_packages_reconcile(params):
    """Reconcile installed packages to the shipped manifest. Accepts only {mode}, where
    mode is 'check' (read-only report) or 'apply' (enforce the manifest). Package names
    and versions come only from the validated manifest, never from the caller."""
    if not isinstance(params, dict) or set(params) - {'mode'}:
        return {'success': False, 'error': 'packages.reconcile accepts only a mode'}
    mode = params.get('mode', 'check')
    if mode not in {'check', 'apply'}:
        return {'success': False, 'error': 'mode must be check or apply'}
    try:
        from limeos_packages import (
            check_packages,
            compliance_report,
            load_manifest,
            plan_actions,
        )
        specs = load_manifest()
    except Exception:
        return {'success': False, 'error': 'Unable to read the package manifest'}

    def dpkg_version(spec):
        if spec.manager != 'apt':
            return None
        result = run_command(['dpkg-query', '-W', '-f', '${Version}', spec.name], timeout=10)
        if result.get('returncode') != 0:
            return None
        return (result.get('stdout') or '').strip() or None

    def dpkg_ge(a, b):
        return run_command(['dpkg', '--compare-versions', a, 'ge', b], timeout=10).get(
            'returncode'
        ) == 0

    if mode == 'check':
        report = compliance_report(check_packages(specs, dpkg_version, version_ge=dpkg_ge))
        return {'success': True, 'mode': 'check', **report}

    apt_actions = [
        action
        for action in plan_actions(specs, dpkg_version, version_ge=dpkg_ge)
        if action.manager == 'apt'
    ]
    if apt_actions:
        run_command(['apt-get', 'update'], timeout=300)
    applied, failed = [], []
    for action in apt_actions:
        argv = _packages_apt_command(action)
        if argv is None:
            continue
        if run_command(argv, timeout=600).get('returncode') == 0:
            applied.append(f'{action.action}:{action.name}')
        else:
            failed.append(f'{action.action}:{action.name}')
    report = compliance_report(check_packages(specs, dpkg_version, version_ge=dpkg_ge))
    return {'success': not failed, 'mode': 'apply', 'applied': applied, 'failed': failed, **report}


PACKAGE_RECONCILE_UNIT = 'limeos-package-reconcile'
PACKAGE_UPDATES_CONFIG = '/etc/limeos/integrations/package-updates.json'


def _dpkg_installed_version(name):
    result = run_command(['dpkg-query', '-W', '-f', '${Version}', name], timeout=10)
    if result.get('returncode') != 0:
        return None
    return (result.get('stdout') or '').strip() or None


def _apt_candidate_version(name):
    """The repo candidate version for an apt package, or None."""
    result = run_command(['apt-cache', 'policy', name], timeout=30)
    if result.get('returncode') != 0:
        return None
    for line in (result.get('stdout') or '').splitlines():
        line = line.strip()
        if line.startswith('Candidate:'):
            value = line.split(':', 1)[1].strip()
            return None if value in ('', '(none)') else value
    return None


def _post_webhook(url, payload):
    """POST a Mattermost incoming-webhook payload (best-effort, stdlib only)."""
    import urllib.error
    import urllib.request
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return {'posted': True}
    except (urllib.error.URLError, OSError) as exc:
        return {'posted': False, 'error': str(exc)}


def _post_package_updates(specs):
    """Compute held/critical pending updates and post them to the updates channel.

    Best-effort and non-fatal: returns a small status dict, never raises into the run.
    """
    from limeos_packages import pending_updates, render_updates_message
    pending = pending_updates(
        specs,
        lambda spec: _dpkg_installed_version(spec.name),
        lambda spec: _apt_candidate_version(spec.name),
    )
    payload = render_updates_message(pending)
    names = [update.name for update in pending]
    if payload is None:
        return {'pending': names, 'skipped': True, 'reason': 'no held updates'}
    try:
        with open(PACKAGE_UPDATES_CONFIG) as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        return {'pending': names, 'skipped': True, 'reason': 'updates channel not configured'}
    if not config.get('enabled') or not config.get('webhook_url'):
        return {'pending': names, 'skipped': True, 'reason': 'updates channel not configured'}
    return {'pending': names, **_post_webhook(config['webhook_url'], payload)}


def cmd_packages_nightly_reconcile(params):
    """Nightly baseline convergence. Accepts no parameters. In order:

    1. `apt-mark hold` every *critical* manifest package so security/distro upgrades can't
       move it, 2. auto-apply non-critical security updates via unattended-upgrades (security
       pocket only, per its own config), 3. reconcile the declarative manifest. Package names
       come only from the validated manifest, never from the caller.
    """
    if not isinstance(params, dict) or set(params):
        return {'success': False, 'error': 'packages.nightly_reconcile accepts no parameters'}
    try:
        from limeos_packages import load_manifest
        specs = load_manifest()
    except Exception:
        return {'success': False, 'error': 'Unable to read the package manifest'}

    held, hold_failed = [], []
    for spec in specs:
        if getattr(spec, 'manager', None) == 'apt' and getattr(spec, 'critical', False):
            rc = run_command(['apt-mark', 'hold', spec.name], timeout=30).get('returncode')
            (held if rc == 0 else hold_failed).append(spec.name)

    if shutil.which('unattended-upgrade'):
        run_command(['apt-get', 'update'], timeout=300)
        ua_rc = run_command(['unattended-upgrade'], timeout=1800).get('returncode')
        security = {'skipped': False, 'ok': ua_rc == 0}
    else:
        security = {'skipped': True, 'reason': 'unattended-upgrade not installed'}

    reconcile = cmd_packages_reconcile({'mode': 'apply'})

    # Surface held/critical updates that were NOT auto-applied to the updates channel.
    try:
        updates = _post_package_updates(specs)
    except Exception:
        updates = {'skipped': True, 'reason': 'update report failed'}

    security_ok = security.get('skipped', False) or security.get('ok', False)
    return {
        'success': (not hold_failed) and security_ok and reconcile.get('success', False),
        'held': held,
        'hold_failed': hold_failed,
        'security': security,
        'reconcile': reconcile,
        'updates': updates,
    }


def cmd_configure_package_reconcile_schedule(params):
    """Install and enable the nightly package-reconcile timer. Params: {app_dir, user,
    on_calendar?}. The timer runs the reconcile back through the helper socket (audited)."""
    if not isinstance(params, dict):
        return {'success': False, 'error': 'invalid parameters'}
    app_dir = params.get('app_dir', '')
    user = params.get('user', '')
    on_calendar = params.get('on_calendar') or 'daily'
    if not isinstance(app_dir, str) or not app_dir.startswith('/'):
        return {'success': False, 'error': 'app_dir must be an absolute path'}
    if not isinstance(user, str) or not re.match(r'^[a-z_][a-z0-9_-]*$', user):
        return {'success': False, 'error': 'invalid user'}
    if not isinstance(on_calendar, str) or not re.match(r'^[A-Za-z0-9 :*_.,+-]{1,64}$', on_calendar):
        return {'success': False, 'error': 'invalid OnCalendar expression'}

    exec_start = (
        '/usr/bin/python3 -c '
        "'import sys; from helper_client import helper_call; "
        'sys.exit(0 if (helper_call("packages_nightly_reconcile", {}) or {}).get("success") else 1)\''
    )
    service, timer = render_package_reconcile_schedule(
        on_calendar, exec_start, user=user, working_dir=app_dir, pythonpath=app_dir
    )
    service_path = f'/etc/systemd/system/{PACKAGE_RECONCILE_UNIT}.service'
    timer_path = f'/etc/systemd/system/{PACKAGE_RECONCILE_UNIT}.timer'
    for path, content in ((service_path, service), (timer_path, timer)):
        result = _write_managed_file(path, content)
        if not result.get('success'):
            return result
    run_command(['systemctl', 'daemon-reload'])
    enable = run_command(['systemctl', 'enable', '--now', f'{PACKAGE_RECONCILE_UNIT}.timer'])
    if enable.get('returncode') != 0:
        return {'success': False, 'error': enable.get('stderr') or 'failed to enable timer'}
    return {'success': True, 'service_path': service_path, 'timer_path': timer_path}


# Command whitelist
COMMANDS = {
    'lsblk': cmd_lsblk,
    'blkid': cmd_blkid,
    'fstab_read': cmd_fstab_read,
    'fstab_add': cmd_fstab_add,
    'fstab_remove': cmd_fstab_remove,
    'fstab_set_section': cmd_fstab_set_section,
    'mounts_read': cmd_mounts_read,
    'mount': cmd_mount,
    'umount': cmd_umount,
    'smart_info': cmd_smart_info,
    'smart_test': cmd_smart_test,
    'smart_all_devices': cmd_smart_all_devices,
    'alert_health_snapshot': cmd_alert_health_snapshot,
    'df': cmd_df,
    'snapraid': cmd_snapraid,
    'mergerfs_mount': cmd_mergerfs_mount,
    'mergerfs_umount': cmd_mergerfs_umount,
    'write_snapraid_conf': cmd_write_snapraid_conf,
    'media_layout_provision': cmd_media_layout_provision,
    'configure_startup_service': cmd_configure_startup_service,
    'preview_startup_service': cmd_preview_startup_service,
    'configure_snapraid_schedule': cmd_configure_snapraid_schedule,
    'systemctl': cmd_systemctl,
    'tailscale_install': cmd_tailscale_install,
    'tailscale_up': cmd_tailscale_up,
    'tailscale_status': cmd_tailscale_status,
    'tailscale_logout': cmd_tailscale_logout,
    'network_info': cmd_network_info,
    'docker_network_create': cmd_docker_network_create,
    'write_vpn_env': cmd_write_vpn_env,
    'backup_create': cmd_backup_create,
    'backup_restore': cmd_backup_restore,
    'seedbox_configure': cmd_seedbox_configure,
    'seedbox_disable': cmd_seedbox_disable,
    'sshfs_list': cmd_sshfs_list,
    'sshfs_configure': cmd_sshfs_configure,
    'sshfs_remove': cmd_sshfs_remove,
    'sshfs_mount': cmd_sshfs_mount,
    'sshfs_unmount': cmd_sshfs_unmount,
    'rclone_list': cmd_rclone_list,
    'rclone_configure': cmd_rclone_configure,
    'rclone_remove': cmd_rclone_remove,
    'rclone_mount': cmd_rclone_mount,
    'rclone_unmount': cmd_rclone_unmount,
    'copyparty_install': cmd_copyparty_install,
    'copyparty_configure': cmd_copyparty_configure,
    'copyparty_status': cmd_copyparty_status,
    'pihealth_update': cmd_pihealth_update,
    'plugin_install': cmd_plugin_install,
    'plugin_remove': cmd_plugin_remove,
    'agent_runtime_install': cmd_agent_runtime_install,
    'agent_runtime_status': cmd_agent_runtime_status,
    'agent_runtime_disable': cmd_agent_runtime_disable,
    'agent_provider_install': cmd_agent_provider_install,
    'agent_provider_auth_start': cmd_agent_provider_auth_start,
    'agent_provider_auth_status': cmd_agent_provider_auth_status,
    'agent_provider_auth_submit': cmd_agent_provider_auth_submit,
    'agent_provider_auth_cancel': cmd_agent_provider_auth_cancel,
    'agent_bot_secret_write': cmd_agent_bot_secret_write,
    'agent_configure': cmd_agent_configure,
    'agent_runtime_start': cmd_agent_runtime_start,
    'agent_usage_read': cmd_agent_usage_read,
    'agent_audit_read': cmd_agent_audit_read,
    'agent_delivery_test': cmd_agent_delivery_test,
    'packages_reconcile': cmd_packages_reconcile,
    'packages_nightly_reconcile': cmd_packages_nightly_reconcile,
    'configure_package_reconcile_schedule': cmd_configure_package_reconcile_schedule,
    'agent_converge_if_stale': cmd_agent_converge_if_stale,
    'ping': lambda p: {'success': True, 'message': 'pong'}
}


# Quick commands that mutate shared system config/state (fstab, mounts, unit files)
# and must not run concurrently with each other. Long or read-only commands run
# lock-free so a slow backup/sync does not block a quick mount or status check.
_MUTATING_COMMANDS = frozenset({
    'fstab_add', 'fstab_remove', 'fstab_set_section',
    'mount', 'umount',
    'mergerfs_mount', 'mergerfs_umount',
    'write_snapraid_conf', 'media_layout_provision',
    'configure_startup_service', 'configure_snapraid_schedule',
    'systemctl', 'docker_network_create', 'write_vpn_env',
    'seedbox_configure', 'seedbox_disable',
    'sshfs_configure', 'sshfs_remove', 'sshfs_mount', 'sshfs_unmount',
    'rclone_configure', 'rclone_remove', 'rclone_mount', 'rclone_unmount',
    'copyparty_configure',
    'agent_runtime_install', 'agent_runtime_disable', 'agent_provider_install',
    'agent_provider_auth_start', 'agent_provider_auth_submit', 'agent_provider_auth_cancel',
    'agent_bot_secret_write', 'agent_configure', 'agent_runtime_start',
    'packages_reconcile', 'packages_nightly_reconcile',
    'configure_package_reconcile_schedule', 'agent_converge_if_stale',
})

_mutation_lock = threading.Lock()


def handle_request(data):
    """Handle a request from the client."""
    try:
        request = json.loads(data)
    except json.JSONDecodeError:
        return {'success': False, 'error': 'Invalid JSON'}

    if not isinstance(request, dict):
        return {'success': False, 'error': 'Request must be an object'}

    cmd = request.get('command')
    params = request.get('params', {})

    if not cmd:
        return {'success': False, 'error': 'No command specified'}

    if not isinstance(cmd, str) or not isinstance(params, dict):
        return {'success': False, 'error': 'Invalid command or parameters'}

    if cmd not in COMMANDS:
        logger.warning(f"Rejected unknown command: {cmd}")
        return {'success': False, 'error': f'Unknown command: {cmd}'}

    logger.info(f"Executing command: {cmd}")
    try:
        if cmd in _MUTATING_COMMANDS:
            with _mutation_lock:
                return COMMANDS[cmd](params)
        return COMMANDS[cmd](params)
    except Exception as e:
        logger.error(f"Command {cmd} failed: {e}")
        return {'success': False, 'error': str(e)}


class ProtocolError(Exception):
    """Raised for malformed or oversized helper socket frames."""


def _recv_exact(conn, size):
    chunks = []
    remaining = size
    while remaining:
        try:
            chunk = conn.recv(remaining)
        except socket.timeout as exc:
            raise ProtocolError('Request frame timed out') from exc
        if not chunk:
            raise ProtocolError('Incomplete request frame')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _recv_frame(conn):
    header = _recv_exact(conn, FRAME_HEADER_SIZE)
    (message_size,) = struct.unpack('!I', header)
    if not 0 < message_size <= MAX_MESSAGE_SIZE:
        raise ProtocolError('Invalid request size')
    try:
        return _recv_exact(conn, message_size).decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ProtocolError('Request is not valid UTF-8') from exc


def _send_frame(conn, response):
    payload = json.dumps(response, separators=(',', ':')).encode('utf-8')
    if len(payload) > MAX_MESSAGE_SIZE:
        payload = json.dumps({
            'success': False,
            'error': 'Helper response exceeds maximum size',
        }, separators=(',', ':')).encode('utf-8')
    conn.sendall(struct.pack('!I', len(payload)) + payload)


def _get_peer_credentials(conn):
    if not hasattr(socket, 'SO_PEERCRED'):
        raise ProtocolError('Peer credentials are unavailable')
    credential_size = struct.calcsize('3i')
    raw_credentials = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, credential_size)
    if len(raw_credentials) != credential_size:
        raise ProtocolError('Invalid peer credentials')
    return struct.unpack('3i', raw_credentials)


def _get_process_group_ids(pid):
    try:
        with open(f'/proc/{pid}/status', 'r') as handle:
            for line in handle:
                if line.startswith('Groups:'):
                    return {int(value) for value in line.split(':', 1)[1].split()}
    except (OSError, ValueError):
        return set()
    return set()


def _peer_is_authorized(conn, allowed_gid):
    pid, uid, primary_gid = _get_peer_credentials(conn)
    if pid <= 0 or uid < 0 or primary_gid < 0:
        return False, (pid, uid, primary_gid)
    if uid == 0:
        return True, (pid, uid, primary_gid)
    group_ids = _get_process_group_ids(pid)
    authorized = primary_gid == allowed_gid or allowed_gid in group_ids
    return authorized, (pid, uid, primary_gid)


def _secure_socket_directory(path, allowed_gid):
    os.chown(path, 0, allowed_gid)
    os.chmod(path, 0o750)


def _secure_socket_file(path, allowed_gid):
    os.chown(path, 0, allowed_gid)
    os.chmod(path, 0o660)


def _serve_connection(conn, allowed_gid):
    try:
        authorized, credentials = _peer_is_authorized(conn, allowed_gid)
        if not authorized:
            pid, uid, gid = credentials
            logger.warning(f'Rejected unauthorized helper peer pid={pid} uid={uid} gid={gid}')
            _send_frame(conn, {'success': False, 'error': 'Unauthorized helper peer'})
            return
        request_data = _recv_frame(conn)
        _send_frame(conn, handle_request(request_data))
    except ProtocolError as exc:
        logger.warning(f'Rejected malformed helper request: {exc}')
        _send_frame(conn, {'success': False, 'error': str(exc)})
    except Exception as exc:
        logger.error(f'Error handling connection: {exc}')
        try:
            _send_frame(conn, {'success': False, 'error': 'Helper request failed'})
        except (OSError, ProtocolError):
            pass


def _handle_connection(conn, allowed_gid):
    """Serve one connection to completion and close it (runs in its own thread)."""
    try:
        conn.settimeout(10)
        _serve_connection(conn, allowed_gid)
    finally:
        conn.close()


def cleanup(signum=None, frame=None):
    """Clean up socket on exit."""
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    logger.info("Helper service stopped")
    sys.exit(0)


def main():
    """Main entry point."""
    # Set up signal handlers
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    _restore_agent_runtime_ownership()

    # Ensure socket directory exists
    socket_dir = os.path.dirname(SOCKET_PATH)
    os.makedirs(socket_dir, exist_ok=True)

    try:
        import grp
        allowed_gid = grp.getgrnam('pihealth').gr_gid
    except KeyError as exc:
        raise RuntimeError('Required pihealth group does not exist') from exc

    _secure_socket_directory(socket_dir, allowed_gid)

    # Remove old socket if exists
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    # Create Unix socket
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)

    _secure_socket_file(SOCKET_PATH, allowed_gid)

    server.listen(5)
    logger.info(f"Helper service started, listening on {SOCKET_PATH}")

    try:
        while True:
            conn, _ = server.accept()
            # Serve each connection in its own daemon thread so a long-running
            # command (backup, snapraid sync) does not block other helper calls.
            threading.Thread(
                target=_handle_connection,
                args=(conn, allowed_gid),
                daemon=True,
            ).start()
    finally:
        cleanup()


if __name__ == '__main__':
    main()
