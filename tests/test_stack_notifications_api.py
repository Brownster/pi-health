"""Token-gated *arr webhook route + authenticated status route."""

from __future__ import annotations

from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, LoginRateLimiter, create_app


def _client(service, *, authenticated=False):
    dependencies = AppDependencies(
        users={"admin": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        stack_notifications_service=service,
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
    service.status.return_value = {"enabled": True, "mode": "quiet", "token": "tok"}
    service.ingest.return_value = ({"status": "forwarded", "event": "imported"}, 200)
    return service


def test_ingest_needs_no_auth_and_passes_token_and_payload_through():
    service = _service()
    client = _client(service)
    response = client.post(
        "/api/integrations/stack-notifications/hook/tok", json={"eventType": "Download"}
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "forwarded"
    service.ingest.assert_called_once_with("tok", {"eventType": "Download"})


def test_ingest_propagates_service_status_code():
    service = _service()
    service.ingest.return_value = ({"error": "Unauthorized"}, 401)
    client = _client(service)
    response = client.post("/api/integrations/stack-notifications/hook/wrong", json={})
    assert response.status_code == 401


def test_ingest_rejects_oversized_body_before_parsing():
    service = _service()
    client = _client(service)
    response = client.post(
        "/api/integrations/stack-notifications/hook/tok",
        data=b"x" * (256 * 1024 + 1),
        content_type="application/json",
    )
    assert response.status_code == 413
    service.ingest.assert_not_called()


def test_ingest_tolerates_a_non_json_body():
    service = _service()
    client = _client(service)
    response = client.post(
        "/api/integrations/stack-notifications/hook/tok",
        data=b"not json",
        content_type="application/json",
    )
    assert response.status_code == 200
    # silent parse yields None; the service decides what to do with it
    service.ingest.assert_called_once_with("tok", None)


def test_status_requires_authentication():
    client = _client(_service(), authenticated=False)
    assert client.get("/api/integrations/stack-notifications").status_code == 401


def test_status_returns_service_status_for_the_admin():
    service = _service()
    client = _client(service, authenticated=True)
    response = client.get("/api/integrations/stack-notifications")
    assert response.status_code == 200
    assert response.get_json()["token"] == "tok"


def test_mode_route_requires_auth():
    client = _client(_service(), authenticated=False)
    assert client.put("/api/integrations/stack-notifications/mode", json={"mode": "verbose"}).status_code == 401


def test_mode_route_passes_mode_to_service():
    service = _service()
    service.set_mode.return_value = ({"mode": "verbose"}, 200)
    client = _client(service, authenticated=True)
    response = client.put(
        "/api/integrations/stack-notifications/mode", json={"mode": "verbose"}
    )
    assert response.status_code == 200
    service.set_mode.assert_called_once_with("verbose")


def test_pending_setup_actions_flags_missing_stack_or_updates_channel():
    from integrations_manager import pending_setup_actions

    # stack notifications missing (updates present)
    actions = pending_setup_actions(
        mattermost_status={"installed": True, "updates_channel_configured": True},
        stack_notifications_status={"configured": False},
    )
    assert [a["id"] for a in actions] == ["limeos-channels-setup"]
    assert actions[0]["href"] == "/integrations"
    # updates channel missing (stack present) — e.g. an install that predates the updates channel
    actions = pending_setup_actions(
        mattermost_status={"installed": True, "updates_channel_configured": False},
        stack_notifications_status={"configured": True},
    )
    assert [a["id"] for a in actions] == ["limeos-channels-setup"]


def test_pending_setup_actions_empty_when_all_configured_or_no_mattermost():
    from integrations_manager import pending_setup_actions

    assert pending_setup_actions(
        mattermost_status={"installed": True, "updates_channel_configured": True},
        stack_notifications_status={"configured": True},
    ) == []
    assert pending_setup_actions(
        mattermost_status={"installed": False},
        stack_notifications_status={"configured": False},
    ) == []
