#!/usr/bin/env python3
"""
Tests for Pi-Health update endpoints.
"""
import json
import os
import sys


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


def test_update_starts_streamed_operation(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        "app.helper_call",
        lambda _cmd, params: {"success": True, "old_commit": "a" * 40, "new_commit": "a" * 40},
    )
    response = authenticated_client.post("/api/pihealth/update")
    assert response.status_code == 202
    data = response.get_json()
    assert data["operation_id"]
    assert data["stream_url"].endswith(f"/api/pihealth/update/operations/{data['operation_id']}/stream")


def test_update_requires_csrf(authenticated_client):
    response = authenticated_client.post(
        "/api/pihealth/update",
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert response.status_code == 403


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def _parse_sse(text):
    events = []
    for frame in text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_update_streams_full_sequence_end_to_end(authenticated_client, monkeypatch):
    def fake_helper(command, params):
        assert command == "pihealth_update"
        step = params["step"]
        if step == "pull":
            return {
                "success": True,
                "old_commit": "a" * 40,
                "new_commit": "b" * 40,
                "changed_files": ["app.py"],  # no deps/UI work
            }
        return {"success": True, "scheduled": True}

    monkeypatch.setattr("app.helper_call", fake_helper)

    created = authenticated_client.post("/api/pihealth/update")
    assert created.status_code == 202
    stream_url = created.get_json()["stream_url"]

    stream = authenticated_client.get(stream_url)
    assert stream.status_code == 200
    events = _parse_sse(stream.get_data(as_text=True))

    steps = [event.get("step") for event in events]
    assert steps[:2] == ["pull", "pull"]
    assert steps[-2:] == ["restart", "restart"]
    # Every stage is represented, in order, exactly once as a group.
    assert [step for step in dict.fromkeys(steps)] == [
        "pull", "deps", "migrate", "build", "agent", "restart"
    ]

    lines = {event.get("step"): event.get("line", "") for event in events}
    assert "No dependency changes." in lines["deps"]  # requirements.txt not in changed_files
    assert "No UI changes." in lines["build"]  # frontend/ not in changed_files
    assert "No agent changes." in lines["agent"]  # no agent paths in changed_files

    terminal = events[-1]
    assert terminal["restarting"] is True
    assert terminal["done"] is True
    assert terminal["new_commit"] == "b" * 40
