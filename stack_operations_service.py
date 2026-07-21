"""Framework-neutral synchronous stack operations."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from stack_read_service import find_compose_file


class StackOperationNotFoundError(Exception):
    """Raised when a stack has no compose file."""


class StackOperationError(Exception):
    """Raised when a stack operation cannot be completed."""


def compose_up_args(detach: bool = True) -> list[str]:
    """Build project reconciliation arguments for compose up."""
    args = ["up"]
    if detach:
        args.append("-d")
    args.append("--remove-orphans")
    return args


class StackOperationsService:
    """Run synchronous compose commands with explicit infrastructure adapters."""

    def __init__(
        self,
        *,
        stacks_path_provider: Callable[[], str],
        lock_provider: Callable[[str], AbstractContextManager[Any]],
        command_runner: Callable[..., Any],
        process_factory: Callable[..., Any],
        service_name_validator: Callable[[str], tuple[bool, str | None]],
    ) -> None:
        self._stacks_path_provider = stacks_path_provider
        self._lock_provider = lock_provider
        self._command_runner = command_runner
        self._process_factory = process_factory
        self._service_name_validator = service_name_validator

    def has_stack(self, stack_name: str) -> bool:
        """Return whether the stack has one supported Compose file."""
        stack_dir = os.path.join(self._stacks_path_provider(), stack_name)
        return find_compose_file(stack_dir) is not None

    def run(
        self,
        stack_name: str,
        command: str,
        *,
        detach: bool = True,
        service: str | None = None,
        timeout_seconds: float = 300,
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Run a lifecycle command while holding the per-stack lock."""
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 1 <= timeout_seconds <= 300
        ):
            return None, "Invalid command timeout"
        with self._lock_provider(stack_name):
            stack_dir = os.path.join(self._stacks_path_provider(), stack_name)
            compose_file = find_compose_file(stack_dir)
            if not compose_file:
                return None, "Stack not found"

            cmd = ["docker", "compose", "-f", os.path.basename(compose_file)]
            if service:
                valid, error = self._service_name_validator(service)
                if not valid:
                    return None, f"Invalid service name: {error}"
                if command != "stop":
                    return None, "Service targeting is only supported for stop"

            command_args = self._command_args(command, detach)
            if command_args is None:
                return None, f"Unknown command: {command}"
            cmd.extend(command_args)
            if service:
                cmd.append(service)

            try:
                result = self._command_runner(
                    cmd,
                    cwd=stack_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                return None, "Command timed out"
            except Exception as exc:
                return None, str(exc)

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }, None

    def logs(
        self,
        stack_name: str,
        *,
        tail: str = "100",
        service: str = "",
    ) -> dict[str, Any]:
        """Read compose logs without taking the lifecycle mutation lock."""
        stack_dir = os.path.join(self._stacks_path_provider(), stack_name)
        compose_file = find_compose_file(stack_dir)
        if not compose_file:
            raise StackOperationNotFoundError("Stack not found")

        cmd = [
            "docker",
            "compose",
            "-f",
            os.path.basename(compose_file),
            "logs",
            "--tail",
            tail,
        ]
        if service:
            cmd.append(service)

        try:
            result = self._command_runner(
                cmd,
                cwd=stack_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise StackOperationError("Timeout getting logs") from exc
        except Exception as exc:
            raise StackOperationError(str(exc)) from exc

        return {
            "logs": result.stdout + result.stderr,
            "returncode": result.returncode,
        }

    def stream(self, stack_name: str, command: str):
        """Yield neutral output events for one streaming lifecycle command."""
        with self._lock_provider(stack_name):
            stack_dir = os.path.join(self._stacks_path_provider(), stack_name)
            compose_file = find_compose_file(stack_dir)
            if not compose_file:
                yield {"error": "Stack not found"}
                return

            command_args = self._stream_command_args(command)
            if command_args is None:
                yield {"error": "Unknown command"}
                return

            cmd = [
                "docker",
                "compose",
                "-f",
                os.path.basename(compose_file),
                *command_args,
            ]
            try:
                process = self._process_factory(
                    cmd,
                    cwd=stack_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                for line in iter(process.stdout.readline, ""):
                    if line:
                        yield {"line": line.rstrip()}
                process.wait()
                yield {"done": True, "returncode": process.returncode}
            except Exception as exc:
                yield {"error": str(exc)}

    @staticmethod
    def _command_args(command: str, detach: bool) -> list[str] | None:
        if command == "up":
            return compose_up_args(detach)
        if command in {"down", "restart", "pull", "stop", "start"}:
            return [command]
        return None

    @staticmethod
    def _stream_command_args(command: str) -> list[str] | None:
        if command == "up":
            return compose_up_args()
        if command in {"down", "pull", "restart"}:
            return [command]
        return None
