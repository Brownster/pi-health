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
import struct
import threading
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.error
import shlex
from helper_templates import cron_to_oncalendar, render_snapraid_schedule, render_startup_files
from fstab_presets import get_fstab_preset, normalize_fstype

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

# SSHFS multi-mount configuration
SSHFS_CONFIG_DIR = '/etc/sshfs'
SSHFS_MOUNTS_CONFIG = '/etc/sshfs/mounts.json'
PLUGIN_DIR = os.getenv("PIHEALTH_PLUGIN_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugins"))
PIHEALTH_REPO_DIR = os.getenv("PIHEALTH_REPO_DIR")
PIHEALTH_SERVICE_NAME = os.getenv("PIHEALTH_SERVICE_NAME", "pi-health")

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

    if result.get("returncode") != 0:
        return {
            'success': False,
            'error': result.get("stderr") or result.get("error") or 'migration failed',
            'stdout': result.get("stdout", ""),
        }
    return {'success': True, 'stdout': result.get("stdout", "")}


def _pihealth_update_build(ctx):
    """Rebuild and publish the web UI bundle when a toolchain is available."""
    user = ctx["user"]
    repo_path = ctx["repo_path"]
    frontend = os.path.join(repo_path, "frontend")

    if not os.path.isdir(frontend):
        return {'success': True, 'skipped': True, 'reason': 'no frontend directory'}
    if not shutil.which("npm"):
        return {'success': True, 'skipped': True, 'reason': 'npm not installed; committed bundle used'}

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
    """Schedule a short-delayed restart so the caller can flush its response first."""
    service_name = ctx["service_name"]

    if shutil.which("systemd-run"):
        result = run_command([
            "systemd-run",
            "--on-active=2",
            "--timer-property=RemainAfterElapse=no",
            "systemctl", "restart", service_name,
        ])
        if result.get("returncode") == 0:
            return {'success': True, 'scheduled': True}

    try:
        subprocess.Popen(
            ["sh", "-c", f"sleep 2; systemctl restart {shlex.quote(service_name)}"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {'success': True, 'scheduled': True}
    except Exception as exc:
        return {'success': False, 'error': str(exc)}


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
    'df': cmd_df,
    'snapraid': cmd_snapraid,
    'mergerfs_mount': cmd_mergerfs_mount,
    'mergerfs_umount': cmd_mergerfs_umount,
    'write_snapraid_conf': cmd_write_snapraid_conf,
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
    'ping': lambda p: {'success': True, 'message': 'pong'}
}


# Quick commands that mutate shared system config/state (fstab, mounts, unit files)
# and must not run concurrently with each other. Long or read-only commands run
# lock-free so a slow backup/sync does not block a quick mount or status check.
_MUTATING_COMMANDS = frozenset({
    'fstab_add', 'fstab_remove', 'fstab_set_section',
    'mount', 'umount',
    'mergerfs_mount', 'mergerfs_umount',
    'write_snapraid_conf', 'configure_startup_service', 'configure_snapraid_schedule',
    'systemctl', 'docker_network_create', 'write_vpn_env',
    'seedbox_configure', 'seedbox_disable',
    'sshfs_configure', 'sshfs_remove', 'sshfs_mount', 'sshfs_unmount',
    'rclone_configure', 'rclone_remove', 'rclone_mount', 'rclone_unmount',
    'copyparty_configure',
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
