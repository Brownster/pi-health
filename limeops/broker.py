"""Framework-neutral request broker for read-only LimeOS operations."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from limeops import SCHEMA_VERSION
from limeops.policy import LimeOpsPolicy, PolicyError


REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
ACTOR_TYPES = frozenset({"local", "mattermost", "system"})
REQUEST_FIELDS = frozenset(
    {"schema_version", "request_id", "operation", "params", "actor"}
)
ACTOR_FIELDS = frozenset({"type", "id", "username"})


class AuditWriter(Protocol):
    def record(self, event: Mapping[str, Any]) -> bool: ...


@dataclass(frozen=True)
class PeerIdentity:
    pid: int
    uid: int
    gid: int


@dataclass(frozen=True)
class OperationContext:
    request_id: str
    audit_id: str
    operation: str
    actor: Mapping[str, str]
    peer: PeerIdentity
    resources: tuple[str, ...]


@dataclass(frozen=True)
class OperationDefinition:
    handler: Callable[[Mapping[str, Any], OperationContext], Any]
    validate_params: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    resource_param: str | None = None


class JsonlAuditWriter:
    """Append durable private audit records without raising into the broker."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], str] | None = None,
        create_parent: bool = True,
    ) -> None:
        self._path = Path(path)
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat()
        )
        self._create_parent = create_parent
        self._lock = threading.Lock()

    def record(self, event: Mapping[str, Any]) -> bool:
        try:
            with self._lock:
                if self._create_parent:
                    self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
                payload = json.dumps(
                    {"ts": self._clock(), **dict(event)},
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8") + b"\n"
                descriptor = os.open(
                    self._path,
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                    0o640,
                )
                try:
                    os.fchmod(descriptor, 0o640)
                    view = memoryview(payload)
                    while view:
                        written = os.write(descriptor, view)
                        view = view[written:]
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            return True
        except (OSError, TypeError, ValueError):
            return False


class LimeOpsBroker:
    def __init__(
        self,
        *,
        policy: LimeOpsPolicy,
        operations: Mapping[str, OperationDefinition],
        audit: AuditWriter,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._policy = policy
        self._operations = dict(operations)
        self._audit = audit
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="limeops-operation",
        )

    def handle(self, raw: Any, peer: PeerIdentity) -> dict[str, Any]:
        audit_id = self._id_factory()
        started = self._clock()
        try:
            parsed = self._validate_request(raw)
        except ValueError as exc:
            return self._audited_error(
                request_id=self._safe_request_id(raw),
                operation=self._safe_operation(raw),
                audit_id=audit_id,
                peer=peer,
                actor={},
                code="invalid_input",
                message=str(exc),
                started=started,
                request_recorded=False,
            )

        request_id = parsed["request_id"]
        operation = parsed["operation"]
        actor = parsed["actor"]
        request_event = self._audit_event(
            phase="request",
            request_id=request_id,
            audit_id=audit_id,
            operation=operation,
            peer=peer,
            actor=actor,
        )
        if not self._audit.record(request_event):
            return self._error_envelope(
                request_id,
                operation,
                audit_id,
                "audit_failure",
                "Audit record could not be persisted",
            )

        try:
            operation_policy = self._policy.require(operation)
        except PolicyError as exc:
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code=exc.code,
                message=str(exc),
                started=started,
                request_recorded=True,
            )

        definition = self._operations.get(operation)
        if definition is None:
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="unavailable_dependency",
                message="Operation is not available",
                started=started,
                request_recorded=True,
            )

        try:
            params = definition.validate_params(parsed["params"])
            if not isinstance(params, Mapping):
                raise ValueError("Operation parameters are invalid")
        except (TypeError, ValueError) as exc:
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="invalid_input",
                message=str(exc) or "Operation parameters are invalid",
                started=started,
                request_recorded=True,
            )

        if definition.resource_param is not None:
            try:
                operation_policy.require_resource(params.get(definition.resource_param))
            except PolicyError as exc:
                return self._audited_error(
                    request_id=request_id,
                    operation=operation,
                    audit_id=audit_id,
                    peer=peer,
                    actor=actor,
                    code=exc.code,
                    message=str(exc),
                    started=started,
                    request_recorded=True,
                )

        context = OperationContext(
            request_id=request_id,
            audit_id=audit_id,
            operation=operation,
            actor=actor,
            peer=peer,
            resources=operation_policy.resources,
        )
        future = self._executor.submit(definition.handler, dict(params), context)
        try:
            data = future.result(timeout=operation_policy.timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="timeout",
                message="Operation timed out",
                started=started,
                request_recorded=True,
            )
        except Exception:
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="upstream_failure",
                message="Operation failed",
                started=started,
                request_recorded=True,
            )

        try:
            output_size = len(
                json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
            )
        except (TypeError, ValueError):
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="upstream_failure",
                message="Operation returned invalid data",
                started=started,
                request_recorded=True,
            )
        if output_size > operation_policy.max_output_bytes:
            return self._audited_error(
                request_id=request_id,
                operation=operation,
                audit_id=audit_id,
                peer=peer,
                actor=actor,
                code="output_limit",
                message="Operation output exceeds its limit",
                started=started,
                request_recorded=True,
            )

        result_event = self._audit_event(
            phase="result",
            request_id=request_id,
            audit_id=audit_id,
            operation=operation,
            peer=peer,
            actor=actor,
            ok=True,
            duration_ms=self._duration_ms(started),
            output_bytes=output_size,
        )
        if not self._audit.record(result_event):
            return self._error_envelope(
                request_id,
                operation,
                audit_id,
                "audit_failure",
                "Audit result could not be persisted",
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "ok": True,
            "operation": operation,
            "data": data,
            "warnings": [],
            "error": None,
            "audit_id": audit_id,
        }

    def _audited_error(
        self,
        *,
        request_id: str,
        operation: str,
        audit_id: str,
        peer: PeerIdentity,
        actor: Mapping[str, str],
        code: str,
        message: str,
        started: float,
        request_recorded: bool,
    ) -> dict[str, Any]:
        event = self._audit_event(
            phase="result",
            request_id=request_id,
            audit_id=audit_id,
            operation=operation,
            peer=peer,
            actor=actor,
            ok=False,
            error_code=code,
            duration_ms=self._duration_ms(started),
            request_recorded=request_recorded,
        )
        if not self._audit.record(event):
            code = "audit_failure"
            message = "Audit result could not be persisted"
        return self._error_envelope(request_id, operation, audit_id, code, message)

    def _duration_ms(self, started: float) -> int:
        return max(0, int((self._clock() - started) * 1000))

    @staticmethod
    def _validate_request(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise ValueError("Request must be a JSON object")
        unknown = set(raw) - REQUEST_FIELDS
        if unknown:
            raise ValueError(f"Unknown request field: {sorted(unknown)[0]}")
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported request schema version")
        request_id = raw.get("request_id")
        operation = raw.get("operation")
        params = raw.get("params")
        actor = raw.get("actor")
        if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
            raise ValueError("Request ID is invalid")
        if (
            not isinstance(operation, str)
            or not re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*", operation)
        ):
            raise ValueError("Operation name is invalid")
        if not isinstance(params, Mapping) or len(params) > 32:
            raise ValueError("Operation parameters must be a bounded JSON object")
        if not isinstance(actor, Mapping) or set(actor) - ACTOR_FIELDS:
            raise ValueError("Actor is invalid")
        actor_type = actor.get("type")
        actor_id = actor.get("id")
        username = actor.get("username")
        if actor_type not in ACTOR_TYPES or not LimeOpsBroker._safe_identity(actor_id):
            raise ValueError("Actor is invalid")
        if username is not None and not LimeOpsBroker._safe_identity(username):
            raise ValueError("Actor is invalid")
        normalized_actor = {"type": actor_type, "id": actor_id}
        if username is not None:
            normalized_actor["username"] = username
        return {
            "request_id": request_id,
            "operation": operation,
            "params": dict(params),
            "actor": normalized_actor,
        }

    @staticmethod
    def _safe_identity(value: Any) -> bool:
        return (
            isinstance(value, str)
            and 0 < len(value) <= 128
            and not any(character in value for character in "\x00\r\n")
        )

    @staticmethod
    def _safe_request_id(raw: Any) -> str:
        value = raw.get("request_id") if isinstance(raw, Mapping) else None
        return value if isinstance(value, str) and REQUEST_ID_PATTERN.fullmatch(value) else "unknown"

    @staticmethod
    def _safe_operation(raw: Any) -> str:
        value = raw.get("operation") if isinstance(raw, Mapping) else None
        return (
            value
            if isinstance(value, str)
            and re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*", value)
            else "unknown"
        )

    @staticmethod
    def _audit_event(
        *,
        phase: str,
        request_id: str,
        audit_id: str,
        operation: str,
        peer: PeerIdentity,
        actor: Mapping[str, str],
        **values: Any,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "request_id": request_id,
            "audit_id": audit_id,
            "operation": operation,
            "peer_pid": peer.pid,
            "peer_uid": peer.uid,
            "peer_gid": peer.gid,
            "actor_type": actor.get("type"),
            "actor_id": actor.get("id"),
            "actor_username": actor.get("username"),
            **values,
        }

    @staticmethod
    def _error_envelope(
        request_id: str,
        operation: str,
        audit_id: str,
        code: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "ok": False,
            "operation": operation,
            "data": None,
            "warnings": [],
            "error": {"code": code, "message": message},
            "audit_id": audit_id,
        }
