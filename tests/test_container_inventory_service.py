from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from container_inventory_service import (
    ContainerInspectNotFoundError,
    ContainerInspectUnavailableError,
    ContainerInventoryService,
)


class FakeDocker:
    def __init__(self, containers=(), *, available=True, error=None):
        self.available = available
        self._containers = list(containers)
        self._error = error

    def list_containers(self, all=True):
        assert all is True
        if self._error is not None:
            raise self._error
        return self._containers

    def get_container(self, container_id):
        for container in self._containers:
            if container.name == container_id or container.id == container_id:
                return container
        raise KeyError(container_id)


def make_container(
    *,
    container_id="container-id-123456",
    name="media",
    status="running",
    network_mode="bridge",
    exit_code=None,
):
    state = {"ExitCode": exit_code}
    return SimpleNamespace(
        id=container_id,
        name=name,
        status=status,
        image=SimpleNamespace(tags=["example:latest"]),
        attrs={
            "Config": {"Labels": {"limeos.web.scheme": "https"}, "ExposedPorts": {}},
            "HostConfig": {"NetworkMode": network_mode},
            "NetworkSettings": {"Ports": {}},
            "State": state,
        },
    )


def test_inventory_composes_metadata_and_injected_state():
    container = make_container()
    stats_calls = []
    service = ContainerInventoryService(
        docker=FakeDocker([container]),
        stats_reader=lambda container_id: stats_calls.append(container_id)
        or {
            "cpu_percent": 4.2,
            "memory": {"percent": 10.0, "used": 100, "limit": 1000},
            "network": {"rx": 20, "tx": 30},
        },
        update_reader=lambda container_id: container_id == "container-id",
    )

    result = service.list_containers()

    assert stats_calls == [container.id]
    assert result == [
        {
            "id": "container-id",
            "name": "media",
            "status": "running",
            "image": "example:latest",
            "stack": None,
            "update_available": True,
            "ports": [],
            "health": None,
            "restart_policy": "no",
            "exit_code": None,
            "network": {
                "mode": "bridge",
                "role": "standalone",
                "provider": None,
                "status": "ok",
            },
            "cpu_percent": 4.2,
            "memory_percent": 10.0,
            "memory_used": 100,
            "memory_limit": 1000,
            "net_rx": 20,
            "net_tx": 30,
            "web_url": None,
            "web_scheme": "https",
        }
    ]


def test_inventory_skips_stats_when_not_requested():
    def unexpected_stats(_container_id):
        raise AssertionError("stats reader must not run")

    service = ContainerInventoryService(
        docker=FakeDocker([make_container()]),
        stats_reader=unexpected_stats,
        update_reader=lambda _container_id: False,
    )

    result = service.list_containers(include_stats=False)

    assert result[0]["cpu_percent"] is None


def test_inventory_exposes_restart_policy_name():
    container = make_container()
    container.attrs["HostConfig"]["RestartPolicy"] = {"Name": "unless-stopped"}
    service = ContainerInventoryService(
        docker=FakeDocker([container]),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    assert service.list_containers(include_stats=False)[0]["restart_policy"] == "unless-stopped"


def test_inventory_reports_docker_unavailable_without_listing():
    service = ContainerInventoryService(
        docker=FakeDocker(available=False, error=AssertionError("must not list")),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    assert service.list_containers() == [
        {
            "id": "docker-not-available",
            "name": "Docker Not Available",
            "status": "unavailable",
            "image": "N/A",
            "ports": [],
        }
    ]


def test_inventory_maps_docker_list_failure():
    service = ContainerInventoryService(
        docker=FakeDocker(error=RuntimeError("daemon unavailable")),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    result = service.list_containers()

    assert result[0]["id"] == "error-listing"
    assert result[0]["image"] == "daemon unavailable"


def test_inventory_includes_compose_project_label():
    container = make_container()
    container.attrs["Config"]["Labels"]["com.docker.compose.project"] = "media"
    service = ContainerInventoryService(
        docker=FakeDocker([container]),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    assert service.list_containers(include_stats=False)[0]["stack"] == "media"


def test_inspect_hides_env_values_and_composes_runtime_details():
    container = make_container()
    container.image.id = "sha256:image"
    container.image.attrs = {"RepoDigests": ["example@sha256:digest"]}
    container.attrs.update(
        {
            "Created": "2026-07-01T10:00:00Z",
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": "/mnt/media",
                    "Destination": "/media",
                    "Mode": "ro",
                    "RW": False,
                }
            ],
        }
    )
    container.attrs["Config"].update(
        {
            "Image": "example:latest",
            "Cmd": ["serve", "--port", "80"],
            "Env": ["TOKEN=secret", "MODE=prod"],
        }
    )
    container.attrs["HostConfig"]["RestartPolicy"] = {"Name": "unless-stopped"}
    container.attrs["State"].update(
        {"Running": True, "StartedAt": "2026-07-01T11:00:00Z"}
    )
    container.attrs["NetworkSettings"]["Networks"] = {
        "frontend": {"IPAddress": "172.20.0.2", "Aliases": ["media"]}
    }
    service = ContainerInventoryService(
        docker=FakeDocker([container]),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
        now_provider=lambda: datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )

    result = service.inspect(container.id)

    assert result["uptime_seconds"] == 3600
    assert result["mounts"][0]["rw"] is False
    assert result["networks"][0]["name"] == "frontend"
    assert result["environment"] == [{"key": "TOKEN"}, {"key": "MODE"}]


def test_inspect_returns_env_values_only_on_explicit_opt_in():
    container = make_container()
    container.attrs["Config"]["Env"] = ["TOKEN=secret", "EMPTY"]
    service = ContainerInventoryService(
        docker=FakeDocker([container]),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    assert service.inspect(container.id, include_env_values=True)["environment"] == [
        {"key": "TOKEN", "value": "secret"},
        {"key": "EMPTY", "value": ""},
    ]


def test_inspect_degrades_when_image_removed():
    # A container whose image was removed (`docker rmi` while stopped): resolving
    # container.image raises. inspect() must degrade, not 500.
    class _RemovedImageContainer:
        id = "removed-image-1"
        name = "orphan"
        status = "exited"
        attrs = {
            "Config": {"Image": "example:latest", "Env": [], "Labels": {}},
            "HostConfig": {},
            "State": {},
            "Mounts": [],
        }

        @property
        def image(self):
            raise RuntimeError("404 Client Error: image not found")

    service = ContainerInventoryService(
        docker=FakeDocker([_RemovedImageContainer()]),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )

    result = service.inspect("removed-image-1")
    assert result["image"] == "example:latest"  # fell back to the attrs reference
    assert result["image_tags"] == []
    assert result["image_id"] is None


def test_inspect_classifies_unavailable_and_missing_container():
    unavailable = ContainerInventoryService(
        docker=FakeDocker(available=False),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )
    with pytest.raises(ContainerInspectUnavailableError):
        unavailable.inspect("missing")

    missing = ContainerInventoryService(
        docker=FakeDocker(),
        stats_reader=lambda _container_id: None,
        update_reader=lambda _container_id: False,
    )
    with pytest.raises(ContainerInspectNotFoundError):
        missing.inspect("missing")
