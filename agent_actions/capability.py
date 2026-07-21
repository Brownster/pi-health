"""Code-owned action capability contracts.

Configuration may select a registered operation and target, but it cannot provide
executable handlers, commands, verification, or rollback logic.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
VERSION_RE = re.compile(r"^[1-9][0-9]{0,5}$")


class CapabilityError(ValueError):
    """A capability contract or payload is invalid."""


class RiskClass(str, Enum):
    READ = "R0"
    REVERSIBLE = "R1"
    MUTATING = "R2"
    SENSITIVE = "R3"
    PROHIBITED = "R4"


class AuthorityMode(str, Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    APPROVAL = "approval"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class TriggerType(str, Enum):
    INTERACTIVE = "interactive"
    SCHEDULED = "scheduled"
    EVENT = "event"


@dataclass(frozen=True)
class ActionActor:
    type: str
    id: str
    username: str | None = None

    @classmethod
    def from_mapping(cls, value: Any) -> ActionActor:
        if not isinstance(value, Mapping) or set(value) - {"type", "id", "username"}:
            raise CapabilityError("Actor is invalid")
        actor_type = value.get("type")
        actor_id = value.get("id")
        username = value.get("username")
        if actor_type not in {"local", "mattermost", "system"}:
            raise CapabilityError("Actor type is invalid")
        if not isinstance(actor_id, str) or not RESOURCE_RE.fullmatch(actor_id):
            raise CapabilityError("Actor id is invalid")
        if username is not None and (
            not isinstance(username, str)
            or not username
            or len(username) > 128
            or any(character in username for character in "\x00\r\n")
        ):
            raise CapabilityError("Actor username is invalid")
        return cls(type=actor_type, id=actor_id, username=username)

    @property
    def key(self) -> str:
        return f"{self.type}:{self.id}"


ParamsNormalizer = Callable[[Mapping[str, Any]], dict[str, Any]]
TargetSelector = Callable[[Mapping[str, Any]], str]
PreconditionReader = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ImpactRenderer = Callable[[Mapping[str, Any]], str]


@dataclass(frozen=True)
class CapabilitySpec:
    operation: str
    version: str
    risk: RiskClass
    eligible_modes: tuple[AuthorityMode, ...]
    normalize_params: ParamsNormalizer
    select_target: TargetSelector
    read_precondition: PreconditionReader
    render_impact: ImpactRenderer

    def __post_init__(self) -> None:
        if not CAPABILITY_ID_RE.fullmatch(self.operation):
            raise CapabilityError("Capability operation is invalid")
        if not VERSION_RE.fullmatch(self.version):
            raise CapabilityError("Capability version is invalid")
        if not self.eligible_modes or len(set(self.eligible_modes)) != len(
            self.eligible_modes
        ):
            raise CapabilityError("Capability authority modes are invalid")
        if self.risk == RiskClass.PROHIBITED:
            raise CapabilityError("Prohibited operations cannot be registered")
        if self.risk == RiskClass.SENSITIVE and any(
            mode in {AuthorityMode.SUPERVISED, AuthorityMode.AUTONOMOUS}
            for mode in self.eligible_modes
        ):
            raise CapabilityError("Sensitive operations must remain approval-bound")

    def normalize(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise CapabilityError("Capability parameters must be an object")
        normalized = self.normalize_params(value)
        if not isinstance(normalized, dict):
            raise CapabilityError("Capability normalizer returned invalid parameters")
        canonical_json(normalized)
        return normalized

    def target(self, params: Mapping[str, Any]) -> str:
        target = self.select_target(params)
        if not isinstance(target, str) or not RESOURCE_RE.fullmatch(target):
            raise CapabilityError("Capability target is invalid")
        return target

    def precondition(self, params: Mapping[str, Any]) -> Mapping[str, Any]:
        value = self.read_precondition(params)
        if not isinstance(value, Mapping):
            raise CapabilityError("Capability precondition is invalid")
        canonical_json(value)
        return value

    def impact(self, params: Mapping[str, Any]) -> str:
        value = self.render_impact(params)
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 1000
            or any(character in value for character in "\x00\r")
        ):
            raise CapabilityError("Capability impact is invalid")
        return value


class CapabilityRegistry:
    def __init__(self, capabilities: tuple[CapabilitySpec, ...] | list[CapabilitySpec]):
        self._capabilities: dict[str, CapabilitySpec] = {}
        for capability in capabilities:
            if capability.operation in self._capabilities:
                raise CapabilityError("Capability operation is duplicated")
            self._capabilities[capability.operation] = capability

    def require(self, operation: str) -> CapabilitySpec:
        capability = self._capabilities.get(operation)
        if capability is None:
            raise CapabilityError("Capability is not registered")
        return capability

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._capabilities))


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CapabilityError("Value is not canonical JSON") from exc


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
