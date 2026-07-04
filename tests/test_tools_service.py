"""Tests for the framework-neutral ToolsService and its route delegation."""

import json
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from helper_client import HelperError
from operation_manager import OperationRegistry
from tools_service import (
    ToolsConfigError,
    ToolsHelperError,
    ToolsOperationError,
    ToolsService,
)

CONFIG_PATH = "copyparty.json"


class FakeRepository:
    def __init__(self, seed=None, path=CONFIG_PATH):
        self.store = {path: dict(seed)} if seed else {}
        self.writes = []

    def read_json(self, path, default=None):
        return self.store.get(path, default)

    def write_json(self, path, data, *, mode=0o644):
        self.store[path] = dict(data)
        self.writes.append(dict(data))


def make_service(*, repository=None, helper_call=None):
    return ToolsService(
        repository=repository if repository is not None else FakeRepository(),
        helper_call=helper_call or (lambda command, params: {"success": True}),
        config_path_provider=lambda: CONFIG_PATH,
    )


# --- Config ------------------------------------------------------------------

def test_load_config_returns_defaults_when_empty():
    config = make_service().load_config()
    assert config["share_path"] == "/srv/copyparty"
    assert config["port"] == 3923


def test_load_config_merges_stored_over_defaults():
    service = make_service(repository=FakeRepository({"port": 8080}))
    config = service.load_config()
    assert config["port"] == 8080
    assert config["share_path"] == "/srv/copyparty"


# --- Status ------------------------------------------------------------------

def test_status_returns_helper_state_and_config():
    def helper(command, params):
        return {"installed": True, "service_active": True, "service_status": "active"}

    result = make_service(helper_call=helper).status()
    assert result["installed"] is True
    assert result["service_status"] == "active"
    assert result["config"]["port"] == 3923


def test_status_maps_helper_error_with_config():
    def boom(command, params):
        raise HelperError("helper down")

    try:
        make_service(helper_call=boom).status()
    except ToolsHelperError as exc:
        assert exc.config is not None
        assert exc.config["share_path"] == "/srv/copyparty"
    else:
        raise AssertionError("expected ToolsHelperError")


# --- Install -----------------------------------------------------------------

def test_install_success():
    assert make_service().install() == {"status": "installed"}


def test_install_maps_helper_error():
    def boom(command, params):
        raise HelperError("down")

    try:
        make_service(helper_call=boom).install()
    except ToolsHelperError:
        pass
    else:
        raise AssertionError("expected ToolsHelperError")


def test_install_rejects_unsuccessful_result():
    try:
        make_service(helper_call=lambda c, p: {"success": False, "error": "nope"}).install()
    except ToolsOperationError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected ToolsOperationError")


# --- Configure ---------------------------------------------------------------

def test_configure_persists_and_applies():
    repo = FakeRepository()
    calls = []
    service = make_service(
        repository=repo,
        helper_call=lambda command, params: calls.append((command, params)) or {"success": True},
    )
    result = service.configure({"share_path": "/data", "port": "8080", "extra_args": " -v "})
    assert result == {"status": "configured"}
    assert repo.writes[-1] == {"share_path": "/data", "port": 8080, "extra_args": "-v"}
    assert calls[0][0] == "copyparty_configure"


def test_configure_rejects_relative_share_path():
    try:
        make_service().configure({"share_path": "relative", "port": 3923})
    except ToolsConfigError as exc:
        assert "absolute" in str(exc)
    else:
        raise AssertionError("expected ToolsConfigError")


def test_configure_rejects_non_integer_port():
    try:
        make_service().configure({"share_path": "/data", "port": "bad"})
    except ToolsConfigError as exc:
        assert "integer" in str(exc)
    else:
        raise AssertionError("expected ToolsConfigError")


def test_configure_maps_unsuccessful_result():
    try:
        make_service(
            helper_call=lambda c, p: {"success": False, "error": "denied"}
        ).configure({"share_path": "/data", "port": 3923})
    except ToolsOperationError as exc:
        assert "denied" in str(exc)
    else:
        raise AssertionError("expected ToolsOperationError")


# --- Route delegation --------------------------------------------------------

def _authed_client(tools_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        tools_service=tools_service,
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


def test_status_route_adds_url_and_delegates():
    service = Mock()
    service.status.return_value = {
        "config": {"port": 3923},
        "installed": True,
        "service_active": True,
        "service_status": "active",
    }
    response = _authed_client(service).get("/api/tools/copyparty/status")
    assert response.status_code == 200
    assert json.loads(response.data)["url"].endswith(":3923")


def test_status_route_maps_helper_error_to_503():
    service = Mock()
    service.status.side_effect = ToolsHelperError("down", config={"port": 3923})
    response = _authed_client(service).get("/api/tools/copyparty/status")
    assert response.status_code == 503
    assert json.loads(response.data)["config"] == {"port": 3923}


def test_config_route_maps_validation_error_to_400():
    service = Mock()
    service.configure.side_effect = ToolsConfigError("share_path must be absolute")
    response = _authed_client(service).post(
        "/api/tools/copyparty/config",
        data=json.dumps({"share_path": "relative"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_install_route_maps_operation_error_to_400():
    service = Mock()
    service.install.side_effect = ToolsOperationError("Install failed")
    response = _authed_client(service).post("/api/tools/copyparty/install")
    assert response.status_code == 400
