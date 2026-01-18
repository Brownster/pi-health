#!/usr/bin/env python3
"""
Tests for tools manager endpoints.
"""
import os
import sys
import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from helper_client import HelperError


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["username"] = "testuser"
    return client


def test_copyparty_status(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")
    monkeypatch.setattr("tools_manager.helper_call", lambda *_args, **_kwargs: {
        "installed": True,
        "service_active": True,
        "service_status": "active"
    })

    response = authenticated_client.get("/api/tools/copyparty/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["installed"] is True
    assert data["service_status"] == "active"
    assert "config" in data


def test_copyparty_status_helper_error(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")

    def raise_error(*_args, **_kwargs):
        raise HelperError("helper down")

    monkeypatch.setattr("tools_manager.helper_call", raise_error)

    response = authenticated_client.get("/api/tools/copyparty/status")
    assert response.status_code == 503
    data = response.get_json()
    assert "error" in data
    assert "config" in data


def test_copyparty_install_helper_error(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")

    def raise_error(*_args, **_kwargs):
        raise HelperError("helper down")

    monkeypatch.setattr("tools_manager.helper_call", raise_error)

    response = authenticated_client.post("/api/tools/copyparty/install")
    assert response.status_code == 503


def test_copyparty_install_failure(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")
    monkeypatch.setattr("tools_manager.helper_call", lambda *_args, **_kwargs: {"success": False, "error": "nope"})

    response = authenticated_client.post("/api/tools/copyparty/install")
    assert response.status_code == 400
    assert response.get_json()["error"] == "nope"


def test_copyparty_config(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")
    monkeypatch.setattr("tools_manager.helper_call", lambda *_args, **_kwargs: {"success": True})

    payload = {
        "share_path": "/srv/copyparty",
        "port": 3923,
        "extra_args": ""
    }
    response = authenticated_client.post(
        "/api/tools/copyparty/config",
        data=json.dumps(payload),
        content_type="application/json"
    )
    assert response.status_code == 200


def test_copyparty_config_invalid_share_path(authenticated_client):
    response = authenticated_client.post(
        "/api/tools/copyparty/config",
        data=json.dumps({"share_path": "relative", "port": 3923}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_copyparty_config_invalid_port(authenticated_client):
    response = authenticated_client.post(
        "/api/tools/copyparty/config",
        data=json.dumps({"share_path": "/srv/copyparty", "port": "bad"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_copyparty_config_helper_error(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")

    def raise_error(*_args, **_kwargs):
        raise HelperError("helper down")

    monkeypatch.setattr("tools_manager.helper_call", raise_error)

    response = authenticated_client.post(
        "/api/tools/copyparty/config",
        data=json.dumps({"share_path": "/srv/copyparty", "port": 3923}),
        content_type="application/json",
    )
    assert response.status_code == 503


def test_copyparty_config_failure(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("tools_manager.CONFIG_PATH", tmp_path / "copyparty.json")
    monkeypatch.setattr("tools_manager.helper_call", lambda *_args, **_kwargs: {"success": False, "error": "nope"})

    response = authenticated_client.post(
        "/api/tools/copyparty/config",
        data=json.dumps({"share_path": "/srv/copyparty", "port": 3923}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "nope"
