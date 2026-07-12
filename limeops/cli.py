"""Command-line client for bounded LimeOS operational reads."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence

from limeops import __version__
from limeops.client import DEFAULT_SOCKET_PATH, LimeOpsClient, LimeOpsClientError


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DENIED = 3
EXIT_NOT_FOUND = 4
EXIT_UNAVAILABLE = 5
EXIT_TIMEOUT = 6
EXIT_UPSTREAM = 7
EXIT_AUDIT = 8
EXIT_PROTOCOL = 9

ERROR_EXIT_CODES = {
    "invalid_input": EXIT_USAGE,
    "denied_operation": EXIT_DENIED,
    "missing_resource": EXIT_NOT_FOUND,
    "unavailable_dependency": EXIT_UNAVAILABLE,
    "timeout": EXIT_TIMEOUT,
    "output_limit": EXIT_UPSTREAM,
    "upstream_failure": EXIT_UPSTREAM,
    "audit_failure": EXIT_AUDIT,
    "invalid_frame": EXIT_PROTOCOL,
    "invalid_encoding": EXIT_PROTOCOL,
    "invalid_json": EXIT_PROTOCOL,
    "invalid_request": EXIT_PROTOCOL,
    "invalid_response": EXIT_PROTOCOL,
}


def _bounded_lines(value: str) -> int:
    try:
        lines = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lines must be a number") from exc
    if not 20 <= lines <= 500:
        raise argparse.ArgumentTypeError("lines must be between 20 and 500")
    return lines


def _resource(parser: argparse.ArgumentParser, name: str = "name") -> None:
    parser.add_argument(name, help=f"Exact allowlisted {name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="limeops",
        description="Read LimeOS operational state through the local policy broker.",
        epilog="Use --json for the stable machine-readable response envelope.",
    )
    parser.add_argument(
        "--socket",
        default=os.getenv("LIMEOPS_SOCKET", DEFAULT_SOCKET_PATH),
        help="Broker Unix socket path",
    )
    parser.add_argument("--timeout", type=float, default=30, help="Socket timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Print the response envelope as JSON")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    context = commands.add_parser("context", help="Show safe host context and capabilities")
    context.set_defaults(operation="context")

    system = commands.add_parser("system", help="Read system state")
    system_commands = system.add_subparsers(dest="system_command", required=True)
    system_status = system_commands.add_parser("status", help="Show system status")
    system_status.set_defaults(operation="system.status")

    container = commands.add_parser("container", help="Read container state")
    container_commands = container.add_subparsers(dest="container_command", required=True)
    container_list = container_commands.add_parser("list", help="List containers")
    container_list.set_defaults(operation="container.list")
    container_status = container_commands.add_parser("status", help="Show container status")
    _resource(container_status)
    container_status.set_defaults(operation="container.status")
    container_logs = container_commands.add_parser("logs", help="Show bounded container logs")
    _resource(container_logs)
    container_logs.add_argument("--lines", type=_bounded_lines, default=200)
    container_logs.set_defaults(operation="container.logs")

    stack = commands.add_parser("stack", help="Read stack state")
    stack_commands = stack.add_subparsers(dest="stack_command", required=True)
    stack_list = stack_commands.add_parser("list", help="List stacks")
    stack_list.set_defaults(operation="stack.list")
    for action in ("status", "inspect"):
        action_parser = stack_commands.add_parser(action, help=f"{action.capitalize()} a stack")
        _resource(action_parser)
        action_parser.set_defaults(operation=f"stack.{action}")

    service = commands.add_parser("service", help="Read allowlisted service state")
    service_commands = service.add_subparsers(dest="service_command", required=True)
    service_status = service_commands.add_parser("status", help="Show service status")
    _resource(service_status)
    service_status.set_defaults(operation="service.status")
    service_logs = service_commands.add_parser("logs", help="Show bounded service logs")
    _resource(service_logs)
    service_logs.add_argument("--lines", type=_bounded_lines, default=200)
    service_logs.set_defaults(operation="service.logs")

    for noun, action, operation in (
        ("disk", "health", "disk.health"),
        ("mount", "status", "mount.status"),
        ("snapraid", "status", "snapraid.status"),
        ("installation", "inventory", "installation.inventory"),
    ):
        noun_parser = commands.add_parser(noun, help=f"Read {noun} state")
        noun_commands = noun_parser.add_subparsers(dest=f"{noun}_command", required=True)
        action_parser = noun_commands.add_parser(action, help=f"Show {noun} {action}")
        action_parser.set_defaults(operation=operation)

    network = commands.add_parser("network", help="Run bounded network reads")
    network_commands = network.add_subparsers(dest="network_command", required=True)
    network_check = network_commands.add_parser("check", help="Check an allowlisted target")
    _resource(network_check, "target")
    network_check.set_defaults(operation="network.check")
    return parser


def _params(args: argparse.Namespace) -> dict:
    params = {}
    if hasattr(args, "name"):
        params["name"] = args.name
    if hasattr(args, "target"):
        params["target"] = args.target
    if hasattr(args, "lines"):
        params["lines"] = args.lines
    return params


def _local_actor() -> dict[str, str]:
    return {
        "type": "local",
        "id": str(os.getuid()),
        "username": getpass.getuser(),
    }


def _client_error(exc: LimeOpsClientError) -> dict:
    return {
        "schema_version": "1",
        "request_id": "unknown",
        "ok": False,
        "operation": "unknown",
        "data": None,
        "warnings": [],
        "error": {"code": exc.code, "message": str(exc)},
        "audit_id": "unknown",
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory=LimeOpsClient,
) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout <= 0 or args.timeout > 120:
        build_parser().error("--timeout must be between 0 and 120 seconds")
    client = client_factory(socket_path=args.socket, timeout=args.timeout)
    try:
        response = client.request(args.operation, _params(args), _local_actor())
    except LimeOpsClientError as exc:
        response = _client_error(exc)

    error = response.get("error") if isinstance(response, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    exit_code = EXIT_OK if response.get("ok") is True else ERROR_EXIT_CODES.get(code, EXIT_UPSTREAM)

    if args.json:
        print(json.dumps(response, sort_keys=True))
    elif response.get("ok") is True:
        print(json.dumps(response.get("data"), indent=2, sort_keys=True))
        for warning in response.get("warnings") or []:
            print(f"warning: {warning}", file=sys.stderr)
    else:
        message = error.get("message") if isinstance(error, dict) else "Operation failed"
        print(f"error: {message}", file=sys.stderr)
    return exit_code
