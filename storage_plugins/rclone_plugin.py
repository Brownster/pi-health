"""
Rclone remote mount plugin.
Mounts cloud storage backends (S3-compatible) via rclone.
"""
import os
import re
import subprocess

from helper_client import helper_call, HelperError
from storage_plugins.remote_base import RemoteMountPlugin, MountResult


class RclonePlugin(RemoteMountPlugin):
    """Rclone remote mount plugin."""

    PLUGIN_ID = "rclone"
    PLUGIN_NAME = "Rclone"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Mount S3-compatible storage via rclone"
    PLUGIN_CATEGORY = "mount"  # UI appears on Mounts page
    PLUGIN_ENABLED_DEFAULT = False  # Not enabled by default
    REQUIRED_PACKAGES = ["rclone", "fusermount"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["id", "name", "backend", "bucket", "mount_point"],
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Unique identifier (lowercase, no spaces)",
                    "pattern": "^[a-z0-9-]+$"
                },
                "name": {"type": "string", "description": "Display name"},
                "backend": {
                    "type": "string",
                    "enum": ["s3", "s3-compatible"],
                    "default": "s3",
                    "description": "Rclone backend"
                },
                "provider": {"type": "string", "default": "AWS", "description": "S3 provider"},
                "access_key_id": {"type": "string", "description": "Access key"},
                "secret_access_key": {"type": "string", "description": "Secret key"},
                "region": {"type": "string", "default": "us-east-1"},
                "endpoint": {"type": "string", "description": "Custom endpoint for S3-compatible"},
                "bucket": {"type": "string", "description": "Bucket name"},
                "mount_point": {"type": "string", "description": "Local mount point"},
                "enabled": {"type": "boolean", "default": False},
                "options": {
                    "type": "object",
                    "properties": {
                        "vfs_cache_mode": {"type": "string", "default": "writes"},
                        "read_only": {"type": "boolean", "default": False},
                        "allow_other": {"type": "boolean", "default": True}
                    }
                }
            }
        }

    def validate_mount_config(self, config: dict) -> list[str]:
        errors = []

        required = ['id', 'name', 'backend', 'bucket', 'mount_point']
        for field in required:
            if not str(config.get(field, '')).strip():
                errors.append(f"'{field}' is required")

        mount_id = config.get('id', '')
        if mount_id and not re.match(r'^[a-z0-9-]+$', mount_id):
            errors.append("ID must be lowercase letters, numbers, and hyphens only")

        mount_point = config.get('mount_point', '')
        if mount_point:
            if not mount_point.startswith('/mnt/'):
                errors.append("Mount point must be under /mnt/")
            if '..' in mount_point:
                errors.append("Mount point cannot contain '..'")

        backend = config.get('backend', 's3')
        if backend not in ('s3', 's3-compatible'):
            errors.append("Unsupported backend")

        if not config.get('access_key_id') and not config.get('secret_access_key'):
            errors.append("Access key and secret key are required")
        elif not config.get('access_key_id'):
            errors.append("Access key is required")
        elif not config.get('secret_access_key'):
            errors.append("Secret key is required")

        if backend == 's3-compatible' and not config.get('endpoint'):
            errors.append("Endpoint is required for S3-compatible backend")

        return errors

    def mount(self, mount_id: str) -> MountResult:
        try:
            result = helper_call('rclone_mount', {'id': mount_id})
            if result.get('success'):
                return MountResult(True, f"Mounted {mount_id}")
            return MountResult(False, "", error=result.get('error', 'Mount failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

    def unmount(self, mount_id: str) -> MountResult:
        try:
            result = helper_call('rclone_unmount', {'id': mount_id})
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
            return {
                'status': 'connected' if is_mounted else 'disconnected',
                'message': 'Connected' if is_mounted else 'Not mounted',
                'mount_point': mount_point
            }
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def enable_automount(self, mount_id: str) -> MountResult:
        try:
            result = helper_call('rclone_configure', {
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
            result = helper_call('rclone_configure', {
                'id': mount_id,
                'enable': False
            })
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
            result = helper_call('rclone_configure', config)
            if not result.get('success'):
                return MountResult(False, "", error=result.get('error', 'Configuration failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

        config_to_save = {k: v for k, v in config.items() if k != 'secret_access_key'}
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
            "secret_access_key": merged.get("secret_access_key", "placeholder"),
            "access_key_id": merged.get("access_key_id", "placeholder")
        })
        if errors and not config.get("secret_access_key"):
            errors = [e for e in errors if "Secret key is required" not in e]
        if errors and not config.get("access_key_id"):
            errors = [e for e in errors if "Access key is required" not in e]
        if errors:
            return MountResult(False, "", error="; ".join(errors))

        try:
            result = helper_call('rclone_configure', merged)
            if not result.get('success'):
                return MountResult(False, "", error=result.get('error', 'Configuration failed'))
        except HelperError as e:
            return MountResult(False, "", error=str(e))

        config_to_save = {k: v for k, v in merged.items() if k != 'secret_access_key'}
        mounts = [m for m in self.load_mounts() if m.get('id') != mount_id]
        mounts.append(config_to_save)
        self.save_mounts(mounts)
        return MountResult(True, f"Mount '{merged.get('name', mount_id)}' updated")
