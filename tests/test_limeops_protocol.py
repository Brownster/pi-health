import json
import socket
import struct

import pytest

from limeops.protocol import (
    MAX_REQUEST_SIZE,
    FrameError,
    encode_json_frame,
    receive_json,
    send_json,
)


def test_json_frame_round_trip_over_unix_socketpair():
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        send_json(left, {"schema_version": "1", "operation": "system.status"})
        assert receive_json(right, max_size=MAX_REQUEST_SIZE) == {
            "schema_version": "1",
            "operation": "system.status",
        }
    finally:
        left.close()
        right.close()


@pytest.mark.parametrize("size", [0, MAX_REQUEST_SIZE + 1])
def test_receive_rejects_invalid_frame_size(size):
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack("!I", size))
        with pytest.raises(FrameError) as error:
            receive_json(right, max_size=MAX_REQUEST_SIZE)
        assert error.value.code == "invalid_frame"
    finally:
        left.close()
        right.close()


def test_receive_rejects_truncated_frame():
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack("!I", 10) + b"{}")
        left.close()
        with pytest.raises(FrameError) as error:
            receive_json(right, max_size=MAX_REQUEST_SIZE)
        assert error.value.code == "invalid_frame"
    finally:
        right.close()


@pytest.mark.parametrize(
    "payload,code",
    [
        (b"\xff", "invalid_encoding"),
        (b"not-json", "invalid_json"),
        (b"[]", "invalid_request"),
    ],
)
def test_receive_rejects_invalid_payload(payload, code):
    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack("!I", len(payload)) + payload)
        with pytest.raises(FrameError) as error:
            receive_json(right, max_size=MAX_REQUEST_SIZE)
        assert error.value.code == code
    finally:
        left.close()
        right.close()


def test_encode_rejects_oversized_payload():
    with pytest.raises(FrameError) as error:
        encode_json_frame({"value": "x" * 200}, max_size=64)
    assert error.value.code == "output_limit"


def test_frames_use_compact_deterministic_json():
    frame = encode_json_frame({"b": 2, "a": 1}, max_size=100)
    size = struct.unpack("!I", frame[:4])[0]
    payload = frame[4:]
    assert size == len(payload)
    assert payload == b'{"a":1,"b":2}'
    assert json.loads(payload) == {"a": 1, "b": 2}
