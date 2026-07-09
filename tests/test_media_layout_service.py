"""Tests for canonical media layout persistence and provisioning."""

import json
from unittest.mock import Mock

import pytest
from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from media_layout import MediaLayout
from media_layout_service import (
    MediaLayoutProvisionError,
    MediaLayoutService,
    MediaLayoutValidationError,
)
from operation_manager import OperationRegistry


def make_service(*, helper=None, repository=None):
    if helper is None:
        helper = Mock()
        helper.available.return_value = False
    if repository is None:
        repository = Mock()
        repository.read_json.return_value = {}
    return MediaLayoutService(
        helper=helper,
        repository=repository,
        config_path_provider=lambda: "/config/media_layout.json",
    )


def test_layout_merges_persisted_roots_over_defaults():
    repository = Mock()
    repository.read_json.return_value = {
        "storage_root": "/mnt/media",
        "downloads_root": "/mnt/nvme",
    }

    layout = make_service(repository=repository).layout()

    assert layout.storage_root == "/mnt/media"
    assert layout.downloads_root == "/mnt/nvme"
    assert layout.config_root == "/home/pi/docker"
    assert layout.backup_root == "/mnt/backup"
    repository.read_json.assert_called_once_with("/config/media_layout.json", default={})


def test_layout_falls_back_after_repository_failure():
    repository = Mock()
    repository.read_json.side_effect = PermissionError

    assert make_service(repository=repository).layout() == MediaLayout()


def test_save_validates_absolute_roots_before_write():
    repository = Mock()
    repository.read_json.return_value = {}

    with pytest.raises(MediaLayoutValidationError, match="storage_root"):
        make_service(repository=repository).save({"storage_root": "relative"})

    repository.write_json.assert_not_called()


def test_save_persists_complete_layout_with_private_mode():
    repository = Mock()
    repository.read_json.return_value = {"storage_root": "/mnt/media"}

    layout = make_service(repository=repository).save({"downloads_root": "/mnt/downloads/"})

    expected = {
        "storage_root": "/mnt/media",
        "downloads_root": "/mnt/downloads",
        "config_root": "/home/pi/docker",
        "backup_root": "/mnt/backup",
    }
    assert layout.as_dict() == expected
    repository.write_json.assert_called_once_with(
        "/config/media_layout.json", expected, mode=0o640
    )


def test_provision_calls_helper_with_layout_roots_and_ids():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {
        "success": True,
        "created": ["/mnt/storage/tv"],
        "existing": [],
    }
    repository = Mock()
    repository.read_json.return_value = {
        "storage_root": "/mnt/media",
        "downloads_root": "/mnt/downloads",
    }

    result = make_service(helper=helper, repository=repository).provision(
        puid=1001, pgid="1002"
    )

    helper.call.assert_called_once_with(
        "media_layout_provision",
        {
            "storage_root": "/mnt/media",
            "downloads_root": "/mnt/downloads",
            "puid": "1001",
            "pgid": "1002",
        },
    )
    assert result["success"] is True
    assert result["layout"]["storage_root"] == "/mnt/media"
    assert result["created"] == ["/mnt/storage/tv"]


def test_provision_requires_available_helper():
    with pytest.raises(MediaLayoutProvisionError, match="Helper service unavailable"):
        make_service().provision()


def test_provision_maps_helper_failure():
    helper = Mock()
    helper.available.return_value = True
    helper.call.return_value = {"success": False, "error": "Invalid storage_root"}

    with pytest.raises(MediaLayoutProvisionError, match="Invalid storage_root"):
        make_service(helper=helper).provision()


def _authed_client(media_layout_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        media_layout_service=media_layout_service,
    )
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "INIT_PLUGINS": False,
            "START_SCHEDULERS": False,
        },
        dependencies,
    )
    client = application.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "testuser"
        session["csrf_token"] = "test-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf-token"
    return client


def test_layout_route_returns_roots_and_derived_paths():
    service = Mock()
    service.layout.return_value = MediaLayout()

    response = _authed_client(service).get("/api/media/layout")

    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["layout"]["storage_root"] == "/mnt/storage"
    assert data["libraries"]["tv"] == "/mnt/storage/tv"
    assert data["downloads"]["complete"]["radarr"] == "/mnt/downloads/complete/radarr"


def test_layout_save_route_requires_csrf():
    service = Mock()
    client = _authed_client(service)
    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)

    response = client.post(
        "/api/media/layout",
        data=json.dumps({"storage_root": "/mnt/media"}),
        content_type="application/json",
    )

    assert response.status_code == 403
    service.save.assert_not_called()


def test_layout_save_route_maps_validation_error():
    service = Mock()
    service.save.side_effect = MediaLayoutValidationError("storage_root must be absolute")

    response = _authed_client(service).post(
        "/api/media/layout",
        data=json.dumps({"storage_root": "relative"}),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_layout_provision_route_delegates_to_service():
    service = Mock()
    service.provision.return_value = {
        "success": True,
        "created": [],
        "existing": ["/mnt/storage/tv"],
        "layout": MediaLayout().as_dict(),
    }

    response = _authed_client(service).post(
        "/api/media/layout/provision",
        data=json.dumps({"puid": "1001", "pgid": "1002"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    service.provision.assert_called_once_with(puid="1001", pgid="1002")


def test_layout_provision_route_maps_helper_error():
    service = Mock()
    service.provision.side_effect = MediaLayoutProvisionError("Helper service unavailable")

    response = _authed_client(service).post(
        "/api/media/layout/provision",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 503
    assert json.loads(response.data)["error"] == "Helper service unavailable"
