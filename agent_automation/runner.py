"""Least-privileged process entry point for report-only automation."""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from agent_automation.reporting import MattermostReportDelivery
from agent_automation.service import AutomationError, AutomationStore, ReportSchedulerService
from limeops.client import LimeOpsClient
from ports import ApschedulerAdapter


DEFAULT_LEDGER_PATH = "/var/lib/limeos/agent-actions/automation.sqlite3"
DEFAULT_SOCKET_PATH = "/run/limeos/limeops.sock"
DEFAULT_SECRETS_PATH = "/etc/limeos/integrations/agent-report/mattermost-webhook.env"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run report-only LimeOS automation.")
    parser.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--secrets", default=DEFAULT_SECRETS_PATH)
    parser.add_argument("--check", action="store_true")
    return parser


def build_service(args, *, scheduler=None, client=None, reporter=None):
    scheduler = scheduler or BackgroundScheduler(daemon=True)
    client = client or LimeOpsClient(socket_path=args.socket, timeout=120)
    reporter = reporter or MattermostReportDelivery(secrets_path=args.secrets)
    return ReportSchedulerService(
        store=AutomationStore(Path(args.ledger)),
        scheduler=ApschedulerAdapter(scheduler),
        diagnostic=lambda operation, params, actor: client.request(
            operation, params, actor
        ),
        reporter=reporter,
        trigger_factory=lambda cron, timezone: CronTrigger.from_crontab(
            cron, timezone=ZoneInfo(timezone)
        ),
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        service = build_service(args)
    except AutomationError:
        return 2
    if args.check:
        return 0
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    service.init_scheduler()
    stopping.wait()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
