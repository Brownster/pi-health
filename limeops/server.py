"""Unix socket server for the local limeops broker."""

from __future__ import annotations

import argparse
import grp
import os
import signal
import socket
import struct
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from limeops import SCHEMA_VERSION
from limeops.broker import JsonlAuditWriter, LimeOpsBroker, PeerIdentity
from limeops.policy import LimeOpsPolicy, PolicyError
from limeops.protocol import (
    MAX_REQUEST_SIZE,
    MAX_RESPONSE_SIZE,
    FrameError,
    receive_json,
    send_json,
)


DEFAULT_SOCKET_PATH = "/run/limeos/limeops.sock"
DEFAULT_POLICY_PATH = "/etc/limeos/agent-policy.json"
DEFAULT_AUDIT_PATH = "/var/log/limeos/agent-audit.jsonl"


def get_peer_identity(connection: socket.socket) -> PeerIdentity:
    if not hasattr(socket, "SO_PEERCRED"):
        raise FrameError("denied_operation", "Peer credentials are unavailable")
    credential_size = struct.calcsize("3i")
    try:
        raw = connection.getsockopt(
            socket.SOL_SOCKET,
            socket.SO_PEERCRED,
            credential_size,
        )
    except OSError as exc:
        raise FrameError("denied_operation", "Peer credentials are unavailable") from exc
    if len(raw) != credential_size:
        raise FrameError("denied_operation", "Peer credentials are invalid")
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid < 0 or gid < 0:
        raise FrameError("denied_operation", "Peer credentials are invalid")
    return PeerIdentity(pid=pid, uid=uid, gid=gid)


def process_group_ids(pid: int) -> set[int]:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Groups:"):
                    return {int(value) for value in line.partition(":")[2].split()}
    except (OSError, ValueError):
        return set()
    return set()


def peer_is_authorized(
    peer: PeerIdentity,
    allowed_gid: int,
    group_reader: Callable[[int], set[int]] = process_group_ids,
) -> bool:
    return (
        peer.uid == 0
        or peer.gid == allowed_gid
        or allowed_gid in group_reader(peer.pid)
    )


def public_error(code: str, message: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": "unknown",
        "ok": False,
        "operation": "unknown",
        "data": None,
        "warnings": [],
        "error": {"code": code, "message": message},
        "audit_id": "unknown",
    }


class LimeOpsUnixServer:
    def __init__(
        self,
        *,
        broker: LimeOpsBroker,
        audit,
        socket_path: str = DEFAULT_SOCKET_PATH,
        allowed_gid: int,
        authorization: Callable[[PeerIdentity, int], bool] = peer_is_authorized,
        peer_reader: Callable[[socket.socket], PeerIdentity] = get_peer_identity,
        socket_factory=socket.socket,
        thread_factory=threading.Thread,
        max_connections: int = 8,
    ) -> None:
        self._broker = broker
        self._audit = audit
        self._socket_path = Path(socket_path)
        self._allowed_gid = allowed_gid
        self._authorization = authorization
        self._peer_reader = peer_reader
        self._socket_factory = socket_factory
        self._thread_factory = thread_factory
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        self._server = None
        self._stopping = threading.Event()

    def serve_connection(self, connection: socket.socket) -> None:
        peer = None
        try:
            peer = self._peer_reader(connection)
            if not self._authorization(peer, self._allowed_gid):
                self._audit.record(
                    {
                        "event": "unauthorized_peer",
                        "peer_pid": peer.pid,
                        "peer_uid": peer.uid,
                        "peer_gid": peer.gid,
                    }
                )
                self._send_public_error(
                    connection,
                    "denied_operation",
                    "Peer is not authorized",
                )
                return
            request = receive_json(connection, max_size=MAX_REQUEST_SIZE)
            response = self._broker.handle(request, peer)
            try:
                send_json(connection, response, max_size=MAX_RESPONSE_SIZE)
            except FrameError as exc:
                if exc.code != "output_limit":
                    raise
                self._send_public_error(
                    connection,
                    "output_limit",
                    "Broker response exceeds the protocol limit",
                )
        except FrameError as exc:
            self._audit.record(
                {
                    "event": "protocol_error",
                    "error_code": exc.code,
                    **self._peer_fields(peer),
                }
            )
            self._send_public_error(connection, exc.code, str(exc))
        except Exception:
            self._audit.record(
                {
                    "event": "server_error",
                    **self._peer_fields(peer),
                }
            )
            self._send_public_error(
                connection,
                "upstream_failure",
                "Broker request failed",
            )

    def handle_connection(self, connection: socket.socket) -> None:
        acquired = self._connection_slots.acquire(blocking=False)
        try:
            if not acquired:
                self._audit.record({"event": "connection_capacity"})
                self._send_public_error(
                    connection,
                    "unavailable_dependency",
                    "Broker connection capacity is exhausted",
                )
                return
            connection.settimeout(10)
            self.serve_connection(connection)
        finally:
            if acquired:
                self._connection_slots.release()
            connection.close()

    def secure_socket_paths(self, socket_dir: Path, socket_path: Path) -> None:
        owner_uid = os.getuid()
        os.chown(socket_dir, owner_uid, self._allowed_gid)
        os.chmod(socket_dir, 0o750)
        os.chown(socket_path, owner_uid, self._allowed_gid)
        os.chmod(socket_path, 0o660)

    def serve_forever(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._socket_path.unlink(missing_ok=True)
        server = self._socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server = server
        try:
            server.bind(str(self._socket_path))
            self.secure_socket_paths(self._socket_path.parent, self._socket_path)
            server.listen(16)
            while not self._stopping.is_set():
                try:
                    connection, _address = server.accept()
                except OSError:
                    if self._stopping.is_set():
                        break
                    raise
                thread = self._thread_factory(
                    target=self.handle_connection,
                    args=(connection,),
                    name="limeops-connection",
                    daemon=True,
                )
                thread.start()
        finally:
            server.close()
            self._server = None
            self._socket_path.unlink(missing_ok=True)

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.close()

    @staticmethod
    def _peer_fields(peer: PeerIdentity | None) -> dict:
        if peer is None:
            return {}
        return {
            "peer_pid": peer.pid,
            "peer_uid": peer.uid,
            "peer_gid": peer.gid,
        }

    @staticmethod
    def _send_public_error(connection: socket.socket, code: str, message: str) -> None:
        try:
            send_json(connection, public_error(code, message), max_size=MAX_RESPONSE_SIZE)
        except FrameError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local limeops policy broker.")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--policy", default=DEFAULT_POLICY_PATH)
    parser.add_argument("--audit", default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--group", default="limeops-client")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate policy and group configuration, then exit",
    )
    return parser


def main(argv=None, *, operation_factory=lambda: {}) -> int:
    args = build_parser().parse_args(argv)
    try:
        allowed_gid = grp.getgrnam(args.group).gr_gid
        policy = LimeOpsPolicy.from_file(args.policy)
    except (KeyError, PolicyError) as exc:
        print(f"limeopsd configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        return 0

    audit = JsonlAuditWriter(args.audit)
    broker = LimeOpsBroker(
        policy=policy,
        operations=operation_factory(),
        audit=audit,
    )
    server = LimeOpsUnixServer(
        broker=broker,
        audit=audit,
        socket_path=args.socket,
        allowed_gid=allowed_gid,
    )
    signal.signal(signal.SIGTERM, lambda *_args: server.stop())
    signal.signal(signal.SIGINT, lambda *_args: server.stop())
    server.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - target entrypoint
    from limeops.wiring import default_operation_factory

    raise SystemExit(main(operation_factory=default_operation_factory))
