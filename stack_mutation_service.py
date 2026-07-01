"""Framework-neutral stack Compose and environment mutations."""

from __future__ import annotations

import os

from stack_read_service import find_compose_file


class StackMutationNotFoundError(RuntimeError):
    pass


class StackMutationError(RuntimeError):
    pass


class StackComposeValidationError(ValueError):
    pass


class StackMutationService:
    def __init__(
        self,
        *,
        stacks_path_provider,
        lock_provider,
        atomic_writer,
        backup_writer,
        compose_validator,
    ):
        self._stacks_path_provider = stacks_path_provider
        self._lock_provider = lock_provider
        self._atomic_writer = atomic_writer
        self._backup_writer = backup_writer
        self._compose_validator = compose_validator

    def save_compose(self, name: str, content: str) -> dict:
        validation_error = self._compose_validator(content)
        if validation_error:
            raise StackComposeValidationError(
                f"Compose YAML invalid: {validation_error}"
            )

        stack_dir = os.path.join(self._stacks_path_provider(), name)
        with self._lock_provider(name):
            compose_file = find_compose_file(stack_dir)
            if not compose_file:
                raise StackMutationNotFoundError("Stack not found")
            try:
                self._backup_writer(name)
                self._atomic_writer(compose_file, content)
            except Exception as exc:
                raise StackMutationError(str(exc)) from exc
        return {"status": "saved"}

    def save_env(self, name: str, content: str) -> dict:
        stack_dir = os.path.join(self._stacks_path_provider(), name)
        with self._lock_provider(name):
            if not os.path.exists(stack_dir):
                raise StackMutationNotFoundError("Stack not found")
            try:
                self._atomic_writer(
                    os.path.join(stack_dir, ".env"),
                    content,
                    mode=0o600,
                )
            except Exception as exc:
                raise StackMutationError(str(exc)) from exc
        return {"status": "saved"}
