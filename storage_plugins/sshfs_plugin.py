"""
SSHFS remote mount plugin.
Mounts remote directories over SSH/SFTP.
"""
import os
import re
import subprocess

from helper_client import helper_call, HelperError
from storage_plugins.remote_base import RemoteMountPlugin, MountResult


class SSHFSPlugin(RemoteMountPlugin):
    """SSHFS remote mount plugin."""

    PLUGIN_ID = "sshfs"
    PLUGIN_NAME = "SSHFS"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Mount remote directories over SSH/SFTP"
    PLUGIN_CATEGORY = "mount"  # UI appears on Mounts page
    REQUIRED_PACKAGES = ["sshfs", "sshpass"]

    CREDENTIALS_DIR = "/etc/sshfs"

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["id", "name", "host", "username", "remote_path", "mount_point"],
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Unique identifier (lowercase, no spaces)",
                    "pattern": "^[a-z0-9-]+$"
                },
                "name": {"type": "string", "description": "Display name"},
                "host": {"type": "string", "description": "Remote hostname or IP"},
                "port": {"type": "integer", "default": 22, "description": "SSH port"},
                "username": {"type": "string", "description": "SSH username"},
                "auth_type": {
                    "type": "string",
                    "enum": ["password", "key"],
                    "default": "password",
                    "description": "Authentication method"
                },
                "password": {"type": "string", "description": "SSH password (stored securely)"},
                "ssh_key_path": {"type": "string", "description": "Path to SSH private key"},
                "remote_path": {"type": "string", "description": "Remote directory path"},
                "mount_point": {"type": "string", "description": "Local mount point"},
                "enabled": {"type": "boolean", "default": True, "description": "Auto-mount on boot"},
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
        errors = []

        required = ['id', 'name', 'host', 'username', 'remote_path', 'mount_point']
        for field in required:
            if not str(config.get(field, '')).strip():
                errors.append(f"'{field}' is required")

        mount_id = config.get('id', '')
        if mount_id and not re.match(r'^[a-z0-9-]+$', mount_id):
            errors.append("ID must be lowercase letters, numbers, and hyphens only")

        remote_path = config.get('remote_path', '')
        if remote_path and not remote_path.startswith('/'):
            errors.append("Remote path must be absolute (start with /)")

        mount_point = config.get('mount_point', '')
        if mount_point:
            if not mount_point.startswith('/mnt/'):
                errors.append("Mount point must be under /mnt/")
            if '..' in mount_point:
                errors.append("Mount point cannot contain '..'")

        port = config.get('port', 22)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append("Port must be between 1 and 65535")

        auth_type = config.get('auth_type', 'password')
        if auth_type == 'password' and not config.get('password'):
            errors.append("Password is required for password authentication")
        if auth_type == 'key' and not config.get('ssh_key_path'):
            errors.append("SSH key path is required for key authentication")

        return errors

    def mount(self, mount_id: str) -> MountResult:
        try:
            result = helper_call('sshfs_mount', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, f"Mounted {mount_id}")
            return MountResult(False, "", error=result.get('error', 'Mount failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def unmount(self, mount_id: str) -> MountResult:
        try:
            result = helper_call('sshfs_unmount', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, f"Unmounted {mount_id}")
            return MountResult(False, "", error=result.get('error', 'Unmount failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def get_mount_status(self, mount_id: str) -> dict:
        mount = self.get_mount(mount_id)
        if not mount:
            return {'status': 'error', 'message': 'Mount not configured'}

        mount_point = mount.get('mount_point', '')

        try:
            result = subprocess.run(
                ['mountpoint', '-q', mount_point],
                capture_output=True
            )
            is_mounted = result.returncode == 0

            if is_mounted:
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
            return {
                'status': 'disconnected',
                'message': 'Not mounted',
                'mount_point': mount_point
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def enable_automount(self, mount_id: str) -> MountResult:
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
        try:
            result = helper_call('sshfs_remove', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, "Automount disabled")
            return MountResult(False, "", error=result.get('error'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def add_mount(self, config: dict) -> MountResult:
        errors = self.validate_mount_config(config)
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        mounts = self.load_mounts()
        if any(m['id'] == config['id'] for m in mounts):
            return MountResult(False, "", error=f"Mount ID already exists: {config['id']}")

        try:
            result = helper_call('sshfs_configure', config)
            if not result.get('success'):
                return MountResult(False, "", error=result.get('error', 'Configuration failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

        config_to_save = {k: v for k, v in config.items() if k != 'password'}
        mounts.append(config_to_save)
        self.save_mounts(mounts)

        return MountResult(True, f"Mount '{config['name']}' configured")

    def update_mount(self, mount_id: str, config: dict) -> MountResult:
        mount = self.get_mount(mount_id)
        if not mount:
            return MountResult(False, "", error=f"Mount not found: {mount_id}")

        merged = {**mount, **config, "id": mount_id}
        errors = self.validate_mount_config({
            **merged,
            "password": merged.get("password", "placeholder")
        })
        if errors and not config.get("password"):
            errors = [e for e in errors if "Password is required" not in e]
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        try:
            result = helper_call('sshfs_configure', merged)
            if not result.get('success'):
                return MountResult(False, "", error=result.get('error', 'Configuration failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

        config_to_save = {k: v for k, v in merged.items() if k != 'password'}
        mounts = [m for m in self.load_mounts() if m.get('id') != mount_id]
        mounts.append(config_to_save)
        self.save_mounts(mounts)
        return MountResult(True, f"Mount '{merged.get('name', mount_id)}' updated")

    def remove_mount(self, mount_id: str) -> MountResult:
        try:
            helper_call('sshfs_remove', {'id': mount_id})
        except HelperError:
            pass
        return super().remove_mount(mount_id)
