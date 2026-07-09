"""Tests for the framework-neutral CatalogService and its route delegation."""

import json
from contextlib import contextmanager
from unittest.mock import Mock

import yaml
from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from catalog_service import CatalogError, CatalogService, _apply_layout_defaults
from operation_manager import OperationRegistry


class FakeConflictError(Exception):
    code = "compose_file_conflict"

    def as_dict(self):
        return {"code": self.code, "error": "conflict"}


@contextmanager
def _noop_lock(_name):
    yield


class Recorder:
    def __init__(self):
        self.saved = []
        self.backed_up = []
        self.compose_calls = []


def write_item(catalog_dir, item):
    catalog_dir.mkdir(exist_ok=True)
    (catalog_dir / f"{item['id']}.yaml").write_text(yaml.safe_dump(item))


def make_service(
    catalog_dir,
    *,
    stacks=(([], None)),
    composes=None,
    validate=lambda name: (True, None),
    run_compose=None,
    stream=None,
    recorder=None,
    path_exists=lambda path: False,
    is_dir=lambda path: True,
):
    composes = composes or {}
    rec = recorder or Recorder()

    def load_stack_compose(stack_dir):
        return composes.get(stack_dir, (None, None))

    def save_stack_compose(stack_dir, data, filename=None):
        rec.saved.append((stack_dir, data))
        return filename or f"{stack_dir}/compose.yaml"

    def run_compose_command(stack, command, service=None):
        rec.compose_calls.append((stack, command, service))
        return (run_compose or (lambda s, c, svc: ({"success": True}, None)))(
            stack, command, service
        )

    def backup_stack(name):
        rec.backed_up.append(name)
        return f"/backups/{name}.tar"

    return CatalogService(
        catalog_dir_provider=lambda: str(catalog_dir),
        media_paths_loader=lambda: {
            "config": "/cfg",
            "downloads": "/dl",
            "storage": "/st",
            "backup": "/bk",
        },
        load_stack_compose=load_stack_compose,
        save_stack_compose=save_stack_compose,
        list_stacks=lambda: stacks,
        get_stack_path=lambda name: f"/stacks/{name}",
        validate_stack_name=validate,
        backup_stack=backup_stack,
        run_compose_command=run_compose_command,
        stream_compose_command=stream or (lambda s, c: iter(['data: {"line":"x"}\n\n'])),
        stack_lock=_noop_lock,
        compose_conflict_error=FakeConflictError,
        path_exists=path_exists,
        is_dir=is_dir,
    )


SAMPLE = {
    "id": "sonarr",
    "name": "Sonarr",
    "description": "PVR",
    "requires": [],
    "service": {"image": "sonarr:{{TAG}}", "environment": ["TZ={{TZ}}"]},
    "fields": [{"key": "TZ", "default": "UTC"}, {"key": "TAG", "default": "latest"}],
}


# --- Reads -------------------------------------------------------------------

def test_list_items_summarizes(tmp_path):
    write_item(tmp_path, SAMPLE)
    result = make_service(tmp_path).list_items()
    assert result["items"][0]["id"] == "sonarr"
    assert result["items"][0]["name"] == "Sonarr"


def test_list_items_includes_nested_bundle_metadata(tmp_path):
    write_item(tmp_path, SAMPLE)
    bundle_dir = tmp_path / "bundles"
    write_item(
        bundle_dir,
        {
            "id": "media-server",
            "kind": "bundle",
            "name": "Media Server",
            "description": "Recommended media stack",
            "members": [
                {"id": "transmission", "order": 10},
                {"id": "sonarr", "order": 20},
            ],
        },
    )

    result = make_service(tmp_path).list_items()
    items = {item["id"]: item for item in result["items"]}

    assert items["sonarr"]["kind"] == "app"
    assert items["media-server"] == {
        "id": "media-server",
        "name": "Media Server",
        "description": "Recommended media stack",
        "kind": "bundle",
        "requires": [],
        "disabled_by_default": False,
        "source": "bundles/media-server.yaml",
        "members": [
            {"id": "transmission", "order": 10},
            {"id": "sonarr", "order": 20},
        ],
    }


def test_get_item_loads_nested_bundle_definition(tmp_path):
    bundle_dir = tmp_path / "bundles"
    write_item(
        bundle_dir,
        {
            "id": "media-server",
            "kind": "bundle",
            "name": "Media Server",
            "target_stack": "media",
            "members": [{"id": "jellyfin", "order": 70}],
        },
    )

    result = make_service(tmp_path).get_item("media-server")

    assert result["item"]["kind"] == "bundle"
    assert result["item"]["target_stack"] == "media"
    assert result["item"]["members"] == [{"id": "jellyfin", "order": 70}]


def test_get_item_not_found_raises(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    try:
        make_service(tmp_path).get_item("ghost")
    except CatalogError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected CatalogError")


def test_get_item_applies_media_paths(tmp_path):
    item = dict(SAMPLE, fields=[{"key": "CONFIG_DIR", "default": "/x"}])
    write_item(tmp_path, item)
    result = make_service(tmp_path).get_item("sonarr", apply_media_paths=True)
    assert result["item"]["fields"][0]["default"] == "/cfg"


def test_get_item_applies_explicit_media_layout_defaults(tmp_path):
    item = dict(
        SAMPLE,
        fields=[
            {"key": "CONFIG_DIR", "default": "", "layout_default": "config_root"},
            {"key": "MEDIA_DIR", "default": "", "layout_default": "library:tv"},
            {"key": "DOWNLOADS_DIR", "default": "", "layout_default": "downloads_root"},
            {
                "key": "COMPLETE_DIR",
                "default": "",
                "layout_default": "download_complete:sonarr",
            },
        ],
    )
    write_item(tmp_path, item)

    result = make_service(tmp_path).get_item("sonarr", apply_media_paths=True)
    fields = {field["key"]: field["default"] for field in result["item"]["fields"]}

    assert fields == {
        "CONFIG_DIR": "/cfg",
        "MEDIA_DIR": "/st/tv",
        "DOWNLOADS_DIR": "/dl",
        "COMPLETE_DIR": "/dl/complete/sonarr",
    }


def test_install_uses_layout_defaults_before_rendering(tmp_path):
    item = dict(
        SAMPLE,
        fields=[
            {"key": "MEDIA_DIR", "default": "", "layout_default": "library:movies"},
            {"key": "DOWNLOADS_DIR", "default": "", "layout_default": "downloads_root"},
        ],
        service={
            "image": "example:latest",
            "volumes": ["{{MEDIA_DIR}}:/movies", "{{DOWNLOADS_DIR}}:/downloads"],
        },
    )
    write_item(tmp_path, item)
    rec = Recorder()

    result, status = make_service(tmp_path, recorder=rec, path_exists=lambda p: False).install(
        {"id": "sonarr", "stack_name": "media"},
        operation_registry=None,
        owner="o",
        username="u",
    )

    assert status == 200
    assert result["status"] == "installed"
    assert rec.saved[-1][1]["services"]["sonarr"]["volumes"] == [
        "/st/movies:/movies",
        "/dl:/downloads",
    ]


def test_apply_layout_defaults_rejects_unknown_tokens():
    item = {"id": "bad", "fields": [{"key": "PATH", "layout_default": "library:TV"}]}

    try:
        _apply_layout_defaults(item, {})
    except ValueError as exc:
        assert "Unknown media library kind" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_status_lists_services_and_stacks(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    composes = {"/stacks/media": ({"services": {"sonarr": {}}}, "/stacks/media/compose.yaml")}
    service = make_service(tmp_path, stacks=([{"name": "media"}], None), composes=composes)
    status = service.status()
    assert status["services"] == ["sonarr"]
    assert status["service_stacks"]["sonarr"] == ["media"]


def test_check_dependencies_reports_missing(tmp_path):
    item = dict(SAMPLE, requires=["postgres"])
    write_item(tmp_path, item)
    service = make_service(tmp_path, stacks=([], None))
    result = service.check_dependencies({"id": "sonarr"})
    assert result["satisfied"] is False
    assert result["missing"] == ["postgres"]


# --- Install -----------------------------------------------------------------

def test_install_missing_id_raises_400(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    try:
        make_service(tmp_path).install({}, operation_registry=None, owner="o", username="u")
    except CatalogError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected CatalogError")


def test_install_rejects_bundle_until_quickstart_exists(tmp_path):
    bundle_dir = tmp_path / "bundles"
    write_item(
        bundle_dir,
        {
            "id": "media-server",
            "kind": "bundle",
            "name": "Media Server",
            "members": [{"id": "jellyfin", "order": 70}],
        },
    )

    try:
        make_service(tmp_path).install(
            {"id": "media-server", "stack_name": "media"},
            operation_registry=None,
            owner="o",
            username="u",
        )
    except CatalogError as exc:
        assert exc.status_code == 400
        assert exc.payload == {
            "error": "Bundle install requires the media quickstart flow",
            "id": "media-server",
        }
    else:
        raise AssertionError("expected CatalogError")


def test_install_creates_service_in_new_stack(tmp_path):
    write_item(tmp_path, SAMPLE)
    rec = Recorder()
    service = make_service(tmp_path, recorder=rec, path_exists=lambda p: False)
    result, status = service.install(
        {"id": "sonarr", "stack_name": "media"},
        operation_registry=None,
        owner="o",
        username="u",
    )
    assert status == 200
    assert result["status"] == "installed"
    assert result["stack"] == "media"
    saved_data = rec.saved[-1][1]
    assert "sonarr" in saved_data["services"]


def test_install_rejects_already_installed(tmp_path):
    write_item(tmp_path, SAMPLE)
    composes = {"/stacks/media": ({"services": {"sonarr": {}}}, "/stacks/media/compose.yaml")}
    service = make_service(
        tmp_path,
        composes=composes,
        stacks=([{"name": "media"}], None),
        path_exists=lambda p: True,
        is_dir=lambda p: True,
    )
    try:
        service.install(
            {"id": "sonarr", "target_stack": "media"},
            operation_registry=None,
            owner="o",
            username="u",
        )
    except CatalogError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected CatalogError")


def test_install_reports_unresolved_placeholders(tmp_path):
    item = dict(SAMPLE, service={"image": "x:{{MISSING}}"}, fields=[])
    write_item(tmp_path, item)
    service = make_service(tmp_path, path_exists=lambda p: False)
    try:
        service.install(
            {"id": "sonarr", "stack_name": "media"},
            operation_registry=None,
            owner="o",
            username="u",
        )
    except CatalogError as exc:
        assert exc.status_code == 400
        assert "{{MISSING}}" in exc.payload["unresolved"][0]
    else:
        raise AssertionError("expected CatalogError")


def test_install_with_start_creates_operation(tmp_path):
    write_item(tmp_path, SAMPLE)
    registry = Mock()
    registry.create.return_value = Mock(operation_id="op-123")
    service = make_service(tmp_path, path_exists=lambda p: False)
    result, status = service.install(
        {"id": "sonarr", "stack_name": "media", "start_service": True},
        operation_registry=registry,
        owner="owner-token",
        username="alice",
    )
    assert status == 202
    assert result["operation_id"] == "op-123"
    assert result["stream_url"].endswith("/stream")
    _, kwargs = registry.create.call_args
    assert kwargs["kind"] == "catalog-install"
    assert kwargs["owner"] == "owner-token"


def test_install_start_thread_failure_maps_500(tmp_path):
    write_item(tmp_path, SAMPLE)
    registry = Mock()
    registry.create.side_effect = RuntimeError("thread unavailable")
    service = make_service(tmp_path, path_exists=lambda p: False)
    try:
        service.install(
            {"id": "sonarr", "stack_name": "media", "start_service": True},
            operation_registry=registry,
            owner="o",
            username="u",
        )
    except CatalogError as exc:
        assert exc.status_code == 500
        assert exc.payload["started"] is False
    else:
        raise AssertionError("expected CatalogError")


# --- Remove ------------------------------------------------------------------

def test_remove_deletes_service_and_backs_up(tmp_path):
    write_item(tmp_path, SAMPLE)
    composes = {"/stacks/media": ({"services": {"sonarr": {}}}, "/stacks/media/compose.yaml")}
    rec = Recorder()
    service = make_service(
        tmp_path,
        composes=composes,
        stacks=([{"name": "media"}], None),
        recorder=rec,
    )
    result = service.remove({"id": "sonarr", "target_stack": "media"})
    assert result["status"] == "removed"
    assert rec.backed_up == ["media"]
    assert "sonarr" not in rec.saved[-1][1]["services"]


def test_remove_missing_service_raises_404(tmp_path):
    composes = {"/stacks/media": ({"services": {}}, "/stacks/media/compose.yaml")}
    service = make_service(tmp_path, composes=composes)
    try:
        service.remove({"id": "sonarr", "target_stack": "media"})
    except CatalogError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected CatalogError")


def test_remove_blocks_on_stop_failure(tmp_path):
    write_item(tmp_path, SAMPLE)
    composes = {"/stacks/media": ({"services": {"sonarr": {}}}, "/stacks/media/compose.yaml")}
    service = make_service(
        tmp_path,
        composes=composes,
        stacks=([{"name": "media"}], None),
        run_compose=lambda s, c, svc: ({"success": False, "stderr": "nope"}, None),
    )
    try:
        service.remove({"id": "sonarr", "target_stack": "media"})
    except CatalogError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected CatalogError")


# --- Route delegation --------------------------------------------------------

def _authed_client(catalog_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        catalog_service=catalog_service,
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


def test_list_route_delegates():
    service = Mock()
    service.list_items.return_value = {"items": []}
    response = _authed_client(service).get("/api/catalog")
    assert response.status_code == 200
    service.list_items.assert_called_once()


def test_get_route_maps_catalog_error():
    service = Mock()
    service.get_item.side_effect = CatalogError({"error": "Catalog item not found"}, 404)
    response = _authed_client(service).get("/api/catalog/ghost")
    assert response.status_code == 404


def test_install_route_requires_csrf():
    service = Mock()
    client = _authed_client(service)
    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)
    response = client.post(
        "/api/catalog/install",
        data=json.dumps({"id": "sonarr"}),
        content_type="application/json",
    )
    assert response.status_code == 403
    service.install.assert_not_called()


def test_install_route_returns_202_with_operation():
    service = Mock()
    service.install.return_value = ({"status": "installed", "operation_id": "op-1"}, 202)
    response = _authed_client(service).post(
        "/api/catalog/install",
        data=json.dumps({"id": "sonarr", "start_service": True}),
        content_type="application/json",
    )
    assert response.status_code == 202
    assert json.loads(response.data)["operation_id"] == "op-1"


def test_remove_route_maps_catalog_error():
    service = Mock()
    service.remove.side_effect = CatalogError({"error": "Service not installed: x"}, 404)
    response = _authed_client(service).post(
        "/api/catalog/remove",
        data=json.dumps({"id": "x"}),
        content_type="application/json",
    )
    assert response.status_code == 404
