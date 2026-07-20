"""Read-only capability adapters for LimeOS-managed integrations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capability_registry_service import ProviderCandidate


DEFAULT_MANIFEST_DIR = Path(__file__).resolve().parent / "config" / "capability_providers"


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _service_counts(value: Any) -> dict[str, int]:
    services = _record(value)
    records = [_record(service) for service in services.values()]
    return {
        "total": len(records),
        "running": sum(service.get("state") == "running" for service in records),
        "healthy": sum(service.get("health") == "healthy" for service in records),
    }


def _tone(state: str) -> str:
    if state == "healthy":
        return "success"
    if state in {"warning", "unconfigured", "disabled"}:
        return "warning"
    if state == "error":
        return "danger"
    return "neutral"


class IntegrationCapabilityAdapter:
    """Expose integration health without taking over setup or operations."""

    def __init__(
        self,
        *,
        mattermost_status: Callable[[], Mapping[str, Any]],
        agent_status: Callable[[], Mapping[str, Any]],
        manifest_dir: str | Path = DEFAULT_MANIFEST_DIR,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._mattermost_status = mattermost_status
        self._agent_status = agent_status
        self._manifest_dir = Path(manifest_dir)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def candidates(self) -> list[ProviderCandidate]:
        """Return built-in adapters; underlying setup state comes from status."""
        return [
            self._candidate("mattermost", "integration.chat", self._mattermost),
            self._candidate("ai-agents", "agent.provider", self._agents),
        ]

    def _candidate(
        self,
        provider_id: str,
        capability_id: str,
        status_reader: Callable[[], dict[str, Any]],
    ) -> ProviderCandidate:
        def read_status(requested: str) -> dict[str, Any]:
            if requested != capability_id:
                raise ValueError("unsupported capability")
            return status_reader()

        return ProviderCandidate(
            manifest=lambda: self._read_manifest(provider_id),
            installed=True,
            enabled=True,
            configured=None,
            status_reader=read_status,
            source="builtin",
            provider_id_hint=provider_id,
            status_lifecycle_authoritative=True,
        )

    def _read_manifest(self, provider_id: str) -> dict[str, Any]:
        path = self._manifest_dir / f"{provider_id}.manifest.json"
        return json.loads(path.read_text())

    def _observed_at(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat()

    def _mattermost(self) -> dict[str, Any]:
        raw = _record(self._mattermost_status())
        state = str(raw.get("state") or "not_installed")
        installed = bool(raw.get("installed"))
        webhook_configured = bool(raw.get("webhook_configured"))
        configured = installed and webhook_configured
        if state in {"disabled", "retained_data", "cleanup_required"}:
            configured = False
        health_state, message, issues = self._mattermost_health(
            state, installed, webhook_configured
        )
        service_counts = _service_counts(raw.get("services"))
        delivery = _record(raw.get("delivery"))
        details = {
            "state": state,
            "site_url": raw.get("site_url"),
            "stack_name": raw.get("stack_name"),
            "team": raw.get("team"),
            "channel": raw.get("channel"),
            "webhook_configured": webhook_configured,
            "updates_channel_configured": bool(raw.get("updates_channel_configured")),
            "services": service_counts,
            "active_incidents": len(raw.get("incidents") or []),
            "monitored_resources": len(raw.get("resources") or []),
            "last_delivery_at": delivery.get("at"),
            "last_delivery_ok": delivery.get("ok"),
        }
        service_value = (
            f"{service_counts['running']}/{service_counts['total']} running"
            if service_counts["total"]
            else "Not started"
        )
        return self._status(
            provider_id="mattermost",
            capability_id="integration.chat",
            installed=installed,
            enabled=installed and state != "disabled",
            available=state not in {"not_installed", "retained_data", "cleanup_required"},
            configured=configured,
            health_state=health_state,
            message=message,
            issues=issues,
            summary=[
                {
                    "id": "services",
                    "label": "Services",
                    "value": service_value,
                    "tone": _tone(health_state),
                },
                {
                    "id": "channel",
                    "label": "Channel",
                    "value": raw.get("channel") or "Not configured",
                    "tone": _tone(health_state),
                },
                {
                    "id": "incidents",
                    "label": "Active incidents",
                    "value": details["active_incidents"],
                    "tone": "warning" if details["active_incidents"] else "neutral",
                },
            ],
            metrics=[
                {"id": "services", "label": "Services", "value": service_counts["total"]},
                {
                    "id": "running",
                    "label": "Running services",
                    "value": service_counts["running"],
                },
                {
                    "id": "incidents",
                    "label": "Active incidents",
                    "value": details["active_incidents"],
                },
            ],
            details=details,
        )

    @staticmethod
    def _mattermost_health(
        state: str,
        installed: bool,
        webhook_configured: bool,
    ) -> tuple[str, str, list[dict[str, str]]]:
        if state == "cleanup_required":
            return (
                "error",
                "Mattermost cleanup must be completed.",
                [{
                    "code": "mattermost_cleanup_required",
                    "severity": "error",
                    "message": "A Mattermost lifecycle operation did not complete.",
                    "recovery": "Open Integrations and retry cleanup.",
                }],
            )
        if state == "retained_data":
            return "unconfigured", "Mattermost data is retained for reinstall.", []
        if state == "disabled":
            return "disabled", "Mattermost is disabled.", []
        if not installed:
            return "unconfigured", "Mattermost setup is required.", []
        if not webhook_configured:
            return (
                "unconfigured",
                "Mattermost alert delivery is not configured.",
                [{
                    "code": "alert_delivery_unconfigured",
                    "severity": "warning",
                    "message": "Connect an alerts channel from Integrations.",
                    "recovery": "Open Integrations and repair the Mattermost setup.",
                }],
            )
        if state == "connected":
            return "healthy", "Mattermost and alert delivery are connected.", []
        if state == "degraded":
            return (
                "warning",
                "Mattermost or alert delivery needs attention.",
                [{
                    "code": "mattermost_degraded",
                    "severity": "warning",
                    "message": "Mattermost reported degraded service or delivery health.",
                    "recovery": "Open Integrations to inspect delivery and service status.",
                }],
            )
        return (
            "error",
            "Mattermost is disconnected.",
            [{
                "code": "mattermost_disconnected",
                "severity": "error",
                "message": "The Mattermost stack is not fully available.",
                "recovery": "Open Integrations and repair the Mattermost setup.",
            }],
        )

    def _agents(self) -> dict[str, Any]:
        raw = _record(self._agent_status())
        state = str(raw.get("state") or "not_installed")
        provider = _record(raw.get("provider"))
        gateway = _record(raw.get("gateway"))
        mattermost = _record(raw.get("mattermost"))
        configured = bool(
            raw.get("configured")
            and provider.get("installed")
            and provider.get("compatible")
            and provider.get("authenticated")
        )
        if state in {"disabled", "not_installed", "cleanup_required"}:
            configured = False
        health_state, message, issues = self._agent_health(state)
        provider_name = "Claude Code" if provider.get("id") == "claude" else (
            provider.get("id") or "Not configured"
        )
        details = {
            "state": state,
            "runtime_installed": bool(raw.get("installed")),
            "runtime_enabled": bool(raw.get("enabled")),
            "runtime_configured": bool(raw.get("configured")),
            "gateway_state": gateway.get("state"),
            "broker_state": gateway.get("broker_state"),
            "provider": {
                "id": provider.get("id"),
                "version": provider.get("version"),
                "installed": bool(provider.get("installed")),
                "compatible": bool(provider.get("compatible")),
                "authenticated": bool(provider.get("authenticated")),
            },
            "mattermost": {
                "state": mattermost.get("state"),
                "team": mattermost.get("team"),
                "channel": mattermost.get("channel"),
            },
        }
        return self._status(
            provider_id="ai-agents",
            capability_id="agent.provider",
            installed=bool(raw.get("installed")),
            enabled=bool(raw.get("enabled")) and state != "disabled",
            available=state not in {"not_installed", "cleanup_required"},
            configured=configured,
            health_state=health_state,
            message=message,
            issues=issues,
            summary=[
                {
                    "id": "provider",
                    "label": "Provider",
                    "value": provider_name,
                    "tone": _tone(health_state),
                },
                {
                    "id": "gateway",
                    "label": "Gateway",
                    "value": gateway.get("state") or "inactive",
                    "tone": _tone(health_state),
                },
                {
                    "id": "broker",
                    "label": "Broker",
                    "value": gateway.get("broker_state") or "inactive",
                    "tone": _tone(health_state),
                },
            ],
            metrics=[],
            details=details,
        )

    @staticmethod
    def _agent_health(state: str) -> tuple[str, str, list[dict[str, str]]]:
        if state == "connected":
            return "healthy", "The LimeOS assistant is connected.", []
        if state == "cleanup_required":
            return (
                "error",
                "AI Agents cleanup must be completed.",
                [{
                    "code": "agent_cleanup_required",
                    "severity": "error",
                    "message": "An AI Agents lifecycle operation did not complete.",
                    "recovery": "Open Integrations and retry cleanup.",
                }],
            )
        if state == "disabled":
            return "disabled", "The LimeOS assistant is disabled.", []
        if state in {"not_installed", "setup_required"}:
            return "unconfigured", "AI Agents setup is required.", []
        if state == "authenticating":
            return "warning", "Claude authorization is in progress.", []
        if state == "degraded":
            return (
                "warning",
                "The LimeOS assistant needs attention.",
                [{
                    "code": "agent_degraded",
                    "severity": "warning",
                    "message": "The agent runtime is not fully healthy.",
                    "recovery": "Open Integrations and repair AI Agents.",
                }],
            )
        return (
            "error",
            "The LimeOS assistant is disconnected.",
            [{
                "code": "agent_disconnected",
                "severity": "error",
                "message": "The agent gateway or broker is not active.",
                "recovery": "Open Integrations and repair AI Agents.",
            }],
        )

    def _status(
        self,
        *,
        provider_id: str,
        capability_id: str,
        installed: bool,
        enabled: bool,
        available: bool,
        configured: bool,
        health_state: str,
        message: str,
        issues: list[dict[str, str]],
        summary: list[dict[str, Any]],
        metrics: list[dict[str, Any]],
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "provider_id": provider_id,
            "capability_id": capability_id,
            "observed_at": self._observed_at(),
            "lifecycle": {
                "installed": installed,
                "enabled": enabled,
                "configured": configured,
                "compatibility": "compatible",
                "availability": "available" if available else "unavailable",
            },
            "health": {"state": health_state, "message": message, "issues": issues},
            "summary": summary,
            "metrics": metrics,
            "recent_activity": [],
            "details": details,
        }
