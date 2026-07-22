"""Framework-neutral stack adapters for the isolated action runtime."""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import threading
from contextlib import contextmanager

from stack_operations_service import StackOperationsService
from stack_read_service import StackReadService


STACKS_PATH = os.getenv("STACKS_PATH", "/opt/stacks")
BACKUP_DIR = os.getenv("STACK_BACKUP_DIR", os.path.join(STACKS_PATH, ".backups"))
STACK_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_stack_lock_state = threading.local()


def validate_stack_name(name: str) -> tuple[bool, str | None]:
    """Validate a stack or service name before passing it to Docker Compose."""
    if not name:
        return False, "Stack name is required"
    if not STACK_NAME_RE.fullmatch(name):
        return False, "Stack name contains unsupported characters"
    if ".." in name or name.startswith("."):
        return False, "Invalid stack name"
    if len(name) > 64:
        return False, "Stack name too long (max 64 characters)"
    return True, None


@contextmanager
def stack_lock(name: str):
    """Hold the same reentrant, inter-process lock used by dashboard mutations."""
    valid, error = validate_stack_name(name)
    if not valid:
        raise ValueError(error)
    lock_dir = os.path.join(STACKS_PATH, ".locks")
    os.makedirs(lock_dir, mode=0o2770, exist_ok=True)
    lock_path = os.path.abspath(os.path.join(lock_dir, f"{name}.lock"))

    current_pid = os.getpid()
    if getattr(_stack_lock_state, "pid", None) != current_pid:
        _stack_lock_state.pid = current_pid
        _stack_lock_state.held_locks = {}
    held_locks = getattr(_stack_lock_state, "held_locks", None)
    if held_locks is None:
        held_locks = {}
        _stack_lock_state.held_locks = held_locks
    held = held_locks.get(lock_path)
    if held:
        held["depth"] += 1
        try:
            yield
        finally:
            held["depth"] -= 1
        return

    lock_file = open(lock_path, "a+")
    try:
        os.chmod(lock_path, 0o660)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        held_locks[lock_path] = {"file": lock_file, "depth": 1}
        try:
            yield
        finally:
            held_locks.pop(lock_path, None)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def default_stack_read_service() -> StackReadService:
    return StackReadService(
        stacks_path_provider=lambda: STACKS_PATH,
        backup_path_provider=lambda: BACKUP_DIR,
        command_runner=lambda command, **kwargs: subprocess.run(command, **kwargs),
    )


def default_stack_operations_service() -> StackOperationsService:
    return StackOperationsService(
        stacks_path_provider=lambda: STACKS_PATH,
        lock_provider=lambda name: stack_lock(name),
        command_runner=lambda command, **kwargs: subprocess.run(command, **kwargs),
        process_factory=lambda command, **kwargs: subprocess.Popen(command, **kwargs),
        service_name_validator=validate_stack_name,
    )
