"""Target wiring tests for fixed, read-only host diagnostic commands."""

from __future__ import annotations

import json
from types import SimpleNamespace

import limeops.wiring as wiring


def _completed(stdout=""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_container_list_uses_bounded_docker_cli_without_python_sdk(monkeypatch):
    calls = []
    inspect_data = [
        {
            "Name": "/jellyfin",
            "Config": {
                "Image": "linuxserver/jellyfin:latest",
                "Labels": {"com.docker.compose.project": "media"},
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
        }
    ]

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv == ["docker", "container", "ls", "--all", "--quiet", "--no-trunc"]:
            return _completed("container-id\n")
        return _completed(json.dumps(inspect_data))

    monkeypatch.setattr(wiring.subprocess, "run", run)

    assert wiring._list_containers() == [
        {
            "name": "jellyfin",
            "status": "running",
            "image": "linuxserver/jellyfin:latest",
            "health": "healthy",
            "stack": "media",
            "restart_policy": "unless-stopped",
        }
    ]
    assert calls[1][0] == ["docker", "container", "inspect", "--", "container-id"]
    assert all(call[1]["timeout"] == 15 for call in calls)
    assert all(call[1]["shell"] is False for call in calls)


def test_container_status_and_logs_end_options_before_resource_name(monkeypatch):
    calls = []
    inspect_data = [{"Name": "/--help", "Config": {}, "State": {}, "HostConfig": {}}]

    def run(argv, **kwargs):
        calls.append(argv)
        if "inspect" in argv:
            return _completed(json.dumps(inspect_data))
        return _completed("bounded logs")

    monkeypatch.setattr(wiring.subprocess, "run", run)

    assert wiring._container_status("--help")["name"] == "--help"
    assert wiring._container_logs("--help", 20) == "bounded logs"
    assert calls == [
        ["docker", "container", "inspect", "--", "--help"],
        ["docker", "container", "logs", "--tail", "20", "--", "--help"],
    ]


def test_action_container_status_adds_private_fingerprint_fields(monkeypatch):
    inspect_data = [{
        "Id": "container-id",
        "Image": "sha256:image-id",
        "Name": "/jellyfin",
        "Config": {"Image": "jellyfin:latest"},
        "State": {"Status": "running", "StartedAt": "2026-07-21T10:00:00Z"},
        "HostConfig": {},
    }]
    monkeypatch.setattr(
        wiring.subprocess,
        "run",
        lambda argv, **kwargs: _completed(json.dumps(inspect_data)),
    )
    status = wiring._container_action_status("jellyfin")
    assert status["id"] == "container-id"
    assert status["image_id"] == "sha256:image-id"
    assert status["started_at"] == "2026-07-21T10:00:00Z"
    assert "id" not in wiring._container_summary(inspect_data[0])


def test_stack_inspect_uses_compose_json_and_never_returns_secret_values(monkeypatch):
    calls = []
    details = {
        "name": "media",
        "path": "/opt/stacks/media",
        "compose_file": "compose.yaml",
        "compose_content": "secret source",
        "has_env": True,
        "env_content": "TOKEN=secret",
        "status": {"status": "running", "containers": []},
    }
    compose = {
        "services": {
            "jellyfin": {
                "image": "jellyfin:latest",
                "environment": {"TOKEN": "secret"},
            }
        }
    }

    class StackReads:
        @staticmethod
        def stack_details(name):
            assert name == "media"
            return details

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return _completed(json.dumps(compose))

    monkeypatch.setattr(wiring, "_stack_reads", lambda: StackReads())
    monkeypatch.setattr(wiring.subprocess, "run", run)

    result = wiring._stack_inspect("media")

    assert result == {
        "name": "media",
        "compose_file": "compose.yaml",
        "has_env": True,
        "status": {"status": "running", "containers": []},
        "services": [
            {
                "name": "jellyfin",
                "image": "jellyfin:latest",
                "ports": [],
                "restart": "",
                "depends_on": [],
                "environment_keys": ["TOKEN"],
            }
        ],
    }
    assert "secret" not in json.dumps(result)
    assert calls[0][0] == [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "config",
        "--format",
        "json",
    ]
    assert calls[0][1]["cwd"] == "/opt/stacks/media"
