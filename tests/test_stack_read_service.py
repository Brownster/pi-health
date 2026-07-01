import json
from types import SimpleNamespace
from unittest.mock import Mock

from stack_read_service import StackReadService


def make_service(stacks_path, command_runner=None):
    return StackReadService(
        stacks_path_provider=lambda: str(stacks_path),
        command_runner=command_runner or Mock(),
    )


def write_compose(root, name, filename="compose.yaml"):
    stack_dir = root / name
    stack_dir.mkdir()
    (stack_dir / filename).write_text("services: {}\n")
    return stack_dir


def test_list_stacks_sorts_and_reports_compose_conflicts(tmp_path):
    write_compose(tmp_path, "beta", "docker-compose.yml")
    alpha = write_compose(tmp_path, "alpha")
    (alpha / "compose.yml").write_text("services: {}\n")
    write_compose(tmp_path, ".hidden")
    service = make_service(tmp_path)

    stacks, error = service.list_stacks()

    assert error is None
    assert [stack["name"] for stack in stacks] == ["alpha", "beta"]
    assert stacks[0]["status"] == "conflict"
    assert stacks[0]["compose_files"] == ["compose.yaml", "compose.yml"]


def test_status_parses_json_array_and_json_lines(tmp_path):
    write_compose(tmp_path, "alpha")
    outputs = [
        json.dumps(
            [{"Name": "web", "Service": "web", "State": "running"}]
        ),
        "\n".join(
            [
                json.dumps({"Name": "web", "Service": "web", "State": "running"}),
                json.dumps({"Name": "db", "Service": "db", "State": "exited"}),
            ]
        ),
    ]
    command_runner = Mock(
        side_effect=[
            SimpleNamespace(returncode=0, stdout=output, stderr="")
            for output in outputs
        ]
    )
    service = make_service(tmp_path, command_runner)

    running, error = service.status("alpha")
    partial, second_error = service.status("alpha")

    assert error is None
    assert running["status"] == "running"
    assert running["container_count"] == 1
    assert second_error is None
    assert partial["status"] == "partial"
    assert partial["running_count"] == 1


def test_list_with_status_uses_one_docker_snapshot(tmp_path):
    alpha = write_compose(tmp_path, "alpha")
    beta = write_compose(tmp_path, "beta")
    stdout = "\n".join(
        [
            "\t".join(
                ["a", "alpha-web", "running", "Up", "", str(alpha), "compose.yaml", "web"]
            ),
            "\t".join(
                ["b", "beta-web", "exited", "Exited", "", str(beta), "", "web"]
            ),
        ]
    )
    command_runner = Mock(
        return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    )
    service = make_service(tmp_path, command_runner)

    stacks, error = service.list_with_status(include_status=True)

    assert error is None
    by_name = {stack["name"]: stack for stack in stacks}
    assert by_name["alpha"]["status"] == "running"
    assert by_name["beta"]["status"] == "stopped"
    command_runner.assert_called_once()


def test_list_with_status_marks_snapshot_failure_unknown(tmp_path):
    write_compose(tmp_path, "alpha")
    command_runner = Mock(
        return_value=SimpleNamespace(returncode=1, stdout="", stderr="Docker unavailable")
    )
    service = make_service(tmp_path, command_runner)

    stacks, error = service.list_with_status(include_status=True)

    assert error is None
    assert stacks[0]["status"] == "unknown"
    assert stacks[0]["status_error"] == "Docker unavailable"
