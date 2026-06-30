from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from network_diagnostics_service import (
    ContainerNotFoundError,
    DockerUnavailableError,
    NetworkDiagnosticsService,
)


class FakeDocker:
    def __init__(self, container=None, *, available=True, error=None):
        self.available = available
        self.container = container
        self.error = error

    def get_container(self, _container_id):
        if self.error:
            raise self.error
        return self.container


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return b"1.2.3.4"


def make_service(docker, *, command_runner=None, socket_connector=None, urlopen=None):
    return NetworkDiagnosticsService(
        docker=docker,
        command_runner=command_runner or Mock(),
        socket_connector=socket_connector or Mock(),
        urlopen=urlopen or (lambda *_args, **_kwargs: Response()),
    )


def test_host_test_composes_injected_probe_dependencies():
    command_runner = Mock(
        side_effect=[
            SimpleNamespace(returncode=0, stdout="ping ok", stderr=""),
            SimpleNamespace(returncode=0, stdout="192.168.1.2\n", stderr=""),
        ]
    )
    service = make_service(FakeDocker(), command_runner=command_runner)

    assert service.host_test() == {
        "ping_success": True,
        "ping_output": "ping ok",
        "local_ip": "192.168.1.2",
        "public_ip": "1.2.3.4",
        "probe_method": "ping",
    }


def test_host_test_uses_socket_when_ping_is_missing():
    command_runner = Mock(
        side_effect=[
            FileNotFoundError(),
            SimpleNamespace(returncode=0, stdout="192.168.1.2\n", stderr=""),
        ]
    )
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=None)
    socket_connector = Mock(return_value=connection)
    service = make_service(
        FakeDocker(),
        command_runner=command_runner,
        socket_connector=socket_connector,
    )

    result = service.host_test()

    assert result["ping_success"] is True
    assert result["probe_method"] == "socket"
    socket_connector.assert_called_once_with(("8.8.8.8", 53), timeout=5)


def test_container_test_reports_lookup_failure_as_payload():
    service = make_service(FakeDocker(error=RuntimeError("not found")))

    assert service.container_test("missing") == {"error": "not found"}


def test_container_test_rejects_unavailable_docker():
    service = make_service(FakeDocker(available=False))

    with pytest.raises(DockerUnavailableError, match="Docker is not available"):
        service.container_test("container-id")


def test_container_test_runs_probe_and_collects_addresses():
    container = Mock(id="container-id", name="media")
    container.exec_run.side_effect = [
        SimpleNamespace(exit_code=0, output=b"ping ok"),
        SimpleNamespace(exit_code=0, output=b"172.18.0.2"),
        SimpleNamespace(exit_code=0, output=b"9.9.9.9"),
    ]
    service = make_service(FakeDocker(container))

    result = service.container_test("container-id")

    assert result["ping_success"] is True
    assert result["local_ip"] == "172.18.0.2"
    assert result["public_ip"] == "9.9.9.9"


def test_health_returns_bounded_latest_output():
    container = Mock()
    container.attrs = {
        "State": {
            "Health": {
                "Status": "unhealthy",
                "FailingStreak": 2,
                "Log": [{"Output": "x" * 600}],
            }
        }
    }
    service = make_service(FakeDocker(container))

    result = service.health("container-id")

    assert result["status"] == "unhealthy"
    assert result["failing_streak"] == 2
    assert result["last_output"] == "x" * 500


def test_health_classifies_lookup_failure():
    service = make_service(FakeDocker(error=RuntimeError("not found")))

    with pytest.raises(ContainerNotFoundError, match="not found"):
        service.health("missing")
