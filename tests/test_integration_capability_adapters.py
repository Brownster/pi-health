import json
from datetime import datetime, timezone

from capability_registry_service import CapabilityRegistryService
from integration_capability_adapters import IntegrationCapabilityAdapter


NOW = datetime(2026, 7, 18, 22, 0, tzinfo=timezone.utc)


def mattermost_status(**overrides):
    status = {
        "state": "connected",
        "installed": True,
        "site_url": "http://mattermost.local:8065",
        "stack_name": "mattermost",
        "team": "limeos",
        "channel": "limeos-alerts",
        "webhook_configured": True,
        "updates_channel_configured": True,
        "resources": [{"key": "container:jellyfin"}],
        "incidents": [],
        "delivery": {"at": "2026-07-18T21:55:00Z", "ok": True},
        "services": {
            "postgres": {"state": "running", "health": "healthy"},
            "mattermost": {"state": "running", "health": "healthy"},
            "alerts": {"state": "running", "health": None},
        },
    }
    status.update(overrides)
    return status


def agent_status(**overrides):
    status = {
        "state": "connected",
        "installed": True,
        "enabled": True,
        "configured": True,
        "mattermost": {
            "state": "connected",
            "site_url": "http://mattermost.local:8065",
            "team": "limeos",
            "channel": "limeos-alerts",
        },
        "gateway": {"state": "active", "broker_state": "active"},
        "provider": {
            "id": "claude",
            "installed": True,
            "version": "2.1.207",
            "compatible": True,
            "authenticated": True,
        },
        "last_successful_turn": {
            "at": "2026-07-18T21:56:00Z",
            "outcome": "ok",
            "prompt": "private operator request",
        },
    }
    status.update(overrides)
    return status


def registry(adapter):
    return CapabilityRegistryService(
        candidate_reader=adapter.candidates,
        limeos_version="1.0.0",
        clock=lambda: NOW,
    )


def provider(snapshot, provider_id):
    return next(item for item in snapshot["providers"] if item["id"] == provider_id)


def test_adapter_maps_connected_integrations_without_exposing_private_records():
    adapter = IntegrationCapabilityAdapter(
        mattermost_status=mattermost_status,
        agent_status=agent_status,
        clock=lambda: NOW,
    )

    snapshot = registry(adapter).snapshot()

    assert snapshot["errors"] == []
    mattermost = provider(snapshot, "mattermost")
    assert mattermost["runtime_kind"] == "integration-adapter"
    assert mattermost["health"]["state"] == "healthy"
    mattermost_status_payload = mattermost["capabilities"][0]["status"]
    assert mattermost_status_payload["details"]["services"] == {
        "total": 3,
        "running": 3,
        "healthy": 2,
    }
    assert mattermost_status_payload["details"]["monitored_resources"] == 1
    agents = provider(snapshot, "ai-agents")
    assert agents["health"]["state"] == "healthy"
    agent_details = agents["capabilities"][0]["status"]["details"]
    assert agent_details["provider"] == {
        "id": "claude",
        "version": "2.1.207",
        "installed": True,
        "compatible": True,
        "authenticated": True,
    }
    payload = json.dumps(snapshot)
    assert "private operator request" not in payload
    assert "last_successful_turn" not in payload


def test_uninstalled_integrations_remain_discoverable_and_link_to_setup():
    adapter = IntegrationCapabilityAdapter(
        mattermost_status=lambda: mattermost_status(
            state="not_installed",
            installed=False,
            site_url=None,
            webhook_configured=False,
            services={},
        ),
        agent_status=lambda: agent_status(
            state="setup_required",
            installed=False,
            enabled=False,
            configured=False,
            gateway={"state": "inactive", "broker_state": "inactive"},
            provider={
                "id": "claude",
                "installed": False,
                "version": None,
                "compatible": False,
                "authenticated": False,
            },
        ),
        clock=lambda: NOW,
    )

    snapshot = registry(adapter).snapshot()

    assert snapshot["errors"] == []
    for provider_id in ("mattermost", "ai-agents"):
        item = provider(snapshot, provider_id)
        status = item["capabilities"][0]["status"]
        assert item["installed"] is True
        assert item["runtime_kind"] == "integration-adapter"
        assert status["lifecycle"]["configured"] is False
        assert status["health"]["state"] == "unconfigured"
        assert item["capabilities"][0]["surface"] == "integrations"


def test_degraded_and_disabled_runtime_health_remain_distinct():
    adapter = IntegrationCapabilityAdapter(
        mattermost_status=lambda: mattermost_status(
            state="degraded",
            delivery={"ok": False, "error": "hook denied secret-token"},
        ),
        agent_status=lambda: agent_status(state="disabled", enabled=False),
        clock=lambda: NOW,
    )

    snapshot = registry(adapter).snapshot()

    mattermost = provider(snapshot, "mattermost")["capabilities"][0]["status"]
    assert mattermost["health"]["state"] == "warning"
    assert mattermost["health"]["issues"][0]["code"] == "mattermost_degraded"
    assert "hook denied" not in json.dumps(mattermost)
    agents = provider(snapshot, "ai-agents")["capabilities"][0]["status"]
    assert agents["lifecycle"]["configured"] is True
    assert agents["health"]["state"] == "disabled"
    assert agents["details"]["runtime_enabled"] is False


def test_provider_status_failure_is_isolated():
    def unavailable():
        raise RuntimeError("helper command included private output")

    adapter = IntegrationCapabilityAdapter(
        mattermost_status=mattermost_status,
        agent_status=unavailable,
        clock=lambda: NOW,
    )

    snapshot = registry(adapter).snapshot()

    assert provider(snapshot, "mattermost")["health"]["state"] == "healthy"
    assert provider(snapshot, "ai-agents")["health"]["state"] == "unavailable"
    assert snapshot["errors"] == [{
        "code": "provider_status_unavailable",
        "message": "Provider status is unavailable.",
        "provider_id": "ai-agents",
    }]
    assert "private output" not in json.dumps(snapshot)


def test_production_manifests_declare_existing_dedicated_diagnostics():
    adapter = IntegrationCapabilityAdapter(
        mattermost_status=mattermost_status,
        agent_status=agent_status,
    )
    manifests = {
        candidate.provider_id_hint: candidate.manifest()
        for candidate in adapter.candidates()
    }

    mattermost = manifests["mattermost"]
    agents = manifests["ai-agents"]
    assert mattermost["runtime"] == {"kind": "integration-adapter"}
    assert agents["runtime"] == {"kind": "integration-adapter"}
    assert mattermost["capabilities"][0]["actions"][0]["id"] == "test-delivery"
    assert agents["capabilities"][0]["actions"][0]["id"] == "test-assistant"
    assert mattermost["capabilities"][0]["surface"] == "integrations"
    assert agents["capabilities"][0]["surface"] == "integrations"
