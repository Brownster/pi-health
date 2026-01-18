#!/usr/bin/env python3
"""
Tests for plugin_manager behaviors.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import plugin_manager


class DummyRegistry:
    def list_plugins(self):
        return []


def setup_temp_config(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    plugin_dir = tmp_path / "plugins"
    config_dir.mkdir()
    plugin_dir.mkdir()
    monkeypatch.setattr(plugin_manager, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(plugin_manager, "CONFIG_FILE", str(config_dir / "plugins.json"))
    monkeypatch.setattr(plugin_manager, "PLUGIN_DIR", str(plugin_dir))
    return config_dir, plugin_dir


def test_set_enabled_round_trip(monkeypatch, tmp_path):
    setup_temp_config(monkeypatch, tmp_path)
    plugin_manager.set_enabled("samba", True)
    assert plugin_manager.is_enabled("samba") is True
    plugin_manager.set_enabled("samba", False)
    assert plugin_manager.is_enabled("samba") is False


def test_list_plugins_includes_defaults(monkeypatch, tmp_path):
    setup_temp_config(monkeypatch, tmp_path)
    plugins = plugin_manager.list_plugins(DummyRegistry())
    ids = {p["id"] for p in plugins}
    assert "snapraid" in ids
    assert "mergerfs" in ids


def test_install_plugin_github(monkeypatch, tmp_path):
    _, plugin_dir = setup_temp_config(monkeypatch, tmp_path)
    plugin_id = "thirdparty"
    plugin_path = plugin_dir / plugin_id
    plugin_path.mkdir()
    manifest = {
        "id": plugin_id,
        "name": "Third Party",
        "entry": "plugin.py",
        "class": "ThirdPartyPlugin",
        "category": "storage"
    }
    (plugin_path / "pihealth_plugin.json").write_text(json.dumps(manifest))

    monkeypatch.setattr(plugin_manager, "helper_call", lambda *_args, **_kwargs: {"success": True, "id": plugin_id})

    result = plugin_manager.install_plugin("github", "https://github.com/example/repo", plugin_id)
    assert result["success"] is True
    entry = plugin_manager.get_plugin_entry(plugin_id)
    assert entry["entry"] == "plugin.py"


def test_install_plugin_pip_requires_entry(monkeypatch, tmp_path):
    setup_temp_config(monkeypatch, tmp_path)
    monkeypatch.setattr(plugin_manager, "helper_call", lambda *_args, **_kwargs: {"success": True})
    result = plugin_manager.install_plugin("pip", "pihealth-plugin-foo")
    assert result["success"] is False


def test_remove_plugin_rejects_builtin(monkeypatch, tmp_path):
    setup_temp_config(monkeypatch, tmp_path)
    result = plugin_manager.remove_plugin("snapraid")
    assert result["success"] is False


def test_remove_plugin_success(monkeypatch, tmp_path):
    setup_temp_config(monkeypatch, tmp_path)
    plugin_id = "thirdparty"
    config = plugin_manager.load_plugins_config()
    config["plugins"].append({"id": plugin_id, "type": "github", "source": "https://github.com/example/repo"})
    with open(plugin_manager.CONFIG_FILE, "w") as handle:
        json.dump(config, handle)

    monkeypatch.setattr(plugin_manager, "helper_call", lambda *_args, **_kwargs: {"success": True})
    result = plugin_manager.remove_plugin(plugin_id)
    assert result["success"] is True
    assert plugin_manager.get_plugin_entry(plugin_id) is None
