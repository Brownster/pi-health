"""Tool-free Claude Code adapter for the provider-neutral agent gateway.

Claude receives bounded context over stdin and can return only one final answer or one
typed LimeOps request. It never receives built-in tools, MCP servers, source access, or
host credential environment variables.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from agent_gateway.provider import (
    FinalAnswer,
    ProviderAuthError,
    ProviderContext,
    ProviderMalformedError,
    ProviderReply,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
)

MINIMUM_VERSION = (2, 1, 205)
DEFAULT_MAX_PROMPT_BYTES = 256 * 1024
DEFAULT_MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
_URL_RE = re.compile(r"https://[^\s<>\"']+")
_AUTH_FAILURE_MARKERS = (
    "not logged in",
    "oauth token expired",
    "oauth token revoked",
    "authentication_error",
    "please run /login",
    "please run claude auth login",
)
_AUTH_URL_HOSTS = frozenset({"claude.ai", "console.anthropic.com"})

TURN_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "text"],
            "properties": {
                "type": {"const": "final"},
                "text": {"type": "string", "maxLength": 32768},
            },
        },
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "operation", "params"],
            "properties": {
                "type": {"const": "tool"},
                "operation": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$",
                    "maxLength": 128,
                },
                "params": {"type": "object"},
            },
        },
    ]
}


class ProcessTimeoutError(Exception):
    """A child process exceeded its wall-clock deadline."""


class ProcessOutputLimitError(Exception):
    """A child process exceeded its combined stdout/stderr limit."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        input_text: str = "",
        env: dict[str, str] | None = None,
        cwd: Path | str | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult: ...


class BoundedProcessRunner:
    """Run one process with bounded pipes and whole-process-group cleanup."""

    def __init__(self, *, max_output_bytes: int = DEFAULT_MAX_PROCESS_OUTPUT_BYTES) -> None:
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._max_output_bytes = max_output_bytes

    def run(
        self,
        argv: list[str],
        *,
        input_text: str = "",
        env: dict[str, str] | None = None,
        cwd: Path | str | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        if timeout_seconds <= 0:
            raise ProcessTimeoutError()
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            start_new_session=True,
        )
        stdout = bytearray()
        stderr = bytearray()
        pending_input = memoryview(input_text.encode("utf-8"))
        selector = selectors.DefaultSelector()
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        for stream in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
        if pending_input:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + timeout_seconds
        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProcessTimeoutError()
                events = selector.select(min(remaining, 0.1))
                if not events and process.poll() is not None:
                    # EOF readiness follows process exit; keep draining registered pipes.
                    continue
                for key, _mask in events:
                    stream = key.fileobj
                    if key.data == "stdin":
                        try:
                            written = os.write(stream.fileno(), pending_input)
                            pending_input = pending_input[written:]
                        except BrokenPipeError:
                            pending_input = pending_input[len(pending_input) :]
                        if not pending_input:
                            selector.unregister(stream)
                            stream.close()
                        continue

                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    target = stdout if key.data == "stdout" else stderr
                    target.extend(chunk)
                    if len(stdout) + len(stderr) > self._max_output_bytes:
                        raise ProcessOutputLimitError()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeoutError()
            returncode = process.wait(timeout=remaining)
            return ProcessResult(
                returncode=returncode,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessTimeoutError() from exc
        except (ProcessTimeoutError, ProcessOutputLimitError):
            self._terminate(process)
            raise
        finally:
            selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=0.5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass


@dataclass(frozen=True)
class ClaudeCodeConfig:
    binary: str = "/usr/bin/claude"
    config_dir: Path = Path("/var/lib/lime-agent/.claude")
    work_dir: Path = Path("/var/lib/limeos/integrations/agents")
    max_prompt_bytes: int = DEFAULT_MAX_PROMPT_BYTES
    minimum_version: tuple[int, int, int] = MINIMUM_VERSION


@dataclass(frozen=True)
class ClaudeCodeHealth:
    installed: bool
    version: str | None
    meets_minimum: bool
    authenticated: bool
    auth_method: str | None


class ClaudeCodeProvider:
    def __init__(
        self,
        *,
        config: ClaudeCodeConfig | None = None,
        runner: ProcessRunner | None = None,
    ) -> None:
        self._config = config or ClaudeCodeConfig()
        self._runner = runner or BoundedProcessRunner()

    def invoke(self, context: ProviderContext, *, timeout_seconds: float) -> ProviderReply:
        prompt = self._build_prompt(context)
        try:
            result = self._runner.run(
                self._turn_command(),
                input_text=prompt,
                env=self._environment(),
                cwd=self._config.work_dir,
                timeout_seconds=timeout_seconds,
            )
        except ProcessTimeoutError as exc:
            raise ProviderTimeoutError("Claude Code timed out") from exc
        except ProcessOutputLimitError as exc:
            raise ProviderMalformedError("Claude Code output exceeded its limit") from exc
        except (FileNotFoundError, OSError) as exc:
            raise ProviderUnavailableError("Claude Code is unavailable") from exc
        if result.returncode != 0:
            combined = f"{result.stdout}\n{result.stderr}".lower()
            if any(marker in combined for marker in _AUTH_FAILURE_MARKERS):
                raise ProviderAuthError("Claude authentication is unavailable")
            raise ProviderUnavailableError("Claude Code invocation failed")
        return self._parse_reply(result.stdout)

    def health(self, *, timeout_seconds: float = 10) -> ClaudeCodeHealth:
        env = self._environment()
        try:
            version_result = self._runner.run(
                [self._config.binary, "--version"],
                env=env,
                cwd=self._config.work_dir,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, ProcessTimeoutError, ProcessOutputLimitError):
            return ClaudeCodeHealth(False, None, False, False, None)
        version_match = _VERSION_RE.search(version_result.stdout)
        if version_result.returncode != 0 or version_match is None:
            return ClaudeCodeHealth(False, None, False, False, None)
        version_tuple = tuple(int(part) for part in version_match.groups())
        version = ".".join(version_match.groups())
        authenticated = False
        auth_method = None
        try:
            auth_result = self._runner.run(
                [self._config.binary, "auth", "status"],
                env=env,
                cwd=self._config.work_dir,
                timeout_seconds=timeout_seconds,
            )
            raw = json.loads(auth_result.stdout) if auth_result.returncode == 0 else {}
            authenticated = bool(raw.get("loggedIn")) if isinstance(raw, dict) else False
            method = str(raw.get("authMethod", "")).lower() if isinstance(raw, dict) else ""
            if authenticated:
                auth_method = "subscription" if method in {"claude.ai", "oauth", "subscription"} else "other"
        except (OSError, ValueError, ProcessTimeoutError, ProcessOutputLimitError):
            pass
        return ClaudeCodeHealth(
            installed=True,
            version=version,
            meets_minimum=version_tuple >= self._config.minimum_version,
            authenticated=authenticated,
            auth_method=auth_method,
        )

    def auth_command(self) -> list[str]:
        """Fixed guided-login command used by the AA-006 operation stream."""
        return [self._config.binary, "auth", "login"]

    def environment(self) -> dict[str, str]:
        """Return the minimal non-secret environment for auth orchestration."""
        return self._environment().copy()

    def _turn_command(self) -> list[str]:
        return [
            self._config.binary,
            "--safe-mode",
            "--tools",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--permission-mode",
            "dontAsk",
            "--max-turns",
            "1",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(TURN_SCHEMA, separators=(",", ":")),
            "--no-session-persistence",
            "--no-chrome",
            "-p",
        ]

    def _environment(self) -> dict[str, str]:
        home = self._config.config_dir.parent
        return {
            "HOME": str(home),
            "USER": "lime-agent",
            "LOGNAME": "lime-agent",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "CLAUDE_CONFIG_DIR": str(self._config.config_dir),
            "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
            "TMPDIR": "/tmp",
        }

    def _build_prompt(self, context: ProviderContext) -> str:
        payload = {
            "instructions": (
                "Act as the LimeOS read-only assistant. Return exactly the structured "
                "final answer or one LimeOps request required by the supplied schema."
            ),
            "system_context": context.system_context,
            "messages": [
                {"role": message.role, "text": message.text} for message in context.messages
            ],
        }
        prompt = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        if len(prompt.encode("utf-8")) > self._config.max_prompt_bytes:
            raise ProviderMalformedError("Provider prompt exceeded its limit")
        return prompt

    @staticmethod
    def _parse_reply(stdout: str) -> ProviderReply:
        try:
            outer = json.loads(stdout)
        except (TypeError, ValueError) as exc:
            raise ProviderMalformedError("Claude Code returned invalid JSON") from exc
        if not isinstance(outer, dict) or "structured_output" not in outer:
            raise ProviderMalformedError("Claude Code omitted structured output")
        reply = outer["structured_output"]
        if not isinstance(reply, dict):
            raise ProviderMalformedError("Claude Code returned an invalid reply")
        reply_type = reply.get("type")
        if reply_type == "final" and set(reply) == {"type", "text"} and isinstance(reply["text"], str):
            return FinalAnswer(reply["text"])
        if (
            reply_type == "tool"
            and set(reply) == {"type", "operation", "params"}
            and isinstance(reply["operation"], str)
            and isinstance(reply["params"], dict)
        ):
            return ToolCall(reply["operation"], reply["params"])
        raise ProviderMalformedError("Claude Code returned a reply outside the contract")


def filter_auth_output(output: str) -> list[dict[str, str]]:
    """Convert raw login output to a tiny non-secret browser event allowlist."""
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in output.splitlines():
        lower = line.lower()
        for candidate in _URL_RE.findall(line):
            url = candidate.rstrip(".,);]")
            parsed = urlsplit(url)
            if parsed.hostname not in _AUTH_URL_HOSTS:
                continue
            key = ("authorization_url", url)
            if key not in seen:
                events.append({"type": "authorization_url", "url": url})
                seen.add(key)
        if "paste code" in lower and ("input_required", "code") not in seen:
            events.append(
                {"type": "input_required", "message": "Paste the authorization code to continue."}
            )
            seen.add(("input_required", "code"))
        if any(marker in lower for marker in ("authenticated successfully", "login successful")):
            if ("status", "complete") not in seen:
                events.append({"type": "status", "message": "Claude authentication completed."})
                seen.add(("status", "complete"))
    return events
