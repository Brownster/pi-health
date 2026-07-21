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


def build_repair_registry(
    *, container_status: Callable[[str], Mapping[str, Any]]
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

    return CapabilityRegistry(
        [
            container_capability("container.start", "Start"),
            container_capability("container.restart", "Restart"),
        ]
    )


def build_action_service(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    policy_path: str | Path = DEFAULT_ACTION_POLICY_PATH,
    ledger_path: str | Path = DEFAULT_ACTION_LEDGER_PATH,
) -> AgentActionService:
    return AgentActionService(
        registry=build_repair_registry(container_status=container_status),
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
