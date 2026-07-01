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


class StackMutationConflictError(RuntimeError):
    pass


class StackForceConfirmationError(ValueError):
    pass


class StackDeleteConflictError(StackMutationConflictError):
    def __init__(self, detail: str, down_result: dict | None):
        super().__init__(f"Cannot delete stack: {detail}")
        self.down_result = down_result


class StackMutationService:
    def __init__(
        self,
        *,
        stacks_path_provider,
        backup_path_provider,
        now_provider,
        lock_provider,
        atomic_writer,
        backup_writer,
        compose_validator,
        directory_maker,
        directory_remover,
        compose_runner,
    ):
        self._stacks_path_provider = stacks_path_provider
        self._backup_path_provider = backup_path_provider
        self._now_provider = now_provider
        self._lock_provider = lock_provider
        self._atomic_writer = atomic_writer
        self._backup_writer = backup_writer
        self._compose_validator = compose_validator
        self._directory_maker = directory_maker
        self._directory_remover = directory_remover
        self._compose_runner = compose_runner

    def create(self, name: str, compose_content: str, env_content: str) -> dict:
        if not compose_content:
            compose_content = self._default_compose(name)
        else:
            validation_error = self._compose_validator(compose_content)
            if validation_error:
                raise StackComposeValidationError(
                    f"Compose YAML invalid: {validation_error}"
                )

        stack_dir = os.path.join(self._stacks_path_provider(), name)
        with self._lock_provider(name):
            if os.path.exists(stack_dir):
                raise StackMutationConflictError("Stack already exists")
            try:
                self._directory_maker(stack_dir)
                self._atomic_writer(
                    os.path.join(stack_dir, "compose.yaml"),
                    compose_content,
                )
                if env_content:
                    self._atomic_writer(
                        os.path.join(stack_dir, ".env"),
                        env_content,
                        mode=0o600,
                    )
            except Exception as exc:
                if os.path.exists(stack_dir):
                    self._directory_remover(stack_dir, ignore_errors=True)
                raise StackMutationError(str(exc)) from exc
        return {"status": "created", "name": name, "path": stack_dir}

    def delete(
        self,
        name: str,
        *,
        force: bool = False,
        confirm_name: str | None = None,
    ) -> dict:
        if force and confirm_name != name:
            raise StackForceConfirmationError(
                "Force delete requires exact stack name confirmation"
            )

        stack_dir = os.path.join(self._stacks_path_provider(), name)
        with self._lock_provider(name):
            if not os.path.exists(stack_dir):
                raise StackMutationNotFoundError("Stack not found")

            down_result, down_error = self._compose_runner(name, "down")
            down_succeeded = bool(
                not down_error and down_result and down_result.get("success")
            )
            if not down_succeeded and not force:
                detail = (
                    down_error
                    or (down_result or {}).get("stderr")
                    or "Compose down failed"
                )
                raise StackDeleteConflictError(detail, down_result)

            try:
                self._backup_writer(name)
                self._directory_remover(stack_dir)
            except Exception as exc:
                raise StackMutationError(str(exc)) from exc

        return {
            "status": "deleted",
            "name": name,
            "forced": force and not down_succeeded,
        }

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

    def create_backup(self, name: str) -> str | None:
        with self._lock_provider(name):
            backup_root = self._backup_path_provider()
            os.makedirs(backup_root, exist_ok=True)
            stack_dir = os.path.join(self._stacks_path_provider(), name)
            compose_file = find_compose_file(stack_dir)
            if not compose_file:
                return None

            backup_dir = os.path.join(backup_root, name)
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = self._now_provider().strftime("%Y%m%d%H%M%S")
            backup_file = os.path.join(backup_dir, f"compose-{timestamp}.yaml")
            with open(compose_file) as handle:
                self._atomic_writer(backup_file, handle.read())

            backups = sorted(
                filename
                for filename in os.listdir(backup_dir)
                if filename.startswith("compose-")
            )
            for old_backup in backups[:-10]:
                os.remove(os.path.join(backup_dir, old_backup))
            return backup_file

    def restore(self, name: str, backup_name: str) -> dict:
        backup_path = os.path.join(self._backup_path_provider(), name, backup_name)
        if not os.path.exists(backup_path):
            raise StackMutationNotFoundError("Backup not found")

        with self._lock_provider(name):
            stack_dir = os.path.join(self._stacks_path_provider(), name)
            compose_file = find_compose_file(stack_dir)
            if not compose_file:
                raise StackMutationNotFoundError("Stack not found")
            try:
                with open(backup_path) as handle:
                    content = handle.read()
                validation_error = self._compose_validator(content)
                if validation_error:
                    raise StackComposeValidationError(
                        f"Compose YAML invalid: {validation_error}"
                    )
                self._backup_writer(name)
                self._atomic_writer(compose_file, content)
            except StackComposeValidationError:
                raise
            except Exception as exc:
                raise StackMutationError(str(exc)) from exc
        return {"status": "restored", "backup": backup_name}

    @staticmethod
    def _default_compose(name: str) -> str:
        return f"""# {name} stack
services:
  # Add your services here
  # example:
  #   image: nginx:latest
  #   ports:
  #     - "8080:80"
"""
