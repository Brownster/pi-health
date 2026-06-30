from types import SimpleNamespace

from container_inventory_service import ContainerInventoryService


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
        return next(container for container in self._containers if container.name == container_id)


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
            "update_available": True,
            "ports": [],
            "health": None,
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
