import json
import struct
from unittest.mock import MagicMock

import pytest

from limeops.client import LimeOpsClient, LimeOpsClientError


def response_frame(response):
    payload = json.dumps(response).encode()
    return struct.pack("!I", len(payload)), payload


def success_response():
    return {
        "schema_version": "1",
        "request_id": "request-1",
        "ok": True,
        "operation": "system.status",
        "data": {"healthy": True},
        "warnings": [],
        "error": None,
        "audit_id": "audit-1",
    }


def test_client_sends_versioned_request_and_validates_response():
    connection = MagicMock()
    connection.recv.side_effect = response_frame(success_response())
    client = LimeOpsClient(
        socket_path="/tmp/limeops.sock",
        timeout=5,
        socket_factory=lambda *_args: connection,
        id_factory=lambda: "request-1",
    )

    result = client.request(
        "system.status",
        {},
        {"type": "local", "id": "1000", "username": "holly"},
    )

    assert result["ok"] is True
    connection.connect.assert_called_once_with("/tmp/limeops.sock")
    connection.settimeout.assert_called_once_with(5)
    frame = connection.sendall.call_args.args[0]
    size = struct.unpack("!I", frame[:4])[0]
    payload = json.loads(frame[4 : 4 + size])
    assert payload == {
        "schema_version": "1",
        "request_id": "request-1",
        "operation": "system.status",
        "params": {},
        "actor": {"type": "local", "id": "1000", "username": "holly"},
    }
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "response",
    [
        {},
        {**success_response(), "schema_version": "2"},
        {**success_response(), "ok": "yes"},
        {**success_response(), "warnings": "none"},
        {**success_response(), "unexpected": True},
        {**success_response(), "ok": False, "error": None},
        {
            **success_response(),
            "ok": False,
            "data": {},
            "error": {"code": "denied_operation", "message": "denied"},
        },
        {
            **success_response(),
            "ok": False,
            "data": None,
            "error": {"code": "new_error", "message": "unknown"},
        },
    ],
)
def test_client_rejects_invalid_response_envelope(response):
    connection = MagicMock()
    connection.recv.side_effect = response_frame(response)
    client = LimeOpsClient(socket_factory=lambda *_args: connection)
    with pytest.raises(LimeOpsClientError) as error:
        client.request("system.status", {}, {"type": "local", "id": "1000"})
    assert error.value.code == "invalid_response"


def test_client_maps_socket_failure_without_leaking_detail():
    connection = MagicMock()
    connection.connect.side_effect = OSError("private path detail")
    client = LimeOpsClient(socket_factory=lambda *_args: connection)
    with pytest.raises(LimeOpsClientError) as error:
        client.request("system.status", {}, {"type": "local", "id": "1000"})
    assert error.value.code == "unavailable_dependency"
    assert "private path detail" not in str(error.value)
    connection.close.assert_called_once()
