"""IL-005 secured streamed integration lifecycle API contract."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from werkzeug.security import generate_password_hash

from app import AppDependencies, LoginRateLimiter, create_app
from operation_manager import OperationRegistry


ROUTES = (
    ("agents", "disable", "/api/integrations/agents/disable", {}),
    (
        "agents",
        "uninstall",
        "/api/integrations/agents/uninstall",
        {
            "confirmation": "AI Agents",
            "admin_username": "limeadmin",
            "admin_password": "fresh-password",
            "remove_claude_code": True,
        },
    ),
    ("mattermost", "disable", "/api/integrations/mattermost/disable", {}),
    ("mattermost", "enable", "/api/integrations/mattermost/enable", {}),
    (
        "mattermost",
        "uninstall",
        "/api/integrations/mattermost/uninstall",
        {"confirmation": "Mattermost"},
    ),
    (
        "mattermost",
        "purge",
        "/api/integrations/mattermost/purge",
        {"confirmation": "Mattermost", "acknowledge_data_loss": True},
    ),
)


class ImmediateThread:
    def __init__(self, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class DormantThread:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        pass


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(dict(event))
        return True


class Authorizer:
    def __init__(self, allowed=True):
        self.allowed = allowed

    def allows(self, username, permission):
        assert username == "admin"
        assert permission == "extensions.admin"
        return self.allowed


class UnavailableAuthorizer:
    def allows(self, _username, _permission):
        raise RuntimeError("policy backend details must stay private")


def _service():
    service = Mock()
    service.status.return_value = {
        "state": "connected",
        "allowed_actions": ["disable", "enable", "uninstall", "purge"],
        "blocked_actions": [],
        "cleanup_operation": None,
    }
    for action in ("disable", "enable", "uninstall", "purge"):
        getattr(service, f"stream_{action}").side_effect = (
            lambda operation_id, *args, selected=action: iter(
                [
                    {"step": selected, "line": f"{selected} completed"},
                    {"step": "complete", "done": True},
                ]
            )
        )
    service.stream_retry_cleanup.side_effect = lambda *_args: iter(
        [{"step": "complete", "done": True}]
    )
    return service


def _client(
    *,
    agents=None,
    mattermost=None,
    authenticated=True,
    authorizer=None,
    audit=None,
    registry=None,
):
    agents = agents or _service()
    mattermost = mattermost or _service()
    dependencies = AppDependencies(
        users={"admin": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=registry
        or OperationRegistry(thread_factory=ImmediateThread),
        agent_integration_service=agents,
        mattermost_integration_service=mattermost,
        capability_authorizer=authorizer or Authorizer(),
        audit=audit,
    )
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "INIT_PLUGINS": False,
            "START_SCHEDULERS": False,
        },
        dependencies,
    )
    client = app.test_client()
    if authenticated:
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["username"] = "admin"
            session["csrf_token"] = "csrf-token"
        client.environ_base["HTTP_X_CSRF_TOKEN"] = "csrf-token"
    return client, agents, mattermost


@pytest.mark.parametrize("_integration,_action,path,values", ROUTES)
def test_lifecycle_routes_require_authentication(_integration, _action, path, values):
    client, _agents, _mattermost = _client(authenticated=False)
    assert client.post(path, json=values).status_code == 401


@pytest.mark.parametrize("_integration,_action,path,values", ROUTES)
def test_lifecycle_routes_require_csrf_and_admin(_integration, _action, path, values):
    client, agents, mattermost = _client()
    client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert client.post(path, json=values).status_code == 403
    agents.status.assert_not_called()
    mattermost.status.assert_not_called()

    client, agents, mattermost = _client(authorizer=Authorizer(False))
    response = client.post(path, json=values)
    assert response.status_code == 403
    assert response.get_json()["code"] == "integration_lifecycle_forbidden"
    agents.status.assert_not_called()
    mattermost.status.assert_not_called()


def test_unavailable_authorization_policy_fails_closed_before_status():
    audit = RecordingAudit()
    client, agents, mattermost = _client(
        authorizer=UnavailableAuthorizer(), audit=audit
    )
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 503
    assert response.get_json() == {
        "code": "integration_authorization_unavailable",
        "error": "Integration authorization policy is unavailable.",
    }
    agents.status.assert_not_called()
    mattermost.status.assert_not_called()
    assert audit.events[-1]["decision"] == "unavailable"

@pytest.mark.parametrize(
    "path,values",
    (
        ("/api/integrations/agents/disable", {"extra": True}),
        ("/api/integrations/mattermost/enable", None),
        (
            "/api/integrations/agents/uninstall",
            {
                "confirmation": "Agents",
                "admin_username": "limeadmin",
                "admin_password": "fresh-password",
                "remove_claude_code": True,
            },
        ),
        (
            "/api/integrations/agents/uninstall",
            {
                "confirmation": "AI Agents",
                "admin_username": "limeadmin",
                "admin_password": "fresh-password",
                "remove_claude_code": "yes",
            },
        ),
        (
            "/api/integrations/mattermost/uninstall",
            {"confirmation": "mattermost"},
        ),
        (
            "/api/integrations/mattermost/purge",
            {"confirmation": "Mattermost", "acknowledge_data_loss": False},
        ),
    ),
)
def test_invalid_lifecycle_values_fail_before_status_or_service(path, values):
    client, agents, mattermost = _client()
    response = (
        client.post(path, data="null", content_type="application/json")
        if values is None
        else client.post(path, json=values)
    )
    assert response.status_code == 400
    agents.status.assert_not_called()
    mattermost.status.assert_not_called()


@pytest.mark.parametrize("integration,action,path,values", ROUTES)
def test_lifecycle_routes_start_owner_bound_operations(
    integration, action, path, values
):
    client, agents, mattermost = _client()
    response = client.post(path, json=values)
    assert response.status_code == 202
    created = response.get_json()
    assert created["operation_id"] in created["stream_url"]
    stream = client.get(created["stream_url"])
    assert stream.status_code == 200
    assert b'"done": true' in stream.data

    service = agents if integration == "agents" else mattermost
    method = getattr(service, f"stream_{action}")
    args = method.call_args.args
    assert args[0] == created["operation_id"]
    if integration == "agents" and action == "uninstall":
        assert args[1] == {
            "admin_username": "limeadmin",
            "admin_password": "fresh-password",
            "remove_claude_code": True,
        }

    other = app_client_for_other_session(client.application)
    assert other.get(created["stream_url"]).status_code == 404


def app_client_for_other_session(application):
    client = application.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "admin"
        session["csrf_token"] = "different-owner"
    return client


def test_stale_or_dependency_blocked_action_returns_server_owned_conflict():
    agents = _service()
    agents.status.return_value = {
        "state": "connected",
        "allowed_actions": [],
        "blocked_actions": [
            {
                "action": "disable",
                "message": "Disable AI Agents before disabling Mattermost.",
            }
        ],
    }
    client, _agents, _mattermost = _client(agents=agents)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 409
    assert response.get_json() == {
        "code": "integration_action_unavailable",
        "error": "Disable AI Agents before disabling Mattermost.",
    }
    agents.stream_disable.assert_not_called()


@pytest.mark.parametrize(
    "status",
    (
        {"allowed_actions": ["disable"], "blocked_actions": None},
        {"allowed_actions": [123], "blocked_actions": []},
    ),
)
def test_malformed_server_action_status_fails_closed(status):
    agents = _service()
    agents.status.return_value = status
    client, _agents, _mattermost = _client(agents=agents)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 503
    assert response.get_json()["code"] == "integration_status_unavailable"
    agents.stream_disable.assert_not_called()


def test_sensitive_blocked_action_message_is_replaced():
    agents = _service()
    agents.status.return_value = {
        "allowed_actions": [],
        "blocked_actions": [
            {"action": "disable", "message": "Read token at /private/state"}
        ],
    }
    client, _agents, _mattermost = _client(agents=agents)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 409
    assert response.get_json()["error"] == (
        "Integration action is not available in the current state."
    )


def test_cleanup_retry_uses_recorded_action_and_fresh_agent_credentials_only():
    agents = _service()
    agents.status.return_value = {
        "state": "cleanup_required",
        "allowed_actions": ["retry_cleanup"],
        "blocked_actions": [],
        "cleanup_operation": {"action": "uninstall"},
    }
    client, _agents, _mattermost = _client(agents=agents)
    response = client.post(
        "/api/integrations/agents/uninstall",
        json={
            "confirmation": "AI Agents",
            "admin_username": "limeadmin",
            "admin_password": "new-password",
            "remove_claude_code": False,
        },
    )
    assert response.status_code == 202
    operation_id = response.get_json()["operation_id"]
    agents.stream_retry_cleanup.assert_called_once_with(
        operation_id,
        {"admin_username": "limeadmin", "admin_password": "new-password"},
    )
    agents.stream_uninstall.assert_not_called()


def test_same_integration_operations_conflict_before_second_service_call():
    registry = OperationRegistry(thread_factory=DormantThread)
    client, agents, _mattermost = _client(registry=registry)
    assert client.post("/api/integrations/agents/disable", json={}).status_code == 202
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 409
    assert response.get_json()["code"] == "integration_operation_conflict"
    assert agents.stream_disable.call_count == 0


def test_operation_capacity_is_a_stable_429():
    registry = OperationRegistry(thread_factory=DormantThread, operation_limit=0)
    client, _agents, _mattermost = _client(registry=registry)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 429
    assert response.get_json() == {
        "code": "operation_capacity_reached",
        "error": "No integration operation slot is available.",
    }


def test_events_and_audit_are_bounded_and_secret_free():
    audit = RecordingAudit()
    agents = _service()
    agents.stream_disable.side_effect = lambda _operation_id: iter(
        [
            {
                "step": "disable",
                "line": "password=hidden /home/holly/private.env",
                "private": "WEBHOOK_URL=https://example.invalid/secret",
            },
            {
                "step": "failed",
                "error": "token=hidden at /var/lib/limeos",
            },
        ]
    )
    client, _agents, _mattermost = _client(agents=agents, audit=audit)
    response = client.post("/api/integrations/agents/disable", json={})
    body = client.get(response.get_json()["stream_url"]).get_data(as_text=True)
    assert "hidden" not in body
    assert "/home/" not in body
    assert "/var/" not in body
    assert "private" not in body
    assert "Integration lifecycle step is running" in body
    assert "Integration lifecycle operation failed" in body

    assert [event["outcome"] for event in audit.events] == ["accepted", "failed"]
    serialized = repr(audit.events)
    assert "hidden" not in serialized
    assert "password" not in serialized
    assert all(event["permission"] == "extensions.admin" for event in audit.events)


@pytest.mark.parametrize(
    "events,outcome,code",
    (
        ([{"step": "complete", "done": True}], "succeeded", "ok"),
        (
            [
                {
                    "step": "complete",
                    "done": True,
                    "warnings": [{"code": "agent_bot_cleanup_failed"}],
                }
            ],
            "warning",
            "agent_bot_cleanup_failed",
        ),
    ),
)
def test_terminal_lifecycle_outcomes_are_audited(events, outcome, code):
    audit = RecordingAudit()
    agents = _service()
    agents.stream_disable.side_effect = lambda _operation_id: iter(events)
    client, _agents, _mattermost = _client(agents=agents, audit=audit)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 202
    client.get(response.get_json()["stream_url"])

    assert [event["outcome"] for event in audit.events] == ["accepted", outcome]
    assert audit.events[-1]["code"] == code


def test_status_failure_is_stable_and_does_not_start_an_operation():
    agents = _service()
    agents.status.side_effect = RuntimeError("token=secret /private/path")
    client, _agents, _mattermost = _client(agents=agents)
    response = client.post("/api/integrations/agents/disable", json={})
    assert response.status_code == 503
    assert response.get_json() == {
        "code": "integration_status_unavailable",
        "error": "Integration status is unavailable.",
    }
    agents.stream_disable.assert_not_called()
