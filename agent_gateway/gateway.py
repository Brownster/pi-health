"""The agent gateway: serialized, bounded, audited turn orchestration (AA-003).

Owns the tool loop from the baseline provider contract: each provider invocation returns
either a final answer or exactly one typed `limeops` request; the gateway validates and
executes the request through the injected executor, appends the bounded result to the
conversation, and invokes the provider again — up to the round limit. Tool execution is
therefore confined to `limeops` reads regardless of what the provider asks for.

Failure contract: every failure maps to a typed `TurnError` from the frozen AA-005
contract (safe to post in-thread); a failed turn is recorded as failed and can never be
reported successful; the disable switch aborts immediately, including between rounds.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_gateway.conversation import ConversationStore
from agent_gateway.provider import (
    FinalAnswer,
    Message,
    Provider,
    ProviderAuthError,
    ProviderContext,
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
)
from agent_gateway.usage import UsageLedger
from agent_transport.gateway_contract import (
    MAX_TURN_OUTPUT_BYTES,
    TurnBusyError,
    TurnError,
    TurnLimitError,
    TurnRequest,
    TurnResult,
    TurnUnavailableError,
)

logger = logging.getLogger("limeos.agent.gateway")

_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

#: limeops executor: (operation, params, actor) -> version-1 response envelope.
LimeOpsExecutor = Callable[[str, dict, dict], dict]


@dataclass
class GatewayConfig:
    turn_timeout_seconds: float = 300
    tool_rounds_per_turn: int = 6
    invocations_per_day: int = 20
    max_tool_result_bytes: int = 16 * 1024
    # Defence in depth: the broker's policy is authoritative, but the gateway refuses to
    # forward operations outside this set at all.
    allowed_operations: tuple[str, ...] = (
        "context",
        "system.status",
        "container.list",
        "container.status",
        "container.logs",
        "stack.list",
        "stack.status",
        "stack.inspect",
        "service.status",
        "service.logs",
        "disk.health",
        "mount.status",
        "snapraid.status",
        "network.check",
    )


@dataclass
class _TurnTrace:
    rounds: int = 0
    tool_operations: list[str] = field(default_factory=list)


class AgentGateway:
    """Implements the frozen AA-005 `TurnHandler` contract."""

    def __init__(
        self,
        *,
        state_dir: Path | str,
        provider: Provider,
        limeops_executor: LimeOpsExecutor,
        config: GatewayConfig | None = None,
        context_provider: Callable[[], str] = lambda: "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._execute_limeops = limeops_executor
        self._config = config or GatewayConfig()
        self._context_provider = context_provider
        self._clock = clock
        self._conversations = ConversationStore(state_dir)
        self._usage = UsageLedger(state_dir)
        self._global_lock = threading.Lock()
        self._conversation_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._disabled = threading.Event()

    # -- controls ---------------------------------------------------------------
    def disable(self) -> None:
        """Immediate disable switch: new turns fail fast; running turns abort between rounds."""
        self._disabled.set()

    def enable(self) -> None:
        self._disabled.clear()

    def usage_totals(self) -> dict:
        return self._usage.totals()

    # -- TurnHandler ---------------------------------------------------------------
    def handle_turn(self, request: TurnRequest) -> TurnResult:
        if self._disabled.is_set():
            raise TurnUnavailableError()
        if not self._global_lock.acquire(blocking=False):
            raise TurnBusyError()
        try:
            conversation_lock = self._lock_for(request.conversation_id)
            if not conversation_lock.acquire(blocking=False):
                raise TurnBusyError()
            try:
                return self._run_turn(request)
            finally:
                conversation_lock.release()
        finally:
            self._global_lock.release()

    # -- turn execution -----------------------------------------------------------
    def _run_turn(self, request: TurnRequest) -> TurnResult:
        started = self._clock()
        correlation_id = uuid.uuid4().hex
        trace = _TurnTrace()
        outcome = "error"
        try:
            result = self._tool_loop(request, correlation_id, started, trace)
            outcome = "ok"
            return result
        except TurnLimitError:
            outcome = "limit"
            raise
        except TurnError:
            raise
        except ProviderError as exc:
            raise self._map_provider_error(exc) from exc
        except Exception as exc:
            logger.exception("turn failed for %s", request.conversation_id)
            raise TurnError() from exc
        finally:
            self._usage.record_turn(
                conversation_id=request.conversation_id,
                correlation_id=correlation_id,
                outcome=outcome,
                rounds=trace.rounds,
                duration_seconds=self._clock() - started,
                tool_operations=trace.tool_operations,
            )

    def _tool_loop(
        self,
        request: TurnRequest,
        correlation_id: str,
        started: float,
        trace: _TurnTrace,
    ) -> TurnResult:
        messages = self._conversations.append(
            request.conversation_id, Message(role="user", text=request.text)
        )
        actor = {
            "kind": "mattermost",
            "username": request.actor_username,
            "correlation_id": correlation_id,
        }

        for _round in range(self._config.tool_rounds_per_turn):
            if self._disabled.is_set():
                raise TurnUnavailableError()
            remaining = self._config.turn_timeout_seconds - (self._clock() - started)
            if remaining <= 0:
                raise TurnError()
            if self._usage.invocations_today() >= self._config.invocations_per_day:
                raise TurnLimitError()

            trace.rounds += 1
            self._usage.record_invocation()
            reply = self._provider.invoke(
                ProviderContext(
                    system_context=self._context_provider(), messages=tuple(messages)
                ),
                timeout_seconds=remaining,
            )

            if isinstance(reply, FinalAnswer):
                text = _truncate(reply.text, MAX_TURN_OUTPUT_BYTES)
                messages = self._conversations.append(
                    request.conversation_id, Message(role="assistant", text=text)
                )
                return TurnResult(text=text)

            if isinstance(reply, ToolCall):
                trace.tool_operations.append(reply.operation)
                tool_text = self._run_tool(reply, actor)
                messages = self._conversations.append(
                    request.conversation_id,
                    Message(role="tool", text=f"{reply.operation}: {tool_text}"),
                )
                continue

            raise TurnError()  # unknown reply type: fail closed

        raise TurnError()  # tool rounds exhausted without a final answer

    def _run_tool(self, call: ToolCall, actor: dict) -> str:
        if (
            not _OPERATION_RE.match(call.operation or "")
            or call.operation not in self._config.allowed_operations
        ):
            return json.dumps({"ok": False, "error": {"code": "denied_operation"}})
        params = call.params if isinstance(call.params, dict) else {}
        try:
            envelope = self._execute_limeops(call.operation, params, actor)
        except Exception:  # noqa: BLE001 - broker failure is a bounded tool result
            logger.exception("limeops execution failed for %s", call.operation)
            return json.dumps({"ok": False, "error": {"code": "unavailable_dependency"}})
        summary = {
            "ok": envelope.get("ok"),
            "data": envelope.get("data"),
            "warnings": envelope.get("warnings") or [],
            "error": envelope.get("error"),
        }
        return _truncate(json.dumps(summary), self._config.max_tool_result_bytes)

    # -- helpers ----------------------------------------------------------------
    def _lock_for(self, conversation_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._conversation_locks.setdefault(conversation_id, threading.Lock())

    @staticmethod
    def _map_provider_error(exc: ProviderError) -> TurnError:
        if isinstance(exc, (ProviderAuthError, ProviderUnavailableError)):
            return TurnUnavailableError()
        if isinstance(exc, ProviderTimeoutError):
            return TurnError()
        return TurnError()


def _truncate(text: str, limit_bytes: int) -> str:
    encoded = text.encode("utf-8")[:limit_bytes]
    return encoded.decode("utf-8", errors="ignore")


def limeops_client_executor(client) -> LimeOpsExecutor:  # pragma: no cover - thin adapter
    """Adapt `limeops.client.LimeOpsClient` to the executor contract."""

    def execute(operation: str, params: dict, actor: dict) -> dict:
        return client.request(operation, params, actor)

    return execute
