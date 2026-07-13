"""AA-006 AI Agents integration orchestration and public state contract."""

from __future__ import annotations

import json

import pytest

from agent_integration_service import AgentIntegrationError, AgentIntegrationService


class FakeHelper:
    def __init__(self):
        self.calls = []
        self.responses = {
            "agent_runtime_status": {
                "success": True,
                "runtime_installed": False,
                "agent_active": "inactive",
                "broker_active": "inactive",
                "claude_installed": False,
                "claude_version": None,
                "claude_credentials_present": False,
                "claude_authenticated": False,
                "configured": False,
                "enabled": False,
            },
            "agent_provider_install": {"success": True, "version": "2.1.205"},
            "agent_runtime_install": {"success": True, "runtime_installed": True},
            "agent_bot_secret_write": {"success": True, "stored": True},
            "agent_configure": {"success": True, "configured": True},
            "agent_runtime_start": {"success": True, "started": True},
            "agent_runtime_disable": {"success": True, "disabled": True},
            "agent_delivery_test": {"success": True, "delivered": True},
            "agent_usage_read": {
                "success": True,
                "totals": {"total_turns": 3, "total_invocations": 5, "invocations_today": 2},
                "records": [],
            },
            "agent_audit_read": {"success": True, "records": []},
            "agent_provider_auth_submit": {"success": True, "accepted": True},
            "agent_provider_auth_cancel": {"success": True, "cancelled": True},
        }

    def __call__(self, command, params=None, *, timeout=30):
        self.calls.append((command, params or {}, timeout))
        response = self.responses.get(command)
        if callable(response):
            return response(params or {})
        return dict(response or {"success": False, "error": "not configured"})


class FakeBotApi:
    def login(self, username, password):
        assert username == "admin" and password == "write-only-password"
        return "admin-1"

    def team_id(self, name):
        assert name == "limeos"
        return "team-1"

    def channel_id(self, team_id, name):
        assert (team_id, name) == ("team-1", "limeos-alerts")
        return "channel-1"

    def enable_bot_settings(self):
        pass

    def ensure_bot(self, *, username, display_name):
        assert username == "limeos"
        return "bot-1"

    def ensure_team_member(self, **_kwargs):
        pass

    def ensure_channel_member(self, **_kwargs):
        pass

    def create_token(self, **_kwargs):
        return "token-id-1", "BOT-SECRET"

    def revoke_token(self, **_kwargs):
        pass


def _mattermost(state="connected"):
    return {
        "state": state,
        "installed": state != "not_installed",
        "site_url": "http://mattermost.local:8065",
        "team": "limeos",
        "channel": "limeos-alerts",
    }


def _service(helper=None, mattermost=None):
    return AgentIntegrationService(
        helper_call=helper or FakeHelper(),
        mattermost_status=lambda: mattermost or _mattermost(),
        bot_api_factory=lambda _url: FakeBotApi(),
        resource_provider=lambda: {
            "containers": ["jellyfin", "limeos-mattermost", "bad/name"],
            "stacks": ["media", "mattermost"],
        },
        sleep=lambda _seconds: None,
    )


def test_status_requires_mattermost_then_maps_runtime_states():
    helper = FakeHelper()
    assert _service(helper, _mattermost("not_installed")).status()["state"] == "setup_required"
    helper.responses["agent_runtime_status"].update(
        runtime_installed=True,
        broker_active="active",
        claude_installed=True,
        claude_compatible=True,
        claude_credentials_present=True,
        claude_authenticated=True,
        configured=True,
        enabled=True,
        agent_active="active",
    )
    status = _service(helper).status()
    assert status["state"] == "connected"
    assert "credentials" not in json.dumps(status).lower()
    helper.responses["agent_runtime_status"]["enabled"] = False
    assert _service(helper).status()["state"] == "disabled"
    helper.responses["agent_runtime_status"].update(enabled=True, agent_active="failed")
    assert _service(helper).status()["state"] == "degraded"


def test_status_includes_last_successful_turn_and_propagates_mattermost_disconnect():
    helper = FakeHelper()
    helper.responses["agent_runtime_status"].update(
        runtime_installed=True,
        broker_active="active",
        agent_active="active",
        claude_installed=True,
        claude_compatible=True,
        claude_authenticated=True,
        configured=True,
        enabled=True,
    )
    helper.responses["agent_usage_read"]["records"] = [
        {"at": "first", "outcome": "error"},
        {"at": "second", "outcome": "ok"},
    ]
    assert _service(helper).status()["last_successful_turn"]["at"] == "second"
    assert _service(helper, _mattermost("disconnected")).status()["state"] == "disconnected"


def test_install_bootstraps_provider_runtime_bot_config_policy_and_service():
    helper = FakeHelper()
    events = list(
        _service(helper).stream_install(
            {"admin_username": "admin", "admin_password": "write-only-password"}
        )
    )
    assert events[-1]["done"] is True
    blob = json.dumps(events)
    assert "write-only-password" not in blob and "BOT-SECRET" not in blob
    assert [call[0] for call in helper.calls] == [
        "agent_provider_install",
        "agent_runtime_install",
        "agent_runtime_status",
        "agent_bot_secret_write",
        "agent_configure",
        "agent_runtime_status",
    ]
    assert helper.calls[0][2] == 1200 and helper.calls[1][2] == 1200
    assert helper.calls[3][1] == {"token": "BOT-SECRET"}
    configured = helper.calls[4][1]
    assert configured["settings"]["mattermost"]["bot_user_id"] == "bot-1"
    assert configured["settings"]["mattermost"]["channel_id"] == "channel-1"
    assert configured["settings"]["mattermost"]["bot_token_id"] == "token-id-1"
    assert configured["policy"]["operations"]["container.logs"]["resources"] == [
        "jellyfin",
        "limeos-mattermost",
    ]
    assert configured["policy"]["operations"]["stack.inspect"]["resources"] == [
        "mattermost",
        "media",
    ]
    assert events[-1]["requires_auth"] is True


def test_install_fails_closed_when_mattermost_or_helper_is_unavailable():
    events = list(
        _service(mattermost=_mattermost("not_installed")).stream_install(
            {"admin_username": "admin", "admin_password": "write-only-password"}
        )
    )
    assert events[-1]["error"] == "Mattermost must be connected before AI Agents setup"
    helper = FakeHelper()
    helper.responses["agent_provider_install"] = {
        "success": False,
        "error": "Failed to install Claude Code",
    }
    events = list(
        _service(helper).stream_install(
            {"admin_username": "admin", "admin_password": "write-only-password"}
        )
    )
    assert events[-1]["error"] == "Failed to install Claude Code"
    assert all(call[0] != "agent_runtime_install" for call in helper.calls)


def test_install_rejects_unknown_fields_and_weak_admin_input():
    service = _service()
    with pytest.raises(AgentIntegrationError):
        list(service.stream_install({"admin_username": "admin", "admin_password": "short"}))
    with pytest.raises(AgentIntegrationError):
        list(
            service.stream_install(
                {
                    "admin_username": "admin",
                    "admin_password": "write-only-password",
                    "command": "rm -rf /",
                }
            )
        )


def test_guided_auth_stream_maps_allowlisted_events_and_accepts_code():
    helper = FakeHelper()
    statuses = iter(
        [
            {
                "success": True,
                "operation_id": "provider-auth-1",
                "state": "running",
                "cursor": 2,
                "events": [
                    {"type": "authorization_url", "url": "https://claude.ai/oauth/x"},
                    {"type": "input_required", "message": "Paste the authorization code to continue."},
                ],
            },
            {
                "success": True,
                "operation_id": "provider-auth-1",
                "state": "complete",
                "cursor": 3,
                "events": [{"type": "status", "message": "Claude authentication completed."}],
            },
        ]
    )
    helper.responses["agent_provider_auth_start"] = {
        "success": True,
        "operation_id": "provider-auth-1",
    }
    helper.responses["agent_provider_auth_status"] = lambda _params: next(statuses)
    events = list(_service(helper).stream_auth())
    assert events[0]["operation_id"] == "provider-auth-1"
    assert events[1]["authorization_url"].startswith("https://claude.ai/")
    assert events[1]["_ephemeral"] is True
    assert events[-1]["done"] is True
    _service(helper).submit_auth("provider-auth-1", "approved-code")
    assert helper.calls[-1][0:2] == (
        "agent_provider_auth_submit",
        {"operation_id": "provider-auth-1", "code": "approved-code"},
    )


def test_guided_auth_drops_non_claude_authorization_urls():
    helper = FakeHelper()
    helper.responses["agent_provider_auth_start"] = {
        "success": True,
        "operation_id": "provider-auth-1",
    }
    helper.responses["agent_provider_auth_status"] = {
        "success": True,
        "state": "failed",
        "cursor": 1,
        "events": [{"type": "authorization_url", "url": "https://evil.example/login"}],
    }
    events = list(_service(helper).stream_auth())
    assert "evil.example" not in json.dumps(events)


def test_repair_reinstalls_provider_and_runtime_before_starting():
    helper = FakeHelper()
    helper.responses["agent_runtime_status"].update(
        configured=True, claude_authenticated=True
    )
    events = list(_service(helper).stream_repair({}))
    assert events[-1]["done"] is True
    assert [call[0] for call in helper.calls] == [
        "agent_provider_install",
        "agent_runtime_install",
        "agent_runtime_status",
        "agent_runtime_start",
    ]


def test_repair_with_admin_credentials_rebuilds_bot_and_configuration():
    helper = FakeHelper()
    helper.responses["agent_runtime_status"].update(claude_authenticated=True)
    events = list(
        _service(helper).stream_repair(
            {"admin_username": "admin", "admin_password": "write-only-password"}
        )
    )
    assert events[-1]["done"] is True
    assert [call[0] for call in helper.calls] == [
        "agent_provider_install",
        "agent_runtime_install",
        "agent_runtime_status",
        "agent_bot_secret_write",
        "agent_configure",
        "agent_runtime_status",
        "agent_runtime_start",
    ]
    assert "write-only-password" not in json.dumps(events)


def test_disable_test_usage_audit_and_permissions_delegate_without_secrets():
    helper = FakeHelper()
    service = _service(helper)
    assert service.disable() == {"state": "disabled"}
    assert service.test_delivery() == {"status": "sent"}
    assert service.usage(limit=25)["totals"]["total_turns"] == 3
    assert service.audit(limit=25) == {"records": []}
    permissions = service.permissions()
    assert "container.logs" in permissions["allowed_operations"]
    assert "container.restart" in permissions["denied_capabilities"]
    assert "token" not in json.dumps(permissions).lower()


def test_helper_error_text_is_private():
    helper = FakeHelper()
    helper.responses["agent_usage_read"] = {
        "success": False,
        "error": "private /etc/limeos/integrations/agents.env SECRET",
    }
    with pytest.raises(AgentIntegrationError) as exc_info:
        _service(helper).usage()
    assert "SECRET" not in str(exc_info.value)
