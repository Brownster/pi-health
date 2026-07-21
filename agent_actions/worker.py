"""Trusted queue worker that forwards authorised IDs to the action broker."""

from __future__ import annotations

import argparse
import signal
import threading
import time

from agent_actions.ledger import ActionLedger, ActionState
from limeops.client import LimeOpsClient


DEFAULT_SOCKET_PATH = "/run/limeos-actions/actions.sock"
DEFAULT_LEDGER_PATH = "/var/lib/limeos/agent-actions/actions.sqlite3"


def run_once(ledger: ActionLedger, client: LimeOpsClient) -> bool:
    action = next(
        (item for item in reversed(ledger.list(limit=200)) if item.state == ActionState.AUTHORISED),
        None,
    )
    if action is None:
        return False
    response = client.request(
        "action.execute",
        {"action_id": action.action_id},
        {"type": "system", "id": "limeops-action-worker"},
    )
    return bool(response.get("ok"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the LimeOS action queue worker.")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.25 <= args.poll_seconds <= 60:
        return 2
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    ledger = ActionLedger(args.ledger)
    client = LimeOpsClient(socket_path=args.socket, timeout=120)
    while not stopping.is_set():
        try:
            worked = run_once(ledger, client)
        except Exception:
            worked = False
        if not worked:
            stopping.wait(args.poll_seconds)
        else:
            time.sleep(0)
    return 0


if __name__ == "__main__":  # pragma: no cover - target entrypoint
    raise SystemExit(main())
