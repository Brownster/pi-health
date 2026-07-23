"""Default repair capability contracts and lazy application wiring."""

from __future__ import annotations

import os
import re
import stat
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_actions.canary import CanaryGateService
from agent_actions.capability import (
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    CapabilitySpec,
    RiskClass,
)
from agent_actions.ledger import ActionLedger, utc_now
from agent_actions.policy import ActionPolicy
from agent_actions.service import AgentActionService
from agent_actions.integrations import safe_extension_health, safe_mattermost_health
from runtime_paths import CONFIG_DIR, STATE_DIR


DEFAULT_ACTION_POLICY_PATH = CONFIG_DIR / "agent-action-policy.json"
DEFAULT_ACTION_LEDGER_PATH = STATE_DIR / "agent-actions" / "actions.sqlite3"
DEFAULT_AGENT_RELEASE_PATH = Path("/usr/lib/limeos-agent/.release")


def _container_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"}:
        raise CapabilityError("Container action accepts only a name")
    name = params.get("name")
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 128
        or any(
            character
            not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in name
        )
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


def _packages_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params):
        raise CapabilityError("Package reconciliation accepts no parameters")
    return {}


def _integration_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"} or params.get("name") not in {
        "agents",
        "mattermost",
    }:
        raise CapabilityError(
            "Integration repair accepts only the agents or mattermost target"
        )
    return {"name": str(params["name"])}


def _extension_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"}:
        raise CapabilityError("Extension repair accepts only a name")
    name = params.get("name")
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 64
        or re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) is None
    ):
        raise CapabilityError("Extension repair target is invalid")
    return {"name": name}


def _job_retry_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if set(params) != {"name"} or params.get("name") != "package-reconcile":
        raise CapabilityError("Job retry accepts only the package-reconcile target")
    return {"name": "package-reconcile"}


def safe_integration_precondition(
    status_reader: Callable[[], Mapping[str, Any]],
    job_status_reader: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    status = status_reader()
    job = job_status_reader()
    if not isinstance(status, Mapping) or not isinstance(job, Mapping):
        raise CapabilityError("AI Agents repair status is unavailable")
    active_state = str(job.get("active_state") or "unknown").lower()
    if active_state in {"activating", "active", "reloading", "deactivating"}:
        raise CapabilityError("AI Agents repair is already running")
    if active_state not in {"inactive", "failed"}:
        raise CapabilityError("AI Agents repair job is unavailable")
    raw_units = status.get("units")
    if not isinstance(raw_units, list):
        raise CapabilityError("AI Agents repair status is unavailable")
    units = sorted(
        (
            {
                "name": str(item.get("name") or ""),
                "load_state": str(item.get("load_state") or "unknown").lower(),
                "active_state": str(item.get("active_state") or "unknown").lower(),
                "unit_file_state": str(
                    item.get("unit_file_state") or "unknown"
                ).lower(),
            }
            for item in raw_units
            if isinstance(item, Mapping) and item.get("name")
        ),
        key=lambda item: item["name"],
    )
    agent = next(
        (item for item in units if item["name"] == "limeos-agent.service"), None
    )
    if agent is None or agent["load_state"] != "loaded":
        raise CapabilityError("AI Agents installation is unavailable")
    if agent["unit_file_state"] not in {"enabled", "enabled-runtime"}:
        raise CapabilityError("AI Agents must be enabled before repair")
    return {
        "name": "agents",
        "units": units,
        "job": {
            "active_state": active_state,
            "result": str(job.get("result") or "unknown").lower(),
            "invocation_id": str(job.get("invocation_id") or ""),
        },
    }


def safe_mattermost_precondition(
    status_reader: Callable[[], Mapping[str, Any]],
    job_status_reader: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Require an installed Mattermost integration outside lifecycle cleanup."""
    status = safe_mattermost_health(status_reader())
    job = job_status_reader()
    if not isinstance(job, Mapping):
        raise CapabilityError("Mattermost repair status is unavailable")
    active_state = str(job.get("active_state") or "unknown").lower()
    if active_state in {"activating", "active", "reloading", "deactivating"}:
        raise CapabilityError("Mattermost repair is already running")
    if active_state not in {"inactive", "failed"}:
        raise CapabilityError("Mattermost repair job is unavailable")
    if not status["installed"] or status["stack_name"] != "mattermost":
        raise CapabilityError("Mattermost installation is unavailable")
    if status["state"] in {"disabled", "retained_data", "cleanup_required"}:
        raise CapabilityError("Mattermost lifecycle must be connected before repair")
    if status["state"] not in {"connected", "disconnected", "degraded"}:
        raise CapabilityError("Mattermost repair status is unavailable")
    return {
        **status,
        "job": {
            "active_state": active_state,
            "result": str(job.get("result") or "unknown").lower(),
            "invocation_id": str(job.get("invocation_id") or ""),
        },
    }


def safe_extension_precondition(
    status_reader: Callable[[str], Mapping[str, Any]],
    job_status_reader: Callable[[str], Mapping[str, Any]],
    name: str,
) -> dict[str, Any]:
    """Require an enabled configured-source extension and an idle repair job."""
    status = safe_extension_health(status_reader(name))
    job = job_status_reader(name)
    if status["name"] != name or not isinstance(job, Mapping):
        raise CapabilityError("Extension repair status is unavailable")
    active_state = str(job.get("active_state") or "unknown").lower()
    if active_state in {"activating", "active", "reloading", "deactivating"}:
        raise CapabilityError("Extension repair is already running")
    if active_state not in {"inactive", "failed"}:
        raise CapabilityError("Extension repair job is unavailable")
    if not status["repairable"] or status["type"] != "github":
        raise CapabilityError("Extension is not eligible for repair")
    return {
        **status,
        "job": {
            "active_state": active_state,
            "result": str(job.get("result") or "unknown").lower(),
            "invocation_id": str(job.get("invocation_id") or ""),
        },
    }


def safe_package_precondition(
    status_reader: Callable[[], Mapping[str, Any]],
    job_status_reader: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    status = status_reader()
    job = job_status_reader()
    if not isinstance(status, Mapping) or not isinstance(job, Mapping):
        raise CapabilityError("Package reconciliation status is unavailable")
    active_state = str(job.get("active_state") or "unknown").lower()
    if active_state in {"activating", "active", "reloading", "deactivating"}:
        raise CapabilityError("Package reconciliation is already running")
    if active_state not in {"inactive", "failed"}:
        raise CapabilityError("Package reconciliation job is unavailable")
    raw_packages = status.get("packages")
    raw_drift = status.get("drift")
    if (
        not isinstance(status.get("ok"), bool)
        or not isinstance(raw_packages, list)
        or not isinstance(raw_drift, list)
    ):
        raise CapabilityError("Package reconciliation status is unavailable")
    packages = sorted(
        (
            {
                "name": str(item.get("name") or ""),
                "policy": str(item.get("policy") or ""),
                "expected": str(item.get("expected") or ""),
                "installed": str(item.get("installed") or ""),
                "compliant": item.get("compliant") is True,
            }
            for item in raw_packages
            if isinstance(item, Mapping) and item.get("name")
        ),
        key=lambda item: item["name"],
    )
    if not packages:
        raise CapabilityError("Package repair manifest is empty")
    package_names = {item["name"] for item in packages}
    drift = sorted(str(item) for item in raw_drift)
    if any(item not in package_names for item in drift):
        raise CapabilityError("Package reconciliation status is unavailable")
    return {
        "target": "shipped-manifest",
        "ok": status["ok"],
        "drift": drift,
        "packages": packages,
        "job": {
            "active_state": active_state,
            "result": str(job.get("result") or "unknown").lower(),
            "invocation_id": str(job.get("invocation_id") or ""),
        },
    }


def safe_job_retry_precondition(
    status_reader: Callable[[], Mapping[str, Any]],
    job_status_reader: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Require one failed fixed package job with work still outstanding."""
    package = safe_package_precondition(status_reader, job_status_reader)
    if package["job"]["active_state"] != "failed":
        raise CapabilityError("Package reconciliation job has not failed")
    if package["ok"] or not package["drift"]:
        raise CapabilityError("Package reconciliation has no remaining drift")
    return {
        "name": "package-reconcile",
        "ok": package["ok"],
        "drift": package["drift"],
        "packages": package["packages"],
        "job": package["job"],
    }


def build_repair_registry(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    stack_status: Callable[[str], Mapping[str, Any]],
    package_status: Callable[[], Mapping[str, Any]],
    package_job_status: Callable[[], Mapping[str, Any]],
    integration_status: Callable[[], Mapping[str, Any]],
    integration_job_status: Callable[[], Mapping[str, Any]],
    mattermost_status: Callable[[], Mapping[str, Any]] | None = None,
    mattermost_job_status: Callable[[], Mapping[str, Any]] | None = None,
    extension_status: Callable[[str], Mapping[str, Any]] | None = None,
    extension_job_status: Callable[[str], Mapping[str, Any]] | None = None,
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

    package_capability = CapabilitySpec(
        operation="packages.reconcile",
        version="1",
        risk=RiskClass.MUTATING,
        eligible_modes=(AuthorityMode.PROPOSE, AuthorityMode.APPROVAL),
        normalize_params=_packages_params,
        select_target=lambda _params: "shipped-manifest",
        read_precondition=lambda _params: safe_package_precondition(
            package_status, package_job_status
        ),
        render_impact=lambda _params: (
            "Reconcile the fixed non-feature, non-pinned package subset from the "
            "shipped LimeOS manifest. Apt metadata may be refreshed and missing "
            "packages installed; package names and versions cannot be supplied."
        ),
    )

    integration_capability = CapabilitySpec(
        operation="integration.repair",
        version="1",
        risk=RiskClass.MUTATING,
        eligible_modes=(AuthorityMode.PROPOSE, AuthorityMode.APPROVAL),
        normalize_params=_integration_params,
        select_target=lambda params: params["name"],
        read_precondition=lambda params: (
            safe_integration_precondition(integration_status, integration_job_status)
            if params["name"] == "agents"
            else safe_mattermost_precondition(
                mattermost_status or (lambda: {}),
                mattermost_job_status or (lambda: {}),
            )
        ),
        render_impact=lambda params: (
            "Repair the installed AI Agents integration using its fixed provider and "
            "runtime definition. Agent services will restart and may be briefly "
            "unavailable; configuration and credentials are preserved."
            if params["name"] == "agents"
            else "Reconcile the fixed installed Mattermost stack through its integration "
            "service. Mattermost, Postgres, and alert delivery may be briefly unavailable; "
            "configuration, credentials, and chat data are preserved."
        ),
    )

    extension_capability = CapabilitySpec(
        operation="extension.repair",
        version="1",
        risk=RiskClass.MUTATING,
        eligible_modes=(AuthorityMode.PROPOSE, AuthorityMode.APPROVAL),
        normalize_params=_extension_params,
        select_target=lambda params: params["name"],
        read_precondition=lambda params: safe_extension_precondition(
            extension_status or (lambda _name: {}),
            extension_job_status or (lambda _name: {}),
            params["name"],
        ),
        render_impact=lambda params: (
            f"Repair the allowlisted {params['name']} extension from its configured "
            "GitHub source, refresh its manifest, and verify provider registration and "
            "health. No source, path, module, class, or revision can be supplied."
        ),
    )

    job_retry_capability = CapabilitySpec(
        operation="job.retry",
        version="1",
        risk=RiskClass.MUTATING,
        eligible_modes=(AuthorityMode.PROPOSE, AuthorityMode.APPROVAL),
        normalize_params=_job_retry_params,
        select_target=lambda params: params["name"],
        read_precondition=lambda _params: safe_job_retry_precondition(
            package_status, package_job_status
        ),
        render_impact=lambda _params: (
            "Reset and retry the failed fixed package reconciliation job. Apt metadata "
            "may be refreshed and missing baseline packages installed; the unit, "
            "package names, and versions cannot be supplied."
        ),
    )

    return CapabilityRegistry(
        [
            container_capability("container.start", "Start"),
            container_capability("container.restart", "Restart"),
            stack_capability,
            package_capability,
            integration_capability,
            extension_capability,
            job_retry_capability,
        ]
    )


def build_action_service(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    stack_status: Callable[[str], Mapping[str, Any]],
    package_status: Callable[[], Mapping[str, Any]],
    package_job_status: Callable[[], Mapping[str, Any]],
    integration_status: Callable[[], Mapping[str, Any]],
    integration_job_status: Callable[[], Mapping[str, Any]],
    mattermost_status: Callable[[], Mapping[str, Any]] | None = None,
    mattermost_job_status: Callable[[], Mapping[str, Any]] | None = None,
    extension_status: Callable[[str], Mapping[str, Any]] | None = None,
    extension_job_status: Callable[[str], Mapping[str, Any]] | None = None,
    policy_path: str | Path = DEFAULT_ACTION_POLICY_PATH,
    ledger_path: str | Path = DEFAULT_ACTION_LEDGER_PATH,
    release_commit_provider: Callable[[], str] | None = None,
) -> AgentActionService:
    registry = build_repair_registry(
        container_status=container_status,
        stack_status=stack_status,
        package_status=package_status,
        package_job_status=package_job_status,
        integration_status=integration_status,
        integration_job_status=integration_job_status,
        mattermost_status=mattermost_status,
        mattermost_job_status=mattermost_job_status,
        extension_status=extension_status,
        extension_job_status=extension_job_status,
    )
    ledger = ActionLedger(ledger_path)
    canary_gate = CanaryGateService(
        registry=registry,
        ledger=ledger,
        release_commit_provider=release_commit_provider or read_agent_release_commit,
        clock=utc_now,
        id_factory=lambda: str(uuid.uuid4()),
    )
    return AgentActionService(
        registry=registry,
        policy_provider=lambda: ActionPolicy.from_file(policy_path),
        ledger=ledger,
        canary_gate=canary_gate,
    )


def read_agent_release_commit(
    path: str | Path = DEFAULT_AGENT_RELEASE_PATH,
    *,
    allowed_owner_ids: frozenset[int] = frozenset({0}),
) -> str:
    release_path = Path(path)
    if release_path.is_symlink():
        raise RuntimeError("Agent release marker is unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(release_path, flags)
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or metadata.st_uid not in allowed_owner_ids
            ):
                raise RuntimeError("Agent release marker is unavailable")
            payload = os.read(descriptor, 66)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise RuntimeError("Agent release marker is unavailable") from exc
    if len(payload) > 65:
        raise RuntimeError("Agent release marker is unavailable")
    try:
        value = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Agent release marker is unavailable") from exc
    if value.endswith("\n"):
        value = value[:-1]
    if "\n" in value or "\r" in value:
        raise RuntimeError("Agent release marker is unavailable")
    return value


def build_canary_service(
    *,
    container_status: Callable[[str], Mapping[str, Any]],
    stack_status: Callable[[str], Mapping[str, Any]],
    package_status: Callable[[], Mapping[str, Any]],
    package_job_status: Callable[[], Mapping[str, Any]],
    integration_status: Callable[[], Mapping[str, Any]],
    integration_job_status: Callable[[], Mapping[str, Any]],
    mattermost_status: Callable[[], Mapping[str, Any]] | None = None,
    mattermost_job_status: Callable[[], Mapping[str, Any]] | None = None,
    extension_status: Callable[[str], Mapping[str, Any]] | None = None,
    extension_job_status: Callable[[str], Mapping[str, Any]] | None = None,
    ledger_path: str | Path = DEFAULT_ACTION_LEDGER_PATH,
    release_commit_provider: Callable[[], str] = read_agent_release_commit,
) -> CanaryGateService:
    return CanaryGateService(
        registry=build_repair_registry(
            container_status=container_status,
            stack_status=stack_status,
            package_status=package_status,
            package_job_status=package_job_status,
            integration_status=integration_status,
            integration_job_status=integration_job_status,
            mattermost_status=mattermost_status,
            mattermost_job_status=mattermost_job_status,
            extension_status=extension_status,
            extension_job_status=extension_job_status,
        ),
        ledger=ActionLedger(ledger_path),
        release_commit_provider=release_commit_provider,
        clock=utc_now,
        id_factory=lambda: str(uuid.uuid4()),
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


class LazyCanaryGateService:
    """Delay canary ledger access until an administrator uses the gate."""

    def __init__(self, factory: Callable[[], CanaryGateService]) -> None:
        self._factory = factory
        self._service: CanaryGateService | None = None
        self._lock = threading.Lock()

    def _get(self) -> CanaryGateService:
        with self._lock:
            if self._service is None:
                self._service = self._factory()
            return self._service

    def attest(self, *args, **kwargs):
        return self._get().attest(*args, **kwargs)

    def revoke(self, *args, **kwargs):
        return self._get().revoke(*args, **kwargs)

    def snapshot(self, **kwargs):
        return self._get().snapshot(**kwargs)

    def require_supervised(self, **kwargs):
        return self._get().require_supervised(**kwargs)
