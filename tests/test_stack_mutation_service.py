from contextlib import contextmanager
from datetime import datetime
import os
import shutil

import pytest

from stack_mutation_service import (
    StackComposeValidationError,
    StackDeleteConflictError,
    StackForceConfirmationError,
    StackMutationConflictError,
    StackMutationError,
    StackMutationNotFoundError,
    StackMutationService,
)


def make_service(
    stacks_path,
    *,
    events=None,
    validator=lambda _content: None,
    atomic_writer=None,
    backup_writer=None,
    compose_runner=None,
    directory_maker=None,
    directory_remover=None,
):
    events = events if events is not None else []

    @contextmanager
    def lock_provider(name):
        events.append(("lock-enter", name))
        try:
            yield
        finally:
            events.append(("lock-exit", name))

    def default_atomic_writer(path, content, **kwargs):
        events.append(("write", path, content, kwargs))

    def default_backup_writer(name):
        events.append(("backup", name))

    return StackMutationService(
        stacks_path_provider=lambda: str(stacks_path),
        backup_path_provider=lambda: str(stacks_path / ".backups"),
        now_provider=lambda: datetime(2026, 7, 1, 12, 34, 56),
        lock_provider=lock_provider,
        atomic_writer=atomic_writer or default_atomic_writer,
        backup_writer=backup_writer or default_backup_writer,
        compose_validator=validator,
        directory_maker=directory_maker or (lambda path: events.append(("mkdir", path))),
        directory_remover=directory_remover
        or (lambda path, **kwargs: events.append(("rmtree", path, kwargs))),
        compose_runner=compose_runner
        or (lambda name, command: ({"success": True}, None)),
    )


def write_stack(root):
    stack_dir = root / "alpha"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services: {}\n")
    return stack_dir


def test_create_validates_supplied_compose_before_lock(tmp_path):
    events = []
    service = make_service(
        tmp_path,
        events=events,
        validator=lambda _content: "invalid yaml",
    )

    with pytest.raises(StackComposeValidationError, match="invalid yaml"):
        service.create("alpha", "invalid", "")

    assert events == []


def test_create_writes_default_compose_and_private_env_under_lock(tmp_path):
    events = []
    service = make_service(tmp_path, events=events)

    result = service.create("alpha", "", "KEY=value\n")

    assert result == {
        "status": "created",
        "name": "alpha",
        "path": str(tmp_path / "alpha"),
    }
    assert events[0:2] == [
        ("lock-enter", "alpha"),
        ("mkdir", str(tmp_path / "alpha")),
    ]
    assert events[2][0:2] == ("write", str(tmp_path / "alpha" / "compose.yaml"))
    assert events[2][2].startswith("# alpha stack\nservices:")
    assert events[3] == (
        "write",
        str(tmp_path / "alpha" / ".env"),
        "KEY=value\n",
        {"mode": 0o600},
    )
    assert events[4] == ("lock-exit", "alpha")


def test_create_rejects_existing_stack_inside_lock(tmp_path):
    write_stack(tmp_path)
    events = []
    service = make_service(tmp_path, events=events)

    with pytest.raises(StackMutationConflictError, match="already exists"):
        service.create("alpha", "services: {}\n", "")

    assert events == [("lock-enter", "alpha"), ("lock-exit", "alpha")]


def test_create_removes_partial_directory_after_write_failure(tmp_path):
    stack_dir = tmp_path / "alpha"

    def make_directory(path):
        os.makedirs(path)

    def fail_write(*_args, **_kwargs):
        raise OSError("write failed")

    service = make_service(
        tmp_path,
        atomic_writer=fail_write,
        directory_maker=make_directory,
        directory_remover=lambda path, **_kwargs: shutil.rmtree(path),
    )

    with pytest.raises(StackMutationError, match="write failed"):
        service.create("alpha", "services: {}\n", "")

    assert not stack_dir.exists()


def test_delete_runs_down_backs_up_and_removes_inside_lock(tmp_path):
    stack_dir = write_stack(tmp_path)
    events = []

    def compose_runner(name, command):
        events.append(("compose", name, command))
        return {"success": True, "stderr": ""}, None

    service = make_service(tmp_path, events=events, compose_runner=compose_runner)

    assert service.delete("alpha") == {
        "status": "deleted",
        "name": "alpha",
        "forced": False,
    }
    assert events == [
        ("lock-enter", "alpha"),
        ("compose", "alpha", "down"),
        ("backup", "alpha"),
        ("rmtree", str(stack_dir), {}),
        ("lock-exit", "alpha"),
    ]


def test_delete_preserves_stack_when_compose_down_fails(tmp_path):
    write_stack(tmp_path)
    events = []
    down_result = {"success": False, "stderr": "network is still in use"}
    service = make_service(
        tmp_path,
        events=events,
        compose_runner=lambda _name, _command: (down_result, None),
    )

    with pytest.raises(StackDeleteConflictError, match="network is still in use") as error:
        service.delete("alpha")

    assert error.value.down_result is down_result
    assert not any(event[0] in {"backup", "rmtree"} for event in events)


def test_force_delete_requires_exact_confirmation_before_lock(tmp_path):
    events = []
    service = make_service(tmp_path, events=events)

    with pytest.raises(StackForceConfirmationError, match="exact stack name"):
        service.delete("alpha", force=True, confirm_name="wrong")

    assert events == []


def test_force_delete_backs_up_after_compose_failure(tmp_path):
    write_stack(tmp_path)
    events = []
    service = make_service(
        tmp_path,
        events=events,
        compose_runner=lambda _name, _command: (
            {"success": False, "stderr": "down failed"},
            None,
        ),
    )

    result = service.delete("alpha", force=True, confirm_name="alpha")

    assert result["forced"] is True
    assert any(event[0] == "backup" for event in events)
    assert any(event[0] == "rmtree" for event in events)


def test_save_compose_validates_before_lock(tmp_path):
    events = []
    service = make_service(
        tmp_path,
        events=events,
        validator=lambda _content: "invalid yaml",
    )

    with pytest.raises(StackComposeValidationError, match="invalid yaml"):
        service.save_compose("alpha", "invalid")

    assert events == []


def test_validate_compose_never_locks_or_writes(tmp_path):
    events = []
    service = make_service(tmp_path, events=events)

    assert service.validate_compose("services: {}\n") == {"status": "valid"}
    assert events == []


def test_validate_compose_returns_same_validation_error_as_save(tmp_path):
    service = make_service(
        tmp_path,
        validator=lambda _content: "line 2: invalid service",
    )

    with pytest.raises(StackComposeValidationError, match="line 2"):
        service.validate_compose("invalid")


def test_save_compose_locks_backs_up_and_writes_in_order(tmp_path):
    stack_dir = write_stack(tmp_path)
    events = []
    service = make_service(tmp_path, events=events)

    assert service.save_compose("alpha", "services:\n  web: {}\n") == {
        "status": "saved"
    }
    assert events == [
        ("lock-enter", "alpha"),
        ("backup", "alpha"),
        (
            "write",
            str(stack_dir / "compose.yaml"),
            "services:\n  web: {}\n",
            {},
        ),
        ("lock-exit", "alpha"),
    ]


def test_save_compose_rejects_missing_stack_inside_lock(tmp_path):
    events = []
    service = make_service(tmp_path, events=events)

    with pytest.raises(StackMutationNotFoundError, match="Stack not found"):
        service.save_compose("alpha", "services: {}\n")

    assert events == [("lock-enter", "alpha"), ("lock-exit", "alpha")]


def test_save_compose_maps_backup_failure_without_writing(tmp_path):
    write_stack(tmp_path)
    writes = []
    service = make_service(
        tmp_path,
        atomic_writer=lambda *args, **kwargs: writes.append((args, kwargs)),
        backup_writer=lambda _name: (_ for _ in ()).throw(OSError("backup failed")),
    )

    with pytest.raises(StackMutationError, match="backup failed"):
        service.save_compose("alpha", "services: {}\n")

    assert writes == []


def test_save_env_locks_and_uses_private_mode(tmp_path):
    stack_dir = write_stack(tmp_path)
    events = []
    service = make_service(tmp_path, events=events)

    assert service.save_env("alpha", "KEY=value\n") == {"status": "saved"}
    assert events[1] == (
        "write",
        str(stack_dir / ".env"),
        "KEY=value\n",
        {"mode": 0o600},
    )


def test_save_env_rejects_missing_stack(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(StackMutationNotFoundError, match="Stack not found"):
        service.save_env("alpha", "KEY=value\n")


def test_create_backup_uses_timestamp_and_prunes_to_ten(tmp_path):
    write_stack(tmp_path)
    backup_dir = tmp_path / ".backups" / "alpha"
    backup_dir.mkdir(parents=True)
    for index in range(11):
        (backup_dir / f"compose-202601010000{index:02d}.yaml").write_text(str(index))

    def atomic_writer(path, content, **_kwargs):
        with open(path, "w") as handle:
            handle.write(content)

    service = make_service(tmp_path, atomic_writer=atomic_writer)

    backup_path = service.create_backup("alpha")

    assert backup_path.endswith("compose-20260701123456.yaml")
    assert open(backup_path).read() == "services: {}\n"
    assert len(list(backup_dir.iterdir())) == 10
    assert not (backup_dir / "compose-20260101000000.yaml").exists()
    assert not (backup_dir / "compose-20260101000001.yaml").exists()


def test_create_backup_returns_none_for_missing_stack(tmp_path):
    service = make_service(tmp_path)

    assert service.create_backup("alpha") is None


def test_restore_validates_then_backs_up_and_atomically_writes(tmp_path):
    stack_dir = write_stack(tmp_path)
    backup_dir = tmp_path / ".backups" / "alpha"
    backup_dir.mkdir(parents=True)
    backup_name = "compose-20240101010101.yaml"
    (backup_dir / backup_name).write_text("services:\n  restored: {}\n")
    events = []
    service = make_service(tmp_path, events=events)

    assert service.restore("alpha", backup_name) == {
        "status": "restored",
        "backup": backup_name,
    }
    assert events == [
        ("lock-enter", "alpha"),
        ("backup", "alpha"),
        (
            "write",
            str(stack_dir / "compose.yaml"),
            "services:\n  restored: {}\n",
            {},
        ),
        ("lock-exit", "alpha"),
    ]


def test_restore_rejects_missing_backup_before_lock(tmp_path):
    events = []
    service = make_service(tmp_path, events=events)

    with pytest.raises(StackMutationNotFoundError, match="Backup not found"):
        service.restore("alpha", "compose-20240101010101.yaml")

    assert events == []


def test_restore_rejects_invalid_yaml_before_pre_restore_backup(tmp_path):
    write_stack(tmp_path)
    backup_dir = tmp_path / ".backups" / "alpha"
    backup_dir.mkdir(parents=True)
    backup_name = "compose-20240101010101.yaml"
    (backup_dir / backup_name).write_text("invalid")
    events = []
    service = make_service(
        tmp_path,
        events=events,
        validator=lambda _content: "invalid yaml",
    )

    with pytest.raises(StackComposeValidationError, match="invalid yaml"):
        service.restore("alpha", backup_name)

    assert events == [("lock-enter", "alpha"), ("lock-exit", "alpha")]
