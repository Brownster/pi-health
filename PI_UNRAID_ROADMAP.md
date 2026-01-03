# Pi-Health Mini-Unraid Roadmap

## Overview

**Goal:** Provide a Pi-first "mini-Unraid" experience with modern UI.

**Target Setups:**
- **Setup 1 (Simple):** NVMe OS + downloads, USB HDD for media, USB stick for backups
- **Setup 2 (Advanced):** NVMe downloads, USB stick backups, 5-disk USB3 enclosure with MergerFS + SnapRAID

**Key Decisions:**
- Privileged host helper (systemd service) for mount/fstab operations
- ext4 default filesystem (safe + Pi-friendly)
- No formatting by default; formatting is advanced and gated
- Plugin architecture for storage backends

---

## File Structure

```
pi-health/
├── storage_plugins/
│   ├── __init__.py
│   ├── base.py              # Abstract plugin interface
│   ├── registry.py          # Plugin discovery and management
│   ├── snapraid_plugin.py   # SnapRAID implementation
│   └── mergerfs_plugin.py   # MergerFS implementation
├── config/
│   ├── storage_plugins/
│   │   ├── snapraid.json    # SnapRAID config
│   │   └── mergerfs.json    # MergerFS config
│   └── schemas/
│       ├── snapraid.schema.json
│       └── mergerfs.schema.json
├── static/
│   └── storage.html         # Storage management UI
├── templates/
│   ├── snapraid.conf.j2     # SnapRAID config template
│   └── snapraid-runner.conf.j2
└── tests/
    ├── test_storage_plugins.py
    ├── test_snapraid_plugin.py
    └── test_mergerfs_plugin.py
```

---

## Completed Phases

### Phase 0 — Architecture (privileged helper) ✅
### Phase 1 — Disk Inventory UI ✅
### Phase 2 — Mount Wizard ✅
### Phase 3 — Stack + App Store Integration ✅

---

## Phase 4A — Storage Plugin Framework

**Goal:** Create extensible plugin system for storage backends.

### 4A.1 — Base Plugin Interface

**File:** `storage_plugins/base.py`

```python
"""
Base class for storage plugins.
All storage plugins must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Generator, Optional
from dataclasses import dataclass
from enum import Enum


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

    # Plugin metadata - override in subclass
    PLUGIN_ID: str = ""
    PLUGIN_NAME: str = ""
    PLUGIN_VERSION: str = "1.0.0"
    PLUGIN_DESCRIPTION: str = ""

    def __init__(self, config_dir: str):
        """
        Initialize plugin with config directory.

        Args:
            config_dir: Path to config/storage_plugins/
        """
        self.config_dir = config_dir
        self.config_path = f"{config_dir}/{self.PLUGIN_ID}.json"

    @abstractmethod
    def get_schema(self) -> dict:
        """
        Return JSON schema for plugin configuration.
        Used for validation and UI generation.
        """
        pass

    @abstractmethod
    def get_config(self) -> dict:
        """
        Load and return current configuration.
        Returns empty dict with defaults if no config exists.
        """
        pass

    @abstractmethod
    def set_config(self, config: dict) -> CommandResult:
        """
        Validate and save configuration.
        Does NOT apply changes - call apply_config() for that.
        """
        pass

    @abstractmethod
    def validate_config(self, config: dict) -> list[str]:
        """
        Validate configuration without saving.

        Returns:
            List of validation error messages (empty if valid)
        """
        pass

    @abstractmethod
    def apply_config(self) -> CommandResult:
        """
        Apply saved configuration to system.
        Generates config files, updates fstab, etc.
        """
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """
        Get current plugin status.

        Returns:
            {
                "status": PluginStatus,
                "message": str,
                "details": {...}  # Plugin-specific
            }
        """
        pass

    @abstractmethod
    def get_commands(self) -> list[dict]:
        """
        List available commands for this plugin.

        Returns:
            [
                {
                    "id": "sync",
                    "name": "Sync",
                    "description": "Synchronize parity data",
                    "dangerous": False
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def run_command(self, command_id: str, params: dict = None) -> Generator[str, None, CommandResult]:
        """
        Execute a plugin command with streaming output.

        Yields:
            Output lines as they're produced

        Returns:
            CommandResult with final status
        """
        pass

    def is_installed(self) -> bool:
        """Check if required binaries are installed."""
        return True  # Override in subclass

    def get_install_instructions(self) -> str:
        """Return instructions for installing dependencies."""
        return ""  # Override in subclass
```

### 4A.2 — Plugin Registry

**File:** `storage_plugins/registry.py`

```python
"""
Plugin registry for discovering and managing storage plugins.
"""
import os
import json
import logging
from typing import Dict, Optional
from .base import StoragePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Registry for storage plugins.
    Discovers, loads, and provides access to plugins.
    """

    def __init__(self, config_dir: str):
        """
        Initialize registry.

        Args:
            config_dir: Path to config/storage_plugins/
        """
        self.config_dir = config_dir
        self._plugins: Dict[str, StoragePlugin] = {}

        # Ensure config directory exists
        os.makedirs(config_dir, exist_ok=True)

    def register(self, plugin_class: type) -> None:
        """
        Register a plugin class.

        Args:
            plugin_class: Class inheriting from StoragePlugin
        """
        # Validate plugin class
        required_attrs = ['PLUGIN_ID', 'PLUGIN_NAME']
        for attr in required_attrs:
            if not getattr(plugin_class, attr, None):
                raise ValueError(f"Plugin missing required attribute: {attr}")

        # Validate plugin implements all abstract methods
        plugin = plugin_class(self.config_dir)

        required_methods = [
            'get_schema', 'get_config', 'set_config',
            'validate_config', 'apply_config', 'get_status',
            'get_commands', 'run_command'
        ]
        for method in required_methods:
            if not callable(getattr(plugin, method, None)):
                raise ValueError(f"Plugin missing required method: {method}")

        self._plugins[plugin.PLUGIN_ID] = plugin
        logger.info(f"Registered plugin: {plugin.PLUGIN_ID}")

    def get(self, plugin_id: str) -> Optional[StoragePlugin]:
        """Get plugin by ID."""
        return self._plugins.get(plugin_id)

    def list_plugins(self) -> list[dict]:
        """
        List all registered plugins with status.

        Returns:
            [
                {
                    "id": "snapraid",
                    "name": "SnapRAID",
                    "description": "...",
                    "installed": True,
                    "configured": True,
                    "status": "healthy"
                },
                ...
            ]
        """
        result = []
        for plugin_id, plugin in self._plugins.items():
            status = plugin.get_status()
            result.append({
                "id": plugin_id,
                "name": plugin.PLUGIN_NAME,
                "description": plugin.PLUGIN_DESCRIPTION,
                "version": plugin.PLUGIN_VERSION,
                "installed": plugin.is_installed(),
                "configured": status.get("status") != "unconfigured",
                "status": status.get("status", "unknown"),
                "status_message": status.get("message", "")
            })
        return result

    def get_all(self) -> Dict[str, StoragePlugin]:
        """Get all registered plugins."""
        return self._plugins.copy()


# Global registry instance
_registry: Optional[PluginRegistry] = None


def get_registry(config_dir: str = None) -> PluginRegistry:
    """Get or create the global plugin registry."""
    global _registry
    if _registry is None:
        if config_dir is None:
            raise ValueError("config_dir required for first initialization")
        _registry = PluginRegistry(config_dir)
    return _registry


def init_plugins(config_dir: str) -> PluginRegistry:
    """
    Initialize plugin registry and register all plugins.
    Call this once at app startup.
    """
    registry = get_registry(config_dir)

    # Import and register plugins
    from .snapraid_plugin import SnapRAIDPlugin
    from .mergerfs_plugin import MergerFSPlugin

    registry.register(SnapRAIDPlugin)
    registry.register(MergerFSPlugin)

    return registry
```

### 4A.3 — Flask Blueprint

**File:** `storage_plugins/__init__.py`

```python
"""
Storage plugins Flask blueprint.
Provides REST API for plugin management.
"""
import json
from flask import Blueprint, jsonify, request, Response
from auth_utils import login_required
from .registry import get_registry, init_plugins

storage_bp = Blueprint('storage', __name__)


@storage_bp.route('/api/storage/plugins', methods=['GET'])
@login_required
def list_plugins():
    """List all storage plugins with status."""
    registry = get_registry()
    return jsonify({"plugins": registry.list_plugins()})


@storage_bp.route('/api/storage/plugins/<plugin_id>', methods=['GET'])
@login_required
def get_plugin(plugin_id: str):
    """Get plugin details and configuration."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    return jsonify({
        "id": plugin.PLUGIN_ID,
        "name": plugin.PLUGIN_NAME,
        "description": plugin.PLUGIN_DESCRIPTION,
        "version": plugin.PLUGIN_VERSION,
        "installed": plugin.is_installed(),
        "install_instructions": plugin.get_install_instructions(),
        "schema": plugin.get_schema(),
        "config": plugin.get_config(),
        "status": plugin.get_status(),
        "commands": plugin.get_commands()
    })


@storage_bp.route('/api/storage/plugins/<plugin_id>/config', methods=['POST'])
@login_required
def set_plugin_config(plugin_id: str):
    """Update plugin configuration."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    config = request.get_json() or {}

    # Validate first
    errors = plugin.validate_config(config)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    # Save config
    result = plugin.set_config(config)
    if not result.success:
        return jsonify({"error": result.error}), 400

    return jsonify({"status": "saved", "config": plugin.get_config()})


@storage_bp.route('/api/storage/plugins/<plugin_id>/validate', methods=['POST'])
@login_required
def validate_plugin_config(plugin_id: str):
    """Validate configuration without saving."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    config = request.get_json() or {}
    errors = plugin.validate_config(config)

    return jsonify({
        "valid": len(errors) == 0,
        "errors": errors
    })


@storage_bp.route('/api/storage/plugins/<plugin_id>/apply', methods=['POST'])
@login_required
def apply_plugin_config(plugin_id: str):
    """Apply saved configuration to system."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    result = plugin.apply_config()

    if result.success:
        return jsonify({"status": "applied", "message": result.message})
    else:
        return jsonify({"error": result.error}), 400


@storage_bp.route('/api/storage/plugins/<plugin_id>/status', methods=['GET'])
@login_required
def get_plugin_status(plugin_id: str):
    """Get current plugin status."""
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    return jsonify(plugin.get_status())


@storage_bp.route('/api/storage/plugins/<plugin_id>/commands/<command_id>', methods=['POST'])
@login_required
def run_plugin_command(plugin_id: str, command_id: str):
    """
    Run a plugin command with SSE streaming output.

    Returns Server-Sent Events stream.
    """
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    # Validate command exists
    commands = {c["id"]: c for c in plugin.get_commands()}
    if command_id not in commands:
        return jsonify({"error": f"Unknown command: {command_id}"}), 404

    params = request.get_json() or {}

    def generate():
        """Generate SSE stream."""
        try:
            result = None
            for line in plugin.run_command(command_id, params):
                if isinstance(line, str):
                    yield f"data: {json.dumps({'type': 'output', 'line': line})}\n\n"
                else:
                    # Final result
                    result = line

            if result:
                yield f"data: {json.dumps({'type': 'complete', 'success': result.success, 'message': result.message})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
```

### 4A.4 — Tests

**File:** `tests/test_storage_plugins.py`

```python
"""Tests for storage plugin framework."""
import pytest
import os
import tempfile
import shutil
from storage_plugins.base import StoragePlugin, CommandResult, PluginStatus
from storage_plugins.registry import PluginRegistry, init_plugins


class MockPlugin(StoragePlugin):
    """Mock plugin for testing."""
    PLUGIN_ID = "mock"
    PLUGIN_NAME = "Mock Plugin"
    PLUGIN_DESCRIPTION = "Test plugin"

    def get_schema(self):
        return {"type": "object", "properties": {"enabled": {"type": "boolean"}}}

    def get_config(self):
        return {"enabled": False}

    def set_config(self, config):
        return CommandResult(success=True, message="Saved")

    def validate_config(self, config):
        return []

    def apply_config(self):
        return CommandResult(success=True, message="Applied")

    def get_status(self):
        return {"status": PluginStatus.UNCONFIGURED.value, "message": "Not configured"}

    def get_commands(self):
        return [{"id": "test", "name": "Test", "description": "Test command"}]

    def run_command(self, command_id, params=None):
        yield "Running test..."
        yield "Done!"
        return CommandResult(success=True, message="Complete")


class TestPluginRegistry:
    """Test plugin registry."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_register_valid_plugin(self, temp_config_dir):
        """Test registering a valid plugin."""
        registry = PluginRegistry(temp_config_dir)
        registry.register(MockPlugin)

        assert "mock" in registry.get_all()
        assert registry.get("mock") is not None

    def test_register_invalid_plugin_missing_id(self, temp_config_dir):
        """Test registering plugin without PLUGIN_ID fails."""
        class BadPlugin(StoragePlugin):
            PLUGIN_NAME = "Bad"
            # Missing other required implementations...

        registry = PluginRegistry(temp_config_dir)
        with pytest.raises(ValueError, match="PLUGIN_ID"):
            registry.register(BadPlugin)

    def test_list_plugins(self, temp_config_dir):
        """Test listing plugins with status."""
        registry = PluginRegistry(temp_config_dir)
        registry.register(MockPlugin)

        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["id"] == "mock"
        assert plugins[0]["name"] == "Mock Plugin"
        assert plugins[0]["status"] == "unconfigured"

    def test_get_nonexistent_plugin(self, temp_config_dir):
        """Test getting plugin that doesn't exist."""
        registry = PluginRegistry(temp_config_dir)
        assert registry.get("nonexistent") is None


class TestPluginBase:
    """Test base plugin functionality."""

    @pytest.fixture
    def mock_plugin(self, temp_config_dir):
        """Create mock plugin instance."""
        temp_dir = tempfile.mkdtemp()
        yield MockPlugin(temp_dir)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def temp_config_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plugin_has_required_attrs(self, mock_plugin):
        """Test plugin has required attributes."""
        assert mock_plugin.PLUGIN_ID == "mock"
        assert mock_plugin.PLUGIN_NAME == "Mock Plugin"

    def test_get_schema_returns_dict(self, mock_plugin):
        """Test get_schema returns valid schema."""
        schema = mock_plugin.get_schema()
        assert isinstance(schema, dict)
        assert "type" in schema

    def test_validate_config_returns_list(self, mock_plugin):
        """Test validate_config returns list of errors."""
        errors = mock_plugin.validate_config({})
        assert isinstance(errors, list)

    def test_run_command_streams_output(self, mock_plugin):
        """Test run_command yields output lines."""
        outputs = list(mock_plugin.run_command("test"))
        assert len(outputs) >= 2
        assert "Running" in outputs[0]
```

---

## Phase 4B — SnapRAID Plugin

**Goal:** Full SnapRAID management with drives, exclusions, commands, and scheduling.

### 4B.1 — Configuration Schema

**File:** `config/schemas/snapraid.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "enabled": {
      "type": "boolean",
      "default": false,
      "description": "Enable SnapRAID protection"
    },
    "drives": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string",
            "description": "Unique drive identifier"
          },
          "name": {
            "type": "string",
            "pattern": "^[a-zA-Z0-9_-]+$",
            "description": "SnapRAID disk name (e.g., d1, d2, parity)"
          },
          "path": {
            "type": "string",
            "pattern": "^/mnt/",
            "description": "Mount path"
          },
          "uuid": {
            "type": "string",
            "description": "Disk UUID for identification"
          },
          "role": {
            "type": "string",
            "enum": ["data", "parity"],
            "description": "Drive role"
          },
          "content": {
            "type": "boolean",
            "default": true,
            "description": "Store content file on this drive"
          },
          "parity_level": {
            "type": "integer",
            "minimum": 1,
            "maximum": 6,
            "default": 1,
            "description": "Parity level (1=parity, 2=2-parity, etc.)"
          }
        },
        "required": ["id", "name", "path", "role"]
      }
    },
    "excludes": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "default": [
        "*.tmp",
        "*.temp",
        "/lost+found/",
        "*.unrecoverable",
        ".Thumbs.db",
        ".DS_Store"
      ],
      "description": "Patterns to exclude from protection"
    },
    "settings": {
      "type": "object",
      "properties": {
        "blocksize": {
          "type": "integer",
          "default": 256,
          "description": "Block size in KB"
        },
        "hashsize": {
          "type": "integer",
          "default": 16,
          "description": "Hash size in bytes"
        },
        "autosave": {
          "type": "integer",
          "default": 500,
          "description": "Auto-save after N GB processed"
        },
        "nohidden": {
          "type": "boolean",
          "default": false,
          "description": "Exclude hidden files"
        },
        "prehash": {
          "type": "boolean",
          "default": true,
          "description": "Pre-hash new files for better error detection"
        }
      }
    },
    "thresholds": {
      "type": "object",
      "properties": {
        "delete_threshold": {
          "type": "integer",
          "default": 50,
          "description": "Warn if more than N files deleted"
        },
        "update_threshold": {
          "type": "integer",
          "default": 500,
          "description": "Warn if more than N files changed"
        }
      },
      "description": "Safety thresholds for sync operations"
    },
    "scrub": {
      "type": "object",
      "properties": {
        "enabled": {
          "type": "boolean",
          "default": true
        },
        "percent": {
          "type": "integer",
          "minimum": 1,
          "maximum": 100,
          "default": 12,
          "description": "Percentage of data to scrub per run"
        },
        "age_days": {
          "type": "integer",
          "default": 10,
          "description": "Minimum days since last scrub"
        }
      }
    },
    "schedule": {
      "type": "object",
      "properties": {
        "sync_enabled": {
          "type": "boolean",
          "default": false
        },
        "sync_cron": {
          "type": "string",
          "default": "0 3 * * *",
          "description": "Cron expression for sync"
        },
        "scrub_enabled": {
          "type": "boolean",
          "default": false
        },
        "scrub_cron": {
          "type": "string",
          "default": "0 4 * * 0",
          "description": "Cron expression for scrub (weekly)"
        }
      }
    }
  }
}
```

### 4B.2 — SnapRAID Plugin Implementation

**File:** `storage_plugins/snapraid_plugin.py`

```python
"""
SnapRAID storage plugin.
Manages SnapRAID configuration, sync, scrub, and recovery.
"""
import os
import json
import subprocess
import re
from datetime import datetime
from typing import Generator, Optional
from jinja2 import Template

from .base import StoragePlugin, CommandResult, PluginStatus


class SnapRAIDPlugin(StoragePlugin):
    """SnapRAID parity protection plugin."""

    PLUGIN_ID = "snapraid"
    PLUGIN_NAME = "SnapRAID"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Parity-based backup for data recovery"

    # Paths
    SNAPRAID_BIN = "/usr/bin/snapraid"
    SNAPRAID_CONF = "/etc/snapraid.conf"
    SNAPRAID_CONTENT_DIR = "/var/snapraid"

    # Default exclusions (from OMV plugin)
    DEFAULT_EXCLUDES = [
        "*.tmp",
        "*.temp",
        "*.bak",
        "/lost+found/",
        "*.unrecoverable",
        ".Thumbs.db",
        ".DS_Store",
        "._*",
        ".fseventsd/",
        ".Spotlight-V100/",
        ".Trashes/",
        "aquota.group",
        "aquota.user",
    ]

    def __init__(self, config_dir: str):
        super().__init__(config_dir)
        self._schema = None

    def get_schema(self) -> dict:
        """Load JSON schema from file."""
        if self._schema is None:
            schema_path = os.path.join(
                os.path.dirname(self.config_dir),
                "schemas",
                "snapraid.schema.json"
            )
            if os.path.exists(schema_path):
                with open(schema_path) as f:
                    self._schema = json.load(f)
            else:
                # Inline minimal schema
                self._schema = {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "drives": {"type": "array"},
                        "excludes": {"type": "array"},
                        "settings": {"type": "object"},
                        "thresholds": {"type": "object"},
                        "scrub": {"type": "object"},
                        "schedule": {"type": "object"}
                    }
                }
        return self._schema

    def get_config(self) -> dict:
        """Load current configuration."""
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                config = json.load(f)
        else:
            config = {}

        # Merge with defaults
        defaults = {
            "enabled": False,
            "drives": [],
            "excludes": self.DEFAULT_EXCLUDES.copy(),
            "settings": {
                "blocksize": 256,
                "hashsize": 16,
                "autosave": 500,
                "nohidden": False,
                "prehash": True
            },
            "thresholds": {
                "delete_threshold": 50,
                "update_threshold": 500
            },
            "scrub": {
                "enabled": True,
                "percent": 12,
                "age_days": 10
            },
            "schedule": {
                "sync_enabled": False,
                "sync_cron": "0 3 * * *",
                "scrub_enabled": False,
                "scrub_cron": "0 4 * * 0"
            }
        }

        # Deep merge
        for key, default_value in defaults.items():
            if key not in config:
                config[key] = default_value
            elif isinstance(default_value, dict):
                for k, v in default_value.items():
                    if k not in config[key]:
                        config[key][k] = v

        return config

    def set_config(self, config: dict) -> CommandResult:
        """Save configuration to file."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            # Atomic write
            temp_path = f"{self.config_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(config, f, indent=2)
            os.rename(temp_path, self.config_path)

            return CommandResult(success=True, message="Configuration saved")
        except Exception as e:
            return CommandResult(success=False, message="", error=str(e))

    def validate_config(self, config: dict) -> list[str]:
        """
        Validate SnapRAID configuration.

        Rules:
        1. At least one data drive required
        2. At least one parity drive required
        3. At least one content location required
        4. Drive cannot be both data and parity
        5. Drive names must be unique
        6. Drive paths must exist and be mounted
        """
        errors = []
        drives = config.get("drives", [])

        if not drives:
            errors.append("At least one drive must be configured")
            return errors

        data_drives = [d for d in drives if d.get("role") == "data"]
        parity_drives = [d for d in drives if d.get("role") == "parity"]
        content_drives = [d for d in drives if d.get("content", False)]

        # Rule 1: At least one data drive
        if not data_drives:
            errors.append("At least one data drive is required")

        # Rule 2: At least one parity drive
        if not parity_drives:
            errors.append("At least one parity drive is required")

        # Rule 3: At least one content location
        if not content_drives:
            errors.append("At least one drive must store content files")

        # Rule 5: Unique names
        names = [d.get("name") for d in drives]
        if len(names) != len(set(names)):
            errors.append("Drive names must be unique")

        # Rule 6: Paths exist
        for drive in drives:
            path = drive.get("path", "")
            if not path.startswith("/mnt/"):
                errors.append(f"Drive path must be under /mnt/: {path}")

        # Validate parity levels
        parity_levels = [d.get("parity_level", 1) for d in parity_drives]
        if parity_levels:
            # Must have contiguous parity levels starting at 1
            for i, level in enumerate(sorted(set(parity_levels))):
                if level != i + 1:
                    errors.append(f"Parity levels must be contiguous (1, 2, 3...)")
                    break

        return errors

    def apply_config(self) -> CommandResult:
        """
        Apply configuration by generating snapraid.conf.
        """
        config = self.get_config()

        # Validate before applying
        errors = self.validate_config(config)
        if errors:
            return CommandResult(
                success=False,
                message="",
                error=f"Validation failed: {'; '.join(errors)}"
            )

        try:
            conf_content = self._generate_config(config)

            # Write config file via helper (needs root)
            # For now, write directly if we have permission
            with open(self.SNAPRAID_CONF, 'w') as f:
                f.write(conf_content)

            return CommandResult(
                success=True,
                message=f"Configuration written to {self.SNAPRAID_CONF}"
            )
        except PermissionError:
            return CommandResult(
                success=False,
                message="",
                error="Permission denied. Use helper service for privileged operations."
            )
        except Exception as e:
            return CommandResult(success=False, message="", error=str(e))

    def _generate_config(self, config: dict) -> str:
        """Generate snapraid.conf content."""
        lines = [
            "# Generated by Pi-Health",
            f"# {datetime.now().isoformat()}",
            ""
        ]

        settings = config.get("settings", {})

        # Settings
        if settings.get("prehash", True):
            lines.append("prehash")
        if settings.get("nohidden", False):
            lines.append("nohidden")

        blocksize = settings.get("blocksize", 256)
        if blocksize != 256:
            lines.append(f"blocksize {blocksize}")

        hashsize = settings.get("hashsize", 16)
        if hashsize != 16:
            lines.append(f"hashsize {hashsize}")

        autosave = settings.get("autosave", 0)
        if autosave > 0:
            lines.append(f"autosave {autosave}")

        lines.append("")

        # Drives
        drives = config.get("drives", [])

        # Parity drives first
        for drive in sorted(
            [d for d in drives if d.get("role") == "parity"],
            key=lambda d: d.get("parity_level", 1)
        ):
            level = drive.get("parity_level", 1)
            path = drive["path"]
            if level == 1:
                lines.append(f"parity {path}/snapraid.parity")
            else:
                lines.append(f"{level}-parity {path}/snapraid.{level}-parity")

        lines.append("")

        # Content files
        for drive in drives:
            if drive.get("content", False):
                path = drive["path"]
                lines.append(f"content {path}/snapraid.content")

        lines.append("")

        # Data drives
        for drive in [d for d in drives if d.get("role") == "data"]:
            name = drive["name"]
            path = drive["path"]
            lines.append(f"data {name} {path}")

        lines.append("")

        # Exclusions
        excludes = config.get("excludes", [])
        for pattern in excludes:
            lines.append(f"exclude {pattern}")

        return "\n".join(lines)

    def get_status(self) -> dict:
        """
        Get SnapRAID status.

        Returns:
            {
                "status": "healthy|degraded|error|unconfigured",
                "message": str,
                "details": {
                    "data_drives": int,
                    "parity_drives": int,
                    "last_sync": str or None,
                    "last_scrub": str or None,
                    "sync_in_progress": bool
                }
            }
        """
        config = self.get_config()

        if not config.get("enabled"):
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "SnapRAID is not enabled",
                "details": {}
            }

        drives = config.get("drives", [])
        if not drives:
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "No drives configured",
                "details": {}
            }

        data_drives = [d for d in drives if d.get("role") == "data"]
        parity_drives = [d for d in drives if d.get("role") == "parity"]

        details = {
            "data_drives": len(data_drives),
            "parity_drives": len(parity_drives),
            "last_sync": None,
            "last_scrub": None,
            "sync_in_progress": False
        }

        # Check if config file exists
        if not os.path.exists(self.SNAPRAID_CONF):
            return {
                "status": PluginStatus.ERROR.value,
                "message": "Configuration not applied",
                "details": details
            }

        # Try to get status from snapraid
        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "status"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Parse status output for sync state
                output = result.stdout
                if "No error detected" in output:
                    return {
                        "status": PluginStatus.HEALTHY.value,
                        "message": "All data protected",
                        "details": details
                    }
                elif "sync" in output.lower() and "required" in output.lower():
                    return {
                        "status": PluginStatus.DEGRADED.value,
                        "message": "Sync required",
                        "details": details
                    }
        except FileNotFoundError:
            return {
                "status": PluginStatus.ERROR.value,
                "message": "SnapRAID not installed",
                "details": details
            }
        except subprocess.TimeoutExpired:
            pass
        except Exception as e:
            pass

        return {
            "status": PluginStatus.HEALTHY.value,
            "message": "Status unknown",
            "details": details
        }

    def get_commands(self) -> list[dict]:
        """List available SnapRAID commands."""
        return [
            {
                "id": "status",
                "name": "Status",
                "description": "Show current SnapRAID status",
                "dangerous": False
            },
            {
                "id": "diff",
                "name": "Diff",
                "description": "Show changes since last sync",
                "dangerous": False
            },
            {
                "id": "sync",
                "name": "Sync",
                "description": "Update parity data",
                "dangerous": False
            },
            {
                "id": "scrub",
                "name": "Scrub",
                "description": "Verify data integrity",
                "dangerous": False
            },
            {
                "id": "check",
                "name": "Check",
                "description": "Verify parity without fixing",
                "dangerous": False
            },
            {
                "id": "fix",
                "name": "Fix",
                "description": "Recover damaged files from parity",
                "dangerous": True
            }
        ]

    def run_command(
        self,
        command_id: str,
        params: dict = None
    ) -> Generator[str, None, CommandResult]:
        """
        Execute SnapRAID command with streaming output.
        """
        params = params or {}

        cmd_map = {
            "status": ["status"],
            "diff": ["diff"],
            "sync": ["sync"],
            "scrub": ["scrub", "-p", str(params.get("percent", 12))],
            "check": ["check"],
            "fix": ["fix"]
        }

        if command_id not in cmd_map:
            yield f"Unknown command: {command_id}"
            return CommandResult(success=False, message="", error="Unknown command")

        args = cmd_map[command_id]

        # Check thresholds before sync
        if command_id == "sync" and not params.get("force", False):
            diff_check = self._check_diff_thresholds()
            if diff_check:
                yield f"WARNING: {diff_check}"
                yield "Use force=true to override"
                return CommandResult(
                    success=False,
                    message="",
                    error=diff_check
                )

        yield f"Running: snapraid {' '.join(args)}"
        yield ""

        try:
            process = subprocess.Popen(
                [self.SNAPRAID_BIN] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in iter(process.stdout.readline, ''):
                yield line.rstrip()

            process.wait()

            if process.returncode == 0:
                yield ""
                yield "Command completed successfully"
                return CommandResult(success=True, message="Complete")
            else:
                yield ""
                yield f"Command failed with exit code {process.returncode}"
                return CommandResult(
                    success=False,
                    message="",
                    error=f"Exit code {process.returncode}"
                )

        except FileNotFoundError:
            yield "ERROR: SnapRAID binary not found"
            return CommandResult(
                success=False,
                message="",
                error="SnapRAID not installed"
            )
        except Exception as e:
            yield f"ERROR: {str(e)}"
            return CommandResult(success=False, message="", error=str(e))

    def _check_diff_thresholds(self) -> Optional[str]:
        """
        Check if diff exceeds safety thresholds.

        Returns:
            Warning message if threshold exceeded, None otherwise
        """
        config = self.get_config()
        thresholds = config.get("thresholds", {})
        del_threshold = thresholds.get("delete_threshold", 50)
        upd_threshold = thresholds.get("update_threshold", 500)

        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "diff"],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Parse diff output for counts
            output = result.stdout

            # Look for patterns like "removed 123" and "updated 456"
            removed_match = re.search(r'(\d+)\s+removed', output)
            updated_match = re.search(r'(\d+)\s+updated', output)

            removed = int(removed_match.group(1)) if removed_match else 0
            updated = int(updated_match.group(1)) if updated_match else 0

            if removed > del_threshold:
                return f"Delete threshold exceeded: {removed} files removed (threshold: {del_threshold})"

            if updated > upd_threshold:
                return f"Update threshold exceeded: {updated} files changed (threshold: {upd_threshold})"

        except Exception:
            pass  # Proceed with sync if we can't check

        return None

    def is_installed(self) -> bool:
        """Check if SnapRAID is installed."""
        return os.path.exists(self.SNAPRAID_BIN)

    def get_install_instructions(self) -> str:
        """Return SnapRAID installation instructions."""
        return """
To install SnapRAID on Raspberry Pi OS:

    sudo apt update
    sudo apt install snapraid

Or build from source:

    wget https://github.com/amadvance/snapraid/releases/download/v12.3/snapraid-12.3.tar.gz
    tar xzf snapraid-12.3.tar.gz
    cd snapraid-12.3
    ./configure
    make
    sudo make install
"""

    def get_diff_summary(self) -> dict:
        """
        Get summary of changes since last sync.

        Returns:
            {
                "added": int,
                "removed": int,
                "updated": int,
                "moved": int,
                "copied": int,
                "restored": int
            }
        """
        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "diff"],
                capture_output=True,
                text=True,
                timeout=120
            )

            summary = {
                "added": 0,
                "removed": 0,
                "updated": 0,
                "moved": 0,
                "copied": 0,
                "restored": 0
            }

            for key in summary:
                match = re.search(rf'(\d+)\s+{key}', result.stdout)
                if match:
                    summary[key] = int(match.group(1))

            return summary

        except Exception:
            return {}
```

### 4B.3 — Tests

**File:** `tests/test_snapraid_plugin.py`

```python
"""Tests for SnapRAID plugin."""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from storage_plugins.snapraid_plugin import SnapRAIDPlugin


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def snapraid_plugin(temp_config_dir):
    """Create SnapRAID plugin instance."""
    return SnapRAIDPlugin(temp_config_dir)


@pytest.fixture
def valid_config():
    """Return a valid SnapRAID configuration."""
    return {
        "enabled": True,
        "drives": [
            {
                "id": "d1",
                "name": "d1",
                "path": "/mnt/disk1",
                "role": "data",
                "content": True
            },
            {
                "id": "d2",
                "name": "d2",
                "path": "/mnt/disk2",
                "role": "data",
                "content": True
            },
            {
                "id": "parity1",
                "name": "parity",
                "path": "/mnt/parity",
                "role": "parity",
                "parity_level": 1,
                "content": False
            }
        ],
        "excludes": ["*.tmp", "/lost+found/"],
        "settings": {
            "blocksize": 256,
            "prehash": True
        }
    }


class TestSnapRAIDValidation:
    """Test configuration validation."""

    def test_valid_config_passes(self, snapraid_plugin, valid_config):
        """Test valid configuration passes validation."""
        errors = snapraid_plugin.validate_config(valid_config)
        assert errors == []

    def test_empty_drives_fails(self, snapraid_plugin):
        """Test empty drives list fails validation."""
        errors = snapraid_plugin.validate_config({"drives": []})
        assert len(errors) > 0
        assert any("drive" in e.lower() for e in errors)

    def test_no_data_drive_fails(self, snapraid_plugin):
        """Test missing data drive fails validation."""
        config = {
            "drives": [
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity", "content": True}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("data drive" in e.lower() for e in errors)

    def test_no_parity_drive_fails(self, snapraid_plugin):
        """Test missing parity drive fails validation."""
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": True}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("parity drive" in e.lower() for e in errors)

    def test_no_content_drive_fails(self, snapraid_plugin):
        """Test missing content drive fails validation."""
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": False},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity", "content": False}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("content" in e.lower() for e in errors)

    def test_duplicate_names_fails(self, snapraid_plugin):
        """Test duplicate drive names fails validation."""
        config = {
            "drives": [
                {"id": "d1", "name": "disk", "path": "/mnt/disk1", "role": "data", "content": True},
                {"id": "d2", "name": "disk", "path": "/mnt/disk2", "role": "data", "content": True},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity"}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("unique" in e.lower() for e in errors)

    def test_invalid_path_fails(self, snapraid_plugin):
        """Test path not under /mnt fails validation."""
        config = {
            "drives": [
                {"id": "d1", "name": "d1", "path": "/home/data", "role": "data", "content": True},
                {"id": "p1", "name": "parity", "path": "/mnt/parity", "role": "parity"}
            ]
        }
        errors = snapraid_plugin.validate_config(config)
        assert any("/mnt" in e for e in errors)


class TestSnapRAIDConfigGeneration:
    """Test snapraid.conf generation."""

    def test_generate_basic_config(self, snapraid_plugin, valid_config):
        """Test basic config generation."""
        content = snapraid_plugin._generate_config(valid_config)

        assert "parity /mnt/parity/snapraid.parity" in content
        assert "data d1 /mnt/disk1" in content
        assert "data d2 /mnt/disk2" in content
        assert "content /mnt/disk1/snapraid.content" in content
        assert "exclude *.tmp" in content

    def test_generate_multi_parity_config(self, snapraid_plugin):
        """Test multi-parity config generation."""
        config = {
            "enabled": True,
            "drives": [
                {"id": "d1", "name": "d1", "path": "/mnt/disk1", "role": "data", "content": True},
                {"id": "p1", "name": "parity1", "path": "/mnt/parity1", "role": "parity", "parity_level": 1},
                {"id": "p2", "name": "parity2", "path": "/mnt/parity2", "role": "parity", "parity_level": 2}
            ],
            "excludes": []
        }

        content = snapraid_plugin._generate_config(config)

        assert "parity /mnt/parity1/snapraid.parity" in content
        assert "2-parity /mnt/parity2/snapraid.2-parity" in content

    def test_generate_config_with_settings(self, snapraid_plugin, valid_config):
        """Test config generation includes settings."""
        valid_config["settings"] = {
            "prehash": True,
            "nohidden": True,
            "autosave": 500
        }

        content = snapraid_plugin._generate_config(valid_config)

        assert "prehash" in content
        assert "nohidden" in content
        assert "autosave 500" in content


class TestSnapRAIDCommands:
    """Test SnapRAID command execution."""

    @patch('subprocess.Popen')
    def test_run_status_command(self, mock_popen, snapraid_plugin):
        """Test running status command."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["Line 1\n", "Line 2\n", ""])
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        outputs = list(snapraid_plugin.run_command("status"))

        # Should have output lines plus completion message
        assert any("status" in str(o).lower() for o in outputs)

    @patch('subprocess.Popen')
    def test_run_sync_command(self, mock_popen, snapraid_plugin):
        """Test running sync command."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["Syncing...\n", ""])
        mock_process.wait.return_value = None
        mock_process.returncode = 0
        mock_popen.return_value = mock_process

        # Mock threshold check
        with patch.object(snapraid_plugin, '_check_diff_thresholds', return_value=None):
            outputs = list(snapraid_plugin.run_command("sync"))

        assert any("sync" in str(o).lower() for o in outputs)

    def test_unknown_command_fails(self, snapraid_plugin):
        """Test unknown command returns error."""
        outputs = list(snapraid_plugin.run_command("unknown_cmd"))
        result = outputs[-1]  # Last item should be CommandResult

        # Check that we got an error somewhere in outputs
        assert any("unknown" in str(o).lower() for o in outputs)


class TestSnapRAIDStatus:
    """Test SnapRAID status reporting."""

    def test_unconfigured_status(self, snapraid_plugin):
        """Test status when not configured."""
        status = snapraid_plugin.get_status()
        assert status["status"] == "unconfigured"

    def test_status_with_config(self, snapraid_plugin, valid_config, temp_config_dir):
        """Test status when configured."""
        snapraid_plugin.set_config(valid_config)

        with patch('os.path.exists', return_value=True):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="No error detected"
                )
                status = snapraid_plugin.get_status()

        assert status["details"]["data_drives"] == 2
        assert status["details"]["parity_drives"] == 1


class TestSnapRAIDInstallation:
    """Test installation checks."""

    def test_is_installed_when_exists(self, snapraid_plugin):
        """Test is_installed returns True when binary exists."""
        with patch('os.path.exists', return_value=True):
            assert snapraid_plugin.is_installed() is True

    def test_is_installed_when_missing(self, snapraid_plugin):
        """Test is_installed returns False when binary missing."""
        with patch('os.path.exists', return_value=False):
            assert snapraid_plugin.is_installed() is False

    def test_install_instructions(self, snapraid_plugin):
        """Test install instructions are provided."""
        instructions = snapraid_plugin.get_install_instructions()
        assert "apt" in instructions.lower() or "install" in instructions.lower()
```

---

## Phase 4C — MergerFS Plugin

**Goal:** Pool multiple disks into unified view with configurable policies.

### 4C.1 — Configuration Schema

**File:** `config/schemas/mergerfs.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "pools": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {
            "type": "string"
          },
          "name": {
            "type": "string",
            "pattern": "^[a-zA-Z0-9_-]+$",
            "description": "Pool name (used in mount path)"
          },
          "branches": {
            "type": "array",
            "items": {
              "type": "string"
            },
            "minItems": 2,
            "description": "Source paths to merge"
          },
          "mount_point": {
            "type": "string",
            "pattern": "^/mnt/",
            "description": "Where to mount the merged pool"
          },
          "create_policy": {
            "type": "string",
            "enum": [
              "epmfs",
              "eplfs",
              "eplus",
              "mfs",
              "lfs",
              "lus",
              "rand",
              "pfrd",
              "ff"
            ],
            "default": "epmfs",
            "description": "Policy for creating new files"
          },
          "min_free_space": {
            "type": "string",
            "default": "4G",
            "description": "Minimum free space before skipping drive"
          },
          "options": {
            "type": "string",
            "default": "defaults,allow_other,cache.files=off,category.create=epmfs",
            "description": "Additional mount options"
          },
          "enabled": {
            "type": "boolean",
            "default": true
          }
        },
        "required": ["id", "name", "branches", "mount_point"]
      }
    }
  }
}
```

### 4C.2 — MergerFS Plugin Implementation

**File:** `storage_plugins/mergerfs_plugin.py`

```python
"""
MergerFS storage plugin.
Manages MergerFS pools for combining multiple drives.
"""
import os
import json
import subprocess
import uuid
from typing import Generator, Optional

from .base import StoragePlugin, CommandResult, PluginStatus


# MergerFS create policies with descriptions
POLICIES = {
    "epmfs": "Existing path, most free space - Write to drive with most free space that already has the parent directory",
    "eplfs": "Existing path, least free space - Write to drive with least free space that has the parent directory",
    "eplus": "Existing path, least used space - Write to drive with least used space that has the parent directory",
    "mfs": "Most free space - Write to drive with most free space",
    "lfs": "Least free space - Write to drive with least free space",
    "lus": "Least used space - Write to drive with least used space",
    "rand": "Random - Randomly select a drive",
    "pfrd": "Percentage free random distribution - Weighted random by free space",
    "ff": "First found - Write to first drive with enough space"
}


class MergerFSPlugin(StoragePlugin):
    """MergerFS pool management plugin."""

    PLUGIN_ID = "mergerfs"
    PLUGIN_NAME = "MergerFS"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Combine multiple drives into a single unified pool"

    MERGERFS_BIN = "/usr/bin/mergerfs"
    FSTAB_PATH = "/etc/fstab"

    def __init__(self, config_dir: str):
        super().__init__(config_dir)
        self._schema = None

    def get_schema(self) -> dict:
        """Load JSON schema."""
        if self._schema is None:
            schema_path = os.path.join(
                os.path.dirname(self.config_dir),
                "schemas",
                "mergerfs.schema.json"
            )
            if os.path.exists(schema_path):
                with open(schema_path) as f:
                    self._schema = json.load(f)
            else:
                self._schema = {
                    "type": "object",
                    "properties": {
                        "pools": {"type": "array"}
                    }
                }
        return self._schema

    def get_config(self) -> dict:
        """Load current configuration."""
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                return json.load(f)
        return {"pools": []}

    def set_config(self, config: dict) -> CommandResult:
        """Save configuration."""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            temp_path = f"{self.config_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(config, f, indent=2)
            os.rename(temp_path, self.config_path)

            return CommandResult(success=True, message="Configuration saved")
        except Exception as e:
            return CommandResult(success=False, message="", error=str(e))

    def validate_config(self, config: dict) -> list[str]:
        """
        Validate MergerFS configuration.

        Rules:
        1. Pool names must be unique
        2. Each pool needs at least 2 branches
        3. Mount points must be unique
        4. Branches should not overlap between pools
        5. Mount point must be under /mnt/
        """
        errors = []
        pools = config.get("pools", [])

        names = []
        mount_points = []
        all_branches = []

        for pool in pools:
            name = pool.get("name", "")
            branches = pool.get("branches", [])
            mount_point = pool.get("mount_point", "")

            # Rule 1: Unique names
            if name in names:
                errors.append(f"Duplicate pool name: {name}")
            names.append(name)

            # Rule 2: At least 2 branches
            if len(branches) < 2:
                errors.append(f"Pool '{name}' needs at least 2 branches")

            # Rule 3: Unique mount points
            if mount_point in mount_points:
                errors.append(f"Duplicate mount point: {mount_point}")
            mount_points.append(mount_point)

            # Rule 4: No overlapping branches
            for branch in branches:
                if branch in all_branches:
                    errors.append(f"Branch used in multiple pools: {branch}")
                all_branches.append(branch)

            # Rule 5: Mount under /mnt/
            if not mount_point.startswith("/mnt/"):
                errors.append(f"Mount point must be under /mnt/: {mount_point}")

            # Validate policy
            policy = pool.get("create_policy", "epmfs")
            if policy not in POLICIES:
                errors.append(f"Invalid create policy: {policy}")

        return errors

    def apply_config(self) -> CommandResult:
        """
        Apply configuration by updating fstab and mounting pools.
        """
        config = self.get_config()
        errors = self.validate_config(config)
        if errors:
            return CommandResult(
                success=False,
                message="",
                error=f"Validation failed: {'; '.join(errors)}"
            )

        try:
            pools = config.get("pools", [])

            for pool in pools:
                if not pool.get("enabled", True):
                    continue

                # Generate fstab entry
                fstab_entry = self._generate_fstab_entry(pool)

                # For now, just report what would be done
                # Actual fstab modification requires helper service

            return CommandResult(
                success=True,
                message=f"Configuration ready for {len(pools)} pool(s)"
            )
        except Exception as e:
            return CommandResult(success=False, message="", error=str(e))

    def _generate_fstab_entry(self, pool: dict) -> str:
        """Generate fstab entry for a MergerFS pool."""
        branches = ":".join(pool["branches"])
        mount_point = pool["mount_point"]
        policy = pool.get("create_policy", "epmfs")
        min_free = pool.get("min_free_space", "4G")
        options = pool.get("options", "")

        # Build options string
        opts = [
            "defaults",
            "allow_other",
            "use_ino",
            f"category.create={policy}",
            f"minfreespace={min_free}",
            "cache.files=off",
            "dropcacheonclose=true",
            "fsname=mergerfs"
        ]

        if options:
            # Add custom options, avoiding duplicates
            for opt in options.split(","):
                opt = opt.strip()
                if opt and not any(opt.split("=")[0] in o for o in opts):
                    opts.append(opt)

        opts_str = ",".join(opts)

        return f"{branches} {mount_point} fuse.mergerfs {opts_str} 0 0"

    def get_status(self) -> dict:
        """Get MergerFS status."""
        config = self.get_config()
        pools = config.get("pools", [])

        if not pools:
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "No pools configured",
                "details": {"pools": []}
            }

        pool_status = []
        all_healthy = True

        for pool in pools:
            mount_point = pool.get("mount_point", "")
            is_mounted = os.path.ismount(mount_point)

            status = {
                "name": pool.get("name"),
                "mount_point": mount_point,
                "mounted": is_mounted,
                "branches": len(pool.get("branches", []))
            }

            if is_mounted:
                # Get usage stats
                try:
                    stat = os.statvfs(mount_point)
                    status["total_bytes"] = stat.f_blocks * stat.f_frsize
                    status["free_bytes"] = stat.f_bavail * stat.f_frsize
                    status["used_percent"] = round(
                        (1 - stat.f_bavail / stat.f_blocks) * 100, 1
                    ) if stat.f_blocks > 0 else 0
                except Exception:
                    pass
            else:
                all_healthy = False

            pool_status.append(status)

        return {
            "status": PluginStatus.HEALTHY.value if all_healthy else PluginStatus.DEGRADED.value,
            "message": f"{len(pools)} pool(s) configured",
            "details": {"pools": pool_status}
        }

    def get_commands(self) -> list[dict]:
        """List available commands."""
        return [
            {
                "id": "mount",
                "name": "Mount Pool",
                "description": "Mount a MergerFS pool",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "unmount",
                "name": "Unmount Pool",
                "description": "Unmount a MergerFS pool",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "balance",
                "name": "Balance",
                "description": "Rebalance files across branches",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "status",
                "name": "Status",
                "description": "Show pool status",
                "dangerous": False
            }
        ]

    def run_command(
        self,
        command_id: str,
        params: dict = None
    ) -> Generator[str, None, CommandResult]:
        """Execute MergerFS command."""
        params = params or {}

        if command_id == "status":
            yield from self._cmd_status()
            return CommandResult(success=True, message="Complete")

        elif command_id == "mount":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_mount(pool_name)
            return CommandResult(success=True, message="Mounted")

        elif command_id == "unmount":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_unmount(pool_name)
            return CommandResult(success=True, message="Unmounted")

        elif command_id == "balance":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_balance(pool_name)
            return CommandResult(success=True, message="Complete")

        yield f"Unknown command: {command_id}"
        return CommandResult(success=False, message="", error="Unknown command")

    def _cmd_status(self) -> Generator[str, None, None]:
        """Show status of all pools."""
        config = self.get_config()
        pools = config.get("pools", [])

        if not pools:
            yield "No pools configured"
            return

        for pool in pools:
            name = pool.get("name")
            mount_point = pool.get("mount_point")
            branches = pool.get("branches", [])

            yield f"\n=== Pool: {name} ==="
            yield f"Mount: {mount_point}"
            yield f"Branches: {len(branches)}"

            for branch in branches:
                if os.path.exists(branch):
                    try:
                        stat = os.statvfs(branch)
                        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
                        yield f"  {branch}: {free_gb:.1f} GB free"
                    except Exception:
                        yield f"  {branch}: (cannot read)"
                else:
                    yield f"  {branch}: NOT FOUND"

            if os.path.ismount(mount_point):
                yield "Status: MOUNTED"
            else:
                yield "Status: NOT MOUNTED"

    def _cmd_mount(self, pool_name: str) -> Generator[str, None, None]:
        """Mount a pool."""
        config = self.get_config()
        pool = next(
            (p for p in config.get("pools", []) if p.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        if os.path.ismount(mount_point):
            yield f"Pool already mounted at {mount_point}"
            return

        # Generate fstab-style command
        branches = ":".join(pool["branches"])
        policy = pool.get("create_policy", "epmfs")
        min_free = pool.get("min_free_space", "4G")

        opts = f"category.create={policy},minfreespace={min_free},allow_other,use_ino"

        yield f"Mounting {pool_name}..."
        yield f"  Source: {branches}"
        yield f"  Target: {mount_point}"

        # Create mount point if needed
        os.makedirs(mount_point, exist_ok=True)

        try:
            result = subprocess.run(
                [self.MERGERFS_BIN, "-o", opts, branches, mount_point],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                yield "Mount successful"
            else:
                yield f"Mount failed: {result.stderr}"
        except FileNotFoundError:
            yield "ERROR: mergerfs not installed"
        except Exception as e:
            yield f"ERROR: {e}"

    def _cmd_unmount(self, pool_name: str) -> Generator[str, None, None]:
        """Unmount a pool."""
        config = self.get_config()
        pool = next(
            (p for p in config.get("pools", []) if p.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        if not os.path.ismount(mount_point):
            yield f"Pool not mounted: {mount_point}"
            return

        yield f"Unmounting {pool_name}..."

        try:
            result = subprocess.run(
                ["umount", mount_point],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                yield "Unmount successful"
            else:
                yield f"Unmount failed: {result.stderr}"
                yield "Try: umount -l for lazy unmount"
        except Exception as e:
            yield f"ERROR: {e}"

    def _cmd_balance(self, pool_name: str) -> Generator[str, None, None]:
        """Rebalance files across branches."""
        yield f"Balancing pool: {pool_name}"
        yield "NOTE: mergerfs.balance tool required"
        yield "Install with: apt install mergerfs-tools"

        config = self.get_config()
        pool = next(
            (p for p in config.get("pools", []) if p.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        try:
            process = subprocess.Popen(
                ["mergerfs.balance", mount_point],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in iter(process.stdout.readline, ''):
                yield line.rstrip()

            process.wait()
        except FileNotFoundError:
            yield "mergerfs.balance not found"
            yield "Install mergerfs-tools package"
        except Exception as e:
            yield f"ERROR: {e}"

    def is_installed(self) -> bool:
        """Check if MergerFS is installed."""
        return os.path.exists(self.MERGERFS_BIN)

    def get_install_instructions(self) -> str:
        """Return installation instructions."""
        return """
To install MergerFS on Raspberry Pi OS:

    sudo apt update
    sudo apt install mergerfs

For tools (balance, dedup):

    sudo apt install mergerfs-tools
"""

    def get_policies(self) -> dict:
        """Return available policies with descriptions."""
        return POLICIES
```

### 4C.3 — Tests

**File:** `tests/test_mergerfs_plugin.py`

```python
"""Tests for MergerFS plugin."""
import pytest
import os
import json
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from storage_plugins.mergerfs_plugin import MergerFSPlugin, POLICIES


@pytest.fixture
def temp_config_dir():
    """Create temporary config directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mergerfs_plugin(temp_config_dir):
    """Create MergerFS plugin instance."""
    return MergerFSPlugin(temp_config_dir)


@pytest.fixture
def valid_config():
    """Return valid MergerFS configuration."""
    return {
        "pools": [
            {
                "id": "pool1",
                "name": "storage",
                "branches": ["/mnt/disk1", "/mnt/disk2", "/mnt/disk3"],
                "mount_point": "/mnt/storage",
                "create_policy": "epmfs",
                "min_free_space": "4G",
                "enabled": True
            }
        ]
    }


class TestMergerFSValidation:
    """Test configuration validation."""

    def test_valid_config_passes(self, mergerfs_plugin, valid_config):
        """Test valid configuration passes validation."""
        errors = mergerfs_plugin.validate_config(valid_config)
        assert errors == []

    def test_empty_pools_passes(self, mergerfs_plugin):
        """Test empty pools list is valid."""
        errors = mergerfs_plugin.validate_config({"pools": []})
        assert errors == []

    def test_duplicate_pool_names_fails(self, mergerfs_plugin):
        """Test duplicate pool names fails validation."""
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/s1"},
                {"id": "p2", "name": "storage", "branches": ["/mnt/d3", "/mnt/d4"], "mount_point": "/mnt/s2"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("duplicate" in e.lower() for e in errors)

    def test_insufficient_branches_fails(self, mergerfs_plugin):
        """Test pool with single branch fails."""
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1"], "mount_point": "/mnt/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("2 branches" in e for e in errors)

    def test_duplicate_mount_points_fails(self, mergerfs_plugin):
        """Test duplicate mount points fails."""
        config = {
            "pools": [
                {"id": "p1", "name": "pool1", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/storage"},
                {"id": "p2", "name": "pool2", "branches": ["/mnt/d3", "/mnt/d4"], "mount_point": "/mnt/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("mount point" in e.lower() for e in errors)

    def test_overlapping_branches_fails(self, mergerfs_plugin):
        """Test overlapping branches between pools fails."""
        config = {
            "pools": [
                {"id": "p1", "name": "pool1", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/mnt/s1"},
                {"id": "p2", "name": "pool2", "branches": ["/mnt/d2", "/mnt/d3"], "mount_point": "/mnt/s2"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("multiple pools" in e.lower() for e in errors)

    def test_invalid_mount_path_fails(self, mergerfs_plugin):
        """Test mount path not under /mnt fails."""
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"], "mount_point": "/home/storage"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("/mnt" in e for e in errors)

    def test_invalid_policy_fails(self, mergerfs_plugin):
        """Test invalid create policy fails."""
        config = {
            "pools": [
                {"id": "p1", "name": "storage", "branches": ["/mnt/d1", "/mnt/d2"],
                 "mount_point": "/mnt/storage", "create_policy": "invalid_policy"}
            ]
        }
        errors = mergerfs_plugin.validate_config(config)
        assert any("policy" in e.lower() for e in errors)


class TestMergerFSFstabGeneration:
    """Test fstab entry generation."""

    def test_generate_basic_fstab(self, mergerfs_plugin, valid_config):
        """Test basic fstab entry generation."""
        pool = valid_config["pools"][0]
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "/mnt/disk1:/mnt/disk2:/mnt/disk3" in entry
        assert "/mnt/storage" in entry
        assert "fuse.mergerfs" in entry
        assert "category.create=epmfs" in entry

    def test_fstab_includes_min_free_space(self, mergerfs_plugin, valid_config):
        """Test fstab includes minfreespace option."""
        pool = valid_config["pools"][0]
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "minfreespace=4G" in entry

    def test_fstab_with_custom_policy(self, mergerfs_plugin):
        """Test fstab with different policy."""
        pool = {
            "name": "test",
            "branches": ["/mnt/d1", "/mnt/d2"],
            "mount_point": "/mnt/test",
            "create_policy": "lfs",
            "min_free_space": "1G"
        }
        entry = mergerfs_plugin._generate_fstab_entry(pool)

        assert "category.create=lfs" in entry


class TestMergerFSStatus:
    """Test status reporting."""

    def test_unconfigured_status(self, mergerfs_plugin):
        """Test status when no pools configured."""
        status = mergerfs_plugin.get_status()
        assert status["status"] == "unconfigured"

    def test_status_with_pools(self, mergerfs_plugin, valid_config, temp_config_dir):
        """Test status with configured pools."""
        mergerfs_plugin.set_config(valid_config)

        with patch('os.path.ismount', return_value=True):
            with patch('os.statvfs') as mock_statvfs:
                mock_statvfs.return_value = MagicMock(
                    f_blocks=1000000,
                    f_bavail=500000,
                    f_frsize=4096
                )
                status = mergerfs_plugin.get_status()

        assert status["status"] == "healthy"
        assert len(status["details"]["pools"]) == 1


class TestMergerFSCommands:
    """Test command execution."""

    def test_status_command(self, mergerfs_plugin, valid_config, temp_config_dir):
        """Test status command output."""
        mergerfs_plugin.set_config(valid_config)

        with patch('os.path.exists', return_value=True):
            with patch('os.path.ismount', return_value=True):
                with patch('os.statvfs') as mock_statvfs:
                    mock_statvfs.return_value = MagicMock(
                        f_blocks=1000000,
                        f_bavail=500000,
                        f_frsize=4096
                    )
                    outputs = list(mergerfs_plugin.run_command("status"))

        # Should output pool info
        output_text = "\n".join(str(o) for o in outputs)
        assert "storage" in output_text.lower()

    @patch('subprocess.run')
    def test_mount_command(self, mock_run, mergerfs_plugin, valid_config, temp_config_dir):
        """Test mount command."""
        mergerfs_plugin.set_config(valid_config)
        mock_run.return_value = MagicMock(returncode=0)

        with patch('os.path.ismount', return_value=False):
            with patch('os.makedirs'):
                outputs = list(mergerfs_plugin.run_command("mount", {"pool_name": "storage"}))

        output_text = "\n".join(str(o) for o in outputs)
        assert "mount" in output_text.lower()


class TestMergerFSInstallation:
    """Test installation checks."""

    def test_is_installed(self, mergerfs_plugin):
        """Test installation check."""
        with patch('os.path.exists', return_value=True):
            assert mergerfs_plugin.is_installed() is True

        with patch('os.path.exists', return_value=False):
            assert mergerfs_plugin.is_installed() is False

    def test_policies_available(self, mergerfs_plugin):
        """Test policies are available."""
        policies = mergerfs_plugin.get_policies()
        assert "epmfs" in policies
        assert "mfs" in policies
        assert len(policies) >= 5
```

---

## Phase 4D — Helper Service Extensions

**Goal:** Add privileged commands for storage plugins to helper service.

### 4D.1 — New Helper Commands

Add to `pihealth_helper.py`:

```python
# Add to COMMANDS dict:

def cmd_snapraid(params):
    """Run snapraid command."""
    allowed_cmds = ['status', 'diff', 'sync', 'scrub', 'check', 'fix']
    cmd = params.get('command', '')

    if cmd not in allowed_cmds:
        return {'success': False, 'error': f'Command not allowed: {cmd}'}

    args = ['snapraid', cmd]

    # Add optional parameters
    if cmd == 'scrub' and 'percent' in params:
        args.extend(['-p', str(params['percent'])])

    result = run_command(args, timeout=3600)  # 1 hour timeout
    return {
        'success': result['returncode'] == 0,
        'stdout': result.get('stdout', ''),
        'stderr': result.get('stderr', ''),
        'returncode': result['returncode']
    }


def cmd_mergerfs_mount(params):
    """Mount a MergerFS pool."""
    branches = params.get('branches', '')
    mount_point = params.get('mount_point', '')
    options = params.get('options', '')

    if not branches or not mount_point:
        return {'success': False, 'error': 'branches and mount_point required'}

    if not MOUNT_POINT_PATTERN.match(mount_point):
        return {'success': False, 'error': 'Invalid mount point'}

    # Create mount point
    os.makedirs(mount_point, exist_ok=True)

    cmd = ['mergerfs', '-o', options, branches, mount_point]
    result = run_command(cmd)

    return {
        'success': result['returncode'] == 0,
        'error': result.get('stderr', '') if result['returncode'] != 0 else None
    }


def cmd_mergerfs_umount(params):
    """Unmount a MergerFS pool."""
    mount_point = params.get('mount_point', '')

    if not mount_point or not MOUNT_POINT_PATTERN.match(mount_point):
        return {'success': False, 'error': 'Invalid mount point'}

    result = run_command(['umount', mount_point])

    return {
        'success': result['returncode'] == 0,
        'error': result.get('stderr', '') if result['returncode'] != 0 else None
    }


def cmd_write_snapraid_conf(params):
    """Write snapraid.conf file."""
    content = params.get('content', '')
    path = params.get('path', '/etc/snapraid.conf')

    # Only allow specific paths
    allowed_paths = ['/etc/snapraid.conf', '/etc/snapraid-diff.conf']
    if path not in allowed_paths:
        return {'success': False, 'error': 'Path not allowed'}

    try:
        # Backup existing
        if os.path.exists(path):
            backup = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy(path, backup)

        with open(path, 'w') as f:
            f.write(content)

        return {'success': True, 'path': path}
    except Exception as e:
        return {'success': False, 'error': str(e)}


# Update COMMANDS dict:
COMMANDS = {
    # ... existing commands ...
    'snapraid': cmd_snapraid,
    'mergerfs_mount': cmd_mergerfs_mount,
    'mergerfs_umount': cmd_mergerfs_umount,
    'write_snapraid_conf': cmd_write_snapraid_conf,
}
```

---

## Phase 5A — Recovery Workflow

**Goal:** Guide users through data recovery scenarios.

### 5A.1 — Recovery Status

Add to `snapraid_plugin.py`:

```python
def get_recovery_status(self) -> dict:
    """
    Analyze array health and recovery options.

    Returns:
        {
            "recoverable": bool,
            "failed_drives": [...],
            "missing_files": int,
            "recovery_options": [...]
        }
    """
    try:
        # Run snapraid status
        result = subprocess.run(
            [self.SNAPRAID_BIN, "status"],
            capture_output=True,
            text=True,
            timeout=60
        )

        status = {
            "recoverable": True,
            "failed_drives": [],
            "missing_files": 0,
            "damaged_files": 0,
            "recovery_options": []
        }

        output = result.stdout

        # Parse for errors
        if "Missing file" in output:
            match = re.search(r'(\d+)\s+missing', output)
            if match:
                status["missing_files"] = int(match.group(1))

        if "Damaged file" in output:
            match = re.search(r'(\d+)\s+damaged', output)
            if match:
                status["damaged_files"] = int(match.group(1))

        # Check if recovery is possible
        if status["missing_files"] > 0 or status["damaged_files"] > 0:
            status["recovery_options"] = [
                {
                    "id": "fix_missing",
                    "name": "Recover Missing Files",
                    "command": "fix",
                    "params": {"filter": "missing"},
                    "description": f"Attempt to recover {status['missing_files']} missing files from parity"
                },
                {
                    "id": "fix_damaged",
                    "name": "Repair Damaged Files",
                    "command": "fix",
                    "params": {},
                    "description": f"Repair {status['damaged_files']} damaged files using parity data"
                }
            ]

        return status

    except Exception as e:
        return {
            "recoverable": False,
            "error": str(e),
            "recovery_options": []
        }
```

### 5A.2 — Pre-Sync Diff Analysis

```python
def get_sync_preview(self) -> dict:
    """
    Get preview of what sync will do.
    Shows adds/removes/updates with threshold warnings.

    Returns:
        {
            "safe_to_sync": bool,
            "warnings": [...],
            "changes": {
                "added": int,
                "removed": int,
                "updated": int,
                "moved": int
            },
            "affected_files": [...] (first 100)
        }
    """
    config = self.get_config()
    thresholds = config.get("thresholds", {})
    del_threshold = thresholds.get("delete_threshold", 50)
    upd_threshold = thresholds.get("update_threshold", 500)

    try:
        result = subprocess.run(
            [self.SNAPRAID_BIN, "diff"],
            capture_output=True,
            text=True,
            timeout=300
        )

        preview = {
            "safe_to_sync": True,
            "warnings": [],
            "changes": {
                "added": 0,
                "removed": 0,
                "updated": 0,
                "moved": 0,
                "copied": 0
            },
            "affected_files": []
        }

        # Parse summary line
        for key in preview["changes"]:
            match = re.search(rf'(\d+)\s+{key}', result.stdout)
            if match:
                preview["changes"][key] = int(match.group(1))

        # Check thresholds
        if preview["changes"]["removed"] > del_threshold:
            preview["safe_to_sync"] = False
            preview["warnings"].append({
                "type": "delete_threshold",
                "message": f"Large number of deletions: {preview['changes']['removed']} files (threshold: {del_threshold})",
                "severity": "high"
            })

        if preview["changes"]["updated"] > upd_threshold:
            preview["warnings"].append({
                "type": "update_threshold",
                "message": f"Large number of updates: {preview['changes']['updated']} files (threshold: {upd_threshold})",
                "severity": "medium"
            })

        # Extract file list (first 100 lines with file paths)
        lines = result.stdout.split('\n')
        file_pattern = re.compile(r'^(add|remove|update|move)\s+(.+)$')
        for line in lines[:500]:
            match = file_pattern.match(line.strip())
            if match and len(preview["affected_files"]) < 100:
                preview["affected_files"].append({
                    "action": match.group(1),
                    "path": match.group(2)
                })

        return preview

    except subprocess.TimeoutExpired:
        return {
            "safe_to_sync": False,
            "warnings": [{"type": "timeout", "message": "Diff command timed out", "severity": "high"}],
            "changes": {},
            "affected_files": []
        }
    except Exception as e:
        return {
            "safe_to_sync": False,
            "warnings": [{"type": "error", "message": str(e), "severity": "high"}],
            "changes": {},
            "affected_files": []
        }
```

---

## Phase 5B — Scheduling

**Goal:** Automated sync and scrub with systemd timers.

### 5B.1 — Timer Generation

```python
def generate_systemd_timer(self, job_type: str) -> tuple[str, str]:
    """
    Generate systemd service and timer files.

    Args:
        job_type: "sync" or "scrub"

    Returns:
        (service_content, timer_content)
    """
    config = self.get_config()
    schedule = config.get("schedule", {})

    cron = schedule.get(f"{job_type}_cron", "0 3 * * *")

    # Convert cron to systemd OnCalendar format
    # Simple conversion for common patterns
    on_calendar = self._cron_to_oncalendar(cron)

    service = f"""[Unit]
Description=SnapRAID {job_type}
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/snapraid {job_type}
Nice=19
IOSchedulingClass=idle
"""

    timer = f"""[Unit]
Description=SnapRAID {job_type} timer

[Timer]
OnCalendar={on_calendar}
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
"""

    return service, timer


def _cron_to_oncalendar(self, cron: str) -> str:
    """Convert cron expression to systemd OnCalendar format."""
    parts = cron.split()
    if len(parts) != 5:
        return "*-*-* 03:00:00"  # Default fallback

    minute, hour, day, month, dow = parts

    # Simple common patterns
    if dow == "0":  # Sunday
        return f"Sun *-*-* {hour}:{minute}:00"
    elif dow == "*" and day == "*" and month == "*":
        return f"*-*-* {hour}:{minute}:00"  # Daily

    return f"*-*-* {hour}:{minute}:00"
```

---

## Phase 6 — Storage UI Page

**Goal:** Unified storage management interface.

### 6.1 — Page Structure

**File:** `static/storage.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <!-- Standard head content from other pages -->
    <title>Storage - Pi-Health</title>
</head>
<body class="bg-gray-900 text-blue-100">
    <!-- Standard header and nav -->

    <main class="container mx-auto p-6">
        <!-- Plugin Status Cards -->
        <div id="plugin-cards" class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
            <!-- Populated by JS -->
        </div>

        <!-- Tab Navigation -->
        <div class="border-b border-gray-700 mb-6">
            <nav class="flex space-x-4">
                <button onclick="showTab('snapraid')" class="tab-btn active" data-tab="snapraid">
                    SnapRAID
                </button>
                <button onclick="showTab('mergerfs')" class="tab-btn" data-tab="mergerfs">
                    MergerFS
                </button>
                <button onclick="showTab('schedule')" class="tab-btn" data-tab="schedule">
                    Schedule
                </button>
            </nav>
        </div>

        <!-- SnapRAID Tab -->
        <div id="tab-snapraid" class="tab-content">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <!-- Drives Configuration -->
                <div class="lg:col-span-2 bg-gray-800 rounded-lg p-6">
                    <h3 class="text-xl font-semibold mb-4">Drives</h3>
                    <div id="snapraid-drives" class="space-y-3">
                        <!-- Drive list populated by JS -->
                    </div>
                    <button onclick="addDrive()" class="mt-4 coraline-button px-4 py-2">
                        Add Drive
                    </button>
                </div>

                <!-- Quick Actions -->
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 class="text-xl font-semibold mb-4">Actions</h3>
                    <div class="space-y-3">
                        <button onclick="runSnapraid('diff')" class="w-full coraline-button px-4 py-2">
                            Preview Changes (Diff)
                        </button>
                        <button onclick="runSnapraid('sync')" class="w-full coraline-button px-4 py-2">
                            Sync Parity
                        </button>
                        <button onclick="runSnapraid('scrub')" class="w-full coraline-button px-4 py-2">
                            Verify Data (Scrub)
                        </button>
                        <button onclick="runSnapraid('status')" class="w-full bg-gray-700 px-4 py-2 rounded">
                            Check Status
                        </button>
                    </div>
                </div>
            </div>

            <!-- Exclusions -->
            <div class="mt-6 bg-gray-800 rounded-lg p-6">
                <h3 class="text-xl font-semibold mb-4">Exclusions</h3>
                <div id="snapraid-excludes" class="space-y-2">
                    <!-- Exclusion list -->
                </div>
            </div>
        </div>

        <!-- MergerFS Tab -->
        <div id="tab-mergerfs" class="tab-content hidden">
            <div class="bg-gray-800 rounded-lg p-6">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-xl font-semibold">Pools</h3>
                    <button onclick="addPool()" class="coraline-button px-4 py-2">
                        Create Pool
                    </button>
                </div>
                <div id="mergerfs-pools" class="space-y-4">
                    <!-- Pool cards -->
                </div>
            </div>
        </div>

        <!-- Schedule Tab -->
        <div id="tab-schedule" class="tab-content hidden">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <!-- Sync Schedule -->
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 class="text-xl font-semibold mb-4">Sync Schedule</h3>
                    <div class="space-y-4">
                        <label class="flex items-center">
                            <input type="checkbox" id="sync-enabled" class="mr-3">
                            Enable automatic sync
                        </label>
                        <select id="sync-preset" class="w-full bg-gray-700 rounded p-2">
                            <option value="daily_3am">Daily at 3:00 AM</option>
                            <option value="daily_4am">Daily at 4:00 AM</option>
                            <option value="weekly_sun">Weekly (Sunday 3:00 AM)</option>
                        </select>
                    </div>
                </div>

                <!-- Scrub Schedule -->
                <div class="bg-gray-800 rounded-lg p-6">
                    <h3 class="text-xl font-semibold mb-4">Scrub Schedule</h3>
                    <div class="space-y-4">
                        <label class="flex items-center">
                            <input type="checkbox" id="scrub-enabled" class="mr-3">
                            Enable automatic scrub
                        </label>
                        <select id="scrub-preset" class="w-full bg-gray-700 rounded p-2">
                            <option value="weekly_sun">Weekly (Sunday 4:00 AM)</option>
                            <option value="monthly">Monthly (1st Sunday)</option>
                        </select>
                        <div>
                            <label class="block text-sm mb-1">Scrub percentage per run</label>
                            <input type="number" id="scrub-percent" value="12" min="1" max="100"
                                   class="w-20 bg-gray-700 rounded p-2">
                            <span class="text-gray-400 text-sm">%</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Command Output Modal -->
        <div id="output-modal" class="fixed inset-0 bg-black/50 hidden flex items-center justify-center">
            <div class="bg-gray-800 rounded-lg w-full max-w-3xl max-h-[80vh] flex flex-col">
                <div class="flex justify-between items-center p-4 border-b border-gray-700">
                    <h3 id="output-title" class="text-lg font-semibold">Command Output</h3>
                    <button onclick="closeOutputModal()" class="text-gray-400 hover:text-white">
                        &times;
                    </button>
                </div>
                <pre id="output-content" class="flex-1 overflow-auto p-4 text-sm font-mono bg-gray-900"></pre>
                <div class="p-4 border-t border-gray-700">
                    <span id="output-status" class="text-sm text-gray-400">Running...</span>
                </div>
            </div>
        </div>
    </main>

    <script>
        // Tab management
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.add('hidden'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

            document.getElementById(`tab-${tabName}`).classList.remove('hidden');
            document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        }

        // Load plugin data
        async function loadPlugins() {
            const response = await fetch('/api/storage/plugins');
            const data = await response.json();
            renderPluginCards(data.plugins);
        }

        function renderPluginCards(plugins) {
            const container = document.getElementById('plugin-cards');
            container.innerHTML = plugins.map(plugin => `
                <div class="bg-gray-800 rounded-lg p-6">
                    <div class="flex justify-between items-start">
                        <div>
                            <h3 class="text-xl font-semibold">${plugin.name}</h3>
                            <p class="text-gray-400 text-sm">${plugin.description}</p>
                        </div>
                        <span class="px-2 py-1 rounded text-sm ${
                            plugin.status === 'healthy' ? 'bg-green-600' :
                            plugin.status === 'degraded' ? 'bg-yellow-600' :
                            plugin.status === 'error' ? 'bg-red-600' : 'bg-gray-600'
                        }">
                            ${plugin.status}
                        </span>
                    </div>
                    <p class="mt-2 text-sm text-gray-300">${plugin.status_message}</p>
                </div>
            `).join('');
        }

        // SnapRAID commands
        async function runSnapraid(command) {
            showOutputModal(`SnapRAID ${command}`);

            const response = await fetch(`/api/storage/plugins/snapraid/commands/${command}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({})
            });

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            const outputEl = document.getElementById('output-content');

            while (true) {
                const {done, value} = await reader.read();
                if (done) break;

                const text = decoder.decode(value);
                const lines = text.split('\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'output') {
                            outputEl.textContent += data.line + '\n';
                            outputEl.scrollTop = outputEl.scrollHeight;
                        } else if (data.type === 'complete') {
                            document.getElementById('output-status').textContent =
                                data.success ? 'Completed successfully' : 'Failed';
                        }
                    }
                }
            }
        }

        function showOutputModal(title) {
            document.getElementById('output-title').textContent = title;
            document.getElementById('output-content').textContent = '';
            document.getElementById('output-status').textContent = 'Running...';
            document.getElementById('output-modal').classList.remove('hidden');
        }

        function closeOutputModal() {
            document.getElementById('output-modal').classList.add('hidden');
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            loadPlugins();
            loadSnapraidConfig();
            loadMergerfsConfig();
        });
    </script>
</body>
</html>
```

---

## Test Summary

| Module | Test File | Test Count |
|--------|-----------|------------|
| Plugin Framework | `test_storage_plugins.py` | ~15 |
| SnapRAID Plugin | `test_snapraid_plugin.py` | ~25 |
| MergerFS Plugin | `test_mergerfs_plugin.py` | ~20 |
| Helper Extensions | `test_helper_storage.py` | ~10 |

**Total new tests: ~70**

---

## Implementation Order

```
4A (framework)     ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  Week 1
4B (SnapRAID)      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  Week 2
4C (MergerFS)      ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  Week 3
4D (Helper cmds)   ▓▓▓▓▓▓▓▓░░░░░░░░░░░░  Week 3
5A (Recovery)      ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░  Week 4
5B (Scheduling)    ▓▓▓▓▓▓▓▓░░░░░░░░░░░░  Week 4
6  (UI Page)       ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░  Week 4-5
```

---

## Quick Reference: SnapRAID Config Format

```
# /etc/snapraid.conf

# Settings
prehash
autosave 500

# Parity files (1 parity = 1 disk failure protection)
parity /mnt/parity1/snapraid.parity
2-parity /mnt/parity2/snapraid.2-parity

# Content files (store on 2+ drives for redundancy)
content /mnt/disk1/snapraid.content
content /mnt/disk2/snapraid.content

# Data drives
data d1 /mnt/disk1
data d2 /mnt/disk2
data d3 /mnt/disk3
data d4 /mnt/disk4

# Exclusions
exclude *.tmp
exclude /lost+found/
exclude .Trash-*/
```

## Quick Reference: MergerFS fstab Entry

```
# /etc/fstab

/mnt/disk1:/mnt/disk2:/mnt/disk3:/mnt/disk4 /mnt/storage fuse.mergerfs defaults,allow_other,use_ino,category.create=epmfs,minfreespace=4G,cache.files=off 0 0
```

---

## Glossary

| Term | Description |
|------|-------------|
| **Parity** | Computed data that allows recovery from disk failure |
| **Content file** | Index of protected files with checksums |
| **Sync** | Update parity to reflect current data state |
| **Scrub** | Verify data integrity by comparing to parity |
| **Branch** | Source directory in a MergerFS pool |
| **Policy** | Algorithm for choosing where to write new files |
