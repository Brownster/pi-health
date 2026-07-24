"""Process entry point for model-free supervised repair scheduling."""

from __future__ import annotations

import argparse
import signal
import threading
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from agent_actions.canary import CanaryGateService
from agent_actions.defaults import build_repair_registry, read_agent_release_commit
from agent_actions.ledger import ActionLedger
from agent_actions.policy import ActionPolicy
from agent_supervision.authorization import SupervisionAuthorizer
from agent_supervision.reporting import (
    DEFAULT_DELIVERY_CONFIG_PATH,
    DEFAULT_DELIVERY_SECRET_PATH,
    MattermostIncidentDelivery,
)
from agent_supervision.runtime import SupervisedRepairRuntime
from agent_supervision.service import SupervisionService, SupervisionStore
from limeops.client import LimeOpsClient
from ports import ApschedulerAdapter


DEFAULT_SUPERVISION_PATH = (
    "/var/lib/limeos/agent-actions/supervision.sqlite3"
)
DEFAULT_LEDGER_PATH = "/var/lib/limeos/agent-actions/actions.sqlite3"
DEFAULT_SOCKET_PATH = "/run/limeos/limeops.sock"
DEFAULT_POLICY_PATH = "/etc/limeos/agent-action-policy.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run model-free LimeOS supervised repair scheduling."
    )
    parser.add_argument("--supervision", default=DEFAULT_SUPERVISION_PATH)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--policy", default=DEFAULT_POLICY_PATH)
    parser.add_argument(
        "--delivery-config", default=DEFAULT_DELIVERY_CONFIG_PATH
    )
    parser.add_argument(
        "--delivery-secrets", default=DEFAULT_DELIVERY_SECRET_PATH
    )
    parser.add_argument("--check", action="store_true")
    return parser


def build_runtime(
    args,
    *,
    scheduler=None,
    client=None,
    delivery=None,
    clock=_utcnow,
) -> SupervisedRepairRuntime:
    scheduler = scheduler or BackgroundScheduler(daemon=True)
    client = client or LimeOpsClient(socket_path=args.socket, timeout=30)
    delivery = delivery or MattermostIncidentDelivery(
        config_path=args.delivery_config,
        secrets_path=args.delivery_secrets,
    )
    store = SupervisionStore(Path(args.supervision))
    ledger = ActionLedger(Path(args.ledger))

    def diagnostic(operation, params, actor):
        return client.request(operation, dict(params), dict(actor))

    def container_status(name: str) -> Mapping:
        response = diagnostic(
            "container.status",
            {"name": name},
            {"type": "system", "id": "limeops-supervisor"},
        )
        data = response.get("data") if isinstance(response, Mapping) else None
        return data if isinstance(data, Mapping) else {}

    def unavailable(*_args):
        return {}
    registry = build_repair_registry(
        container_status=container_status,
        stack_status=unavailable,
        package_status=unavailable,
        package_job_status=unavailable,
        integration_status=unavailable,
        integration_job_status=unavailable,
        mattermost_status=unavailable,
        mattermost_job_status=unavailable,
        extension_status=unavailable,
        extension_job_status=unavailable,
    )
    canary_gate = CanaryGateService(
        registry=registry,
        ledger=ledger,
        release_commit_provider=read_agent_release_commit,
        clock=clock,
        id_factory=lambda: str(uuid.uuid4()),
    )
    authorizer = SupervisionAuthorizer(
        store=store,
        ledger=ledger,
        registry=registry,
        policy_provider=lambda: ActionPolicy.from_file(args.policy),
        canary_gate=canary_gate,
        clock=clock,
    )
    service = SupervisionService(store=store, clock=clock)
    return SupervisedRepairRuntime(
        store=store,
        service=service,
        authorizer=authorizer,
        ledger=ledger,
        scheduler=ApschedulerAdapter(scheduler),
        diagnostic=diagnostic,
        deliver=delivery,
        clock=clock,
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runtime = build_runtime(args)
    except Exception:
        return 2
    if args.check:
        return 0
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_args: stopping.set())
    signal.signal(signal.SIGINT, lambda *_args: stopping.set())
    try:
        runtime.init_scheduler()
    except Exception:
        return 1
    stopping.wait()
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
