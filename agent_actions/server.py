"""Separate Unix-socket process for trusted action execution."""

from __future__ import annotations

import argparse
import grp
import signal
import subprocess
import sys

from agent_actions.actuator import (
    ActionActuator,
    build_container_executors,
    build_integration_executors,
    build_job_retry_executors,
    build_package_executors,
    build_stack_executors,
)
from agent_actions.broker import build_actuator_operations
from agent_actions.defaults import build_repair_registry
from agent_actions.integrations import agent_integration_status, agent_repair_job_status
from agent_actions.ledger import ActionLedger
from agent_actions.packages import package_job_status, package_repair_status
from agent_actions.policy import ActionPolicy, ActionPolicyError
from container_operations_service import ContainerOperationsService
from helper_client import HelperError, helper_call
from limeops.broker import JsonlAuditWriter, LimeOpsBroker
from limeops.policy import LimeOpsPolicy, PolicyError
from limeops.server import LimeOpsUnixServer
from limeops.wiring import _container_action_status, _stack_inspect
from ports import DockerClientAdapter
from stack_manager import default_stack_operations_service


DEFAULT_SOCKET_PATH = "/run/limeos-actions/actions.sock"
DEFAULT_BROKER_POLICY_PATH = "/etc/limeos/agent-actuator-policy.json"
DEFAULT_ACTION_POLICY_PATH = "/etc/limeos/agent-action-policy.json"
DEFAULT_LEDGER_PATH = "/var/lib/limeos/agent-actions/actions.sqlite3"
DEFAULT_AUDIT_PATH = "/var/log/limeos/agent-action-audit.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the LimeOS action broker.")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH)
    parser.add_argument("--broker-policy", default=DEFAULT_BROKER_POLICY_PATH)
    parser.add_argument("--action-policy", default=DEFAULT_ACTION_POLICY_PATH)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--audit", default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--group", default="limeops-action")
    parser.add_argument("--check", action="store_true")
    return parser


def _build_actuator(action_policy_path: str, ledger_path: str) -> ActionActuator:
    try:
        import docker

        docker_client = docker.from_env()
    except Exception:
        docker_client = None
    container_service = ContainerOperationsService(
        docker=DockerClientAdapter(docker_client),
        compose_runner=subprocess.run,
        update_writer=lambda container_id, available: None,
    )
    stack_service = default_stack_operations_service()

    def reconcile_stack(name: str):
        result, error = stack_service.run(
            name, "up", detach=True, timeout_seconds=60
        )
        if error or not result or result.get("success") is not True:
            return {"error": "stack_reconcile_failed"}
        return {"reconciled": True}

    registry = build_repair_registry(
        container_status=_container_action_status,
        stack_status=_stack_inspect,
        package_status=package_repair_status,
        package_job_status=package_job_status,
        integration_status=agent_integration_status,
        integration_job_status=agent_repair_job_status,
    )
    executors = build_container_executors(
        control=container_service.control,
        status_reader=_container_action_status,
    )
    executors.update(
        build_stack_executors(
            reconcile=reconcile_stack,
            status_reader=_stack_inspect,
        )
    )

    def start_package_reconcile():
        try:
            result = helper_call("packages_agent_reconcile_start", {}, timeout=15)
        except HelperError:
            return {"error": "package_reconcile_unavailable"}
        if not isinstance(result, dict) or result.get("success") is not True:
            return {"error": "package_reconcile_start_failed"}
        return {"started": True}

    executors.update(
        build_package_executors(
            start=start_package_reconcile,
            status_reader=package_repair_status,
            job_status_reader=package_job_status,
        )
    )

    def start_agent_repair():
        try:
            result = helper_call("agent_integration_repair_start", {}, timeout=15)
        except HelperError:
            return {"error": "agent_repair_unavailable"}
        if not isinstance(result, dict) or result.get("success") is not True:
            return {"error": "agent_repair_start_failed"}
        return {"started": True}

    def agent_runtime_health():
        try:
            result = helper_call("agent_runtime_status", {}, timeout=30)
        except HelperError:
            return {}
        return result if isinstance(result, dict) else {}

    executors.update(
        build_integration_executors(
            start=start_agent_repair,
            status_reader=agent_integration_status,
            job_status_reader=agent_repair_job_status,
            runtime_status_reader=agent_runtime_health,
        )
    )

    def retry_job(name: str):
        try:
            result = helper_call(
                "agent_job_retry_start", {"name": name}, timeout=15
            )
        except HelperError:
            return {"error": "job_retry_unavailable"}
        if not isinstance(result, dict) or result.get("success") is not True:
            return {"error": "job_retry_start_failed"}
        return {"started": True}

    executors.update(
        build_job_retry_executors(
            start=retry_job,
            status_reader=package_repair_status,
            job_status_reader=package_job_status,
        )
    )
    return ActionActuator(
        registry=registry,
        executors=executors,
        policy_provider=lambda: ActionPolicy.from_file(action_policy_path),
        ledger=ActionLedger(ledger_path),
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        allowed_gid = grp.getgrnam(args.group).gr_gid
        broker_policy = LimeOpsPolicy.from_file(args.broker_policy)
        ActionPolicy.from_file(args.action_policy)
    except (KeyError, PolicyError, ActionPolicyError) as exc:
        print(f"limeops-actuatord configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        return 0

    audit = JsonlAuditWriter(args.audit)
    actuator = _build_actuator(args.action_policy, args.ledger)
    broker = LimeOpsBroker(
        policy=broker_policy,
        operations=build_actuator_operations(actuator),
        audit=audit,
    )
    server = LimeOpsUnixServer(
        broker=broker,
        audit=audit,
        socket_path=args.socket,
        allowed_gid=allowed_gid,
        max_connections=2,
    )
    signal.signal(signal.SIGTERM, lambda *_args: server.stop())
    signal.signal(signal.SIGINT, lambda *_args: server.stop())
    server.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - target entrypoint
    raise SystemExit(main())
