"""AA-006 authenticated Flask routes and owner-bound operation streams."""

from __future__ import annotations

import threading
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, LoginRateLimiter, create_app
from agent_actions.service import AgentActionError
from agent_findings.service import FindingError
from operation_manager import OperationRegistry


class ImmediateThread:
    def __init__(self, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def _client(
    service,
    *,
    authenticated=True,
    thread_factory=ImmediateThread,
    action_service=None,
    findings_service=None,
    capability_roles=None,
):
    dependencies = AppDependencies(
        users={"admin": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(thread_factory=thread_factory),
        agent_integration_service=service,
        agent_action_service=action_service,
        agent_findings_service=findings_service,
        capability_roles=capability_roles,
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
    service.stream_disable.return_value = iter([{"step": "complete", "done": True}])
    service.test_delivery.return_value = {"status": "sent"}
    service.submit_auth.return_value = {"accepted": True}
    service.cancel_auth.return_value = {"cancelled": True}
    service.stream_install.return_value = iter([{"step": "complete", "done": True}])
    service.stream_repair.return_value = iter([{"step": "complete", "done": True}])
    service.stream_auth.return_value = iter([{"step": "complete", "done": True}])
    return service


def _action_service():
    service = Mock()
    service.list.return_value = {"actions": []}
    service.get.return_value = {"id": "action-1", "state": "awaiting_approval"}
    service.approve.return_value = {"id": "action-1", "state": "authorised"}
    service.reject.return_value = {"id": "action-1", "state": "rejected"}
    return service


def _findings_service():
    service = Mock()
    service.list.return_value = {"findings": []}
    service.get.return_value = {"id": "finding-1", "state": "draft"}
    service.update.return_value = {"id": "finding-1", "state": "draft"}
    service.reject.return_value = {"id": "finding-1", "state": "rejected"}
    return service


def test_all_agent_routes_require_authentication():
    client = _client(_service(), authenticated=False)
    for path in (
        "/api/integrations/agents",
        "/api/integrations/agents/providers",
        "/api/integrations/agents/permissions",
        "/api/integrations/agents/usage",
        "/api/integrations/agents/audit",
        "/api/integrations/agents/actions",
        "/api/integrations/agents/findings",
    ):
        assert client.get(path).status_code == 401
    assert client.post("/api/integrations/agents/install", json={}).status_code == 401
    assert client.post(
        "/api/integrations/agents/actions/action-1/approve", json={}
    ).status_code == 401


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
    service.status.return_value = {
        "state": "connected",
        "allowed_actions": ["disable"],
    }
    disable = client.post("/api/integrations/agents/disable", json={})
    assert disable.status_code == 202
    assert client.get(disable.get_json()["stream_url"]).status_code == 200
    assert client.post("/api/integrations/agents/test").status_code == 200
    client.environ_base.pop("HTTP_X_CSRF_TOKEN")
    assert client.post("/api/integrations/agents/disable").status_code == 403


def test_auth_rejects_malformed_missing_and_unknown_fields():
    service = _service()
    client = _client(service)
    path = "/api/integrations/agents/providers/claude/auth"
    assert client.post(path, data="{", content_type="application/json").status_code == 400
    assert client.post(path, json={}).status_code == 400
    assert client.post(path, json={"action": "start", "extra": True}).status_code == 400
    assert client.post(path, json={"action": "submit", "operation_id": "auth-1"}).status_code == 400
    service.stream_auth.assert_not_called()
    service.submit_auth.assert_not_called()


def test_operation_stream_is_not_visible_to_another_session():
    service = _service()
    owner = _client(service)
    install = owner.post("/api/integrations/agents/install", json={})
    stream_url = install.get_json()["stream_url"]
    other = _client(service)
    with other.session_transaction() as session:
        session["csrf_token"] = "different-owner"
    assert other.get(stream_url).status_code == 404


def test_action_routes_list_read_approve_and_reject_with_stable_local_actor():
    actions = _action_service()
    client = _client(_service(), action_service=actions)
    listed = client.get("/api/integrations/agents/actions?limit=25")
    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "no-store"
    actions.list.assert_called_once_with(limit=25)

    detail = client.get("/api/integrations/agents/actions/action-1")
    assert detail.status_code == 200
    actions.get.assert_called_once_with("action-1")

    approved = client.post(
        "/api/integrations/agents/actions/action-1/approve", json={}
    )
    assert approved.status_code == 200
    actions.approve.assert_called_once_with(
        "action-1",
        approver={"type": "local", "id": "admin", "username": "admin"},
    )

    rejected = client.post(
        "/api/integrations/agents/actions/action-2/reject", json={}
    )
    assert rejected.status_code == 200
    actions.reject.assert_called_once_with("action-2")


def test_action_mutations_require_admin_and_strict_empty_body():
    actions = _action_service()
    client = _client(
        _service(),
        action_service=actions,
        capability_roles={"admin": "viewer"},
    )
    assert client.get("/api/integrations/agents/actions").status_code == 200
    assert client.post(
        "/api/integrations/agents/actions/action-1/approve", json={}
    ).status_code == 403
    actions.approve.assert_not_called()

    admin = _client(_service(), action_service=actions)
    assert admin.post(
        "/api/integrations/agents/actions/action-1/approve", json={"extra": True}
    ).status_code == 400
    actions.approve.assert_not_called()


def test_action_api_maps_bounded_domain_errors():
    actions = _action_service()
    actions.get.side_effect = AgentActionError("not_found", "Action was not found")
    actions.approve.side_effect = AgentActionError(
        "precondition_changed", "Target changed after proposal"
    )
    client = _client(_service(), action_service=actions)
    assert client.get("/api/integrations/agents/actions/missing").status_code == 404
    changed = client.post(
        "/api/integrations/agents/actions/action-1/approve", json={}
    )
    assert changed.status_code == 409
    assert changed.get_json()["code"] == "precondition_changed"


def test_finding_routes_are_private_editable_and_admin_bound():
    findings = _findings_service()
    client = _client(_service(), findings_service=findings)
    assert client.get("/api/integrations/agents/findings?limit=10").status_code == 200
    findings.list.assert_called_once_with(limit=10)
    detail = client.get("/api/integrations/agents/findings/finding-1")
    assert detail.status_code == 200

    payload = {
        "kind": "bug",
        "title": "Edited",
        "summary": "Summary",
        "component": "agent",
        "affected_version": "",
        "expected_behavior": "",
        "actual_behavior": "",
        "reproduction_steps": [],
        "impact": "Impact",
        "frequency": "",
        "workaround": "",
        "confidence": "medium",
        "acceptance_criteria": [],
        "source_type": "manual",
    }
    assert client.put(
        "/api/integrations/agents/findings/finding-1", json=payload
    ).status_code == 200
    findings.update.assert_called_once_with("finding-1", payload)
    assert client.post(
        "/api/integrations/agents/findings/finding-1/reject", json={}
    ).status_code == 200
    findings.reject.assert_called_once_with("finding-1")

    viewer = _client(
        _service(), findings_service=findings, capability_roles={"admin": "viewer"}
    )
    assert viewer.get("/api/integrations/agents/findings").status_code == 200
    assert viewer.put(
        "/api/integrations/agents/findings/finding-1", json=payload
    ).status_code == 403


def test_finding_api_maps_bounded_store_errors():
    findings = _findings_service()
    findings.get.side_effect = FindingError("not_found", "Finding was not found")
    client = _client(_service(), findings_service=findings)
    response = client.get("/api/integrations/agents/findings/missing")
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
