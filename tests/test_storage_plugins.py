"""Tests for storage plugin framework."""
import os
import shutil
import tempfile
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.base import StoragePlugin, CommandResult, PluginStatus
from storage_plugins.registry import PluginRegistry


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
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_register_valid_plugin(self, temp_config_dir):
        registry = PluginRegistry(temp_config_dir)
        registry.register(MockPlugin)

        assert "mock" in registry.get_all()
        assert registry.get("mock") is not None

    def test_register_invalid_plugin_missing_id(self, temp_config_dir):
        class BadPlugin(StoragePlugin):
            PLUGIN_NAME = "Bad"

            def get_schema(self):
                return {}

            def get_config(self):
                return {}

            def set_config(self, config):
                return CommandResult(success=False, message="Nope")

            def validate_config(self, config):
                return ["bad"]

            def apply_config(self):
                return CommandResult(success=False, message="Nope")

            def get_status(self):
                return {"status": PluginStatus.ERROR.value, "message": "bad"}

            def get_commands(self):
                return []

            def run_command(self, command_id, params=None):
                yield "nope"
                return CommandResult(success=False, message="Nope")

        registry = PluginRegistry(temp_config_dir)
        with pytest.raises(ValueError, match="PLUGIN_ID"):
            registry.register(BadPlugin)

    def test_list_plugins(self, temp_config_dir):
        registry = PluginRegistry(temp_config_dir)
        registry.register(MockPlugin)

        plugins = registry.list_plugins()
        assert len(plugins) == 1
        assert plugins[0]["id"] == "mock"
        assert plugins[0]["name"] == "Mock Plugin"
        assert plugins[0]["status"] == "unconfigured"

    def test_get_nonexistent_plugin(self, temp_config_dir):
        registry = PluginRegistry(temp_config_dir)
        assert registry.get("nonexistent") is None


class TestPluginBase:
    """Test base plugin functionality."""

    @pytest.fixture
    def temp_config_dir(self):
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_plugin(self, temp_config_dir):
        yield MockPlugin(temp_config_dir)

    def test_plugin_has_required_attrs(self, mock_plugin):
        assert mock_plugin.PLUGIN_ID == "mock"
        assert mock_plugin.PLUGIN_NAME == "Mock Plugin"

    def test_get_schema_returns_dict(self, mock_plugin):
        schema = mock_plugin.get_schema()
        assert isinstance(schema, dict)
        assert "type" in schema

    def test_validate_config_returns_list(self, mock_plugin):
        errors = mock_plugin.validate_config({})
        assert isinstance(errors, list)

    def test_run_command_streams_output(self, mock_plugin):
        outputs = list(mock_plugin.run_command("test"))
        assert len(outputs) >= 2
        assert "Running" in outputs[0]
