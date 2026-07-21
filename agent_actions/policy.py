"""Strict, deny-by-default per-operation and per-target action policy."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.capability import (
    CAPABILITY_ID_RE,
    RESOURCE_RE,
    ActionActor,
    AuthorityMode,
    TriggerType,
)


_ROOT_FIELDS = frozenset(
    {"schema_version", "kill_switch", "defaults", "operations"}
)
_DEFAULT_FIELDS = frozenset({"proposal_ttl_seconds"})
_OPERATION_FIELDS = frozenset({"enabled", "approvers", "targets"})
_TARGET_FIELDS = frozenset(trigger.value for trigger in TriggerType)
MAX_OPERATIONS = 128
MAX_TARGETS = 256
MAX_APPROVERS = 128


class ActionPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TargetPolicy:
    modes: Mapping[TriggerType, AuthorityMode]

    def mode_for(self, trigger: TriggerType) -> AuthorityMode:
        return self.modes[trigger]


@dataclass(frozen=True)
class OperationActionPolicy:
    approvers: tuple[str, ...]
    targets: Mapping[str, TargetPolicy]


class ActionPolicy:
    def __init__(
        self,
        *,
        kill_switch: bool,
        proposal_ttl_seconds: int,
        operations: Mapping[str, OperationActionPolicy],
        configuration: Mapping[str, Any],
    ) -> None:
        self.kill_switch = kill_switch
        self.proposal_ttl_seconds = proposal_ttl_seconds
        self._operations = dict(operations)
        self._configuration = dict(configuration)

    @classmethod
    def from_file(cls, path: str | Path) -> ActionPolicy:
        try:
            value = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise ActionPolicyError("invalid_policy", "Action policy is unavailable") from exc
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: Any) -> ActionPolicy:
        if not isinstance(value, Mapping):
            raise ActionPolicyError("invalid_policy", "Action policy must be an object")
        cls._reject_unknown(value, _ROOT_FIELDS, "action policy")
        if value.get("schema_version") != "1":
            raise ActionPolicyError("invalid_policy", "Unsupported action policy version")
        kill_switch = value.get("kill_switch")
        if not isinstance(kill_switch, bool):
            raise ActionPolicyError("invalid_policy", "Action kill switch must be Boolean")
        defaults = value.get("defaults")
        operations = value.get("operations")
        if not isinstance(defaults, Mapping) or not isinstance(operations, Mapping):
            raise ActionPolicyError(
                "invalid_policy", "Action defaults and operations must be objects"
            )
        cls._reject_unknown(defaults, _DEFAULT_FIELDS, "action defaults")
        ttl = defaults.get("proposal_ttl_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 60 <= ttl <= 86400:
            raise ActionPolicyError("invalid_policy", "Proposal expiry is invalid")
        if len(operations) > MAX_OPERATIONS:
            raise ActionPolicyError("invalid_policy", "Too many action operations")

        normalized: dict[str, OperationActionPolicy] = {}
        configuration_operations: dict[str, Any] = {}
        for operation, raw in operations.items():
            if not isinstance(operation, str) or not CAPABILITY_ID_RE.fullmatch(operation):
                raise ActionPolicyError("invalid_policy", "Action operation is invalid")
            if not isinstance(raw, Mapping):
                raise ActionPolicyError("invalid_policy", "Action operation must be an object")
            cls._reject_unknown(raw, _OPERATION_FIELDS, f"action operation {operation}")
            enabled = raw.get("enabled")
            if not isinstance(enabled, bool):
                raise ActionPolicyError("invalid_policy", "Action enabled flag is invalid")
            approvers = cls._approvers(raw.get("approvers", []))
            targets = cls._targets(raw.get("targets", {}))
            configuration_operations[operation] = {
                "enabled": enabled,
                "approvers": list(approvers),
                "targets": {
                    target: {
                        trigger.value: target_policy.mode_for(trigger).value
                        for trigger in TriggerType
                    }
                    for target, target_policy in targets.items()
                },
            }
            if enabled:
                normalized[operation] = OperationActionPolicy(
                    approvers=approvers,
                    targets=targets,
                )
        return cls(
            kill_switch=kill_switch,
            proposal_ttl_seconds=ttl,
            operations=normalized,
            configuration={
                "schema_version": "1",
                "kill_switch": kill_switch,
                "defaults": {"proposal_ttl_seconds": ttl},
                "operations": configuration_operations,
            },
        )

    def mode_for(
        self, operation: str, target: str, trigger: TriggerType
    ) -> AuthorityMode:
        operation_policy = self._operations.get(operation)
        if operation_policy is None:
            raise ActionPolicyError("denied_operation", "Action operation is disabled")
        target_policy = operation_policy.targets.get(target)
        if target_policy is None:
            raise ActionPolicyError("denied_target", "Action target is not allowlisted")
        return target_policy.mode_for(trigger)

    def require_approver(self, operation: str, actor: ActionActor) -> None:
        operation_policy = self._operations.get(operation)
        if operation_policy is None or actor.key not in operation_policy.approvers:
            raise ActionPolicyError("denied_approver", "Actor cannot approve this action")

    def require_execution_enabled(self) -> None:
        if self.kill_switch:
            raise ActionPolicyError("kill_switch", "Agent actions are disabled")

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    def public_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._configuration))

    def capability_policy(self, operation: str) -> dict[str, Any]:
        raw = self._configuration["operations"].get(operation)
        if raw is None:
            return {"enabled": False, "targets": {}}
        return {
            "enabled": raw["enabled"],
            "targets": json.loads(json.dumps(raw["targets"])),
        }

    @staticmethod
    def _reject_unknown(value: Mapping, allowed: frozenset[str], label: str) -> None:
        unknown = set(value) - allowed
        if unknown:
            raise ActionPolicyError(
                "invalid_policy", f"Unknown {label} field: {sorted(unknown)[0]}"
            )

    @classmethod
    def _targets(cls, value: Any) -> dict[str, TargetPolicy]:
        if not isinstance(value, Mapping) or len(value) > MAX_TARGETS:
            raise ActionPolicyError("invalid_policy", "Action targets are invalid")
        targets = {}
        for target, raw in value.items():
            if not isinstance(target, str) or not RESOURCE_RE.fullmatch(target):
                raise ActionPolicyError("invalid_policy", "Action target is invalid")
            if not isinstance(raw, Mapping):
                raise ActionPolicyError("invalid_policy", "Target policy must be an object")
            cls._reject_unknown(raw, _TARGET_FIELDS, f"action target {target}")
            if set(raw) != _TARGET_FIELDS:
                raise ActionPolicyError(
                    "invalid_policy", "Target policy must define every trigger"
                )
            try:
                modes = {
                    trigger: AuthorityMode(raw[trigger.value]) for trigger in TriggerType
                }
            except (KeyError, ValueError) as exc:
                raise ActionPolicyError(
                    "invalid_policy", "Target authority mode is invalid"
                ) from exc
            targets[target] = TargetPolicy(modes=modes)
        return targets

    @staticmethod
    def _approvers(value: Any) -> tuple[str, ...]:
        if not isinstance(value, list) or len(value) > MAX_APPROVERS:
            raise ActionPolicyError("invalid_policy", "Action approvers are invalid")
        approvers = []
        for item in value:
            if not isinstance(item, str) or ":" not in item or len(item) > 160:
                raise ActionPolicyError("invalid_policy", "Action approver is invalid")
            actor_type, _, actor_id = item.partition(":")
            if actor_type not in {"local", "mattermost"} or not RESOURCE_RE.fullmatch(
                actor_id
            ):
                raise ActionPolicyError("invalid_policy", "Action approver is invalid")
            if item in approvers:
                raise ActionPolicyError("invalid_policy", "Action approver is duplicated")
            approvers.append(item)
        return tuple(approvers)
