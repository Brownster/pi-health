"""Tests for the media stack seed service."""

import json
from pathlib import Path
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from arr_client import read_api_key
from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from media_layout import MediaLayout
from media_seed_service import MediaSeedService
from operation_manager import OperationRegistry


CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class FakeArrClient:
    def __init__(self):
        self.root_folders = [
            {"id": 1, "path": "/downloads/complete/sonarr"},
        ]
        self.download_clients = []
        self.deleted_roots = []
        self.added_roots = []
        self.added_download_clients = []
        self.media_management_calls = []
        self.quality_profiles = []
        self.naming_presets = []
        self.applications = []
        self.added_applications = []

    def list_root_folders(self):
        return list(self.root_folders)

    def add_root_folder(self, path):
        self.root_folders.append({"id": len(self.root_folders) + 1, "path": path})
        self.added_roots.append(path)

    def delete_root_folder(self, root_folder_id):
        self.deleted_roots.append(root_folder_id)
        self.root_folders = [
            root for root in self.root_folders if root["id"] != root_folder_id
        ]

    def list_download_clients(self):
        return list(self.download_clients)

    def add_download_client(self, client):
        self.download_clients.append(client)
        self.added_download_clients.append(client)

    def set_media_management(self, **kwargs):
        self.media_management_calls.append(kwargs)

    def set_quality_profile_default(self, profile_name):
        self.quality_profiles.append(profile_name)

    def set_naming(self, preset):
        self.naming_presets.append(preset)

    def list_applications(self):
        return list(self.applications)

    def add_application(self, application):
        self.applications.append(application)
        self.added_applications.append(application)


def make_service(fake_client, *, services=None, api_key_reader=None):
    if services is None:
        services = {
            "sonarr": {},
            "transmission": {},
            "sabnzbd": {},
        }
    if api_key_reader is None:
        def api_key_reader(config_file):
            return f"key-for:{config_file}"

    return MediaSeedService(
        catalog_dir_provider=lambda: str(CATALOG_DIR),
        stack_path_provider=lambda stack: f"/stacks/{stack}",
        load_stack_compose=lambda _path: (
            {"services": services},
            "/stacks/media/compose.yaml",
        ),
        layout_provider=lambda: MediaLayout(),
        api_key_reader=api_key_reader,
        client_factory=lambda _service_id, _seed, _api_key: fake_client,
    )


def make_file_seed_service(*, services, files):
    def read_text(path):
        return files[path]

    def write_text(path, content):
        files[path] = content

    return MediaSeedService(
        catalog_dir_provider=lambda: str(CATALOG_DIR),
        stack_path_provider=lambda stack: f"/stacks/{stack}",
        load_stack_compose=lambda _path: (
            {"services": services},
            "/stacks/media/compose.yaml",
        ),
        layout_provider=lambda: MediaLayout(),
        api_key_reader=lambda config_file: f"key-for:{config_file}",
        client_factory=lambda _service_id, _seed, _api_key: FakeArrClient(),
        text_reader=read_text,
        text_writer=write_text,
        path_exists=lambda path: path in files,
    )


def test_seed_stack_removes_download_root_and_adds_canonical_root_and_clients():
    fake_client = FakeArrClient()

    events = list(make_service(fake_client).seed_stack("media"))

    assert events[-1]["done"] is True
    assert fake_client.deleted_roots == [1]
    assert fake_client.added_roots == ["/tv"]
    assert [
        client["implementation"] for client in fake_client.added_download_clients
    ] == ["Transmission", "Sabnzbd"]
    assert [
        client["fields"][0]["value"] for client in fake_client.added_download_clients
    ] == ["sonarr", "sonarr"]
    assert fake_client.media_management_calls[-1] == {
        "import_mode": "move",
        "recycle_bin": "/tv/.recycle",
        "completed_download_handling": True,
    }
    assert fake_client.quality_profiles == ["HD-1080p"]
    assert fake_client.naming_presets == ["standard"]


def test_seed_stack_is_rerunnable_without_duplicate_roots_or_clients():
    fake_client = FakeArrClient()
    service = make_service(fake_client)

    first_events = list(service.seed_stack("media"))
    second_events = list(service.seed_stack("media"))

    assert first_events[-1]["changes"] == 4
    assert second_events[-1]["done"] is True
    assert second_events[-1]["changes"] == 0
    assert fake_client.added_roots == ["/tv"]
    assert len(fake_client.added_download_clients) == 2


def test_seed_stack_adds_prowlarr_applications_for_installed_arr_services():
    fake_client = FakeArrClient()
    fake_client.root_folders = [
        {"id": 1, "path": "/tv"},
        {"id": 2, "path": "/movies"},
    ]
    api_keys = []

    events = list(
        make_service(
            fake_client,
            services={
                "prowlarr": {},
                "sonarr": {},
                "radarr": {},
            },
            api_key_reader=lambda config_file: api_keys.append(config_file) or f"key:{config_file}",
        ).seed_stack("media")
    )

    assert events[-1]["done"] is True
    assert events[-1]["changes"] == 2
    assert [
        application["implementation"] for application in fake_client.added_applications
    ] == ["Sonarr", "Radarr"]
    assert fake_client.added_applications[0]["fields"][:2] == [
        {"name": "baseUrl", "value": "http://127.0.0.1:8989"},
        {"name": "apiKey", "value": "key:/home/pi/docker/sonarr/config.xml"},
    ]
    assert fake_client.added_applications[1]["fields"][:2] == [
        {"name": "baseUrl", "value": "http://127.0.0.1:7878"},
        {"name": "apiKey", "value": "key:/home/pi/docker/radarr/config.xml"},
    ]
    assert "/home/pi/docker/prowlarr/config.xml" in api_keys
    assert "/home/pi/docker/sonarr/config.xml" in api_keys
    assert "/home/pi/docker/radarr/config.xml" in api_keys


def test_seed_stack_does_not_duplicate_prowlarr_applications():
    fake_client = FakeArrClient()
    fake_client.root_folders = [{"id": 1, "path": "/tv"}]
    service = make_service(
        fake_client,
        services={
            "prowlarr": {},
            "sonarr": {},
        },
    )

    first_events = list(service.seed_stack("media"))
    second_events = list(service.seed_stack("media"))

    assert first_events[-1]["changes"] == 1
    assert second_events[-1]["changes"] == 0
    assert len(fake_client.added_applications) == 1


def test_seed_stack_updates_transmission_local_config():
    files = {
        "/home/pi/docker/transmission/settings.json": json.dumps(
            {
                "download-dir": "/downloads",
                "rpc-enabled": True,
            }
        )
    }
    service = make_file_seed_service(services={"transmission": {}}, files=files)

    first_events = list(service.seed_stack("media"))
    second_events = list(service.seed_stack("media"))

    assert first_events[-1]["changes"] == 3
    assert second_events[-1]["changes"] == 0
    config = json.loads(files["/home/pi/docker/transmission/settings.json"])
    assert config["download-dir"] == "/downloads/complete"
    assert config["incomplete-dir"] == "/downloads/incomplete"
    assert config["incomplete-dir-enabled"] is True
    assert config["rpc-enabled"] is True


def test_seed_stack_updates_sabnzbd_local_config():
    files = {
        "/home/pi/docker/sabnzbd/config/sabnzbd.ini": (
            "[misc]\n"
            "complete_dir = /old/complete\n"
            "download_dir = /old/incomplete\n"
            "host = 0.0.0.0\n"
        )
    }
    service = make_file_seed_service(services={"sabnzbd": {}}, files=files)

    first_events = list(service.seed_stack("media"))
    second_events = list(service.seed_stack("media"))

    assert first_events[-1]["changes"] == 2
    assert second_events[-1]["changes"] == 0
    updated = files["/home/pi/docker/sabnzbd/config/sabnzbd.ini"]
    assert "complete_dir = /downloads/complete" in updated
    assert "download_dir = /downloads/incomplete" in updated
    assert "host = 0.0.0.0" in updated


def test_seed_stack_skips_download_client_without_local_config_file():
    service = make_file_seed_service(services={"rdtclient": {}}, files={})

    events = list(service.seed_stack("media"))

    assert events[-1]["done"] is True
    assert events[-1]["changes"] == 0
    assert any("no local config file" in event.get("line", "") for event in events)


def _authed_client(media_seed_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(thread_factory=ImmediateThread),
        media_seed_service=media_seed_service,
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


def _parse_sse(text):
    events = []
    for frame in text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_media_seed_route_starts_and_streams_operation():
    service = Mock()
    service.seed_stack.return_value = iter(
        [
            {"step": "sonarr", "line": "Added root folder /tv"},
            {"step": "complete", "done": True},
        ]
    )
    client = _authed_client(service)

    response = client.post(
        "/api/media/seed",
        data=json.dumps({"stack": "media"}),
        content_type="application/json",
    )

    assert response.status_code == 202
    stream_url = response.get_json()["stream_url"]
    stream = client.get(stream_url)
    assert stream.status_code == 200
    assert _parse_sse(stream.get_data(as_text=True)) == [
        {"step": "sonarr", "line": "Added root folder /tv"},
        {"step": "complete", "done": True},
    ]
    service.seed_stack.assert_called_once_with("media")


def test_media_seed_route_requires_csrf():
    service = Mock()
    client = _authed_client(service)
    client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)

    response = client.post("/api/media/seed", data=json.dumps({}), content_type="application/json")

    assert response.status_code == 403
    service.seed_stack.assert_not_called()


def test_media_seed_route_rejects_invalid_stack_name():
    service = Mock()
    client = _authed_client(service)

    response = client.post(
        "/api/media/seed",
        data=json.dumps({"stack": "../media"}),
        content_type="application/json",
    )

    assert response.status_code == 400
    service.seed_stack.assert_not_called()


def test_read_api_key_extracts_servarr_config_value(tmp_path):
    config = tmp_path / "config.xml"
    config.write_text("<Config><ApiKey>secret-key</ApiKey></Config>")

    assert read_api_key(str(config)) == "secret-key"
