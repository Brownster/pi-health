"""Fail-closed operation policy for the limeops broker."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z][a-z0-9]*)*$")
MAX_POLICY_TIMEOUT_SECONDS = 120
MAX_POLICY_OUTPUT_BYTES = 1024 * 1024
_TOP_LEVEL_KEYS = frozenset({"schema_version", "defaults", "operations"})
_DEFAULT_KEYS = frozenset({"timeout_seconds", "max_output_bytes"})
_OPERATION_KEYS = frozenset(
    {"enabled", "timeout_seconds", "max_output_bytes", "resources"}
)


class PolicyError(Exception):
    """Invalid policy configuration or a denied operation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class OperationPolicy:
    timeout_seconds: float
    max_output_bytes: int
    resources: tuple[str, ...]

    def require_resource(self, resource: Any) -> str:
        if not isinstance(resource, str) or resource not in self.resources:
            raise PolicyError("denied_operation", "Resource is denied by policy")
        return resource


class LimeOpsPolicy:
    def __init__(self, operations: Mapping[str, OperationPolicy]) -> None:
        self._operations = dict(operations)

    @classmethod
    def from_file(cls, path: str | Path) -> "LimeOpsPolicy":
        try:
            value = json.loads(Path(path).read_text())
        except (OSError, ValueError) as exc:
            raise PolicyError("invalid_policy", "Unable to read limeops policy") from exc
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: Any) -> "LimeOpsPolicy":
        if not isinstance(value, Mapping) or not value:
            raise PolicyError("invalid_policy", "Policy must be a JSON object")
        cls._reject_unknown(value, _TOP_LEVEL_KEYS, "policy")
        if value.get("schema_version") != "1":
            raise PolicyError("invalid_policy", "Unsupported policy schema version")

        defaults = value.get("defaults")
        operations = value.get("operations")
        if not isinstance(defaults, Mapping) or not isinstance(operations, Mapping):
            raise PolicyError(
                "invalid_policy", "Policy defaults and operations must be objects"
            )
        cls._reject_unknown(defaults, _DEFAULT_KEYS, "policy defaults")
        default_timeout = cls._timeout(defaults.get("timeout_seconds"))
        default_output = cls._output_limit(defaults.get("max_output_bytes"))

        normalized = {}
        for name, raw in operations.items():
            if not isinstance(name, str) or not OPERATION_PATTERN.fullmatch(name):
                raise PolicyError("invalid_policy", "Policy operation name is invalid")
            if not isinstance(raw, Mapping):
                raise PolicyError("invalid_policy", f"Policy for {name} must be an object")
            cls._reject_unknown(raw, _OPERATION_KEYS, f"policy operation {name}")
            enabled = raw.get("enabled")
            if not isinstance(enabled, bool):
                raise PolicyError(
                    "invalid_policy", f"Policy operation {name} requires enabled=true or false"
                )
            resources = cls._resources(raw.get("resources", []), name)
            if enabled:
                normalized[name] = OperationPolicy(
                    timeout_seconds=cls._timeout(
                        raw.get("timeout_seconds", default_timeout)
                    ),
                    max_output_bytes=cls._output_limit(
                        raw.get("max_output_bytes", default_output)
                    ),
                    resources=resources,
                )
        return cls(normalized)

    def require(self, operation: str) -> OperationPolicy:
        policy = self._operations.get(operation)
        if policy is None:
            raise PolicyError("denied_operation", "Operation is denied by policy")
        return policy

    @property
    def operations(self) -> tuple[str, ...]:
        return tuple(sorted(self._operations))

    @staticmethod
    def _reject_unknown(value: Mapping, allowed: frozenset[str], label: str) -> None:
        unknown = set(value) - allowed
        if unknown:
            raise PolicyError(
                "invalid_policy",
                f"Unknown {label} field: {sorted(unknown)[0]}",
            )

    @staticmethod
    def _timeout(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyError("invalid_policy", "Policy timeout must be a number")
        if not 0 < value <= MAX_POLICY_TIMEOUT_SECONDS:
            raise PolicyError("invalid_policy", "Policy timeout is outside the allowed range")
        return float(value)

    @staticmethod
    def _output_limit(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise PolicyError("invalid_policy", "Policy output limit must be an integer")
        if not 64 <= value <= MAX_POLICY_OUTPUT_BYTES:
            raise PolicyError(
                "invalid_policy", "Policy output limit is outside the allowed range"
            )
        return value

    @staticmethod
    def _resources(value: Any, operation: str) -> tuple[str, ...]:
        if not isinstance(value, list) or len(value) > 256:
            raise PolicyError(
                "invalid_policy", f"Resources for {operation} must be a bounded list"
            )
        resources = []
        for resource in value:
            if (
                not isinstance(resource, str)
                or not resource
                or len(resource) > 128
                or any(character in resource for character in "\x00\r\n")
            ):
                raise PolicyError(
                    "invalid_policy", f"Resource for {operation} is invalid"
                )
            if resource in resources:
                raise PolicyError(
                    "invalid_policy", f"Resources for {operation} contain a duplicate"
                )
            resources.append(resource)
        return tuple(resources)
