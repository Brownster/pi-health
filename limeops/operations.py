"""Bounded diagnostic and local action-proposal operations behind the broker.

Every handler is a thin, bounded adapter over an injected domain reader — nothing here
constructs Docker, helper, or filesystem access itself, and nothing mutates. The broker
remains the authorization boundary (policy, resource allowlists, timeouts, output
limits, audit); this module adds the diagnostic behavior, a proposal-only bridge, and
the redaction/sanitization guarantees:

- Log text is redacted (passwords, tokens, bearer headers, webhook URLs, URL
  credentials) and byte-bounded below the policy output limit, with an explicit
  truncation flag.
- `stack.inspect` never returns compose or env *content* — only structure with
  environment variable **keys** (values are secrets).
- Parameter validators are strict: unknown fields are rejected before dispatch.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from limeops.broker import OperationDefinition

MIN_LOG_LINES = 20
MAX_LOG_LINES = 500
DEFAULT_LOG_LINES = 200
#: Kept under the 131072-byte policy cap for log operations so redacted, truncated
#: output returns as data instead of tripping the broker's output_limit error.
MAX_LOG_TEXT_BYTES = 120_000

_REDACTED = "[redacted]"
# All quantifiers are bounded: log content is attacker-influenced, and an unbounded
# quantifier ahead of a required literal (e.g. `[a-z0-9+.-]*` before `://`) scans
# quadratically on long secret-free lines — a redaction-time DoS.
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|auth|"
        r"database[_-]?url|db[_-]?url|connection[_-]?string|dsn)\b"
        r"(\s*[=:]\s*)\S{1,512}"
    ),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{1,512}"),
    re.compile(
        r"(?i)\b([a-z][a-z0-9+.-]{0,15}://)[^\s/@]{1,256}:[^\s/@]{1,256}@"
    ),  # credentials inside URLs
    re.compile(r"(?i)https?://\S{0,2048}/hooks/\S{1,512}"),  # incoming-webhook URLs
)


def redact_text(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub(rf"\1\2{_REDACTED}", text)
    text = _SECRET_PATTERNS[1].sub(_REDACTED, text)
    text = _SECRET_PATTERNS[2].sub(rf"\1{_REDACTED}@", text)
    text = _SECRET_PATTERNS[3].sub(_REDACTED, text)
    return text


def bounded_log(text: str) -> dict[str, Any]:
    """Redact then byte-bound log text, flagging truncation explicitly."""
    redacted = redact_text(text or "")
    encoded = redacted.encode("utf-8")
    truncated = len(encoded) > MAX_LOG_TEXT_BYTES
    if truncated:
        redacted = encoded[-MAX_LOG_TEXT_BYTES:].decode("utf-8", errors="ignore")
    return {"text": redacted, "truncated": truncated}


def sanitize_stack_details(details: Mapping[str, Any], compose: Mapping[str, Any]) -> dict:
    """Structure-only stack view: services, images, ports, env KEYS — never values."""
    services = []
    for service_name, service in ((compose or {}).get("services") or {}).items():
        if not isinstance(service, Mapping):
            continue
        environment = service.get("environment")
        if isinstance(environment, Mapping):
            env_keys = sorted(str(key) for key in environment)
        elif isinstance(environment, list):
            env_keys = sorted(str(item).partition("=")[0] for item in environment)
        else:
            env_keys = []
        services.append(
            {
                "name": str(service_name),
                "image": str(service.get("image") or ""),
                "ports": [str(port) for port in (service.get("ports") or [])],
                "restart": str(service.get("restart") or ""),
                "depends_on": sorted(str(dep) for dep in (service.get("depends_on") or [])),
                "environment_keys": env_keys,
            }
        )
    return {
        "name": str(details.get("name") or ""),
        "compose_file": str(details.get("compose_file") or ""),
        "has_env": bool(details.get("has_env")),
        "status": details.get("status"),
        "services": services,
    }


# -- parameter validators (strict: unknown fields rejected) ---------------------
def _require_fields(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"Unknown parameters: {', '.join(sorted(unknown))}")


def _name(params: Mapping[str, Any], field: str) -> str:
    value = params.get(field)
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError(f"Parameter '{field}' must be a short string")
    return value


def _no_params(params: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_fields(params, set())
    return {}


def _name_params(field: str) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    def validate(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_fields(params, {field})
        return {field: _name(params, field)}

    return validate


def _log_params(field: str) -> Callable[[Mapping[str, Any]], Mapping[str, Any]]:
    def validate(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_fields(params, {field, "lines"})
        lines = params.get("lines", DEFAULT_LOG_LINES)
        if not isinstance(lines, int) or isinstance(lines, bool):
            raise ValueError("Parameter 'lines' must be an integer")
        if not MIN_LOG_LINES <= lines <= MAX_LOG_LINES:
            raise ValueError(
                f"Parameter 'lines' must be between {MIN_LOG_LINES} and {MAX_LOG_LINES}"
            )
        return {field: _name(params, field), "lines": lines}

    return validate


def _action_proposal_params(params: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_fields(
        params,
        {"operation", "params", "reason", "evidence_ids", "idempotency_key"},
    )
    operation = _name(params, "operation")
    action_params = params.get("params")
    reason = params.get("reason")
    idempotency_key = params.get("idempotency_key")
    evidence_ids = params.get("evidence_ids", [])
    if not isinstance(action_params, Mapping):
        raise ValueError("Parameter 'params' must be an object")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("Parameter 'reason' must be a non-empty string")
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise ValueError("Parameter 'idempotency_key' must be a short string")
    if (
        not isinstance(evidence_ids, list)
        or len(evidence_ids) > 15
        or any(not isinstance(item, str) for item in evidence_ids)
    ):
        raise ValueError("Parameter 'evidence_ids' must be a short string list")
    return {
        "operation": operation,
        "params": dict(action_params),
        "reason": reason.strip(),
        "evidence_ids": list(evidence_ids),
        "idempotency_key": idempotency_key,
    }


def _finding_proposal_params(params: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_fields(params, {"finding", "evidence_ids"})
    finding = params.get("finding")
    evidence_ids = params.get("evidence_ids", [])
    if not isinstance(finding, Mapping):
        raise ValueError("Parameter 'finding' must be an object")
    if (
        not isinstance(evidence_ids, list)
        or len(evidence_ids) > 15
        or any(not isinstance(item, str) for item in evidence_ids)
    ):
        raise ValueError("Parameter 'evidence_ids' must be a short string list")
    return {"finding": dict(finding), "evidence_ids": list(evidence_ids)}


# -- dependencies ----------------------------------------------------------------
@dataclass(frozen=True)
class DiagnosticDependencies:
    """Injected bounded domain adapters. Each returns JSON-serializable data."""

    system_status: Callable[[], dict]
    list_containers: Callable[[], list]
    container_status: Callable[[str], dict]
    container_logs: Callable[[str, int], str]
    list_stacks: Callable[[], list]
    stack_status: Callable[[str], dict]
    stack_inspect: Callable[[str], dict]
    service_status: Callable[[str], dict]
    service_logs: Callable[[str, int], str]
    disk_health: Callable[[], dict]
    mount_status: Callable[[], dict]
    snapraid_status: Callable[[], dict]
    network_check: Callable[[str], dict]
    installation_inventory: Callable[[], dict]
    package_status: Callable[[], dict]
    package_pending: Callable[[], dict] = lambda: {"pending": []}
    action_propose: Callable[[Mapping[str, Any], Mapping[str, str], str], dict] = (
        lambda params, actor, audit_id: {
            "available": False,
            "message": "Action proposal service is unavailable",
        }
    )
    finding_propose: Callable[[Mapping[str, Any], Mapping[str, str], str], dict] = (
        lambda params, actor, audit_id: {
            "available": False,
            "message": "Finding proposal service is unavailable",
        }
    )


def build_operations(deps: DiagnosticDependencies) -> dict[str, OperationDefinition]:
    operations: dict[str, OperationDefinition] = {}

    def add(
        name: str,
        handler: Callable[[Mapping[str, Any], Any], Any],
        validate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        resource_param: str | None = None,
    ) -> None:
        operations[name] = OperationDefinition(
            handler=handler, validate_params=validate, resource_param=resource_param
        )

    def context_handler(_params: Mapping[str, Any], _context: Any) -> dict:
        return {
            "capabilities": "read-and-propose",
            "operations": sorted(operations),
        }

    add("context", context_handler, _no_params)
    add("system.status", lambda p, c: deps.system_status(), _no_params)
    add("container.list", lambda p, c: {"containers": deps.list_containers()}, _no_params)
    add(
        "container.status",
        lambda p, c: deps.container_status(p["name"]),
        _name_params("name"),
        resource_param="name",
    )
    add(
        "container.logs",
        lambda p, c: bounded_log(deps.container_logs(p["name"], p["lines"])),
        _log_params("name"),
        resource_param="name",
    )
    add("stack.list", lambda p, c: {"stacks": deps.list_stacks()}, _no_params)
    add(
        "stack.status",
        lambda p, c: deps.stack_status(p["name"]),
        _name_params("name"),
        resource_param="name",
    )
    add(
        "stack.inspect",
        lambda p, c: deps.stack_inspect(p["name"]),
        _name_params("name"),
        resource_param="name",
    )
    add(
        "service.status",
        lambda p, c: deps.service_status(p["unit"]),
        _name_params("unit"),
        resource_param="unit",
    )
    add(
        "service.logs",
        lambda p, c: bounded_log(deps.service_logs(p["unit"], p["lines"])),
        _log_params("unit"),
        resource_param="unit",
    )
    add("disk.health", lambda p, c: deps.disk_health(), _no_params)
    add("mount.status", lambda p, c: deps.mount_status(), _no_params)
    add("snapraid.status", lambda p, c: deps.snapraid_status(), _no_params)
    add(
        "network.check",
        lambda p, c: deps.network_check(p["target"]),
        _name_params("target"),
        resource_param="target",
    )
    add(
        "installation.inventory",
        lambda p, c: deps.installation_inventory(),
        _no_params,
    )
    add("packages.status", lambda p, c: deps.package_status(), _no_params)
    add("packages.pending", lambda p, c: deps.package_pending(), _no_params)
    add(
        "action.propose",
        lambda p, c: deps.action_propose(p, c.actor, c.audit_id),
        _action_proposal_params,
    )
    add(
        "finding.propose",
        lambda p, c: deps.finding_propose(p, c.actor, c.audit_id),
        _finding_proposal_params,
    )
    return operations
