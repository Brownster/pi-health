#!/usr/bin/env python3
"""
Tests for Pi-Health update endpoints.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))




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


def test_update_config_requires_auth(client):
    response = client.get("/api/pihealth/update/config")
    assert response.status_code == 401

    response = client.post(
        "/api/pihealth/update/config",
        data=json.dumps({}),
        content_type="application/json"
    )
    assert response.status_code == 401


def test_update_requires_auth(client):
    response = client.post("/api/pihealth/update")
    assert response.status_code == 401


def test_update_calls_helper(authenticated_client, monkeypatch):
    monkeypatch.setattr("app.helper_call", lambda *_args, **_kwargs: {"success": True})
    response = authenticated_client.post("/api/pihealth/update")
    assert response.status_code == 200
