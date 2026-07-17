from unittest.mock import Mock

import pytest

from capability_api import CapabilityLifecycleError


SNAPSHOT = {
    "schema_version": "1",
    "providers": [
        {
            "id": "mergerfs",
            "name": "MergerFS",
            "enabled": True,
            "capabilities": [{"id": "storage.pooling"}],
        },
        {
            "id": "snapraid",
            "name": "SnapRAID",
            "enabled": False,
            "capabilities": [{"id": "storage.protection"}],
        },
    ],
    "capabilities": [
        {
            "id": "storage.pooling",
            "surface": "pools",
            "providers": [{"id": "mergerfs"}],
        },
        {
            "id": "storage.protection",
            "surface": "protection",
            "providers": [{"id": "snapraid"}],
        },
    ],
    "errors": [
        {
            "code": "provider_status_unavailable",
            "provider_id": "snapraid",
            "message": "Provider status is unavailable.",
        }
    ],
}


class Registry:
    def __init__(self, snapshot=SNAPSHOT):
        self._snapshot = snapshot

    def snapshot(self):
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot


class Authorizer:
    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = []

    def allows(self, username, permission):
        self.calls.append((username, permission))
        return self.allowed


class LifecycleService:
    def __init__(self):
        self.calls = []

    def install(self, values, *, username):
        self.calls.append(("install", values, username))
        return {"status": "installed", "id": "new-provider"}, 201

    def transition(self, provider_id, action, values, *, username):
        self.calls.append((action, provider_id, values, username))
        return {"status": action, "id": provider_id}


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/capabilities"),
        ("get", "/api/capabilities/storage.pooling"),
        ("get", "/api/extensions"),
        ("get", "/api/extensions/mergerfs"),
        ("post", "/api/extensions/install"),
        ("post", "/api/extensions/mergerfs/enable"),
        ("delete", "/api/extensions/mergerfs"),
    ],
)
def test_capability_routes_require_authentication(client, method, path):
    response = getattr(client, method)(path, json={})
    assert response.status_code == 401


def test_list_routes_return_registry_collections_and_disable_caching(
    authenticated_client, app
):
    app.extensions["capability_registry_service"] = Registry()

    capabilities = authenticated_client.get("/api/capabilities")
    extensions = authenticated_client.get("/api/extensions")

    assert capabilities.status_code == 200
    assert capabilities.get_json() == {
        "schema_version": "1",
        "capabilities": SNAPSHOT["capabilities"],
        "errors": SNAPSHOT["errors"],
    }
    assert extensions.get_json() == {
        "schema_version": "1",
        "extensions": SNAPSHOT["providers"],
        "errors": SNAPSHOT["errors"],
    }
    assert capabilities.headers["Cache-Control"] == "no-store"
    assert extensions.headers["Cache-Control"] == "no-store"


def test_default_registry_is_available_before_provider_adapters(authenticated_client):
    response = authenticated_client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.get_json() == {
        "schema_version": "1",
        "capabilities": [],
        "errors": [],
    }


def test_detail_routes_return_one_item_and_relevant_diagnostics(
    authenticated_client, app
):
    app.extensions["capability_registry_service"] = Registry()

    capability = authenticated_client.get("/api/capabilities/storage.pooling")
    protection = authenticated_client.get("/api/capabilities/storage.protection")
    extension = authenticated_client.get("/api/extensions/snapraid")

    assert capability.status_code == 200
    assert capability.get_json()["capability"]["id"] == "storage.pooling"
    assert capability.get_json()["errors"] == []
    assert protection.get_json()["errors"] == SNAPSHOT["errors"]
    assert extension.status_code == 200
    assert extension.get_json()["extension"]["id"] == "snapraid"
    assert extension.get_json()["errors"] == SNAPSHOT["errors"]


@pytest.mark.parametrize(
    "path,code,status",
    [
        ("/api/capabilities/missing.capability", "capability_not_found", 404),
        ("/api/extensions/missing", "extension_not_found", 404),
        ("/api/capabilities/INVALID", "invalid_capability_id", 400),
        ("/api/extensions/INVALID", "invalid_extension_id", 400),
    ],
)
def test_detail_routes_return_stable_lookup_errors(
    authenticated_client, app, path, code, status
):
    app.extensions["capability_registry_service"] = Registry()

    response = authenticated_client.get(path)

    assert response.status_code == status
    assert response.get_json()["code"] == code


@pytest.mark.parametrize(
    "snapshot",
    [
        RuntimeError("secret=must-not-leak"),
        {},
        {"schema_version": "2", "providers": [], "capabilities": [], "errors": []},
        {
            "schema_version": "1",
            "providers": ["invalid"],
            "capabilities": [],
            "errors": [],
        },
    ],
)
def test_registry_transport_failures_are_bounded(
    authenticated_client, app, snapshot
):
    app.extensions["capability_registry_service"] = Registry(snapshot)

    response = authenticated_client.get("/api/capabilities")

    assert response.status_code == 503
    assert response.get_json() == {
        "code": "capability_registry_unavailable",
        "error": "Capability registry is unavailable.",
    }
    assert "must-not-leak" not in response.get_data(as_text=True)


def test_registry_diagnostics_remain_a_successful_partial_read(
    authenticated_client, app
):
    partial = {
        "schema_version": "1",
        "providers": [],
        "capabilities": [],
        "errors": [{"code": "provider_discovery_unavailable"}],
    }
    app.extensions["capability_registry_service"] = Registry(partial)

    response = authenticated_client.get("/api/extensions")

    assert response.status_code == 200
    assert response.get_json()["errors"] == partial["errors"]


def test_lifecycle_fails_closed_without_cp006_authorization(authenticated_client):
    response = authenticated_client.post("/api/extensions/mergerfs/enable", json={})

    assert response.status_code == 503
    assert response.get_json()["code"] == "authorization_unavailable"


def test_lifecycle_denies_user_without_admin_permission(
    authenticated_client, app
):
    authorizer = Authorizer(False)
    service = LifecycleService()
    app.extensions["capability_authorizer"] = authorizer
    app.extensions["capability_lifecycle_service"] = service

    response = authenticated_client.post("/api/extensions/mergerfs/enable", json={})

    assert response.status_code == 403
    assert authorizer.calls == [("testuser", "extensions.admin")]
    assert service.calls == []


def test_lifecycle_requires_json_object_after_authorization(
    authenticated_client, app
):
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = LifecycleService()

    response = authenticated_client.post(
        "/api/extensions/mergerfs/enable",
        data="not-json",
        content_type="text/plain",
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_request"


def test_lifecycle_fails_closed_when_implementation_is_missing(
    authenticated_client, app
):
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = None

    response = authenticated_client.post("/api/extensions/mergerfs/enable", json={})

    assert response.status_code == 503
    assert response.get_json()["code"] == "extension_lifecycle_unavailable"


@pytest.mark.parametrize("action", ["enable", "disable", "update", "repair"])
def test_lifecycle_transitions_use_fixed_actions_and_actor(
    authenticated_client, app, action
):
    service = LifecycleService()
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = service

    response = authenticated_client.post(
        f"/api/extensions/mergerfs/{action}", json={"force": False}
    )

    assert response.status_code == 200
    assert response.get_json() == {"id": "mergerfs", "status": action}
    assert service.calls == [(action, "mergerfs", {"force": False}, "testuser")]


def test_install_and_remove_use_bounded_lifecycle_transport(
    authenticated_client, app
):
    service = LifecycleService()
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = service

    installed = authenticated_client.post(
        "/api/extensions/install",
        json={"source": "https://example.invalid/provider"},
    )
    removed = authenticated_client.delete("/api/extensions/mergerfs")

    assert installed.status_code == 201
    assert removed.status_code == 200
    assert service.calls == [
        (
            "install",
            {"source": "https://example.invalid/provider"},
            "testuser",
        ),
        ("remove", "mergerfs", {}, "testuser"),
    ]


def test_unknown_lifecycle_action_is_not_dispatched(authenticated_client, app):
    service = LifecycleService()
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = service

    response = authenticated_client.post(
        "/api/extensions/mergerfs/run-shell", json={}
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "invalid_lifecycle_action"
    assert service.calls == []


def test_lifecycle_service_errors_are_public_and_unexpected_errors_are_redacted(
    authenticated_client, app
):
    service = Mock()
    service.transition.side_effect = CapabilityLifecycleError(
        "Extension is busy.", code="extension_busy", status_code=409
    )
    app.extensions["capability_authorizer"] = Authorizer(True)
    app.extensions["capability_lifecycle_service"] = service

    expected = authenticated_client.post(
        "/api/extensions/mergerfs/enable", json={}
    )
    service.transition.side_effect = RuntimeError("token=must-not-leak")
    unexpected = authenticated_client.post(
        "/api/extensions/mergerfs/enable", json={}
    )

    assert expected.status_code == 409
    assert expected.get_json() == {
        "code": "extension_busy",
        "error": "Extension is busy.",
    }
    assert unexpected.status_code == 500
    assert unexpected.get_json()["code"] == "extension_lifecycle_failed"
    assert "must-not-leak" not in unexpected.get_data(as_text=True)


def test_lifecycle_public_errors_are_bounded():
    error = CapabilityLifecycleError(
        "x" * 241,
        code="INVALID-CODE",
        status_code=599,
    )

    assert error.message == "Extension lifecycle operation failed."
    assert error.code == "extension_lifecycle_failed"
    assert error.status_code == 409
