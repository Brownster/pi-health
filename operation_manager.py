"""Bounded, session-owned background operations with replayable SSE output."""

import hmac
import json
import threading
import time
import uuid

from flask import Response, jsonify, request, session


OPERATION_TTL_SECONDS = 15 * 60
OPERATION_LIMIT = 100
OPERATION_EVENT_LIMIT = 5000
_operations = {}
_operations_lock = threading.Lock()


class OperationCapacityError(RuntimeError):
    """Raised when all retained operation slots are active."""


class BackgroundOperation:
    """In-memory output buffer for one exactly-once background operation."""

    def __init__(self, operation_id, owner_token, username, kind, target):
        self.operation_id = operation_id
        self.owner_token = owner_token
        self.username = username
        self.kind = kind
        self.target = target
        self.created_at = time.monotonic()
        self.events = []
        self.first_event_id = 0
        self.complete = False
        self.condition = threading.Condition()

    def append(self, payload):
        with self.condition:
            self.events.append(payload)
            if len(self.events) > OPERATION_EVENT_LIMIT:
                self.events.pop(0)
                self.first_event_id += 1
            if payload.get('done') or payload.get('error'):
                self.complete = True
            self.condition.notify_all()

    def finish(self):
        with self.condition:
            self.complete = True
            self.condition.notify_all()


def _prune_operations():
    cutoff = time.monotonic() - OPERATION_TTL_SECONDS
    expired = [
        operation_id
        for operation_id, operation in _operations.items()
        if operation.complete and operation.created_at < cutoff
    ]
    for operation_id in expired:
        _operations.pop(operation_id, None)
    if len(_operations) > OPERATION_LIMIT:
        oldest = sorted(
            (operation for operation in _operations.values() if operation.complete),
            key=lambda operation: operation.created_at,
        )
        excess = len(_operations) - OPERATION_LIMIT
        for operation in oldest[:excess]:
            _operations.pop(operation.operation_id, None)


def _run_operation(operation, producer):
    terminal_event = False
    try:
        for payload in producer():
            if not isinstance(payload, dict):
                continue
            operation.append(payload)
            terminal_event = terminal_event or bool(
                payload.get('done') or payload.get('error')
            )
    except Exception as exc:
        operation.append({'error': str(exc)})
        terminal_event = True
    finally:
        if not terminal_event:
            operation.append({'error': 'Operation ended without a result'})
        operation.finish()


def start_operation(owner_token, username, kind, target, producer):
    """Register and start one operation, or raise when capacity/startup fails."""
    operation_id = uuid.uuid4().hex
    operation = BackgroundOperation(
        operation_id=operation_id,
        owner_token=owner_token,
        username=username,
        kind=kind,
        target=target,
    )
    with _operations_lock:
        _prune_operations()
        if len(_operations) >= OPERATION_LIMIT:
            oldest_complete = min(
                (item for item in _operations.values() if item.complete),
                key=lambda item: item.created_at,
                default=None,
            )
            if oldest_complete is None:
                raise OperationCapacityError('Too many background operations')
            _operations.pop(oldest_complete.operation_id, None)
        _operations[operation_id] = operation

    thread = threading.Thread(
        target=_run_operation,
        args=(operation, producer),
        name=f'{kind}-operation-{operation_id[:8]}',
        daemon=True,
    )
    try:
        thread.start()
    except RuntimeError:
        with _operations_lock:
            _operations.pop(operation_id, None)
        raise
    return operation


def parse_sse_payload(frame):
    """Return the first JSON object from an SSE frame."""
    for line in frame.splitlines():
        if not line.startswith('data:'):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def stream_operation_response(operation_id, expected_kind):
    """Return a replay/follow SSE response for an operation owned by this session."""
    with _operations_lock:
        _prune_operations()
        operation = _operations.get(operation_id)
    owner_token = session.get('csrf_token')
    if (
        not operation
        or operation.kind != expected_kind
        or not isinstance(owner_token, str)
        or not hmac.compare_digest(operation.owner_token, owner_token)
    ):
        return jsonify({'error': 'Operation not found'}), 404

    try:
        last_event_id = int(request.headers.get('Last-Event-ID', '-1'))
    except ValueError:
        last_event_id = -1
    start_index = max(0, last_event_id + 1)

    def generate():
        index = start_index
        while True:
            with operation.condition:
                index = max(index, operation.first_event_id)
                end_index = operation.first_event_id + len(operation.events)
                if index >= end_index and not operation.complete:
                    operation.condition.wait(timeout=15)
                    index = max(index, operation.first_event_id)
                    end_index = operation.first_event_id + len(operation.events)
                offset = index - operation.first_event_id
                events = operation.events[offset:]
                complete = operation.complete

            if not events and not complete:
                yield ': keep-alive\n\n'
                continue
            for payload in events:
                yield f'id: {index}\ndata: {json.dumps(payload)}\n\n'
                index += 1
            if complete and index >= end_index:
                break

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
