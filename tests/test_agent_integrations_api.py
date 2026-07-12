"""AA-006 authenticated Flask routes and owner-bound operation streams."""

from __future__ import annotations

import threading
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, LoginRateLimiter, create_app
from operation_manager import OperationRegistry


class ImmediateThread:
    def __init__(self, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def _client(service, *, authenticated=True, thread_factory=ImmediateThread):
    dependencies = AppDependencies(
        users={"admin": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(thread_factory=thread_factory),
        agent_integration_service=service,
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
    return client


def _service():
    service = Mock()
    service.status.return_value = {"state": "not_installed"}
    service.providers.return_value = {"providers": []}
    service.permissions.return_value = {"allowed_operations": []}
    service.usage.return_value = {"totals": {}, "records": []}
    service.audit.return_value = {"records": []}
    service.disable.return_value = {"state": "disabled"}
    service.test_delivery.return_value = {"status": "sent"}
    service.submit_auth.return_value = {"accepted": True}
    service.cancel_auth.return_value = {"cancelled": True}
    service.stream_install.return_value = iter([{"step": "complete", "done": True}])
    service.stream_repair.return_value = iter([{"step": "complete", "done": True}])
    service.stream_auth.return_value = iter([{"step": "complete", "done": True}])
    return service


def test_all_agent_routes_require_authentication():
    client = _client(_service(), authenticated=False)
    for path in (
        "/api/integrations/agents",
        "/api/integrations/agents/providers",
        "/api/integrations/agents/permissions",
        "/api/integrations/agents/usage",
        "/api/integrations/agents/audit",
    ):
        assert client.get(path).status_code == 401
    assert client.post("/api/integrations/agents/install", json={}).status_code == 401


def test_read_routes_delegate_to_agent_service():
    service = _service()
    client = _client(service)
    assert client.get("/api/integrations/agents").status_code == 200
    assert client.get("/api/integrations/agents/providers").status_code == 200
    assert client.get("/api/integrations/agents/permissions").status_code == 200
    assert client.get("/api/integrations/agents/usage?limit=25").status_code == 200
    assert client.get("/api/integrations/agents/audit?limit=30").status_code == 200
    service.usage.assert_called_once_with(limit=25)
    service.audit.assert_called_once_with(limit=30)


def test_install_repair_and_auth_start_owner_bound_streams():
    service = _service()
    client = _client(service, thread_factory=threading.Thread)
    install = client.post(
        "/api/integrations/agents/install",
        json={"admin_username": "admin", "admin_password": "write-only-password"},
    )
    assert install.status_code == 202
    assert client.get(install.get_json()["stream_url"]).status_code == 200
    repair = client.post("/api/integrations/agents/repair", json={})
    assert repair.status_code == 202
    assert client.get(repair.get_json()["stream_url"]).status_code == 200
    auth = client.post("/api/integrations/agents/providers/claude/auth", json={"action": "start"})
    assert auth.status_code == 202
    assert client.get(auth.get_json()["stream_url"]).status_code == 200


def test_auth_submit_cancel_disable_and_delivery_test_are_csrf_protected():
    service = _service()
    client = _client(service)
    assert client.post(
        "/api/integrations/agents/providers/claude/auth",
        json={"action": "submit", "operation_id": "auth-1", "code": "approved"},
    ).status_code == 200
    assert client.post(
        "/api/integrations/agents/providers/claude/auth",
        json={"action": "cancel", "operation_id": "auth-1"},
    ).status_code == 200
    assert client.post("/api/integrations/agents/disable").status_code == 200
    assert client.post("/api/integrations/agents/test").status_code == 200
    client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert client.post("/api/integrations/agents/disable").status_code == 403


def test_operation_stream_is_not_visible_to_another_session():
    service = _service()
    owner = _client(service)
    install = owner.post("/api/integrations/agents/install", json={})
    stream_url = install.get_json()["stream_url"]
    other = _client(service)
    with other.session_transaction() as session:
        session["csrf_token"] = "different-owner"
    assert other.get(stream_url).status_code == 404
