"""Process-scoped background operations with bounded replayable output."""

from __future__ import annotations

import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable


OPERATION_TTL_SECONDS = 15 * 60
OPERATION_LIMIT = 100
OPERATION_EVENT_LIMIT = 5000

OperationProducer = Callable[[], Iterable[dict]]
OperationProducerFactory = Callable[[str], Iterable[dict]]
ThreadFactory = Callable[..., threading.Thread]


class OperationCapacityError(RuntimeError):
    """Raised when all retained operation slots are active."""


class OperationConflictError(RuntimeError):
    """Raised when an exclusive operation is already active."""


@dataclass(frozen=True)
class OperationEvent:
    event_id: int
    payload: dict


@dataclass(frozen=True)
class OperationEventBatch:
    events: tuple[OperationEvent, ...]
    next_cursor: int
    complete: bool


class BackgroundOperation:
    """In-memory output buffer for one exactly-once background operation."""

    def __init__(
        self,
        operation_id,
        owner,
        username,
        kind,
        target,
        created_at,
        conflict_key=None,
    ):
        self.operation_id = operation_id
        self.owner = owner
        self.username = username
        self.kind = kind
        self.target = target
        self.created_at = created_at
        self.conflict_key = conflict_key
        self.events = []
        self.first_event_id = 0
        self.complete = False
        self.condition = threading.Condition()

    def append(self, payload, event_limit):
        with self.condition:
            self.events.append(payload)
            if len(self.events) > event_limit:
                self.events.pop(0)
                self.first_event_id += 1
            if payload.get("done") or payload.get("error"):
                self.complete = True
            self.condition.notify_all()

    def finish(self):
        with self.condition:
            self.events = [
                {"expired": True} if payload.get("_ephemeral") else payload
                for payload in self.events
            ]
            self.complete = True
            self.condition.notify_all()


class OperationRegistry:
    """Own one process's operation threads, retention, ownership, and replay state.

    Injection makes lifecycle ownership explicit; it does not make this registry safe to share
    across worker processes. Deploy one application worker until operation state has a shared-store
    design.
    """

    def __init__(
        self,
        *,
        clock=time.monotonic,
        thread_factory: ThreadFactory = threading.Thread,
        ttl_seconds=OPERATION_TTL_SECONDS,
        operation_limit=OPERATION_LIMIT,
        event_limit=OPERATION_EVENT_LIMIT,
    ):
        self._clock = clock
        self._thread_factory = thread_factory
        self._ttl_seconds = ttl_seconds
        self._operation_limit = operation_limit
        self._event_limit = event_limit
        self._operations = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        owner,
        username,
        kind,
        target,
        producer=None,
        producer_factory=None,
        conflict_key=None,
        before_start=None,
    ):
        """Register and start one operation, or raise when capacity or startup fails."""
        if (producer is None) == (producer_factory is None):
            raise ValueError("Provide exactly one operation producer")
        operation_id = uuid.uuid4().hex
        operation = BackgroundOperation(
            operation_id=operation_id,
            owner=owner,
            username=username,
            kind=kind,
            target=target,
            created_at=self._clock(),
            conflict_key=conflict_key,
        )
        with self._lock:
            self._prune_locked()
            if conflict_key is not None and any(
                item.conflict_key == conflict_key and not item.complete
                for item in self._operations.values()
            ):
                raise OperationConflictError("An integration operation is already running")
            if len(self._operations) >= self._operation_limit:
                oldest_complete = min(
                    (item for item in self._operations.values() if item.complete),
                    key=lambda item: item.created_at,
                    default=None,
                )
                if oldest_complete is None:
                    raise OperationCapacityError("Too many background operations")
                self._operations.pop(oldest_complete.operation_id, None)
            self._operations[operation_id] = operation

        try:
            resolved_producer = (
                producer
                if producer_factory is None
                else lambda: producer_factory(operation_id)
            )
            if before_start is not None:
                before_start(operation)
            thread = self._thread_factory(
                target=self._run,
                args=(operation, resolved_producer),
                name=f"{kind}-operation-{operation_id[:8]}",
                daemon=True,
            )
            thread.start()
        except Exception:
            with self._lock:
                self._operations.pop(operation_id, None)
            raise
        return operation

    def is_owner(self, operation_id, *, expected_kind, owner):
        with self._lock:
            self._prune_locked()
            operation = self._operations.get(operation_id)
        return bool(
            operation
            and _kind_matches(operation.kind, expected_kind)
            and isinstance(owner, str)
            and hmac.compare_digest(operation.owner, owner)
        )

    def events_since(
        self,
        operation_id,
        *,
        expected_kind,
        owner,
        cursor=0,
        wait_timeout=0,
    ):
        """Return retained events at or after the next-event cursor for an owner."""
        with self._lock:
            self._prune_locked()
            operation = self._operations.get(operation_id)
        if not (
            operation
            and _kind_matches(operation.kind, expected_kind)
            and isinstance(owner, str)
            and hmac.compare_digest(operation.owner, owner)
        ):
            return None

        with operation.condition:
            cursor = max(cursor, operation.first_event_id)
            end_cursor = operation.first_event_id + len(operation.events)
            if cursor >= end_cursor and not operation.complete and wait_timeout:
                operation.condition.wait(timeout=wait_timeout)
                cursor = max(cursor, operation.first_event_id)
                end_cursor = operation.first_event_id + len(operation.events)

            offset = cursor - operation.first_event_id
            payloads = tuple(operation.events[offset:])
            events = tuple(
                OperationEvent(event_id=cursor + index, payload=payload)
                for index, payload in enumerate(payloads)
            )
            return OperationEventBatch(
                events=events,
                next_cursor=cursor + len(events),
                complete=operation.complete,
            )

    def _run(self, operation, producer):
        terminal_event = False
        try:
            for payload in producer():
                if not isinstance(payload, dict):
                    continue
                operation.append(payload, self._event_limit)
                terminal_event = terminal_event or bool(
                    payload.get("done") or payload.get("error")
                )
        except Exception as exc:
            if operation.kind.startswith("agent-"):
                error = "AI Agents operation failed"
            elif operation.kind.startswith("integration-lifecycle-"):
                error = "Integration lifecycle operation failed"
            else:
                error = str(exc)
            operation.append({"error": error}, self._event_limit)
            terminal_event = True
        finally:
            if not terminal_event:
                operation.append(
                    {"error": "Operation ended without a result"},
                    self._event_limit,
                )
            operation.finish()

    def _prune_locked(self):
        cutoff = self._clock() - self._ttl_seconds
        expired = [
            operation_id
            for operation_id, operation in self._operations.items()
            if operation.complete and operation.created_at < cutoff
        ]
        for operation_id in expired:
            self._operations.pop(operation_id, None)
        if len(self._operations) > self._operation_limit:
            oldest = sorted(
                (operation for operation in self._operations.values() if operation.complete),
                key=lambda operation: operation.created_at,
            )
            excess = len(self._operations) - self._operation_limit
            for operation in oldest[:excess]:
                self._operations.pop(operation.operation_id, None)


def parse_sse_payload(frame):
    """Return the first JSON object from an SSE frame."""
    for line in frame.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _kind_matches(actual, expected):
    if isinstance(expected, (tuple, list, frozenset)):
        return actual in expected
    return actual == expected
