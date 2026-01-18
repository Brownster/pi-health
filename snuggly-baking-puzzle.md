# Plugin Architecture for Remote Mounts

## Overview

Extend the existing `storage_plugins` architecture to support remote filesystem mounts (SSHFS, rclone, NFS, SMB). The existing `StoragePlugin` base class handles local storage technologies (SnapRAID, MergerFS). We'll create a new `RemoteMountPlugin` base class for remote filesystems.

**Key Difference:**
- `StoragePlugin`: Single configuration, manages local storage technology
- `RemoteMountPlugin`: Multiple mount configurations, manages remote connections

---

## Architecture

```
storage_plugins/
├── base.py                    # StoragePlugin (existing)
├── remote_base.py             # NEW: RemoteMountPlugin base class
├── registry.py                # Updated: register both plugin types
├── __init__.py                # Updated: API endpoints for remote mounts
├── snapraid_plugin.py         # existing
├── mergerfs_plugin.py         # existing
├── sshfs_plugin.py            # NEW: SSHFS implementation
├── rclone_plugin.py           # FUTURE: Google Drive, S3, etc.
├── nfs_plugin.py              # FUTURE: NFS mounts
└── smb_plugin.py              # FUTURE: Windows shares
```

---

## Task 1: Create RemoteMountPlugin Base Class

**File:** `storage_plugins/remote_base.py`

```python
"""
Base class for remote mount plugins.
Handles remote filesystem mounts (SSHFS, rclone, NFS, SMB).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import json
import os


class MountStatus(Enum):
    """Mount connection status."""
    CONNECTED = "connected"      # Currently mounted and accessible
    DISCONNECTED = "disconnected"  # Not mounted
    ERROR = "error"              # Mount failed
    CONNECTING = "connecting"    # In progress


@dataclass
class MountConfig:
    """Configuration for a single mount."""
    id: str                      # Unique identifier (e.g., "seedbox", "gdrive")
    name: str                    # Display name
    enabled: bool = True         # Auto-mount on boot
    mount_point: str = ""        # Local path (e.g., /mnt/seedbox)
    # Subclasses add protocol-specific fields


@dataclass
class MountResult:
    """Result from mount/unmount operation."""
    success: bool
    message: str
    error: Optional[str] = None


class RemoteMountPlugin(ABC):
    """
    Abstract base class for remote mount plugins.

    Each plugin manages a specific mount protocol (SSHFS, rclone, NFS, SMB).
    Supports multiple mount configurations per plugin.
    """

    PLUGIN_ID: str = ""           # e.g., "sshfs", "rclone", "nfs"
    PLUGIN_NAME: str = ""         # e.g., "SSHFS", "Rclone", "NFS"
    PLUGIN_VERSION: str = "1.0.0"
    PLUGIN_DESCRIPTION: str = ""
    REQUIRED_PACKAGES: list[str] = []  # e.g., ["sshfs", "sshpass"]

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = f"{config_dir}/{self.PLUGIN_ID}_mounts.json"

    # =========================================================================
    # Configuration Management
    # =========================================================================

    def load_mounts(self) -> list[dict]:
        """Load all mount configurations."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    return json.load(f).get('mounts', [])
        except Exception:
            pass
        return []

    def save_mounts(self, mounts: list[dict]) -> None:
        """Save all mount configurations."""
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump({'mounts': mounts}, f, indent=2)

    def get_mount(self, mount_id: str) -> Optional[dict]:
        """Get a specific mount configuration."""
        for mount in self.load_mounts():
            if mount.get('id') == mount_id:
                return mount
        return None

    def add_mount(self, config: dict) -> MountResult:
        """Add a new mount configuration."""
        errors = self.validate_mount_config(config)
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        mounts = self.load_mounts()

        # Check for duplicate ID
        if any(m['id'] == config['id'] for m in mounts):
            return MountResult(False, "", error=f"Mount ID already exists: {config['id']}")

        mounts.append(config)
        self.save_mounts(mounts)
        return MountResult(True, f"Mount '{config['name']}' added")

    def update_mount(self, mount_id: str, config: dict) -> MountResult:
        """Update an existing mount configuration."""
        errors = self.validate_mount_config(config)
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        mounts = self.load_mounts()
        for i, mount in enumerate(mounts):
            if mount.get('id') == mount_id:
                config['id'] = mount_id  # Preserve original ID
                mounts[i] = config
                self.save_mounts(mounts)
                return MountResult(True, f"Mount '{config['name']}' updated")

        return MountResult(False, "", error=f"Mount not found: {mount_id}")

    def remove_mount(self, mount_id: str) -> MountResult:
        """Remove a mount configuration."""
        mounts = self.load_mounts()
        original_count = len(mounts)
        mounts = [m for m in mounts if m.get('id') != mount_id]

        if len(mounts) == original_count:
            return MountResult(False, "", error=f"Mount not found: {mount_id}")

        self.save_mounts(mounts)
        return MountResult(True, f"Mount '{mount_id}' removed")

    # =========================================================================
    # Abstract Methods - Implement in Subclasses
    # =========================================================================

    @abstractmethod
    def get_schema(self) -> dict:
        """
        Return JSON schema for mount configuration.
        Defines fields like host, username, remote_path, options, etc.
        """
        raise NotImplementedError

    @abstractmethod
    def validate_mount_config(self, config: dict) -> list[str]:
        """Validate mount configuration. Returns list of error messages."""
        raise NotImplementedError

    @abstractmethod
    def mount(self, mount_id: str) -> MountResult:
        """Mount a configured remote filesystem."""
        raise NotImplementedError

    @abstractmethod
    def unmount(self, mount_id: str) -> MountResult:
        """Unmount a remote filesystem."""
        raise NotImplementedError

    @abstractmethod
    def get_mount_status(self, mount_id: str) -> dict:
        """
        Get status of a specific mount.
        Returns: {status: MountStatus, message: str, details: dict}
        """
        raise NotImplementedError

    @abstractmethod
    def enable_automount(self, mount_id: str) -> MountResult:
        """Enable auto-mount on boot (systemd units)."""
        raise NotImplementedError

    @abstractmethod
    def disable_automount(self, mount_id: str) -> MountResult:
        """Disable auto-mount on boot."""
        raise NotImplementedError

    # =========================================================================
    # Common Methods
    # =========================================================================

    def is_installed(self) -> bool:
        """Check if required packages are installed."""
        import shutil
        for pkg in self.REQUIRED_PACKAGES:
            if not shutil.which(pkg):
                return False
        return True

    def get_install_instructions(self) -> str:
        """Return instructions for installing dependencies."""
        if not self.REQUIRED_PACKAGES:
            return ""
        pkgs = " ".join(self.REQUIRED_PACKAGES)
        return f"sudo apt install {pkgs}"

    def list_mounts_with_status(self) -> list[dict]:
        """List all mounts with their current status."""
        result = []
        for mount in self.load_mounts():
            mount_id = mount.get('id', '')
            status = self.get_mount_status(mount_id)
            result.append({
                **mount,
                'status': status.get('status', 'unknown'),
                'status_message': status.get('message', ''),
                'mounted': status.get('status') == 'connected'
            })
        return result
```

---

## Task 2: Implement SSHFS Plugin

**File:** `storage_plugins/sshfs_plugin.py`

```python
"""
SSHFS remote mount plugin.
Mounts remote directories over SSH/SFTP.
"""
import os
import re
import subprocess
from typing import Optional

from helper_client import helper_call, HelperError
from storage_plugins.remote_base import RemoteMountPlugin, MountResult, MountStatus


class SSHFSPlugin(RemoteMountPlugin):
    """SSHFS remote mount plugin."""

    PLUGIN_ID = "sshfs"
    PLUGIN_NAME = "SSHFS"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Mount remote directories over SSH/SFTP"
    REQUIRED_PACKAGES = ["sshfs", "sshpass"]

    # Credential storage directory (on the Pi, managed by helper)
    CREDENTIALS_DIR = "/etc/sshfs"

    def get_schema(self) -> dict:
        """JSON schema for SSHFS mount configuration."""
        return {
            "type": "object",
            "required": ["id", "name", "host", "username", "remote_path", "mount_point"],
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Unique identifier (lowercase, no spaces)",
                    "pattern": "^[a-z0-9-]+$"
                },
                "name": {
                    "type": "string",
                    "description": "Display name"
                },
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP"
                },
                "port": {
                    "type": "integer",
                    "default": 22,
                    "description": "SSH port"
                },
                "username": {
                    "type": "string",
                    "description": "SSH username"
                },
                "auth_type": {
                    "type": "string",
                    "enum": ["password", "key"],
                    "default": "password",
                    "description": "Authentication method"
                },
                "password": {
                    "type": "string",
                    "description": "SSH password (stored securely)"
                },
                "ssh_key_path": {
                    "type": "string",
                    "description": "Path to SSH private key"
                },
                "remote_path": {
                    "type": "string",
                    "description": "Remote directory path"
                },
                "mount_point": {
                    "type": "string",
                    "description": "Local mount point (e.g., /mnt/remote)"
                },
                "enabled": {
                    "type": "boolean",
                    "default": True,
                    "description": "Auto-mount on boot"
                },
                "options": {
                    "type": "object",
                    "properties": {
                        "reconnect": {"type": "boolean", "default": True},
                        "compression": {"type": "boolean", "default": False},
                        "allow_other": {"type": "boolean", "default": True},
                        "server_alive_interval": {"type": "integer", "default": 15},
                        "server_alive_count_max": {"type": "integer", "default": 3}
                    }
                }
            }
        }

    def validate_mount_config(self, config: dict) -> list[str]:
        """Validate SSHFS mount configuration."""
        errors = []

        # Required fields
        required = ['id', 'name', 'host', 'username', 'remote_path', 'mount_point']
        for field in required:
            if not config.get(field, '').strip():
                errors.append(f"'{field}' is required")

        # ID format
        mount_id = config.get('id', '')
        if mount_id and not re.match(r'^[a-z0-9-]+$', mount_id):
            errors.append("ID must be lowercase letters, numbers, and hyphens only")

        # Remote path must be absolute
        remote_path = config.get('remote_path', '')
        if remote_path and not remote_path.startswith('/'):
            errors.append("Remote path must be absolute (start with /)")

        # Mount point validation
        mount_point = config.get('mount_point', '')
        if mount_point:
            if not mount_point.startswith('/mnt/'):
                errors.append("Mount point must be under /mnt/")
            if '..' in mount_point:
                errors.append("Mount point cannot contain '..'")

        # Port validation
        port = config.get('port', 22)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append("Port must be between 1 and 65535")

        # Auth validation
        auth_type = config.get('auth_type', 'password')
        if auth_type == 'password' and not config.get('password'):
            errors.append("Password is required for password authentication")
        if auth_type == 'key' and not config.get('ssh_key_path'):
            errors.append("SSH key path is required for key authentication")

        return errors

    def mount(self, mount_id: str) -> MountResult:
        """Mount an SSHFS filesystem."""
        try:
            result = helper_call('sshfs_mount', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, f"Mounted {mount_id}")
            return MountResult(False, "", error=result.get('error', 'Mount failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def unmount(self, mount_id: str) -> MountResult:
        """Unmount an SSHFS filesystem."""
        try:
            result = helper_call('sshfs_unmount', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, f"Unmounted {mount_id}")
            return MountResult(False, "", error=result.get('error', 'Unmount failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def get_mount_status(self, mount_id: str) -> dict:
        """Get status of an SSHFS mount."""
        mount = self.get_mount(mount_id)
        if not mount:
            return {'status': 'error', 'message': 'Mount not configured'}

        mount_point = mount.get('mount_point', '')

        try:
            # Check if mounted
            result = subprocess.run(
                ['mountpoint', '-q', mount_point],
                capture_output=True
            )
            is_mounted = result.returncode == 0

            if is_mounted:
                # Check if accessible
                try:
                    os.listdir(mount_point)
                    return {
                        'status': 'connected',
                        'message': 'Connected and accessible',
                        'mount_point': mount_point
                    }
                except PermissionError:
                    return {
                        'status': 'connected',
                        'message': 'Connected (permission denied for listing)',
                        'mount_point': mount_point
                    }
                except OSError as e:
                    return {
                        'status': 'error',
                        'message': f'Mount stale: {e}',
                        'mount_point': mount_point
                    }
            else:
                return {
                    'status': 'disconnected',
                    'message': 'Not mounted',
                    'mount_point': mount_point
                }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def enable_automount(self, mount_id: str) -> MountResult:
        """Enable systemd automount for this mount."""
        try:
            result = helper_call('sshfs_configure', {
                'id': mount_id,
                'enable': True
            })
            if result.get('success'):
                return MountResult(True, "Automount enabled")
            return MountResult(False, "", error=result.get('error'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def disable_automount(self, mount_id: str) -> MountResult:
        """Disable systemd automount for this mount."""
        try:
            result = helper_call('sshfs_disable', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, "Automount disabled")
            return MountResult(False, "", error=result.get('error'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def add_mount(self, config: dict) -> MountResult:
        """Add mount and configure systemd units via helper."""
        # First validate
        errors = self.validate_mount_config(config)
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        # Save to local config
        mounts = self.load_mounts()
        if any(m['id'] == config['id'] for m in mounts):
            return MountResult(False, "", error=f"Mount ID already exists: {config['id']}")

        # Configure via helper (creates systemd units, stores password)
        try:
            result = helper_call('sshfs_configure', config)
            if not result.get('success'):
                return MountResult(False, "", error=result.get('error', 'Configuration failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

        # Save config (without password - it's stored by helper)
        config_to_save = {k: v for k, v in config.items() if k != 'password'}
        mounts.append(config_to_save)
        self.save_mounts(mounts)

        return MountResult(True, f"Mount '{config['name']}' configured")

    def remove_mount(self, mount_id: str) -> MountResult:
        """Remove mount and cleanup systemd units."""
        # Disable automount first
        try:
            helper_call('sshfs_remove', {'id': mount_id})
        except HelperError:
            pass  # Continue even if helper fails

        # Remove from local config
        return super().remove_mount(mount_id)
```

---

## Task 3: Add Helper Commands

**File:** `pihealth_helper.py` - Add these commands (some already exist from previous work)

```python
# =============================================================================
# SSHFS Multi-Mount Commands (add near line 867)
# =============================================================================

SSHFS_CONFIG_DIR = '/etc/sshfs'
SSHFS_MOUNTS_CONFIG = '/etc/sshfs/mounts.json'


def _get_sshfs_unit_names(mount_id: str) -> dict:
    """Get systemd unit names for a mount ID."""
    safe_id = re.sub(r'[^a-zA-Z0-9]', '-', mount_id)
    # Systemd mount units use path-based names
    # For /mnt/foo -> mnt-foo.mount
    return {
        'mount': f'sshfs-{safe_id}.mount',
        'automount': f'sshfs-{safe_id}.automount'
    }


def cmd_sshfs_list(params):
    """List all configured SSHFS mounts with status."""
    try:
        if os.path.exists(SSHFS_MOUNTS_CONFIG):
            with open(SSHFS_MOUNTS_CONFIG, 'r') as f:
                mounts = json.load(f).get('mounts', [])
        else:
            mounts = []

        result = []
        for mount in mounts:
            mount_point = mount.get('mount_point', '')
            mount_id = mount.get('id', '')
            units = _get_sshfs_unit_names(mount_id)

            # Check mounted status
            mp_result = run_command(['mountpoint', '-q', mount_point])
            is_mounted = mp_result.get('returncode') == 0

            # Check enabled status
            enabled_result = run_command(['systemctl', 'is-enabled', units['automount']])
            is_enabled = enabled_result.get('returncode') == 0

            result.append({
                'id': mount_id,
                'name': mount.get('name', ''),
                'host': mount.get('host', ''),
                'port': mount.get('port', 22),
                'username': mount.get('username', ''),
                'remote_path': mount.get('remote_path', ''),
                'mount_point': mount_point,
                'mounted': is_mounted,
                'enabled': is_enabled
            })

        return {'success': True, 'mounts': result}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def cmd_sshfs_configure(params):
    """Configure an SSHFS mount (add or update)."""
    mount_id = params.get('id', '').strip()
    name = params.get('name', '').strip()
    host = params.get('host', '').strip()
    port = str(params.get('port', '22')).strip()
    username = params.get('username', '').strip()
    password = params.get('password', '')
    remote_path = params.get('remote_path', '').strip()
    mount_point = params.get('mount_point', '').strip()
    auth_type = params.get('auth_type', 'password')
    ssh_key_path = params.get('ssh_key_path', '')
    options = params.get('options', {})

    # Validation
    if not mount_id or not host or not username or not remote_path or not mount_point:
        return {'success': False, 'error': 'id, host, username, remote_path, mount_point required'}

    if not re.match(r'^[a-z0-9-]+$', mount_id):
        return {'success': False, 'error': 'ID must be lowercase alphanumeric with hyphens'}

    if not mount_point.startswith('/mnt/') or '..' in mount_point:
        return {'success': False, 'error': 'Mount point must be under /mnt/'}

    if not remote_path.startswith('/'):
        return {'success': False, 'error': 'Remote path must be absolute'}

    if not port.isdigit() or not (1 <= int(port) <= 65535):
        return {'success': False, 'error': 'Invalid port'}

    if auth_type == 'password' and not password:
        return {'success': False, 'error': 'Password required for password auth'}

    # Create directories
    os.makedirs(SSHFS_CONFIG_DIR, exist_ok=True)
    os.makedirs(mount_point, exist_ok=True)

    units = _get_sshfs_unit_names(mount_id)
    passfile = f"{SSHFS_CONFIG_DIR}/{mount_id}.pass"

    # Store password if using password auth
    if auth_type == 'password' and password:
        with open(passfile, 'w') as f:
            f.write(password)
        os.chmod(passfile, 0o600)

    # Build mount options
    opts = ['_netdev', 'users', 'reconnect', 'ServerAliveInterval=15',
            'ServerAliveCountMax=3', 'StrictHostKeyChecking=accept-new']

    if options.get('allow_other', True):
        opts.append('allow_other')
    if options.get('compression', False):
        opts.append('Compression=yes')

    if auth_type == 'password':
        opts.append(f'ssh_command=sshpass -f {passfile} ssh')
    elif auth_type == 'key' and ssh_key_path:
        opts.append(f'IdentityFile={ssh_key_path}')

    opts.append(f'port={port}')

    # Create systemd mount unit
    mount_unit = f"""[Unit]
Description=SSHFS Mount: {name}
After=network-online.target
Wants=network-online.target

[Mount]
What=sshfs#{username}@{host}:{remote_path}
Where={mount_point}
Type=fuse.sshfs
Options={','.join(opts)}
TimeoutSec=30

[Install]
WantedBy=multi-user.target
"""

    # Create automount unit
    automount_unit = f"""[Unit]
Description=SSHFS Automount: {name}
After=network-online.target
Wants=network-online.target

[Automount]
Where={mount_point}
TimeoutIdleSec=0

[Install]
WantedBy=multi-user.target
"""

    try:
        with open(f"/etc/systemd/system/{units['mount']}", 'w') as f:
            f.write(mount_unit)
        with open(f"/etc/systemd/system/{units['automount']}", 'w') as f:
            f.write(automount_unit)
    except Exception as e:
        return {'success': False, 'error': f'Failed to write unit files: {e}'}

    # Reload and enable
    run_command(['systemctl', 'daemon-reload'])

    if params.get('enabled', True):
        result = run_command(['systemctl', 'enable', '--now', units['automount']])
        if result.get('returncode') != 0:
            return {'success': False, 'error': result.get('stderr', 'Failed to enable')}

    return {'success': True, 'message': f'Mount {mount_id} configured'}


def cmd_sshfs_remove(params):
    """Remove an SSHFS mount configuration."""
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}

    units = _get_sshfs_unit_names(mount_id)
    passfile = f"{SSHFS_CONFIG_DIR}/{mount_id}.pass"

    # Stop and disable units
    run_command(['systemctl', 'disable', '--now', units['automount']])
    run_command(['systemctl', 'stop', units['mount']])

    # Remove unit files
    for unit in [units['mount'], units['automount']]:
        path = f"/etc/systemd/system/{unit}"
        if os.path.exists(path):
            os.remove(path)

    # Remove password file
    if os.path.exists(passfile):
        os.remove(passfile)

    run_command(['systemctl', 'daemon-reload'])

    return {'success': True}


def cmd_sshfs_mount(params):
    """Manually mount an SSHFS filesystem."""
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}

    units = _get_sshfs_unit_names(mount_id)
    result = run_command(['systemctl', 'start', units['mount']])

    if result.get('returncode') == 0:
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', 'Mount failed')}


def cmd_sshfs_unmount(params):
    """Manually unmount an SSHFS filesystem."""
    mount_id = params.get('id', '').strip()
    if not mount_id:
        return {'success': False, 'error': 'id required'}

    units = _get_sshfs_unit_names(mount_id)
    result = run_command(['systemctl', 'stop', units['mount']])

    if result.get('returncode') == 0:
        return {'success': True}
    return {'success': False, 'error': result.get('stderr', 'Unmount failed')}


# Add to COMMANDS dict:
# 'sshfs_list': cmd_sshfs_list,
# 'sshfs_configure': cmd_sshfs_configure,
# 'sshfs_remove': cmd_sshfs_remove,
# 'sshfs_mount': cmd_sshfs_mount,
# 'sshfs_unmount': cmd_sshfs_unmount,
```

---

## Task 4: Update Plugin Registry

**File:** `storage_plugins/registry.py` - Update to handle both plugin types

```python
# Add import at top
from storage_plugins.remote_base import RemoteMountPlugin

# Update init_plugins function:
def init_plugins(config_dir: str) -> PluginRegistry:
    registry = get_registry(config_dir)

    # Storage plugins
    try:
        from storage_plugins.snapraid_plugin import SnapRAIDPlugin
        registry.register(SnapRAIDPlugin)
    except Exception:
        pass

    try:
        from storage_plugins.mergerfs_plugin import MergerFSPlugin
        registry.register(MergerFSPlugin)
    except Exception:
        pass

    # Remote mount plugins
    try:
        from storage_plugins.sshfs_plugin import SSHFSPlugin
        registry.register(SSHFSPlugin)
    except Exception:
        pass

    return registry
```

---

## Task 5: Add API Endpoints for Remote Mounts

**File:** `storage_plugins/__init__.py` - Add new endpoints

```python
# Add these endpoints after existing ones:

@storage_bp.route("/api/storage/mounts/<plugin_id>", methods=["GET"])
@login_required
def list_mounts(plugin_id: str):
    """List all mounts for a remote mount plugin."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    if not hasattr(plugin, 'list_mounts_with_status'):
        return jsonify({"error": "Not a remote mount plugin"}), 400

    return jsonify({"mounts": plugin.list_mounts_with_status()})


@storage_bp.route("/api/storage/mounts/<plugin_id>", methods=["POST"])
@login_required
def add_mount(plugin_id: str):
    """Add a new mount configuration."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'add_mount'):
        return jsonify({"error": "Plugin not found or not a mount plugin"}), 404

    config = request.get_json() or {}
    result = plugin.add_mount(config)

    if result.success:
        return jsonify({"status": "created", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/mounts/<plugin_id>/<mount_id>", methods=["PUT"])
@login_required
def update_mount(plugin_id: str, mount_id: str):
    """Update a mount configuration."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'update_mount'):
        return jsonify({"error": "Plugin not found"}), 404

    config = request.get_json() or {}
    result = plugin.update_mount(mount_id, config)

    if result.success:
        return jsonify({"status": "updated", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/mounts/<plugin_id>/<mount_id>", methods=["DELETE"])
@login_required
def delete_mount(plugin_id: str, mount_id: str):
    """Delete a mount configuration."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'remove_mount'):
        return jsonify({"error": "Plugin not found"}), 404

    result = plugin.remove_mount(mount_id)

    if result.success:
        return jsonify({"status": "deleted", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/mounts/<plugin_id>/<mount_id>/mount", methods=["POST"])
@login_required
def mount_filesystem(plugin_id: str, mount_id: str):
    """Mount a remote filesystem."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'mount'):
        return jsonify({"error": "Plugin not found"}), 404

    result = plugin.mount(mount_id)

    if result.success:
        return jsonify({"status": "mounted", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/mounts/<plugin_id>/<mount_id>/unmount", methods=["POST"])
@login_required
def unmount_filesystem(plugin_id: str, mount_id: str):
    """Unmount a remote filesystem."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'unmount'):
        return jsonify({"error": "Plugin not found"}), 404

    result = plugin.unmount(mount_id)

    if result.success:
        return jsonify({"status": "unmounted", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/mounts/<plugin_id>/<mount_id>/status", methods=["GET"])
@login_required
def get_mount_status(plugin_id: str, mount_id: str):
    """Get mount status."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin or not hasattr(plugin, 'get_mount_status'):
        return jsonify({"error": "Plugin not found"}), 404

    return jsonify(plugin.get_mount_status(mount_id))
```

---

## Task 6: Frontend - Update storage.html

Add a new tab or section for Remote Mounts. Key components:

```html
<!-- Remote Mounts Section -->
<div id="remote-mounts-section" class="mt-8">
    <div class="flex items-center justify-between mb-4">
        <h3 class="text-xl font-semibold">Remote Mounts</h3>
        <button onclick="openAddMountModal()" class="coraline-button text-sm py-2 px-4 rounded">
            + Add Mount
        </button>
    </div>

    <!-- SSHFS Mounts -->
    <div id="sshfs-mounts" class="space-y-3">
        <!-- Dynamically populated -->
    </div>
</div>

<!-- Add Mount Modal -->
<div id="add-mount-modal" class="hidden fixed inset-0 bg-black bg-opacity-60 z-50 flex items-center justify-center p-4">
    <div class="bg-gray-800 w-full max-w-lg rounded-lg shadow-xl border border-purple-900">
        <div class="p-4 border-b border-purple-800 flex justify-between items-center">
            <h3 class="text-xl font-semibold">Add SSHFS Mount</h3>
            <button onclick="closeAddMountModal()" class="text-gray-400 hover:text-white">&times;</button>
        </div>
        <form id="add-mount-form" class="p-4 space-y-4">
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Name</label>
                    <input type="text" name="name" required
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">ID (lowercase)</label>
                    <input type="text" name="id" required pattern="[a-z0-9-]+"
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Host</label>
                    <input type="text" name="host" required placeholder="192.168.1.100"
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Port</label>
                    <input type="number" name="port" value="22" min="1" max="65535"
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
            </div>
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Username</label>
                    <input type="text" name="username" required
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Password</label>
                    <input type="password" name="password" required
                           class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
                </div>
            </div>
            <div>
                <label class="block text-sm text-gray-400 mb-1">Remote Path</label>
                <input type="text" name="remote_path" required placeholder="/home/user/files"
                       class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
            </div>
            <div>
                <label class="block text-sm text-gray-400 mb-1">Local Mount Point</label>
                <input type="text" name="mount_point" required placeholder="/mnt/remote"
                       class="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white">
            </div>
            <div class="flex items-center gap-2">
                <input type="checkbox" name="enabled" id="enabled" checked>
                <label for="enabled" class="text-sm text-gray-400">Auto-mount on boot</label>
            </div>
        </form>
        <div class="p-4 border-t border-purple-800 flex justify-end gap-3">
            <button onclick="closeAddMountModal()" class="px-4 py-2 text-gray-400 hover:text-white">Cancel</button>
            <button onclick="submitAddMount()" class="coraline-button px-4 py-2 rounded">Add Mount</button>
        </div>
    </div>
</div>
```

**JavaScript functions:**

```javascript
async function loadRemoteMounts() {
    try {
        const res = await apiFetch('/api/storage/mounts/sshfs');
        const data = await res.json();
        renderSSHFSMounts(data.mounts || []);
    } catch (e) {
        console.error('Failed to load mounts:', e);
    }
}

function renderSSHFSMounts(mounts) {
    const container = document.getElementById('sshfs-mounts');
    if (!mounts.length) {
        container.innerHTML = '<p class="text-gray-500">No SSHFS mounts configured</p>';
        return;
    }

    container.innerHTML = mounts.map(m => `
        <div class="bg-gray-800 border border-purple-900/40 rounded-lg p-4">
            <div class="flex items-center justify-between">
                <div>
                    <h4 class="font-semibold">${m.name}</h4>
                    <p class="text-sm text-gray-400">${m.username}@${m.host}:${m.remote_path}</p>
                    <p class="text-xs text-gray-500">→ ${m.mount_point}</p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="status-pill ${m.mounted ? 'status-healthy' : 'status-unconfigured'}">
                        ${m.mounted ? 'Connected' : 'Disconnected'}
                    </span>
                    ${m.mounted
                        ? `<button onclick="unmountSSHFS('${m.id}')" class="text-sm text-red-400 hover:text-red-300">Unmount</button>`
                        : `<button onclick="mountSSHFS('${m.id}')" class="text-sm text-green-400 hover:text-green-300">Mount</button>`
                    }
                    <button onclick="removeSSHFS('${m.id}')" class="text-sm text-gray-400 hover:text-red-400">Remove</button>
                </div>
            </div>
        </div>
    `).join('');
}

async function mountSSHFS(id) {
    showSpinner('sshfs-mounts');
    try {
        await apiFetch(`/api/storage/mounts/sshfs/${id}/mount`, { method: 'POST' });
        showToast('Mount connected', 'success');
        loadRemoteMounts();
    } catch (e) {
        showToast('Mount failed: ' + e.message, 'error');
    }
    hideSpinner('sshfs-mounts');
}

async function unmountSSHFS(id) {
    showSpinner('sshfs-mounts');
    try {
        await apiFetch(`/api/storage/mounts/sshfs/${id}/unmount`, { method: 'POST' });
        showToast('Mount disconnected', 'success');
        loadRemoteMounts();
    } catch (e) {
        showToast('Unmount failed: ' + e.message, 'error');
    }
    hideSpinner('sshfs-mounts');
}

async function removeSSHFS(id) {
    if (!confirm('Remove this mount configuration?')) return;
    try {
        await apiFetch(`/api/storage/mounts/sshfs/${id}`, { method: 'DELETE' });
        showToast('Mount removed', 'success');
        loadRemoteMounts();
    } catch (e) {
        showToast('Remove failed: ' + e.message, 'error');
    }
}

function openAddMountModal() {
    document.getElementById('add-mount-modal').classList.remove('hidden');
}

function closeAddMountModal() {
    document.getElementById('add-mount-modal').classList.add('hidden');
    document.getElementById('add-mount-form').reset();
}

async function submitAddMount() {
    const form = document.getElementById('add-mount-form');
    const data = Object.fromEntries(new FormData(form));
    data.port = parseInt(data.port) || 22;
    data.enabled = form.querySelector('[name=enabled]').checked;

    try {
        await apiFetch('/api/storage/mounts/sshfs', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        showToast('Mount added', 'success');
        closeAddMountModal();
        loadRemoteMounts();
    } catch (e) {
        showToast('Failed: ' + e.message, 'error');
    }
}

// Call on page load
document.addEventListener('DOMContentLoaded', loadRemoteMounts);
```

---

## Task 7: Cleanup Seedbox Legacy Code

After SSHFS plugin is working, migrate seedbox to use it:

1. Create a migration that converts the old `seedbox_mount.json` to the new SSHFS plugin format
2. Keep `cmd_seedbox_configure` and `cmd_seedbox_disable` as aliases for backward compatibility
3. Eventually remove the legacy seedbox code

---

## Task 8: Write Tests

**File:** `tests/test_sshfs_plugin.py`

```python
import pytest
from unittest.mock import patch, MagicMock
from storage_plugins.sshfs_plugin import SSHFSPlugin
from storage_plugins.remote_base import MountResult


@pytest.fixture
def plugin(tmp_path):
    return SSHFSPlugin(str(tmp_path))


class TestSSHFSValidation:
    def test_valid_config(self, plugin):
        config = {
            'id': 'test-mount',
            'name': 'Test Mount',
            'host': '192.168.1.100',
            'port': 22,
            'username': 'user',
            'password': 'pass',
            'remote_path': '/home/user',
            'mount_point': '/mnt/test',
            'auth_type': 'password'
        }
        errors = plugin.validate_mount_config(config)
        assert errors == []

    def test_missing_required_fields(self, plugin):
        errors = plugin.validate_mount_config({})
        assert len(errors) >= 5  # Missing id, name, host, username, remote_path, mount_point

    def test_invalid_id_format(self, plugin):
        config = {'id': 'Test Mount!', 'name': 'x', 'host': 'x',
                  'username': 'x', 'remote_path': '/x', 'mount_point': '/mnt/x'}
        errors = plugin.validate_mount_config(config)
        assert any('ID' in e for e in errors)

    def test_invalid_mount_point(self, plugin):
        config = {'id': 'test', 'name': 'x', 'host': 'x',
                  'username': 'x', 'remote_path': '/x', 'mount_point': '/home/test'}
        errors = plugin.validate_mount_config(config)
        assert any('/mnt/' in e for e in errors)


class TestSSHFSMountOperations:
    @patch('storage_plugins.sshfs_plugin.helper_call')
    def test_mount_success(self, mock_helper, plugin):
        mock_helper.return_value = {'success': True}
        result = plugin.mount('test-id')
        assert result.success
        mock_helper.assert_called_with('sshfs_mount', {'id': 'test-id'})

    @patch('storage_plugins.sshfs_plugin.helper_call')
    def test_mount_failure(self, mock_helper, plugin):
        mock_helper.return_value = {'success': False, 'error': 'Connection refused'}
        result = plugin.mount('test-id')
        assert not result.success
        assert 'Connection refused' in result.error
```

---

## Future Plugins Reference

### Rclone Plugin (cloud storage)
```python
class RclonePlugin(RemoteMountPlugin):
    PLUGIN_ID = "rclone"
    PLUGIN_NAME = "Rclone"
    REQUIRED_PACKAGES = ["rclone", "fuse3"]
    # Supports: Google Drive, S3, Dropbox, OneDrive, etc.
```

### NFS Plugin
```python
class NFSPlugin(RemoteMountPlugin):
    PLUGIN_ID = "nfs"
    PLUGIN_NAME = "NFS"
    REQUIRED_PACKAGES = ["nfs-common"]
```

### SMB/CIFS Plugin
```python
class SMBPlugin(RemoteMountPlugin):
    PLUGIN_ID = "smb"
    PLUGIN_NAME = "SMB/CIFS"
    REQUIRED_PACKAGES = ["cifs-utils"]
```

---

## Implementation Order

1. **Task 1**: Create `remote_base.py` with `RemoteMountPlugin` base class
2. **Task 3**: Add SSHFS helper commands to `pihealth_helper.py` and register in COMMANDS
3. **Task 2**: Create `sshfs_plugin.py`
4. **Task 4**: Update `registry.py` to register SSHFS plugin
5. **Task 5**: Add API endpoints to `__init__.py`
6. **Task 6**: Update frontend (storage.html)
7. **Task 8**: Write tests
8. **Task 7**: Migrate seedbox (can be done later)

---

## Verification

1. Run tests: `pytest tests/test_sshfs_plugin.py -v`
2. Start app: `python app.py`
3. Navigate to Storage page
4. Click "Add Mount" and configure an SSHFS mount
5. Verify mount/unmount buttons work
6. Verify automount works after reboot (on Pi)
7. Run full test suite: `tox`
