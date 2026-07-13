import json
import os
import socket
import stat
import struct
import threading
from unittest.mock import MagicMock, Mock, call, patch

from limeops.broker import PeerIdentity
from limeops.client import LimeOpsClient
from limeops.server import (
    LimeOpsUnixServer,
    get_peer_identity,
    peer_is_authorized,
)


def request_frame(value):
    payload = json.dumps(value).encode()
    return [struct.pack("!I", len(payload)), payload]


def sent_response(connection):
    frame = connection.sendall.call_args.args[0]
    size = struct.unpack("!I", frame[:4])[0]
    return json.loads(frame[4 : 4 + size])


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(dict(event))
        return True


def test_get_peer_identity_from_unix_socketpair():
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        peer = get_peer_identity(left)
        assert peer.pid == os.getpid()
        assert peer.uid == os.getuid()
        assert peer.gid == os.getgid()
    finally:
        left.close()
        right.close()


def test_peer_authorization_accepts_root_primary_or_supplementary_group():
    assert peer_is_authorized(PeerIdentity(1, 0, 0), 2000, lambda _pid: set()) is True
    assert peer_is_authorized(PeerIdentity(2, 1000, 2000), 2000, lambda _pid: set()) is True
    assert peer_is_authorized(PeerIdentity(3, 1000, 1000), 2000, lambda _pid: {2000}) is True
    assert peer_is_authorized(PeerIdentity(4, 1000, 1000), 2000, lambda _pid: {1000}) is False


def make_server(*, broker=None, audit=None, authorized=True, max_connections=8):
    broker = broker or Mock()
    audit = audit or RecordingAudit()
    server = LimeOpsUnixServer(
        broker=broker,
        audit=audit,
        socket_path="/tmp/limeops.sock",
        allowed_gid=2000,
        authorization=lambda _peer, _gid: authorized,
        peer_reader=lambda _connection: PeerIdentity(123, 1000, 1000),
        max_connections=max_connections,
    )
    return server, broker, audit


def test_server_rejects_unauthorized_peer_before_read_or_dispatch():
    server, broker, audit = make_server(authorized=False)
    connection = MagicMock()
    server.serve_connection(connection)
    assert sent_response(connection)["error"]["code"] == "denied_operation"
    connection.recv.assert_not_called()
    broker.handle.assert_not_called()
    assert audit.events[0]["event"] == "unauthorized_peer"


def test_server_dispatches_authorized_request_with_peer_identity():
    response = {
        "schema_version": "1",
        "request_id": "request-1",
        "ok": True,
        "operation": "system.status",
        "data": {},
        "warnings": [],
        "error": None,
        "audit_id": "audit-1",
    }
    server, broker, _audit = make_server()
    broker.handle.return_value = response
    connection = MagicMock()
    request = {
        "schema_version": "1",
        "request_id": "request-1",
        "operation": "system.status",
        "params": {},
        "actor": {"type": "local", "id": "1000"},
    }
    connection.recv.side_effect = request_frame(request)
    server.serve_connection(connection)
    broker.handle.assert_called_once_with(request, PeerIdentity(123, 1000, 1000))
    assert sent_response(connection) == response


def test_server_returns_stable_protocol_error_without_dispatch():
    server, broker, audit = make_server()
    connection = MagicMock()
    connection.recv.return_value = struct.pack("!I", 0)
    server.serve_connection(connection)
    response = sent_response(connection)
    assert response["error"]["code"] == "invalid_frame"
    broker.handle.assert_not_called()
    assert audit.events[0]["event"] == "protocol_error"


def test_server_hides_unexpected_failure_detail():
    server, broker, audit = make_server()
    broker.handle.side_effect = RuntimeError("secret detail")
    connection = MagicMock()
    connection.recv.side_effect = request_frame(
        {
            "schema_version": "1",
            "request_id": "request-1",
            "operation": "system.status",
            "params": {},
            "actor": {"type": "local", "id": "1000"},
        }
    )
    server.serve_connection(connection)
    response = sent_response(connection)
    assert response["error"] == {
        "code": "upstream_failure",
        "message": "Broker request failed",
    }
    assert "secret detail" not in json.dumps(response)
    assert audit.events[-1]["event"] == "server_error"


def test_server_secures_socket_directory_and_file(tmp_path):
    socket_dir = tmp_path / "run"
    socket_dir.mkdir()
    socket_path = socket_dir / "limeops.sock"
    socket_path.touch()
    server, _broker, _audit = make_server()
    with (
        patch("limeops.server.os.chown") as chown,
        patch("limeops.server.os.getuid", return_value=1234),
    ):
        server.secure_socket_paths(socket_dir, socket_path)
    assert stat.S_IMODE(socket_dir.stat().st_mode) == 0o750
    assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660
    assert chown.call_args_list == [call(socket_dir, 1234, 2000), call(socket_path, 1234, 2000)]


def test_server_connection_wrapper_sets_timeout_and_closes():
    server, _broker, _audit = make_server(authorized=False)
    connection = MagicMock()
    server.handle_connection(connection)
    connection.settimeout.assert_called_once_with(10)
    connection.close.assert_called_once()


def test_server_rejects_connections_above_capacity_without_dispatch():
    server, broker, audit = make_server(max_connections=1)
    assert server._connection_slots.acquire(blocking=False) is True
    connection = MagicMock()
    server.handle_connection(connection)
    response = sent_response(connection)
    assert response["error"]["code"] == "unavailable_dependency"
    broker.handle.assert_not_called()
    assert audit.events[-1]["event"] == "connection_capacity"
    connection.close.assert_called_once()


def test_client_and_server_round_trip_over_real_unix_frames():
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    class ConnectedSocket:
        def settimeout(self, timeout):
            left.settimeout(timeout)

        def connect(self, _path):
            return None

        def sendall(self, value):
            left.sendall(value)

        def recv(self, size):
            return left.recv(size)

        def close(self):
            left.close()

    response = {
        "schema_version": "1",
        "request_id": "request-1",
        "ok": True,
        "operation": "system.status",
        "data": {"healthy": True},
        "warnings": [],
        "error": None,
        "audit_id": "audit-1",
    }
    server, broker, _audit = make_server()
    broker.handle.return_value = response
    worker = threading.Thread(target=server.handle_connection, args=(right,))
    worker.start()
    client = LimeOpsClient(
        socket_factory=lambda *_args: ConnectedSocket(),
        id_factory=lambda: "request-1",
    )
    result = client.request(
        "system.status",
        {},
        {"type": "local", "id": "1000"},
    )
    worker.join(timeout=1)

    assert result == response
    assert worker.is_alive() is False
