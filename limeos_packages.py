"""LimeOS package baseline manifest (PB-001): load, validate, model.

The manifest (`config/limeos-packages.json`) is the declarative source of truth for the
packages LimeOS depends on and how their versions are governed. This module parses and
strictly validates it into typed `PackageSpec`s that later reconcile work (PB-002) turns
into apt/pip/self-updater actions.

Validation is deliberately strict because reconcile passes these names/versions to system
package managers: names and versions must match conservative patterns (no shell
metacharacters), managers and policies are closed enums, and versioned policies must
carry a valid version while unversioned ones must not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

MANAGERS = frozenset({"apt", "pip", "npm", "claude"})
POLICIES = frozenset({"pinned", "present-min", "present", "absent"})
_VERSIONED_POLICIES = frozenset({"pinned", "present-min"})
# Debian-ish package name; conservative enough for pip/npm too.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+._-]{0,127}$")
_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.:+~-]{0,63}$")
_ALLOWED_FIELDS = frozenset(
    {"name", "manager", "policy", "version", "critical", "disable_self_update"}
)

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "config" / "limeos-packages.json"


class PackageManifestError(ValueError):
    """Raised when the package manifest is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class PackageSpec:
    name: str
    manager: str
    policy: str
    critical: bool
    version: str | None = None
    disable_self_update: bool = False


def _parse_package(raw: object) -> PackageSpec:
    if not isinstance(raw, dict):
        raise PackageManifestError("package entry must be an object")
    unknown = set(raw) - _ALLOWED_FIELDS
    if unknown:
        raise PackageManifestError(f"unknown package fields: {sorted(unknown)}")

    name = raw.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise PackageManifestError(f"invalid package name: {name!r}")
    manager = raw.get("manager")
    if manager not in MANAGERS:
        raise PackageManifestError(f"invalid manager for {name}: {manager!r}")
    policy = raw.get("policy")
    if policy not in POLICIES:
        raise PackageManifestError(f"invalid policy for {name}: {policy!r}")

    critical = raw.get("critical", False)
    if not isinstance(critical, bool):
        raise PackageManifestError(f"critical must be a boolean for {name}")
    disable_self_update = raw.get("disable_self_update", False)
    if not isinstance(disable_self_update, bool):
        raise PackageManifestError(f"disable_self_update must be a boolean for {name}")

    version = raw.get("version")
    if policy in _VERSIONED_POLICIES:
        if not isinstance(version, str) or not _VERSION_RE.match(version):
            raise PackageManifestError(f"policy {policy} for {name} requires a valid version")
    elif version is not None:
        raise PackageManifestError(f"policy {policy} for {name} must not set a version")

    return PackageSpec(
        name=name,
        manager=manager,
        policy=policy,
        critical=critical,
        version=version,
        disable_self_update=disable_self_update,
    )


def parse_manifest(raw: object) -> list[PackageSpec]:
    if not isinstance(raw, dict) or set(raw) - {"schema_version", "packages"}:
        raise PackageManifestError("invalid manifest structure")
    if raw.get("schema_version") != "1":
        raise PackageManifestError("unsupported manifest schema version")
    packages = raw.get("packages")
    if not isinstance(packages, list) or not packages:
        raise PackageManifestError("packages must be a non-empty list")
    specs = [_parse_package(item) for item in packages]
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise PackageManifestError("duplicate package names in manifest")
    return specs


def load_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> list[PackageSpec]:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise PackageManifestError("unable to read package manifest") from exc
    return parse_manifest(raw)


def critical_packages(specs: list[PackageSpec]) -> list[PackageSpec]:
    return [spec for spec in specs if spec.critical]
