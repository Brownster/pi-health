"""Default repair capability contracts and lazy application wiring."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_actions.capability import (
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
)
from agent_actions.ledger import ActionLedger
from agent_actions.policy import ActionPolicy
from agent_actions.service import AgentActionService
from runtime_paths import CONFIG_DIR, STATE_DIR


DEFAULT_ACTION_POLICY_PATH = CONFIG_DIR / "agent-action-policy.json"
DEFAULT_ACTION_LEDGER_PATH = STATE_DIR / "agent-actions" / "actions.sqlite3"


def _container_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"}:
        raise CapabilityError("Container action accepts only a name")
    name = params.get("name")
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 128
        or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in name)
    ):
        raise CapabilityError("Container name is invalid")
    return {"name": name}


def _safe_container_precondition(
    status_reader: Callable[[str], Mapping[str, Any]], name: str
) -> dict[str, Any]:
    status = status_reader(name)
    if not isinstance(status, Mapping):
        raise CapabilityError("Container status is unavailable")
    return {
        "name": str(status.get("name") or name),
        "id": str(status.get("id") or ""),
        "status": str(status.get("status") or "unknown"),
        "health": str(status.get("health") or ""),
        "started_at": str(status.get("started_at") or ""),
        "image_id": str(status.get("image_id") or ""),
    }


def _stack_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"}:
        raise CapabilityError("Stack action accepts only a name")
    name = params.get("name")
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or not name[0].isalnum()
        or ".." in name
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in name
        )
    ):
        raise CapabilityError("Stack name is invalid")
    return {"name": name}


def safe_stack_precondition(
    status_reader: Callable[[str], Mapping[str, Any]], name: str
) -> dict[str, Any]:
    value = status_reader(name)
    if not isinstance(value, Mapping):
        raise CapabilityError("Stack status is unavailable")
    raw_services = value.get("services")
    runtime = value.get("status")
    if not isinstance(raw_services, list) or not isinstance(runtime, Mapping):
        raise CapabilityError("Stack status is unavailable")
    expected_services = sorted(
        {
            str(item.get("name"))
            for item in raw_services
            if isinstance(item, Mapping) and item.get("name")
        }
    )
    if not expected_services:
        raise CapabilityError("Stack has no reconcilable services")
    raw_containers = runtime.get("containers")
    if not isinstance(raw_containers, list):
        raise CapabilityError("Stack runtime status is unavailable")
    containers = sorted(
        (
            {
                "name": str(item.get("name") or ""),
                "service": str(item.get("service") or ""),
                "status": str(item.get("status") or "unknown"),
                "health": str(item.get("health") or ""),
            }
            for item in raw_containers
            if isinstance(item, Mapping)
        ),
        key=lambda item: (item["service"], item["name"]),
    )
    return {
        "name": name,
        "compose_file": str(value.get("compose_file") or ""),
        "expected_services": expected_services,
        "status": str(runtime.get("status") or "unknown"),
        "containers": containers,
    }


def build_repair_registry(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    stack_status: Callable[[str], Mapping[str, Any]],
) -> CapabilityRegistry:
    modes = (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
        AuthorityMode.SUPERVISED,
        AuthorityMode.AUTONOMOUS,
    )

    def container_capability(operation: str, verb: str) -> CapabilitySpec:
        return CapabilitySpec(
            operation=operation,
            version="1",
            risk=RiskClass.REVERSIBLE,
            eligible_modes=modes,
            normalize_params=_container_params,
            select_target=lambda params: params["name"],
            read_precondition=lambda params: _safe_container_precondition(
                container_status, params["name"]
            ),
            render_impact=lambda params: (
                f"{verb} the allowlisted {params['name']} container. "
                "The service may be briefly unavailable."
            ),
        )

    stack_modes = (AuthorityMode.PROPOSE, AuthorityMode.APPROVAL)
    stack_capability = CapabilitySpec(
        operation="stack.reconcile",
        version="1",
        risk=RiskClass.MUTATING,
        eligible_modes=stack_modes,
        normalize_params=_stack_params,
        select_target=lambda params: params["name"],
        read_precondition=lambda params: safe_stack_precondition(
            stack_status, params["name"]
        ),
        render_impact=lambda params: (
            f"Reconcile the allowlisted {params['name']} stack to its existing Compose "
            "definition. Services may be recreated or briefly unavailable, and "
            "same-project orphan containers will be removed."
        ),
    )

    return CapabilityRegistry(
        [
            container_capability("container.start", "Start"),
            container_capability("container.restart", "Restart"),
            stack_capability,
        ]
    )


def build_action_service(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    stack_status: Callable[[str], Mapping[str, Any]],
    policy_path: str | Path = DEFAULT_ACTION_POLICY_PATH,
    ledger_path: str | Path = DEFAULT_ACTION_LEDGER_PATH,
) -> AgentActionService:
    return AgentActionService(
        registry=build_repair_registry(
            container_status=container_status,
            stack_status=stack_status,
        ),
        policy_provider=lambda: ActionPolicy.from_file(policy_path),
        ledger=ActionLedger(ledger_path),
    )


class LazyAgentActionService:
    """Delay filesystem access until an action endpoint or proposal is used."""

    def __init__(self, factory: Callable[[], AgentActionService]) -> None:
        self._factory = factory
        self._service: AgentActionService | None = None
        self._lock = threading.Lock()

    def _get(self) -> AgentActionService:
        with self._lock:
            if self._service is None:
                self._service = self._factory()
            return self._service

    def propose(self, **kwargs):
        return self._get().propose(**kwargs)

    def approve(self, *args, **kwargs):
        return self._get().approve(*args, **kwargs)

    def reject(self, *args, **kwargs):
        return self._get().reject(*args, **kwargs)

    def cancel(self, *args, **kwargs):
        return self._get().cancel(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._get().get(*args, **kwargs)

    def list(self, **kwargs):
        return self._get().list(**kwargs)

    def capabilities(self):
        return self._get().capabilities()

    def policy(self):
        return self._get().policy()

    def validate_policy(self, value):
        return self._get().validate_policy(value)
