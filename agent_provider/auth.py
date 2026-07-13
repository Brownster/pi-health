"""Short-lived guided Claude login process for the privileged helper.

Raw provider output, authorization URLs, and submitted codes remain in memory only. The
manager exposes a small allowlisted event stream and removes authorization URLs as soon
as the operation reaches a terminal state.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from agent_provider.claude import filter_auth_output

MAX_AUTH_OUTPUT_BYTES = 64 * 1024
MAX_AUTH_EVENTS = 32


class AuthBusyError(Exception):
    pass


class AuthNotFoundError(Exception):
    pass


class AuthInputError(Exception):
    pass


class GuidedAuthManager:
    """Own at most one interactive login child and its bounded public events."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path | str,
        env: dict[str, str] | None = None,
        credential_path: Path | str | None = None,
        timeout_seconds: float = 600,
        popen_factory=subprocess.Popen,
        id_factory=lambda: uuid.uuid4().hex,
    ) -> None:
        self._command = list(command)
        self._cwd = str(cwd)
        self._env = env
        self._credential_path = Path(credential_path) if credential_path else None
        self._timeout_seconds = timeout_seconds
        self._popen_factory = popen_factory
        self._id_factory = id_factory
        self._lock = threading.Lock()
        self._operation_id: str | None = None
        self._process = None
        self._state = "idle"
        self._events: list[tuple[int, dict[str, str]]] = []
        self._sequence = 0
        self._output_bytes = 0
        self._timer: threading.Timer | None = None

    def start(self) -> str:
        with self._lock:
            if self._state == "running":
                raise AuthBusyError()
            process = self._popen_factory(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self._cwd,
                env=self._env,
                start_new_session=True,
            )
            self._operation_id = self._id_factory()
            self._process = process
            self._state = "running"
            self._events = []
            self._sequence = 0
            self._output_bytes = 0
            operation_id = self._operation_id
            self._timer = threading.Timer(
                self._timeout_seconds, self._expire, args=(operation_id,)
            )
            self._timer.daemon = True
            self._timer.start()
            thread = threading.Thread(
                target=self._read_process,
                args=(operation_id, process),
                name="claude-auth-output",
                daemon=True,
            )
            thread.start()
            return operation_id

    def status(self, operation_id: str, *, cursor: int = 0) -> dict:
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
            raise AuthInputError()
        with self._lock:
            self._require_operation(operation_id)
            return {
                "operation_id": operation_id,
                "state": self._state,
                "cursor": self._sequence,
                "events": [event.copy() for seq, event in self._events if seq > cursor],
            }

    def submit(self, operation_id: str, code: str) -> None:
        if (
            not isinstance(code, str)
            or not 1 <= len(code) <= 4096
            or any(character in code for character in ("\x00", "\n", "\r"))
        ):
            raise AuthInputError()
        with self._lock:
            self._require_operation(operation_id)
            if self._state != "running" or self._process is None or self._process.stdin is None:
                raise AuthInputError()
            try:
                self._process.stdin.write((code + "\n").encode("utf-8"))
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise AuthInputError() from exc

    def cancel(self, operation_id: str) -> None:
        with self._lock:
            self._require_operation(operation_id)
            process = self._process
            if self._state != "running" or process is None:
                return
            self._state = "cancelled"
            self._remove_authorization_urls()
        self._terminate(process)

    def current_state(self) -> str:
        with self._lock:
            return self._state

    def _read_process(self, operation_id: str, process) -> None:
        assert process.stdout is not None
        pending = bytearray()
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                with self._lock:
                    if operation_id != self._operation_id or self._state != "running":
                        break
                    self._output_bytes += len(chunk)
                    if self._output_bytes > MAX_AUTH_OUTPUT_BYTES:
                        self._state = "failed"
                        self._append({"type": "status", "message": "Claude authentication failed."})
                        self._remove_authorization_urls()
                        over_limit = True
                    else:
                        over_limit = False
                        pending.extend(chunk)
                        boundary = max(pending.rfind(b"\n"), pending.rfind(b"\r"))
                        if boundary >= 0:
                            complete = bytes(pending[: boundary + 1])
                            del pending[: boundary + 1]
                            self._append_filtered(complete)
                        # Claude's input prompt is intentionally not newline-terminated.
                        partial = pending.decode("utf-8", errors="replace")
                        for event in filter_auth_output(partial):
                            if event.get("type") == "input_required":
                                self._append(event)
                if over_limit:
                    self._terminate(process)
                    break
            with self._lock:
                if operation_id == self._operation_id and self._state == "running" and pending:
                    self._append_filtered(bytes(pending))
            returncode = process.wait()
            with self._lock:
                if operation_id != self._operation_id or self._state != "running":
                    return
                self._state = "complete" if returncode == 0 else "failed"
                self._remove_authorization_urls()
                message = (
                    "Claude authentication completed."
                    if returncode == 0
                    else "Claude authentication failed."
                )
                if not any(event.get("message") == message for _seq, event in self._events):
                    self._append({"type": "status", "message": message})
                if returncode == 0 and self._credential_path and self._credential_path.is_file():
                    os.chmod(self._credential_path, 0o600)
        finally:
            with self._lock:
                if operation_id == self._operation_id and self._timer:
                    self._timer.cancel()

    def _append_filtered(self, output: bytes) -> None:
        for event in filter_auth_output(output.decode("utf-8", errors="replace")):
            self._append(event)

    def _expire(self, operation_id: str) -> None:
        with self._lock:
            if operation_id != self._operation_id or self._state != "running":
                return
            process = self._process
            self._state = "timeout"
            self._remove_authorization_urls()
            self._append({"type": "status", "message": "Claude authentication timed out."})
        if process is not None:
            self._terminate(process)

    def _append(self, event: dict[str, str]) -> None:
        if any(existing == event for _seq, existing in self._events):
            return
        self._sequence += 1
        self._events.append((self._sequence, event.copy()))
        self._events = self._events[-MAX_AUTH_EVENTS:]

    def _remove_authorization_urls(self) -> None:
        self._events = [
            (sequence, event)
            for sequence, event in self._events
            if event.get("type") != "authorization_url"
        ]

    def _require_operation(self, operation_id: str) -> None:
        if not isinstance(operation_id, str) or operation_id != self._operation_id:
            raise AuthNotFoundError()

    @staticmethod
    def _terminate(process) -> None:
        process_group = process.pid
        try:
            os.killpg(process_group, signal.SIGTERM)
        except ProcessLookupError:
            return

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(process_group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
