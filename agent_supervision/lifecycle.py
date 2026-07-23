"""Fail-closed lifecycle commands for the isolated supervision runtime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from agent_actions.ledger import ActionLedger


DEFAULT_LEDGER_PATH = "/var/lib/limeos/agent-actions/actions.sqlite3"


def disable_pending_actions(
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    *,
    at: datetime | None = None,
) -> int:
    """Cancel queued supervised actions while allowing claimed work to finish."""
    moment = at or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ValueError("Lifecycle time must include a timezone")
    cancelled = ActionLedger(ledger_path).cancel_pending_supervised_actions(
        cancelled_at=moment.astimezone(timezone.utc).isoformat()
    )
    return len(cancelled)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply an AI Agents lifecycle transition to supervision."
    )
    parser.add_argument("command", choices=("disable",))
    parser.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "disable":
            disable_pending_actions(args.ledger)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
