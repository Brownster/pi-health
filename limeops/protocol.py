"""Bounded length-framed JSON protocol for the local limeops socket."""

from __future__ import annotations

import json
import socket
import struct
from collections.abc import Mapping
from typing import Any


FRAME_HEADER_SIZE = 4
MAX_REQUEST_SIZE = 64 * 1024
MAX_RESPONSE_SIZE = 1024 * 1024
PUBLIC_ERROR_CODES = frozenset(
    {
        "invalid_input",
        "denied_operation",
        "missing_resource",
        "unavailable_dependency",
        "timeout",
        "output_limit",
        "upstream_failure",
        "audit_failure",
        "invalid_frame",
        "invalid_encoding",
        "invalid_json",
        "invalid_request",
        "invalid_response",
    }
)


class FrameError(Exception):
    """A malformed, truncated, or oversized protocol frame."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        try:
            chunk = connection.recv(remaining)
        except socket.timeout as exc:
            raise FrameError("timeout", "Socket frame timed out") from exc
        except OSError as exc:
            raise FrameError("unavailable_dependency", "Socket read failed") from exc
        if not chunk:
            raise FrameError("invalid_frame", "Socket frame is incomplete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def encode_json_frame(value: Mapping[str, Any], *, max_size: int) -> bytes:
    try:
        payload = json.dumps(
            dict(value),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FrameError("invalid_json", "Value cannot be encoded as JSON") from exc
    if not 0 < len(payload) <= max_size:
        raise FrameError("output_limit", "JSON frame exceeds the output limit")
    return struct.pack("!I", len(payload)) + payload


def send_json(
    connection: socket.socket,
    value: Mapping[str, Any],
    *,
    max_size: int = MAX_RESPONSE_SIZE,
) -> None:
    frame = encode_json_frame(value, max_size=max_size)
    try:
        connection.sendall(frame)
    except OSError as exc:
        raise FrameError("unavailable_dependency", "Socket write failed") from exc


def receive_json(
    connection: socket.socket,
    *,
    max_size: int,
) -> dict[str, Any]:
    header = _receive_exact(connection, FRAME_HEADER_SIZE)
    (message_size,) = struct.unpack("!I", header)
    if not 0 < message_size <= max_size:
        raise FrameError("invalid_frame", "Socket frame size is invalid")
    payload = _receive_exact(connection, message_size)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrameError("invalid_encoding", "Socket frame is not valid UTF-8") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FrameError("invalid_json", "Socket frame is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FrameError("invalid_request", "Socket frame must contain a JSON object")
    return value
