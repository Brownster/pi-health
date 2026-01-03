"""
Base class for storage plugins.
All storage plugins must inherit from this class.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Generator, Optional


class PluginStatus(Enum):
    """Plugin health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ERROR = "error"
    UNCONFIGURED = "unconfigured"


@dataclass
class CommandResult:
    """Result from running a plugin command."""
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None


class StoragePlugin(ABC):
    """
    Abstract base class for storage plugins.

    Each plugin manages a specific storage technology
    (SnapRAID, MergerFS, etc.)
    """

    PLUGIN_ID: str = ""
    PLUGIN_NAME: str = ""
    PLUGIN_VERSION: str = "1.0.0"
    PLUGIN_DESCRIPTION: str = ""

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = f"{config_dir}/{self.PLUGIN_ID}.json"

    @abstractmethod
    def get_schema(self) -> dict:
        """Return JSON schema for plugin configuration."""
        raise NotImplementedError

    @abstractmethod
    def get_config(self) -> dict:
        """Load and return current configuration."""
        raise NotImplementedError

    @abstractmethod
    def set_config(self, config: dict) -> CommandResult:
        """Validate and save configuration."""
        raise NotImplementedError

    @abstractmethod
    def validate_config(self, config: dict) -> list[str]:
        """Validate configuration without saving."""
        raise NotImplementedError

    @abstractmethod
    def apply_config(self) -> CommandResult:
        """Apply saved configuration to system."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> dict:
        """Get current plugin status."""
        raise NotImplementedError

    @abstractmethod
    def get_commands(self) -> list[dict]:
        """List available commands for this plugin."""
        raise NotImplementedError

    @abstractmethod
    def run_command(self, command_id: str, params: dict = None) -> Generator[str, None, CommandResult]:
        """Execute a plugin command with streaming output."""
        raise NotImplementedError

    def is_installed(self) -> bool:
        """Check if required binaries are installed."""
        return True

    def get_install_instructions(self) -> str:
        """Return instructions for installing dependencies."""
        return ""
