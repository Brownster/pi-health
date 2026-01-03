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
from pathlib import Path

# Configuration
SOCKET_PATH = '/run/pihealth/helper.sock'
LOG_FILE = '/var/log/pihealth-helper.log'
MAX_MESSAGE_SIZE = 65536

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


def run_command(cmd, timeout=30):
    """Run a command and return stdout, stderr, returncode."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
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
    fstype = params.get('fstype', 'ext4')
    options = params.get('options', 'defaults,nofail')

    # Validate inputs
    if not uuid or not UUID_PATTERN.match(uuid):
        return {'success': False, 'error': 'Invalid UUID format'}
    if not mountpoint or not MOUNT_POINT_PATTERN.match(mountpoint) or '..' in mountpoint:
        return {'success': False, 'error': 'Invalid mountpoint (must be /mnt/<name>)'}
    if fstype not in ['ext4', 'ext3', 'ext2', 'xfs', 'btrfs', 'ntfs', 'vfat', 'exfat']:
        return {'success': False, 'error': 'Invalid filesystem type'}

    # Sanitize options
    safe_options = re.sub(r'[^a-zA-Z0-9,_=-]', '', options)

    fstab_line = f"UUID={uuid} {mountpoint} {fstype} {safe_options} 0 2\n"

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
            f.write(f"# Added by pi-health\n")
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
    """Get SMART health info for a device."""
    device = params.get('device', '')

    if not device or not DEVICE_PATTERN.match(device):
        return {'success': False, 'error': 'Invalid device path'}

    # Check if smartctl is available
    result = run_command(['which', 'smartctl'])
    if result.get('returncode') != 0:
        return {'success': False, 'error': 'smartctl not installed'}

    result = run_command(['smartctl', '-H', '-j', device])
    if result.get('returncode') in [0, 4]:  # 4 = SMART health check failed but command succeeded
        try:
            return {'success': True, 'data': json.loads(result['stdout'])}
        except json.JSONDecodeError:
            return {'success': False, 'error': 'Failed to parse smartctl output'}
    return {'success': False, 'error': result.get('stderr', 'smartctl failed')}


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


def cmd_snapraid(params):
    """Run snapraid command."""
    allowed_cmds = ['status', 'diff', 'sync', 'scrub', 'check', 'fix']
    cmd = params.get('command', '')

    if cmd not in allowed_cmds:
        return {'success': False, 'error': f'Command not allowed: {cmd}'}

    args = ['snapraid', cmd]
    if cmd == 'scrub' and 'percent' in params:
        args.extend(['-p', str(params['percent'])])

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


def cmd_write_systemd_unit(params):
    """Write a systemd unit file for SnapRAID timers."""
    unit_name = params.get('unit_name', '')
    content = params.get('content', '')

    allowed_units = {
        'pihealth-snapraid-sync.service',
        'pihealth-snapraid-sync.timer',
        'pihealth-snapraid-scrub.service',
        'pihealth-snapraid-scrub.timer'
    }

    if unit_name not in allowed_units:
        return {'success': False, 'error': 'Unit not allowed'}

    path = f"/etc/systemd/system/{unit_name}"

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


def cmd_systemctl(params):
    """Run systemctl commands for SnapRAID timers."""
    action = params.get('action', '')
    unit = params.get('unit', '')

    allowed_actions = {'daemon-reload', 'enable', 'disable', 'start', 'stop'}
    allowed_units = {
        'pihealth-snapraid-sync.timer',
        'pihealth-snapraid-scrub.timer'
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


# Command whitelist
COMMANDS = {
    'lsblk': cmd_lsblk,
    'blkid': cmd_blkid,
    'fstab_read': cmd_fstab_read,
    'fstab_add': cmd_fstab_add,
    'fstab_remove': cmd_fstab_remove,
    'mounts_read': cmd_mounts_read,
    'mount': cmd_mount,
    'umount': cmd_umount,
    'smart_info': cmd_smart_info,
    'df': cmd_df,
    'snapraid': cmd_snapraid,
    'mergerfs_mount': cmd_mergerfs_mount,
    'mergerfs_umount': cmd_mergerfs_umount,
    'write_snapraid_conf': cmd_write_snapraid_conf,
    'write_systemd_unit': cmd_write_systemd_unit,
    'systemctl': cmd_systemctl,
    'ping': lambda p: {'success': True, 'message': 'pong'}
}


def handle_request(data):
    """Handle a request from the client."""
    try:
        request = json.loads(data)
    except json.JSONDecodeError:
        return {'success': False, 'error': 'Invalid JSON'}

    cmd = request.get('command')
    params = request.get('params', {})

    if not cmd:
        return {'success': False, 'error': 'No command specified'}

    if cmd not in COMMANDS:
        logger.warning(f"Rejected unknown command: {cmd}")
        return {'success': False, 'error': f'Unknown command: {cmd}'}

    logger.info(f"Executing command: {cmd}")
    try:
        result = COMMANDS[cmd](params)
        return result
    except Exception as e:
        logger.error(f"Command {cmd} failed: {e}")
        return {'success': False, 'error': str(e)}


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

    # Remove old socket if exists
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    # Create Unix socket
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)

    # Set socket permissions (allow pihealth user/group)
    os.chmod(SOCKET_PATH, 0o660)

    # Try to set group ownership to 'pihealth' if it exists
    try:
        import grp
        gid = grp.getgrnam('pihealth').gr_gid
        os.chown(SOCKET_PATH, 0, gid)
    except (KeyError, PermissionError):
        pass  # Group doesn't exist or can't change ownership

    server.listen(5)
    logger.info(f"Helper service started, listening on {SOCKET_PATH}")

    try:
        while True:
            conn, addr = server.accept()
            try:
                data = conn.recv(MAX_MESSAGE_SIZE).decode('utf-8')
                if data:
                    response = handle_request(data)
                    conn.sendall(json.dumps(response).encode('utf-8'))
            except Exception as e:
                logger.error(f"Error handling connection: {e}")
                try:
                    conn.sendall(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                except:
                    pass
            finally:
                conn.close()
    finally:
        cleanup()


if __name__ == '__main__':
    main()
