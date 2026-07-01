from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stack_operations_service import (
    StackOperationError,
    StackOperationNotFoundError,
    StackOperationsService,
)


@pytest.fixture
def stack_dir(tmp_path):
    path = tmp_path / "alpha"
    path.mkdir()
    (path / "compose.yaml").write_text("services: {}\n")
    return path


def make_service(tmp_path, runner, lock_events=None, process_factory=None):
    lock_events = lock_events if lock_events is not None else []

    @contextmanager
    def lock(name):
        lock_events.append(("enter", name))
        try:
            yield
        finally:
            lock_events.append(("exit", name))

    return StackOperationsService(
        stacks_path_provider=lambda: str(tmp_path),
        lock_provider=lock,
        command_runner=runner,
        process_factory=process_factory or (lambda *_args, **_kwargs: None),
        service_name_validator=lambda name: (name.isidentifier(), "invalid name"),
    )


@pytest.mark.parametrize(
    ("detach", "expected_tail"),
    [(True, ["up", "-d", "--remove-orphans"]), (False, ["up", "--remove-orphans"])],
)
def test_run_up_uses_lock_and_preserves_arguments(
    tmp_path, stack_dir, detach, expected_tail
):
    calls = []
    lock_events = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    service = make_service(tmp_path, runner, lock_events)
    result, error = service.run("alpha", "up", detach=detach)

    assert error is None
    assert result == {"success": True, "stdout": "ok", "stderr": "", "returncode": 0}
    assert calls[0][0] == [
        "docker", "compose", "-f", "compose.yaml", *expected_tail
    ]
    assert calls[0][1] == {
        "cwd": str(stack_dir),
        "capture_output": True,
        "text": True,
        "timeout": 300,
    }
    assert lock_events == [("enter", "alpha"), ("exit", "alpha")]


def test_run_targets_only_stop_service(tmp_path, stack_dir):
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    service = make_service(tmp_path, runner)
    result, error = service.run("alpha", "stop", service="web")
    assert error is None
    assert result["success"] is True
    assert calls == [["docker", "compose", "-f", "compose.yaml", "stop", "web"]]

    result, error = service.run("alpha", "start", service="web")
    assert result is None
    assert error == "Service targeting is only supported for stop"


def test_run_maps_missing_unknown_and_runner_errors(tmp_path, stack_dir):
    service = make_service(tmp_path, lambda *_args, **_kwargs: None)
    assert service.run("missing", "up") == (None, "Stack not found")
    assert service.run("alpha", "unknown") == (None, "Unknown command: unknown")

    def fail(*_args, **_kwargs):
        raise RuntimeError("compose unavailable")

    assert make_service(tmp_path, fail).run("alpha", "up") == (
        None,
        "compose unavailable",
    )


def test_logs_preserves_output_and_does_not_take_lock(tmp_path, stack_dir):
    calls = []
    lock_events = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=1, stdout="out\n", stderr="err\n")

    service = make_service(tmp_path, runner, lock_events)
    result = service.logs("alpha", tail="20", service="web")

    assert result == {"logs": "out\nerr\n", "returncode": 1}
    assert calls[0][0] == [
        "docker", "compose", "-f", "compose.yaml", "logs", "--tail", "20", "web"
    ]
    assert calls[0][1]["cwd"] == str(stack_dir)
    assert calls[0][1]["timeout"] == 30
    assert lock_events == []


def test_logs_maps_missing_stack_and_runner_error(tmp_path, stack_dir):
    service = make_service(tmp_path, lambda *_args, **_kwargs: None)
    with pytest.raises(StackOperationNotFoundError, match="Stack not found"):
        service.logs("missing")

    def fail(*_args, **_kwargs):
        raise RuntimeError("compose unavailable")

    with pytest.raises(StackOperationError, match="compose unavailable"):
        make_service(tmp_path, fail).logs("alpha")


@pytest.mark.parametrize(
    ("command", "expected_tail"),
    [
        ("up", ["up", "-d", "--remove-orphans"]),
        ("down", ["down"]),
        ("pull", ["pull"]),
        ("restart", ["restart"]),
    ],
)
def test_stream_yields_neutral_events_under_lock(
    tmp_path, stack_dir, command, expected_tail
):
    lock_events = []
    calls = []
    process = SimpleNamespace(
        stdout=SimpleNamespace(readline=MagicMock(side_effect=["one\n", "two\n", ""])),
        wait=MagicMock(),
        returncode=0,
    )

    def process_factory(command_args, **kwargs):
        calls.append((command_args, kwargs))
        return process

    service = make_service(
        tmp_path,
        lambda *_args, **_kwargs: None,
        lock_events,
        process_factory,
    )

    assert list(service.stream("alpha", command)) == [
        {"line": "one"},
        {"line": "two"},
        {"done": True, "returncode": 0},
    ]
    assert calls[0][0] == [
        "docker", "compose", "-f", "compose.yaml", *expected_tail
    ]
    assert calls[0][1]["cwd"] == str(stack_dir)
    assert lock_events == [("enter", "alpha"), ("exit", "alpha")]
    process.wait.assert_called_once_with()


def test_stream_maps_preflight_and_process_failures(tmp_path, stack_dir):
    service = make_service(tmp_path, lambda *_args, **_kwargs: None)
    assert list(service.stream("missing", "up")) == [{"error": "Stack not found"}]
    assert list(service.stream("alpha", "unknown")) == [{"error": "Unknown command"}]

    def fail(*_args, **_kwargs):
        raise RuntimeError("process unavailable")

    service = make_service(
        tmp_path,
        lambda *_args, **_kwargs: None,
        process_factory=fail,
    )
    assert list(service.stream("alpha", "up")) == [
        {"error": "process unavailable"}
    ]
