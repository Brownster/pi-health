#!/usr/bin/env python3
"""
Tests for Pi-Health update endpoints.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


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


def test_update_config_roundtrip(authenticated_client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.PIHEALTH_UPDATE_CONFIG", tmp_path / "pihealth_update.json")

    payload = {"repo_path": "/home/testuser/pi-health", "service_name": "pi-health"}
    response = authenticated_client.post(
        "/api/pihealth/update/config",
        data=json.dumps(payload),
        content_type="application/json"
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["config"]["repo_path"] == payload["repo_path"]

    response = authenticated_client.get("/api/pihealth/update/config")
    assert response.status_code == 200
    data = response.get_json()
    assert data["repo_path"] == payload["repo_path"]


def test_update_calls_helper(authenticated_client, monkeypatch):
    monkeypatch.setattr("app.helper_call", lambda *_args, **_kwargs: {"success": True})
    response = authenticated_client.post("/api/pihealth/update")
    assert response.status_code == 200
