#!/usr/bin/env python3
"""
Tests for Samba share plugin.
"""
import os
import sys
import tempfile
import shutil
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_plugins.samba_plugin import SambaPlugin


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


def sample_config():
    return {
        "shares": [
            {
                "name": "media",
                "path": "/mnt/media",
                "read_only": False,
                "guest_ok": True,
                "valid_users": ""
            }
        ]
    }


def test_validate_config_ok(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    errors = plugin.validate_config(sample_config())
    assert errors == []


def test_validate_config_duplicate_name(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    config = {
        "shares": [
            {"name": "media", "path": "/mnt/media"},
            {"name": "media", "path": "/mnt/other"}
        ]
    }
    errors = plugin.validate_config(config)
    assert errors


def test_validate_config_invalid_name(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    config = {"shares": [{"name": "bad name", "path": "/mnt/media"}]}
    errors = plugin.validate_config(config)
    assert errors


def test_validate_config_invalid_path(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    config = {"shares": [{"name": "media", "path": "mnt/media"}]}
    errors = plugin.validate_config(config)
    assert errors


def test_apply_config_generates_file(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    config = sample_config()
    plugin.set_config(config)

    result = plugin.apply_config()
    assert result.success is True

    output_path = os.path.join(temp_config_dir, "samba.generated.conf")
    assert os.path.exists(output_path)
    with open(output_path) as handle:
        content = handle.read()
    assert "[media]" in content
    assert "path = /mnt/media" in content


def test_status_not_installed(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    with patch("storage_plugins.samba_plugin.shutil.which", return_value=None):
        status = plugin.get_status()
    assert status["status"] == "error"


def test_status_unconfigured(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    with patch("storage_plugins.samba_plugin.shutil.which", return_value="/usr/sbin/smbd"):
        status = plugin.get_status()
    assert status["status"] == "unconfigured"


def test_status_configured(temp_config_dir):
    plugin = SambaPlugin(temp_config_dir)
    plugin.set_config(sample_config())
    with patch("storage_plugins.samba_plugin.shutil.which", return_value="/usr/sbin/smbd"):
        with patch.object(plugin, "_is_service_running", return_value=True):
            status = plugin.get_status()
    assert status["status"] == "healthy"


def test_import_existing_shares(temp_config_dir, monkeypatch):
    smb_conf = os.path.join(temp_config_dir, "smb.conf")
    with open(smb_conf, "w") as handle:
        handle.write(
            """
[global]
   workgroup = WORKGROUP

[media]
   path = /mnt/media
   read only = no
   guest ok = yes
   browseable = yes
   valid users = pi,media

[homes]
   read only = no

[docs]
   path = /srv/docs
   read only = yes
   browseable = no
   available = no
"""
        )

    monkeypatch.setenv("SAMBA_CONFIG_PATH", smb_conf)
    plugin = SambaPlugin(temp_config_dir)
    result = plugin.import_existing_shares()
    assert result.success is True
    assert result.data["imported"] == 2

    config = plugin.get_config()
    names = {share["name"] for share in config.get("shares", [])}
    assert names == {"media", "docs"}

    docs = next(share for share in config["shares"] if share["name"] == "docs")
    assert docs["read_only"] is True
    assert docs["browseable"] is False
    assert docs["enabled"] is False
