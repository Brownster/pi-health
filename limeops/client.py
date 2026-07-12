"""Client for the local limeops Unix socket."""

from __future__ import annotations

import socket
import uuid
from collections.abc import Mapping
from typing import Any

from limeops import SCHEMA_VERSION
from limeops.protocol import (
    MAX_RESPONSE_SIZE,
    PUBLIC_ERROR_CODES,
    FrameError,
    receive_json,
    send_json,
)


DEFAULT_SOCKET_PATH = "/run/limeos/limeops.sock"
RESPONSE_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "ok",
        "operation",
        "data",
        "warnings",
        "error",
        "audit_id",
    }
)


class LimeOpsClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class LimeOpsClient:
    def __init__(
        self,
        *,
        socket_path: str = DEFAULT_SOCKET_PATH,
        timeout: float = 30,
        socket_factory=socket.socket,
        id_factory=None,
    ) -> None:
        self._socket_path = socket_path
        self._timeout = timeout
        self._socket_factory = socket_factory
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def request(
        self,
        operation: str,
        params: Mapping[str, Any],
        actor: Mapping[str, str],
    ) -> dict[str, Any]:
        connection = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(self._timeout)
            connection.connect(self._socket_path)
            send_json(
                connection,
                {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": self._id_factory(),
                    "operation": operation,
                    "params": dict(params),
                    "actor": dict(actor),
                },
                max_size=64 * 1024,
            )
            return self._validate_response(
                receive_json(connection, max_size=MAX_RESPONSE_SIZE)
            )
        except FrameError as exc:
            raise LimeOpsClientError(exc.code, str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise LimeOpsClientError(
                "unavailable_dependency", "Unable to reach the limeops broker"
            ) from exc
        finally:
            connection.close()

    @staticmethod
    def _validate_response(value: dict[str, Any]) -> dict[str, Any]:
        if set(value) != RESPONSE_FIELDS or value.get("schema_version") != SCHEMA_VERSION:
            raise LimeOpsClientError("invalid_response", "Broker returned an invalid response")
        if not isinstance(value.get("ok"), bool):
            raise LimeOpsClientError("invalid_response", "Broker returned an invalid response")
        for field in ("request_id", "operation", "audit_id"):
            if not isinstance(value.get(field), str) or not value[field]:
                raise LimeOpsClientError(
                    "invalid_response", "Broker returned an invalid response"
                )
        warnings = value.get("warnings")
        if not isinstance(warnings, list) or not all(
            isinstance(warning, str) for warning in warnings
        ):
            raise LimeOpsClientError("invalid_response", "Broker returned an invalid response")
        error = value.get("error")
        if value["ok"]:
            if error is not None:
                raise LimeOpsClientError(
                    "invalid_response", "Broker returned an invalid response"
                )
        elif (
            not isinstance(error, dict)
            or set(error) != {"code", "message"}
            or not isinstance(error.get("code"), str)
            or error.get("code") not in PUBLIC_ERROR_CODES
            or not isinstance(error.get("message"), str)
            or value.get("data") is not None
        ):
            raise LimeOpsClientError("invalid_response", "Broker returned an invalid response")
        return value
