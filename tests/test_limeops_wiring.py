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
