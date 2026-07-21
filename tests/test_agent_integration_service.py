"""AA-006 AI Agents integration orchestration and public state contract."""

from __future__ import annotations

import json

import pytest

from agent_integration_service import (
    AGENT_LIFECYCLE_FAILURE_MESSAGE,
    AgentIntegrationError,
    AgentIntegrationService,
)
from integration_lifecycle_service import (
    IntegrationLifecycleResolver,
    LifecycleStateRepository,
    load_lifecycle_policy,
)


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
            "agent_integration_repair": {"success": True, "repaired": True},
            "agent_runtime_disable": {"success": True, "disabled": True},
            "agent_runtime_uninstall": {"success": True, "steps": []},
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
    def __init__(self):
        self.deleted = []

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

    def delete_bot(self, *, user_id):
        self.deleted.append(user_id)


def _mattermost(state="connected"):
    return {
        "state": state,
        "installed": state != "not_installed",
        "site_url": "http://mattermost.local:8065",
        "team": "limeos",
        "channel": "limeos-alerts",
    }


def _service(
    helper=None,
    mattermost=None,
    lifecycle_resolver=None,
    lifecycle_repository=None,
    lifecycle_policy=None,
    bot_api=None,
):
    return AgentIntegrationService(
        helper_call=helper or FakeHelper(),
        mattermost_status=(mattermost if callable(mattermost) else lambda: mattermost or _mattermost()),
        bot_api_factory=lambda _url: bot_api or FakeBotApi(),
        resource_provider=lambda: {
            "containers": ["jellyfin", "limeos-mattermost", "bad/name"],
            "stacks": ["media", "mattermost"],
        },
        sleep=lambda _seconds: None,
        lifecycle_resolver=lifecycle_resolver,
        lifecycle_repository=lifecycle_repository,
        lifecycle_policy=lifecycle_policy,
        lifecycle_timestamp=lambda: "2026-07-21T12:00:00+00:00",
    )


def _lifecycle_service(tmp_path, helper=None, mattermost=None, bot_api=None):
    repository = LifecycleStateRepository(tmp_path / "agents-lifecycle.json", "agents")
    policy = load_lifecycle_policy()
    return (
        _service(
            helper,
            mattermost,
            lifecycle_resolver=IntegrationLifecycleResolver(repository, policy=policy),
            lifecycle_repository=repository,
            lifecycle_policy=policy,
            bot_api=bot_api,
        ),
        repository,
    )


def test_uninstalled_lifecycle_record_avoids_removed_runtime_calls(tmp_path):
    lifecycle = LifecycleStateRepository(
        tmp_path / "agents-lifecycle.json",
        "agents",
    )
    lifecycle.write(
        {
            "schema_version": "1",
            "integration": "agents",
            "operation_id": "operation-1",
            "action": "uninstall",
            "phase": "complete",
            "target_state": "not_installed",
            "started_at": "2026-07-20T20:00:00+00:00",
            "updated_at": "2026-07-20T20:01:00+00:00",
            "completed_steps": [],
            "retained_data": False,
            "remove_claude_code": True,
            "failure": None,
            "warning_codes": [],
        }
    )

    def removed_helper(*_args, **_kwargs):
        raise AssertionError("removed runtime must not be queried")

    status = _service(
        removed_helper,
        lifecycle_resolver=IntegrationLifecycleResolver(lifecycle),
    ).status()

    assert status["state"] == "not_installed"
    assert status["installed"] is False
    assert status["allowed_actions"] == ["setup"]


def test_authoritative_agent_lifecycle_status_survives_unavailable_mattermost(tmp_path):
    service, repository = _lifecycle_service(
        tmp_path,
        mattermost=lambda: (_ for _ in ()).throw(RuntimeError("private outage")),
    )
    repository.write(
        {
            "schema_version": "1",
            "integration": "agents",
            "operation_id": "operation-1",
            "action": "disable",
            "phase": "complete",
            "target_state": "disabled",
            "started_at": "2026-07-21T12:00:00+00:00",
            "updated_at": "2026-07-21T12:00:00+00:00",
            "completed_steps": ["disable_runtime"],
            "retained_data": False,
            "remove_claude_code": None,
            "failure": None,
            "warning_codes": [],
        }
    )

    status = service.status()

    assert status["state"] == "disabled"
    assert status["allowed_actions"] == ["enable", "uninstall"]


def test_authoritative_agent_lifecycle_status_keeps_available_mattermost_details(
    tmp_path,
):
    service, repository = _lifecycle_service(tmp_path)
    repository.write(
        {
            "schema_version": "1",
            "integration": "agents",
            "operation_id": "operation-1",
            "action": "disable",
            "phase": "complete",
            "target_state": "disabled",
            "started_at": "2026-07-21T12:00:00+00:00",
            "updated_at": "2026-07-21T12:00:00+00:00",
            "completed_steps": ["disable_runtime"],
            "retained_data": False,
            "remove_claude_code": None,
            "failure": None,
            "warning_codes": [],
        }
    )

    status = service.status()

    assert status["mattermost"]["state"] == "connected"
    assert status["mattermost"]["site_url"] == "http://mattermost.local:8065"


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
    assert status["configured"] is True
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
    helper.responses["agent_runtime_status"].update(configured=True)
    statuses = iter(
        [
            {
                "success": True,
                "operation_id": "provider-auth-1",
                "state": "running",
                "cursor": 2,
                "events": [
                    {"type": "authorization_url", "url": "https://claude.com/oauth/x"},
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
    assert events[1]["authorization_url"].startswith("https://claude.com/")
    assert events[1]["_ephemeral"] is True
    assert events[-1]["done"] is True
    _service(helper).submit_auth("provider-auth-1", "approved-code")
    assert helper.calls[-1][0:2] == (
        "agent_provider_auth_submit",
        {"operation_id": "provider-auth-1", "code": "approved-code"},
    )


def test_guided_auth_completes_when_agent_configuration_still_needs_setup():
    helper = FakeHelper()
    statuses = iter(
        [
            {
                "success": True,
                "operation_id": "provider-auth-1",
                "state": "complete",
                "cursor": 1,
                "events": [{"type": "status", "message": "Claude authentication completed."}],
            }
        ]
    )
    helper.responses["agent_provider_auth_start"] = {
        "success": True,
        "operation_id": "provider-auth-1",
    }
    helper.responses["agent_provider_auth_status"] = lambda _params: next(statuses)

    events = list(_service(helper).stream_auth())

    assert events[-1] == {
        "step": "complete",
        "line": "Claude authentication completed. Finish assistant setup.",
        "requires_setup": True,
        "done": True,
    }
    assert not any(call[0] == "agent_runtime_start" for call in helper.calls)


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


def test_repair_delegates_to_the_fixed_helper_workflow():
    helper = FakeHelper()
    helper.responses["agent_runtime_status"].update(
        configured=True, claude_authenticated=True
    )
    events = list(_service(helper).stream_repair({}))
    assert events[-1]["done"] is True
    assert [call[0] for call in helper.calls] == ["agent_integration_repair"]
    assert helper.calls[0][2] == 1800


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


def test_lifecycle_disable_writes_tombstone_before_helper_and_completes(tmp_path):
    helper = FakeHelper()
    service, repository = _lifecycle_service(tmp_path, helper=helper)

    def disable(_params):
        record = repository.read()
        assert record["phase"] == "running"
        assert record["completed_steps"] == []
        return {"success": True, "disabled": True}

    helper.responses["agent_runtime_disable"] = disable
    events = list(service.stream_disable("disable-1"))

    assert events[-1]["done"] is True
    record = repository.read()
    assert record["target_state"] == "disabled"
    assert record["phase"] == "complete"
    assert record["completed_steps"] == ["disable_runtime"]
    assert record["remove_claude_code"] is None


def test_disable_failure_requires_cleanup_and_retry_is_idempotent(tmp_path):
    helper = FakeHelper()
    attempts = 0

    def disable(_params):
        nonlocal attempts
        attempts += 1
        return {
            "success": attempts > 1,
            "disabled": attempts > 1,
            "error": "private systemctl output",
        }

    helper.responses["agent_runtime_disable"] = disable
    service, repository = _lifecycle_service(tmp_path, helper=helper)

    failed = list(service.stream_disable("disable-failed"))

    assert failed[-1] == {
        "step": "error",
        "error": AGENT_LIFECYCLE_FAILURE_MESSAGE,
    }
    assert "private systemctl output" not in json.dumps(failed)
    assert service.status()["state"] == "cleanup_required"
    assert repository.read()["completed_steps"] == []

    retried = list(service.stream_retry_cleanup("disable-retry", {}))

    assert retried[-1]["done"] is True
    assert attempts == 2
    assert repository.read()["target_state"] == "disabled"


@pytest.mark.parametrize("remove_claude_code", [True, False])
def test_lifecycle_uninstall_removes_bot_then_exact_local_boundary(
    tmp_path, remove_claude_code
):
    helper = FakeHelper()
    helper.responses["agent_runtime_status"]["bot_user_id"] = "bot-1"
    bot = FakeBotApi()
    service, repository = _lifecycle_service(
        tmp_path, helper=helper, bot_api=bot
    )
    values = {
        "admin_username": "admin",
        "admin_password": "write-only-password",
        "remove_claude_code": remove_claude_code,
    }

    events = list(service.stream_uninstall("uninstall-1", values))

    assert events[-1] == {
        "step": "complete",
        "line": "AI Agents was uninstalled",
        "done": True,
    }
    assert bot.deleted == ["bot-1"]
    assert [call[0] for call in helper.calls] == [
        "agent_runtime_status",
        "agent_runtime_uninstall",
    ]
    assert helper.calls[-1][1] == {"remove_claude_code": remove_claude_code}
    record = repository.read()
    assert record["phase"] == "complete"
    assert record["target_state"] == "not_installed"
    assert record["completed_steps"] == [
        "remove_remote_bot",
        "remove_local_runtime",
    ]
    assert record["remove_claude_code"] is remove_claude_code
    serialized = json.dumps({"events": events, "record": record})
    assert "write-only-password" not in serialized


def test_remote_bot_failure_completes_only_after_local_cleanup_with_warning(tmp_path):
    class FailingBot(FakeBotApi):
        def delete_bot(self, *, user_id):
            raise RuntimeError(f"private remote failure for {user_id}")

    helper = FakeHelper()
    helper.responses["agent_runtime_status"]["bot_user_id"] = "bot-1"
    local_cleanup_observed = []
    helper.responses["agent_runtime_uninstall"] = lambda params: (
        local_cleanup_observed.append(dict(params))
        or {"success": True, "steps": []}
    )
    service, repository = _lifecycle_service(
        tmp_path, helper=helper, bot_api=FailingBot()
    )

    events = list(
        service.stream_uninstall(
            "uninstall-warning",
            {
                "admin_username": "admin",
                "admin_password": "write-only-password",
                "remove_claude_code": True,
            },
        )
    )

    assert local_cleanup_observed == [{"remove_claude_code": True}]
    assert events[-1]["warnings"] == [
        {
            "code": "agent_bot_cleanup_failed",
            "message": (
                "AI Agents was removed locally, but the Mattermost bot could not be removed."
            ),
        }
    ]
    assert "private remote failure" not in json.dumps(events)
    record = repository.read()
    assert record["phase"] == "complete"
    assert record["warning_codes"] == ["agent_bot_cleanup_failed"]
    assert service.status()["warnings"] == events[-1]["warnings"]


def test_local_cleanup_failure_retains_checkpoint_and_retry_skips_bot(tmp_path):
    helper = FakeHelper()
    helper.responses["agent_runtime_status"]["bot_user_id"] = "bot-1"
    attempts = 0

    def uninstall(_params):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"success": False, "failed_step": "remove_runtime", "steps": []}
        return {"success": True, "steps": []}

    helper.responses["agent_runtime_uninstall"] = uninstall
    bot = FakeBotApi()
    service, repository = _lifecycle_service(
        tmp_path, helper=helper, bot_api=bot
    )
    values = {
        "admin_username": "admin",
        "admin_password": "write-only-password",
        "remove_claude_code": False,
    }

    failed = list(service.stream_uninstall("uninstall-failed", values))

    assert failed[-1] == {
        "step": "error",
        "error": AGENT_LIFECYCLE_FAILURE_MESSAGE,
    }
    record = repository.read()
    assert record["phase"] == "cleanup_required"
    assert record["completed_steps"] == ["remove_remote_bot"]
    assert record["failure"]["code"] == "agent_uninstall_failed"
    assert bot.deleted == ["bot-1"]

    retried = list(
        service.stream_retry_cleanup(
            "uninstall-retry",
            {
                "admin_username": "admin",
                "admin_password": "fresh-write-only-password",
            },
        )
    )

    assert retried[-1]["done"] is True
    assert attempts == 2
    assert bot.deleted == ["bot-1"]
    record = repository.read()
    assert record["operation_id"] == "uninstall-retry"
    assert record["phase"] == "complete"
    assert record["completed_steps"] == [
        "remove_remote_bot",
        "remove_local_runtime",
    ]
    serialized = json.dumps({"failed": failed, "retried": retried, "record": record})
    assert "write-only-password" not in serialized
    assert "fresh-write-only-password" not in serialized


def test_uninstall_from_disabled_replaces_tombstone_and_setup_clears_it(tmp_path):
    helper = FakeHelper()
    helper.responses["agent_runtime_status"].update(
        bot_user_id=None,
        claude_authenticated=False,
    )
    service, repository = _lifecycle_service(tmp_path, helper=helper)
    assert list(service.stream_disable("disable-first"))[-1]["done"] is True

    assert list(
        service.stream_uninstall(
            "uninstall-after-disable",
            {
                "admin_username": "admin",
                "admin_password": "write-only-password",
                "remove_claude_code": True,
            },
        )
    )[-1]["done"] is True
    assert repository.read()["target_state"] == "not_installed"

    events = list(
        service.stream_install(
            {
                "admin_username": "admin",
                "admin_password": "write-only-password",
            }
        )
    )
    assert events[-1]["done"] is True
    assert repository.read() is None


def test_uninstall_and_retry_reject_unknown_or_missing_secret_fields(tmp_path):
    service, repository = _lifecycle_service(tmp_path)
    events = list(
        service.stream_uninstall(
            "bad-uninstall",
            {
                "admin_username": "admin",
                "admin_password": "write-only-password",
                "remove_claude_code": True,
                "path": "/var/lib/private",
            },
        )
    )
    assert events[-1]["error"] == "Uninstall values are invalid"
    assert repository.read() is None


def test_helper_error_text_is_private():
    helper = FakeHelper()
    helper.responses["agent_usage_read"] = {
        "success": False,
        "error": "private /etc/limeos/integrations/agents.env SECRET",
    }
    with pytest.raises(AgentIntegrationError) as exc_info:
        _service(helper).usage()
    assert "SECRET" not in str(exc_info.value)
