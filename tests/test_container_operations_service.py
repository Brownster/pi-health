from types import SimpleNamespace
from unittest.mock import Mock

from container_operations_service import ContainerOperationsService


class FakeDocker:
    def __init__(self, container=None, *, available=True, error=None, pulled_id="new-image"):
        self.available = available
        self.container = container
        self.error = error
        self.pulled_id = pulled_id
        self.get_calls = []
        self.pull_calls = []

    def get_container(self, container_id):
        self.get_calls.append(container_id)
        if self.error:
            raise self.error
        return self.container

    def pull_image(self, tag):
        self.pull_calls.append(tag)
        if self.error:
            raise self.error
        return SimpleNamespace(id=self.pulled_id)


def make_container(*, image_id="old-image", tags=None, image_ref="example:latest"):
    container = Mock()
    container.id = "container-id-123456"
    container.name = "media"
    container.attrs = {"Config": {"Image": image_ref}} if image_ref is not None else {"Config": {}}
    container.image = SimpleNamespace(
        id=image_id,
        tags=["example:latest"] if tags is None else tags,
    )
    return container


def make_service(docker, *, compose_runner=None, updates=None):
    updates = updates if updates is not None else []
    return ContainerOperationsService(
        docker=docker,
        compose_runner=compose_runner or Mock(),
        update_writer=lambda container_id, value: updates.append((container_id, value)),
    )


def test_control_dispatches_lifecycle_action():
    container = make_container()
    docker = FakeDocker(container)
    service = make_service(docker)

    assert service.control("container-id", "restart") == {
        "status": "Container restarted successfully"
    }
    container.restart.assert_called_once_with()
    assert docker.get_calls == ["container-id"]


def test_control_rejects_invalid_action_after_container_lookup():
    docker = FakeDocker(make_container())
    service = make_service(docker)

    assert service.control("container-id", "invalid") == {"error": "Invalid action"}
    assert docker.get_calls == ["container-id"]


def test_control_reports_docker_unavailable():
    service = make_service(FakeDocker(available=False))

    assert service.control("container-id", "start") == {
        "error": "Docker is not available"
    }


def test_check_update_pulls_tag_and_records_result():
    container = make_container()
    updates = []
    docker = FakeDocker(container, pulled_id="new-image")
    service = make_service(docker, updates=updates)

    assert service.check_update(container) == {"update_available": True}
    assert docker.pull_calls == ["example:latest"]
    assert updates == [("container-id", True)]


def test_update_pulls_recreates_and_clears_update_state():
    container = make_container()
    updates = []
    compose_runner = Mock()
    docker = FakeDocker(container)
    service = make_service(docker, compose_runner=compose_runner, updates=updates)

    assert service.update(container) == {"status": "Container updated"}
    compose_runner.assert_called_once_with(
        ["docker", "compose", "up", "-d", "media"],
        check=False,
    )
    assert updates == [("container-id", False)]


def test_update_rejects_image_without_any_reference():
    # No configured Config.Image and no tags -> nothing to pull.
    container = make_container(tags=[], image_ref=None)
    compose_runner = Mock()
    docker = FakeDocker(container)
    service = make_service(docker, compose_runner=compose_runner)

    assert service.update(container) == {"error": "Container image has no tag"}
    assert docker.pull_calls == []
    compose_runner.assert_not_called()


def test_update_uses_configured_ref_when_running_image_is_dangling():
    # After a check_update pull, the running image is dangling (tags == []); the
    # configured Config.Image reference must still drive the pull.
    container = make_container(tags=[], image_ref="example/app:latest")
    compose_runner = Mock()
    docker = FakeDocker(container)
    service = make_service(docker, compose_runner=compose_runner)

    assert service.update(container) == {"status": "Container updated"}
    assert docker.pull_calls == ["example/app:latest"]
    compose_runner.assert_called_once()


def test_logs_decodes_bytes_and_passes_tail():
    container = make_container()
    container.logs.return_value = b"hello\n"
    service = make_service(FakeDocker(container))

    assert service.logs("container-id", tail=50) == {
        "logs": "hello\n",
        "container": "media",
    }
    container.logs.assert_called_once_with(tail=50)


def test_logs_maps_lookup_failure():
    service = make_service(FakeDocker(error=RuntimeError("not found")))

    assert service.logs("missing") == {"error": "not found"}
