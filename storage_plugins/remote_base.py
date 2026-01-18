"""
Base class for remote mount plugins.
Handles remote filesystem mounts (SSHFS, rclone, NFS, SMB).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import json
import os


class MountStatus(Enum):
    """Mount connection status."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    CONNECTING = "connecting"


@dataclass
class MountConfig:
    """Configuration for a single mount."""
    id: str
    name: str
    enabled: bool = True
    mount_point: str = ""


@dataclass
class MountResult:
    """Result from mount/unmount operation."""
    success: bool
    message: str
    error: Optional[str] = None
    data: Optional[dict] = None


class RemoteMountPlugin(ABC):
    """
    Abstract base class for remote mount plugins.
    Supports multiple mount configurations per plugin.
    """

    PLUGIN_ID: str = ""
    PLUGIN_NAME: str = ""
    PLUGIN_VERSION: str = "1.0.0"
    PLUGIN_DESCRIPTION: str = ""
    PLUGIN_CATEGORY: str = "mount"  # UI appears on Mounts page
    PLUGIN_ENABLED_DEFAULT: bool = True  # Whether plugin is enabled by default
    REQUIRED_PACKAGES: list[str] = []

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = f"{config_dir}/{self.PLUGIN_ID}_mounts.json"

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
                config['id'] = mount_id
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

    @abstractmethod
    def get_schema(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_mount_config(self, config: dict) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def mount(self, mount_id: str) -> MountResult:
        raise NotImplementedError

    @abstractmethod
    def unmount(self, mount_id: str) -> MountResult:
        raise NotImplementedError

    @abstractmethod
    def get_mount_status(self, mount_id: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def enable_automount(self, mount_id: str) -> MountResult:
        raise NotImplementedError

    @abstractmethod
    def disable_automount(self, mount_id: str) -> MountResult:
        raise NotImplementedError

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
