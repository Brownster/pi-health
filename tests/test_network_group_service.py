from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from network_diagnostics_service import DockerUnavailableError
from network_group_service import NetworkGroupService


class FakeDocker:
    def __init__(self, containers=(), *, available=True, error=None):
        self.available = available
        self.containers = list(containers)
        self.error = error

    def list_containers(self, all=True):
        assert all is True
        if self.error:
            raise self.error
        return self.containers

    def get_container(self, container_id):
        if self.error:
            raise self.error
        return next(container for container in self.containers if container.name == container_id)


def make_container(
    name,
    container_id,
    *,
    status="running",
    network_mode="bridge",
    labels=None,
    health=None,
):
    state = {}
    if health:
        state["Health"] = {"Status": health}
    return SimpleNamespace(
        name=name,
        id=container_id,
        status=status,
        attrs={
            "HostConfig": {"NetworkMode": network_mode},
            "Config": {"Labels": labels or {}},
            "State": state,
        },
    )


def make_service(docker, *, command_runner=None, host_ip="1.1.1.1", provider_ip="9.9.9.9"):
    return NetworkGroupService(
        docker=docker,
        command_runner=command_runner or Mock(),
        host_ip_reader=lambda: host_ip,
        container_ip_reader=lambda _container: provider_ip,
    )


def test_list_groups_marks_orphans_and_degraded_provider():
    provider = make_container("vpn", "VPNID", health="healthy")
    member = make_container("sonarr", "S", network_mode="container:VPNID")
    orphan = make_container(
        "transmission",
        "T",
        status="created",
        network_mode="container:DEAD",
        labels={"com.docker.compose.depends_on": "vpn:service_started:true"},
    )
    service = make_service(FakeDocker([provider, member, orphan]))

    result = service.list_groups()

    group = result["groups"][0]
    assert group["provider"] == "vpn"
    assert group["status"] == "degraded"
    assert group["orphaned_members"] == ["transmission"]
    assert result["orphans"][0]["name"] == "transmission"


def test_list_groups_detects_matching_public_ip():
    provider = make_container("vpn", "VPNID")
    member = make_container("sonarr", "S", network_mode="container:VPNID")
    service = make_service(
        FakeDocker([provider, member]), host_ip="9.9.9.9", provider_ip="9.9.9.9"
    )

    group = service.list_groups(probe=True)["groups"][0]

    assert group["vpn_leak"] is True
    assert group["host_public_ip"] == "9.9.9.9"
    assert group["provider_public_ip"] == "9.9.9.9"


def test_list_groups_maps_unavailable_and_list_failure():
    assert make_service(FakeDocker(available=False)).list_groups() == {
        "docker_available": False,
        "groups": [],
        "orphans": [],
    }
    result = make_service(FakeDocker(error=RuntimeError("daemon failed"))).list_groups()
    assert result["docker_available"] is True
    assert result["error"] == "daemon failed"


def test_recreate_requires_compose_metadata():
    provider = make_container("vpn", "VPNID")
    service = make_service(FakeDocker([provider]))

    result = service.recreate("vpn")

    assert "not managed by docker compose" in result["error"]


def test_recreate_builds_provider_first_compose_command():
    provider = make_container(
        "vpn",
        "VPNID",
        labels={
            "com.docker.compose.project.config_files": "/stacks/base.yml,/stacks/vpn.yml",
            "com.docker.compose.project.working_dir": "/stacks",
            "com.docker.compose.service": "vpn-service",
        },
    )
    member = make_container(
        "sonarr",
        "S",
        network_mode="container:VPNID",
        labels={"com.docker.compose.service": "sonarr-service"},
    )
    command_runner = Mock(
        return_value=SimpleNamespace(returncode=0, stdout="done", stderr="")
    )
    service = make_service(
        FakeDocker([provider, member]), command_runner=command_runner
    )

    result = service.recreate("vpn")

    assert result["status"] == "recreated"
    assert result["services"] == ["vpn-service", "sonarr-service"]
    command = command_runner.call_args.args[0]
    assert command == [
        "docker",
        "compose",
        "-f",
        "/stacks/base.yml",
        "-f",
        "/stacks/vpn.yml",
        "--project-directory",
        "/stacks",
        "up",
        "-d",
        "vpn-service",
        "sonarr-service",
    ]


def test_recreate_classifies_unavailable_docker():
    service = make_service(FakeDocker(available=False))

    with pytest.raises(DockerUnavailableError, match="Docker is not available"):
        service.recreate("vpn")
