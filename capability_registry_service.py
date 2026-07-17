"""Framework-neutral capability-provider discovery and health aggregation."""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource


logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent / "config" / "schemas"
SCHEMA_FILES = {
    "manifest": "capability-provider-manifest.schema.json",
    "permissions": "capability-provider-permissions.schema.json",
    "renderer": "capability-provider-renderer.schema.json",
    "setup": "capability-provider-setup.schema.json",
    "status": "capability-provider-status.schema.json",
    "actions": "capability-provider-actions.schema.json",
}
DEFAULT_CAPABILITY_SURFACES = {
    "storage.pooling": "pools",
    "storage.protection": "protection",
    "storage.remote_mount": "mounts",
    "storage.share": "shares",
    "integration.chat": "integrations",
    "integration.notifications": "integrations",
    "agent.provider": "integrations",
}
DEFAULT_TAILORED_RENDERERS = {
    ("mergerfs", "storage.pooling", "mergerfs"),
    ("snapraid", "storage.protection", "snapraid"),
    ("mattermost", "integration.chat", "mattermost"),
    ("ai-agents", "agent.provider", "ai-agent"),
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HEALTH_PRIORITY = {
    "disabled": 0,
    "healthy": 1,
    "unknown": 2,
    "unconfigured": 3,
    "warning": 4,
    "unavailable": 5,
    "incompatible": 6,
    "error": 7,
}
MAX_STATUS_BYTES = 262_144
REDACTED = "[redacted]"
SENSITIVE_KEYS = frozenset(
    {
        "access_key",
        "api_key",
        "authorization",
        "credential",
        "credentials",
        "database_url",
        "password",
        "private_key",
        "secret",
        "secret_access_key",
        "token",
        "webhook",
        "webhook_url",
    }
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|auth|"
        r"database[_-]?url|db[_-]?url)\b(\s*[=:]\s*)\S{1,512}"
    ),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{1,512}"),
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,15}://)[^\s/@]{1,256}:[^\s/@]{1,256}@"),
    re.compile(r"(?i)https?://\S{0,2048}/hooks/\S{1,512}"),
)


class CapabilityContractError(ValueError):
    """Base class for a provider contract that cannot be used."""

    code = "contract_error"

    def __init__(self, details: Iterable[str] = ()) -> None:
        self.details = tuple(details)
        super().__init__(self.code)


class CapabilityContractInvalidError(CapabilityContractError):
    """Raised when a supported contract has invalid structure or semantics."""

    code = "contract_invalid"


class CapabilityContractIncompatibleError(CapabilityContractError):
    """Raised when a manifest requests an unsupported contract version."""

    code = "contract_incompatible"


@dataclass(frozen=True)
class ProviderCandidate:
    """Installed-provider facts supplied by a package or integration adapter."""

    manifest: Mapping[str, Any] | Callable[[], Mapping[str, Any]]
    installed: bool = True
    enabled: bool = True
    configured: bool | Mapping[str, bool] | None = None
    status_reader: Callable[[str], Mapping[str, Any]] | None = None
    source: str = "builtin"
    provider_id_hint: str | None = None

    def configured_for(self, capability_id: str) -> bool:
        if isinstance(self.configured, Mapping):
            return bool(self.configured.get(capability_id, False))
        return bool(self.configured)


class CapabilityContractValidator:
    """Validate provider contracts with local schemas and server-owned policy."""

    def __init__(
        self,
        *,
        schema_dir: str | Path,
        capability_surfaces: Mapping[str, str] | None = None,
        tailored_renderers: Iterable[tuple[str, str, str]] | None = None,
    ) -> None:
        self._capability_surfaces = dict(
            capability_surfaces or DEFAULT_CAPABILITY_SURFACES
        )
        self._tailored_renderers = set(
            tailored_renderers or DEFAULT_TAILORED_RENDERERS
        )
        schemas = {}
        resources = []
        schema_path = Path(schema_dir)

        for contract, filename in SCHEMA_FILES.items():
            schema = json.loads((schema_path / filename).read_text())
            Draft7Validator.check_schema(schema)
            schemas[contract] = schema
            resources.append((schema["$id"], Resource.from_contents(schema)))

        registry = Registry().with_resources(resources)
        self._validators = {
            contract: Draft7Validator(
                schema,
                registry=registry,
                format_checker=FormatChecker(),
            )
            for contract, schema in schemas.items()
        }

    def validate(self, contract: str, payload: Mapping[str, Any]) -> None:
        validator = self._validators.get(contract)
        if validator is None:
            raise ValueError(f"Unknown capability contract: {contract}")
        if not isinstance(payload, Mapping):
            raise CapabilityContractInvalidError(("$: type",))

        errors = sorted(validator.iter_errors(dict(payload)), key=_validation_sort_key)
        if errors:
            raise CapabilityContractInvalidError(
                _public_validation_detail(error) for error in errors
            )

    def validate_manifest(self, manifest: Mapping[str, Any]) -> None:
        if not isinstance(manifest, Mapping):
            raise CapabilityContractInvalidError(("$: type",))
        manifest_version = manifest.get("manifest_version")
        if manifest_version is not None and manifest_version != "1":
            raise CapabilityContractIncompatibleError(("manifest_version",))
        compatibility = manifest.get("compatibility")
        capability_api = (
            compatibility.get("capability_api")
            if isinstance(compatibility, Mapping)
            else None
        )
        if capability_api is not None and capability_api != "1":
            raise CapabilityContractIncompatibleError(("capability_api",))

        self.validate("manifest", manifest)
        semantic_errors = self._manifest_semantic_errors(manifest)
        if semantic_errors:
            raise CapabilityContractInvalidError(semantic_errors)

    def _manifest_semantic_errors(self, manifest: Mapping[str, Any]) -> list[str]:
        errors = []
        capability_ids = set()
        compatibility = manifest.get("compatibility", {})
        minimum_version = compatibility.get("limeos_min")
        maximum_version = compatibility.get("limeos_max")
        if (
            minimum_version
            and maximum_version
            and _version_tuple(minimum_version) > _version_tuple(maximum_version)
        ):
            errors.append("invalid_compatibility_range")

        for capability in manifest.get("capabilities", []):
            capability_id = capability.get("id")
            if capability_id in capability_ids:
                errors.append(f"duplicate_capability:{capability_id}")
            capability_ids.add(capability_id)

            expected_surface = self._capability_surfaces.get(capability_id)
            if expected_surface and capability.get("surface") != expected_surface:
                errors.append(f"invalid_surface:{capability_id}")

            renderer = capability.get("renderer", {})
            if renderer.get("mode") == "tailored":
                renderer_key = (
                    manifest.get("id"),
                    capability_id,
                    renderer.get("id"),
                )
                if renderer_key not in self._tailored_renderers:
                    errors.append(
                        f"unregistered_tailored_renderer:{renderer.get('id')}"
                    )

            action_ids = set()
            for action in capability.get("actions", []):
                action_id = action.get("id")
                if action_id in action_ids:
                    errors.append(f"duplicate_action:{action_id}")
                action_ids.add(action_id)

                parameter_names = [
                    item.get("name") for item in action.get("parameters", [])
                ]
                if len(parameter_names) != len(set(parameter_names)):
                    errors.append(f"duplicate_action_parameter:{action_id}")
                for parameter in action.get("parameters", []):
                    minimum = parameter.get("minimum")
                    maximum = parameter.get("maximum")
                    if (
                        minimum is not None
                        and maximum is not None
                        and minimum > maximum
                    ):
                        errors.append(
                            f"invalid_action_parameter_range:{action_id}:"
                            f"{parameter.get('name')}"
                        )

        return errors


class CapabilityRegistryService:
    """Build an on-demand capability index from isolated provider candidates."""

    def __init__(
        self,
        *,
        candidate_reader: Callable[[], Iterable[ProviderCandidate]],
        limeos_version: str,
        schema_dir: str | Path = DEFAULT_SCHEMA_DIR,
        validator: CapabilityContractValidator | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not VERSION_PATTERN.fullmatch(limeos_version):
            raise ValueError("limeos_version must use major.minor.patch")
        self._candidate_reader = candidate_reader
        self._limeos_version = _version_tuple(limeos_version)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._validator_error = False
        try:
            self._validator = validator or CapabilityContractValidator(
                schema_dir=schema_dir
            )
        except Exception:
            logger.error("Capability contract schemas are unavailable")
            self._validator = None
            self._validator_error = True

    def snapshot(self) -> dict:
        """Return providers and capability health without retaining live state."""
        if self._validator_error or self._validator is None:
            return {
                "schema_version": "1",
                "providers": [],
                "capabilities": [],
                "errors": [_registry_error("contract_schemas_unavailable")],
            }

        try:
            candidates = list(self._candidate_reader())
        except Exception:
            logger.error("Capability provider discovery failed")
            return {
                "schema_version": "1",
                "providers": [],
                "capabilities": [],
                "errors": [_registry_error("provider_discovery_unavailable")],
            }

        providers = []
        errors = []
        seen_provider_ids = set()

        for candidate in candidates:
            try:
                provider, provider_errors = self._provider(candidate)
            except Exception:
                logger.error("Capability provider candidate failed")
                errors.append(_registry_error("provider_candidate_invalid"))
                continue
            errors.extend(provider_errors)
            if provider is None:
                continue
            provider_id = provider["id"]
            if provider_id in seen_provider_ids:
                errors.append(_registry_error("duplicate_provider", provider_id))
                continue
            seen_provider_ids.add(provider_id)
            providers.append(provider)

        providers.sort(key=lambda item: item["id"])
        return {
            "schema_version": "1",
            "providers": providers,
            "capabilities": _build_capability_index(providers),
            "errors": sorted(
                errors,
                key=lambda item: (item.get("provider_id", ""), item["code"]),
            ),
        }

    def _provider(
        self, candidate: ProviderCandidate
    ) -> tuple[dict | None, list[dict]]:
        try:
            raw_manifest = (
                candidate.manifest()
                if callable(candidate.manifest)
                else candidate.manifest
            )
            manifest = copy.deepcopy(dict(raw_manifest))
        except Exception:
            provider_id = _safe_id(candidate.provider_id_hint)
            logger.warning(
                "Capability manifest read failed for %s", provider_id or "unknown"
            )
            return None, [_registry_error("manifest_unavailable", provider_id)]

        provider_id = _safe_id(manifest.get("id")) or _safe_id(
            candidate.provider_id_hint
        )
        if not provider_id:
            return None, [_registry_error("manifest_identity_invalid")]

        try:
            self._validator.validate_manifest(manifest)
        except CapabilityContractIncompatibleError as exc:
            return (
                _unusable_provider(
                    manifest,
                    candidate,
                    contract_state="incompatible",
                    health_state="incompatible",
                    issue_code=exc.code,
                ),
                [_registry_error(exc.code, provider_id)],
            )
        except CapabilityContractInvalidError as exc:
            return (
                _unusable_provider(
                    manifest,
                    candidate,
                    contract_state="invalid",
                    health_state="error",
                    issue_code=exc.code,
                ),
                [_registry_error(exc.code, provider_id)],
            )
        except Exception:
            logger.error("Capability manifest validation failed for %s", provider_id)
            return (
                _unusable_provider(
                    manifest,
                    candidate,
                    contract_state="invalid",
                    health_state="error",
                    issue_code="contract_invalid",
                ),
                [_registry_error("contract_invalid", provider_id)],
            )

        compatibility = self._compatibility(manifest["compatibility"])
        provider_issues = []
        capabilities = []

        for capability in manifest["capabilities"]:
            status, status_error = self._capability_status(
                provider_id,
                capability,
                candidate,
                compatibility,
            )
            if status_error:
                provider_issues.append(_registry_error(status_error, provider_id))
            capabilities.append(
                {
                    "id": capability["id"],
                    "provider_id": provider_id,
                    "surface": capability["surface"],
                    "renderer": copy.deepcopy(capability["renderer"]),
                    "permissions": copy.deepcopy(capability["permissions"]),
                    "setup": copy.deepcopy(capability["setup"]),
                    "actions": copy.deepcopy(capability["actions"]),
                    "status": status,
                    "operational": _is_operational(status),
                }
            )

        provider_health = _aggregate_health(
            [item["status"]["health"]["state"] for item in capabilities]
        )
        return (
            {
                "id": provider_id,
                "name": str(manifest["name"]),
                "description": str(manifest["description"]),
                "version": str(manifest["version"]),
                "runtime_kind": manifest["runtime"]["kind"],
                "source": _public_source(candidate.source),
                "installed": bool(candidate.installed),
                "enabled": bool(candidate.enabled),
                "contract_state": "valid",
                "compatibility": compatibility,
                "health": provider_health,
                "capabilities": capabilities,
            },
            provider_issues,
        )

    def _compatibility(self, compatibility: Mapping[str, Any]) -> str:
        minimum = compatibility.get("limeos_min")
        maximum = compatibility.get("limeos_max")
        if minimum and self._limeos_version < _version_tuple(minimum):
            return "incompatible"
        if maximum and self._limeos_version > _version_tuple(maximum):
            return "incompatible"
        return "compatible"

    def _capability_status(
        self,
        provider_id: str,
        capability: Mapping[str, Any],
        candidate: ProviderCandidate,
        compatibility: str,
    ) -> tuple[dict, str | None]:
        capability_id = capability["id"]
        configured = candidate.configured_for(capability_id)

        if not candidate.installed:
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unavailable",
                health_state="unavailable",
                message="Provider is not installed.",
                issue_code="provider_not_installed",
            ), None
        if compatibility == "incompatible":
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unknown",
                health_state="incompatible",
                message="Provider is incompatible with this LimeOS version.",
                issue_code="limeos_version_unsupported",
            ), None
        if not candidate.enabled:
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unknown",
                health_state="disabled",
                message="Provider is disabled.",
            ), None
        if candidate.status_reader is None:
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unavailable",
                health_state="unavailable",
                message="Provider status is unavailable.",
                issue_code="provider_status_unavailable",
            ), "provider_status_unavailable"

        try:
            raw_status = copy.deepcopy(dict(candidate.status_reader(capability_id)))
            status_bytes = json.dumps(raw_status, separators=(",", ":")).encode("utf-8")
            if len(status_bytes) > MAX_STATUS_BYTES:
                raise CapabilityContractInvalidError(("status_size",))
            self._validator.validate("status", raw_status)
            if raw_status["provider_id"] != provider_id:
                raise CapabilityContractInvalidError(("provider_id",))
            if raw_status["capability_id"] != capability_id:
                raise CapabilityContractInvalidError(("capability_id",))
        except CapabilityContractInvalidError:
            logger.warning("Capability status contract invalid for %s", provider_id)
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unavailable",
                health_state="unavailable",
                message="Provider returned invalid status.",
                issue_code="provider_status_invalid",
            ), "provider_status_invalid"
        except Exception:
            logger.warning("Capability status read failed for %s", provider_id)
            return self._synthetic_status(
                provider_id,
                capability_id,
                candidate,
                configured=configured,
                compatibility=compatibility,
                availability="unavailable",
                health_state="unavailable",
                message="Provider status is unavailable.",
                issue_code="provider_status_unavailable",
            ), "provider_status_unavailable"

        lifecycle = raw_status["lifecycle"]
        lifecycle["installed"] = bool(candidate.installed)
        lifecycle["enabled"] = bool(candidate.enabled)
        lifecycle["compatibility"] = compatibility
        if candidate.configured is not None:
            lifecycle["configured"] = configured

        effective_state = _effective_health(raw_status)
        if effective_state != raw_status["health"]["state"]:
            raw_status["health"] = {
                "state": effective_state,
                "message": _health_message(effective_state),
                "issues": raw_status["health"].get("issues", []),
            }
        return _redact_value(raw_status), None

    def _synthetic_status(
        self,
        provider_id: str,
        capability_id: str,
        candidate: ProviderCandidate,
        *,
        configured: bool,
        compatibility: str,
        availability: str,
        health_state: str,
        message: str,
        issue_code: str | None = None,
    ) -> dict:
        issues = []
        if issue_code:
            issues.append(
                {
                    "code": issue_code,
                    "severity": "error",
                    "message": message,
                }
            )
        return {
            "schema_version": "1",
            "provider_id": provider_id,
            "capability_id": capability_id,
            "observed_at": self._clock().astimezone(timezone.utc).isoformat(),
            "lifecycle": {
                "installed": bool(candidate.installed),
                "enabled": bool(candidate.enabled),
                "configured": configured,
                "compatibility": compatibility,
                "availability": availability,
            },
            "health": {
                "state": health_state,
                "message": message,
                "issues": issues,
            },
            "summary": [],
            "metrics": [],
            "recent_activity": [],
            "details": {},
        }


def _validation_sort_key(error) -> tuple:
    return tuple(str(item) for item in error.absolute_path), error.validator


def _public_validation_detail(error) -> str:
    path = ".".join(str(item) for item in error.absolute_path) or "$"
    return f"{path}:{error.validator}"


def _version_tuple(version: str) -> tuple[int, int, int]:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must use major.minor.patch")
    return tuple(int(part) for part in version.split("."))


def _safe_id(value: Any) -> str | None:
    candidate = str(value or "")
    return candidate if ID_PATTERN.fullmatch(candidate) else None


def _public_source(source: Any) -> str:
    value = str(source or "")
    if not value or len(value) > 512 or any(ord(character) < 32 for character in value):
        return "unknown"
    if ID_PATTERN.fullmatch(value):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return "unknown"
        hostname = parsed.hostname
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        netloc = hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, "", ""))
    except ValueError:
        return "unknown"


def _redact_value(value: Any, key: str = "", depth: int = 0) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return REDACTED
    if depth >= 16:
        return "[truncated]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_value(item_value, str(item_key), depth + 1)
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        result = value
        result = SENSITIVE_TEXT_PATTERNS[0].sub(rf"\1\2{REDACTED}", result)
        result = SENSITIVE_TEXT_PATTERNS[1].sub(REDACTED, result)
        result = SENSITIVE_TEXT_PATTERNS[2].sub(rf"\1{REDACTED}@", result)
        return SENSITIVE_TEXT_PATTERNS[3].sub(REDACTED, result)
    return value


def redact_capability_value(value: Any) -> Any:
    """Return a bounded public copy with capability secrets removed."""
    return _redact_value(value)


def _registry_error(code: str, provider_id: str | None = None) -> dict:
    result = {"code": code, "message": _registry_error_message(code)}
    if provider_id:
        result["provider_id"] = provider_id
    return result


def _registry_error_message(code: str) -> str:
    messages = {
        "contract_schemas_unavailable": "Capability contracts are unavailable.",
        "provider_discovery_unavailable": "Provider discovery is unavailable.",
        "manifest_unavailable": "Provider manifest is unavailable.",
        "manifest_identity_invalid": "Provider manifest has an invalid identity.",
        "contract_invalid": "Provider manifest is invalid.",
        "contract_incompatible": "Provider manifest is incompatible.",
        "duplicate_provider": "Provider identity is duplicated.",
        "provider_candidate_invalid": "Provider candidate is invalid.",
        "provider_status_unavailable": "Provider status is unavailable.",
        "provider_status_invalid": "Provider returned invalid status.",
    }
    return messages.get(code, "Capability provider error.")


def _unusable_provider(
    manifest: Mapping[str, Any],
    candidate: ProviderCandidate,
    *,
    contract_state: str,
    health_state: str,
    issue_code: str,
) -> dict:
    provider_id = _safe_id(manifest.get("id")) or candidate.provider_id_hint or "unknown"
    message = _registry_error_message(issue_code)
    return {
        "id": provider_id,
        "name": str(manifest.get("name") or provider_id),
        "description": str(manifest.get("description") or ""),
        "version": str(manifest.get("version") or ""),
        "runtime_kind": str(manifest.get("runtime", {}).get("kind") or "unknown"),
        "source": _public_source(candidate.source),
        "installed": bool(candidate.installed),
        "enabled": bool(candidate.enabled),
        "contract_state": contract_state,
        "compatibility": "incompatible" if contract_state == "incompatible" else "unknown",
        "health": {
            "state": health_state,
            "message": message,
            "counts": {health_state: 1},
        },
        "capabilities": [],
    }


def _effective_health(status: Mapping[str, Any]) -> str:
    lifecycle = status["lifecycle"]
    if not lifecycle["installed"]:
        return "unavailable"
    if lifecycle["compatibility"] == "incompatible":
        return "incompatible"
    if not lifecycle["enabled"]:
        return "disabled"
    if lifecycle["availability"] == "unavailable":
        return "unavailable"
    if not lifecycle["configured"]:
        return "unconfigured"
    return str(status["health"]["state"])


def _is_operational(status: Mapping[str, Any]) -> bool:
    lifecycle = status["lifecycle"]
    return bool(
        lifecycle["installed"]
        and lifecycle["enabled"]
        and lifecycle["compatibility"] == "compatible"
        and lifecycle["availability"] == "available"
    )


def _health_message(state: str) -> str:
    messages = {
        "disabled": "Provider is disabled.",
        "incompatible": "Provider is incompatible with this LimeOS version.",
        "unavailable": "Provider status is unavailable.",
        "unconfigured": "Provider is not configured.",
    }
    return messages.get(state, "Provider status reported by its adapter.")


def _aggregate_health(states: Iterable[str]) -> dict:
    state_list = list(states)
    if not state_list:
        return {
            "state": "unconfigured",
            "message": "No providers are available.",
            "counts": {},
        }
    counts = {state: state_list.count(state) for state in sorted(set(state_list))}
    state = max(state_list, key=lambda item: HEALTH_PRIORITY.get(item, 2))
    return {
        "state": state,
        "message": _aggregate_message(state, len(state_list)),
        "counts": counts,
    }


def _aggregate_message(state: str, count: int) -> str:
    if state == "healthy":
        return f"{count} provider(s) healthy."
    if state == "disabled":
        return "No providers are enabled."
    return f"Provider health requires attention: {state}."


def _build_capability_index(providers: Iterable[Mapping[str, Any]]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for provider in providers:
        for capability in provider.get("capabilities", []):
            item = grouped.setdefault(
                capability["id"],
                {
                    "id": capability["id"],
                    "surface": capability["surface"],
                    "providers": [],
                },
            )
            item["providers"].append(
                {
                    "id": provider["id"],
                    "name": provider["name"],
                    "installed": provider["installed"],
                    "enabled": provider["enabled"],
                    "operational": capability["operational"],
                    "renderer": copy.deepcopy(capability["renderer"]),
                    "status": copy.deepcopy(capability["status"]),
                }
            )

    result = []
    for capability_id, item in grouped.items():
        item["providers"].sort(key=lambda provider: provider["id"])
        item["health"] = _aggregate_health(
            provider["status"]["health"]["state"]
            for provider in item["providers"]
            if provider["enabled"]
        )
        item["counts"] = {
            "providers": len(item["providers"]),
            "enabled": sum(1 for provider in item["providers"] if provider["enabled"]),
            "operational": sum(
                1 for provider in item["providers"] if provider["operational"]
            ),
        }
        result.append(item)

    return sorted(result, key=lambda item: capability_id_sort_key(item["id"]))


def capability_id_sort_key(capability_id: str) -> tuple[str, ...]:
    return tuple(capability_id.split("."))
