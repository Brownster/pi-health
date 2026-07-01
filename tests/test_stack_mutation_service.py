from contextlib import contextmanager
from datetime import datetime

import pytest

from stack_mutation_service import (
    StackComposeValidationError,
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
    )


def write_stack(root):
    stack_dir = root / "alpha"
    stack_dir.mkdir()
    (stack_dir / "compose.yaml").write_text("services: {}\n")
    return stack_dir


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
