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
from collections.abc import Callable
from dataclasses import asdict, dataclass
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
    critical: bool = False
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


# -- reconcile logic (pure) ------------------------------------------------------
#: Query an installed version for a spec; returns None when the package is absent.
VersionOf = Callable[["PackageSpec"], "str | None"]
#: True when version `a` is at least version `b`.
VersionGe = Callable[[str, str], bool]


def upstream_version(version: str) -> str:
    """The upstream part of a Debian version: strip an epoch (`N:`) and revision (`-N`).

    A `pinned` package names an upstream version (e.g. 2.1.207); the packaging revision
    (2.1.207-1) is metadata, not a version bump, so `2.1.207-1` satisfies pin `2.1.207`.
    Enforcement is the hold that freezes the installed version, not an exact reinstall.
    """
    version = version.split(":", 1)[-1]
    return version.rsplit("-", 1)[0] if "-" in version else version


def _version_key(version: str) -> list:
    return [int(part) if part.isdigit() else part for part in re.findall(r"\d+|[A-Za-z]+", version)]


def default_version_ge(a: str, b: str) -> bool:
    """Best-effort version comparison for the pure default.

    The privileged reconcile injects a dpkg-based comparator for correctness; this keeps
    the module dependency-free and good enough for the common numeric cases.
    """
    try:
        return _version_key(a) >= _version_key(b)
    except TypeError:
        return a >= b


@dataclass(frozen=True)
class PackageStatus:
    name: str
    manager: str
    policy: str
    expected: str | None
    installed: str | None
    compliant: bool
    detail: str


@dataclass(frozen=True)
class ReconcileAction:
    name: str
    manager: str
    action: str  # install | install_version | hold | upgrade_min | remove | disable_self_update
    version: str | None = None


def _evaluate(spec: PackageSpec, installed: str | None, version_ge: VersionGe) -> tuple[bool, str]:
    if spec.policy == "absent":
        if installed is None:
            return True, "absent as required"
        return False, f"installed ({installed}) but should be absent"
    if installed is None:
        return False, "not installed"
    if spec.policy == "pinned":
        if upstream_version(installed) == upstream_version(spec.version or ""):
            return True, f"at pinned version {spec.version}"
        return False, f"at {installed}, pinned to {spec.version}"
    if spec.policy == "present-min":
        if version_ge(installed, spec.version or ""):
            return True, f"{installed} meets minimum {spec.version}"
        return False, f"at {installed}, below minimum {spec.version}"
    return True, f"present ({installed})"


def check_packages(
    specs: list[PackageSpec],
    version_of: VersionOf,
    *,
    version_ge: VersionGe = default_version_ge,
) -> list[PackageStatus]:
    statuses = []
    for spec in specs:
        installed = version_of(spec)
        compliant, detail = _evaluate(spec, installed, version_ge)
        statuses.append(
            PackageStatus(
                name=spec.name,
                manager=spec.manager,
                policy=spec.policy,
                expected=spec.version,
                installed=installed,
                compliant=compliant,
                detail=detail,
            )
        )
    return statuses


def compliance_report(statuses: list[PackageStatus]) -> dict:
    """Non-secret compliance summary for `packages.status` and the nightly job."""
    drift = [status.name for status in statuses if not status.compliant]
    return {
        "ok": not drift,
        "drift": drift,
        "packages": [asdict(status) for status in statuses],
    }


def plan_actions(
    specs: list[PackageSpec],
    version_of: VersionOf,
    *,
    version_ge: VersionGe = default_version_ge,
) -> list[ReconcileAction]:
    """The manifest-enforcement steps `reconcile apply` should perform (no security-pocket
    updates — that is the nightly unattended-upgrades job's role)."""
    actions: list[ReconcileAction] = []
    for spec in specs:
        installed = version_of(spec)
        if spec.policy == "absent":
            if installed is not None:
                actions.append(ReconcileAction(spec.name, spec.manager, "remove"))
            continue
        if spec.policy == "pinned":
            if installed is None or upstream_version(installed) != upstream_version(
                spec.version or ""
            ):
                actions.append(
                    ReconcileAction(spec.name, spec.manager, "install_version", spec.version)
                )
            actions.append(ReconcileAction(spec.name, spec.manager, "hold"))
            if spec.disable_self_update:
                actions.append(ReconcileAction(spec.name, spec.manager, "disable_self_update"))
        elif spec.policy == "present-min":
            if installed is None or not version_ge(installed, spec.version or ""):
                actions.append(
                    ReconcileAction(spec.name, spec.manager, "upgrade_min", spec.version)
                )
        elif spec.policy == "present":
            if installed is None:
                actions.append(ReconcileAction(spec.name, spec.manager, "install"))
    return actions
