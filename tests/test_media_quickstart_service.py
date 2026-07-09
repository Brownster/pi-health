"""Tests for the media quickstart orchestration service."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from catalog_service import CatalogError
from media_layout import MediaLayout
from media_quickstart_service import MediaQuickstartService
from operation_manager import OperationRegistry


CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class FakeLayoutService:
    def __init__(self):
        self.provision_calls = []

    def layout(self):
        return MediaLayout(
            storage_root="/mnt/storage",
            downloads_root="/mnt/downloads",
            config_root="/home/pi/docker",
            backup_root="/mnt/backup",
        )

    def provision(self, *, puid="1000", pgid="1000"):
        self.provision_calls.append({"puid": puid, "pgid": pgid})
        return {"success": True, "created": ["/mnt/storage/tv"], "existing": []}


class FakeCatalogService:
    def __init__(self):
        self.install_calls = []
        self.items = {
            "media-server": {
                "id": "media-server",
                "kind": "bundle",
                "shared_fields": {
                    "USE_VPN": "true",
                    "TZ": "Europe/London",
                    "PUID": "1000",
                    "PGID": "1000",
                    "CONFIG_DIR": {"layout_default": "config_root"},
                    "DOWNLOADS_DIR": {"layout_default": "downloads_root"},
                    "STORAGE_DIR": {"layout_default": "storage_root"},
                },
                "members": [
                    {
                        "id": "vpn",
                        "order": 0,
                        "when": {"field": "USE_VPN", "equals": "true"},
                        "values": {
                            "CONFIG_DIR": "{{CONFIG_DIR}}",
                            "VPN_ENV_FILE": "{{CONFIG_DIR}}/vpn/.env",
                        },
                    },
                    {
                        "id": "transmission",
                        "order": 10,
                        "values": {
                            "TZ": "{{TZ}}",
                            "PUID": "{{PUID}}",
                            "PGID": "{{PGID}}",
                            "CONFIG_DIR": "{{CONFIG_DIR}}",
                            "DOWNLOADS_DIR": "{{DOWNLOADS_DIR}}",
                        },
                    },
                    {
                        "id": "jellyfin",
                        "order": 70,
                        "values": {
                            "TZ": "{{TZ}}",
                            "PUID": "{{PUID}}",
                            "PGID": "{{PGID}}",
                            "CONFIG_DIR": "{{CONFIG_DIR}}",
                            "STORAGE_DIR": "{{STORAGE_DIR}}",
                        },
                    },
                ],
            }
        }

    def get_item(self, item_id):
        return {"item": self.items[item_id]}

    def install(self, data, *, operation_registry, owner, username):
        self.install_calls.append(
            {
                "data": data,
                "operation_registry": operation_registry,
                "owner": owner,
                "username": username,
            }
        )
        return {"status": "installed", "id": data["id"]}, 200


class FakeStackOperationsService:
    def __init__(self, events=None):
        self.calls = []
        self.events = events or [{"line": "created"}, {"done": True, "returncode": 0}]

    def stream(self, stack_name, command):
        self.calls.append((stack_name, command))
        yield from self.events


class FakeSeedService:
    def __init__(self, events=None):
        self.calls = []
        self.events = events or [
            {"step": "start", "line": "seed start"},
            {"step": "complete", "line": "Seeded 3 service(s); 4 change(s)", "done": True, "changes": 4},
        ]

    def seed_stack(self, stack_name):
        self.calls.append(stack_name)
        yield from self.events


class FakeProfileService:
    def __init__(self):
        self.saved = []

    def save(self, profile):
        self.saved.append(profile)
        return profile


def make_service(*, catalog=None, stack_ops=None, seed=None, layout=None, profile=None):
    return MediaQuickstartService(
        media_layout_service=layout or FakeLayoutService(),
        catalog_service=catalog or FakeCatalogService(),
        stack_operations_service=stack_ops or FakeStackOperationsService(),
        media_seed_service=seed or FakeSeedService(),
        media_profile_service=profile,
    )


def test_quickstart_provisions_installs_starts_and_seeds_bundle():
    layout = FakeLayoutService()
    catalog = FakeCatalogService()
    stack_ops = FakeStackOperationsService()
    seed = FakeSeedService()
    service = make_service(layout=layout, catalog=catalog, stack_ops=stack_ops, seed=seed)

    events = list(
        service.stream_quickstart(
            stack_name="media",
            values={"PUID": "1001", "PGID": "1002"},
            username="alice",
        )
    )

    assert events[-1]["done"] is True
    assert layout.provision_calls == [{"puid": "1001", "pgid": "1002"}]
    assert [call["data"]["id"] for call in catalog.install_calls] == [
        "vpn",
        "transmission",
        "jellyfin",
    ]
    assert catalog.install_calls[0]["data"]["target_stack"] == "new"
    assert catalog.install_calls[0]["data"]["stack_name"] == "media"
    assert catalog.install_calls[1]["data"]["target_stack"] == "media"
    assert catalog.install_calls[1]["data"]["values"]["DOWNLOADS_DIR"] == "/mnt/downloads"
    assert catalog.install_calls[2]["data"]["values"]["STORAGE_DIR"] == "/mnt/storage"
    assert {call["username"] for call in catalog.install_calls} == {"alice"}
    assert stack_ops.calls == [("media", "up")]
    assert seed.calls == ["media"]
    assert not any(event.get("done") for event in events[:-1])


def test_quickstart_persists_resolved_media_profile_before_completion():
    profile = FakeProfileService()

    events = list(
        make_service(profile=profile).stream_quickstart(
            stack_name="family-media",
            values={"PUID": "1005"},
        )
    )

    assert events[-2] == {"step": "profile", "line": "Saved media profile"}
    assert events[-1]["done"] is True
    assert profile.saved == [
        {
            "version": 1,
            "stack_name": "family-media",
            "bundle_id": "media-server",
            "values": {
                "USE_VPN": "true",
                "TZ": "Europe/London",
                "PUID": "1005",
                "PGID": "1000",
                "CONFIG_DIR": "/home/pi/docker",
                "DOWNLOADS_DIR": "/mnt/downloads",
                "STORAGE_DIR": "/mnt/storage",
            },
            "layout": {
                "storage_root": "/mnt/storage",
                "downloads_root": "/mnt/downloads",
                "config_root": "/home/pi/docker",
                "backup_root": "/mnt/backup",
            },
            "members": ["vpn", "transmission", "jellyfin"],
        }
    ]


def test_quickstart_skips_already_installed_members():
    catalog = FakeCatalogService()

    def install(data, **_kwargs):
        catalog.install_calls.append({"data": data})
        if data["id"] == "vpn":
            raise CatalogError({"error": "Service already installed in stack media: vpn"}, 409)
        return {"status": "installed"}, 200

    catalog.install = install
    events = list(make_service(catalog=catalog).stream_quickstart())

    assert events[-1]["done"] is True
    assert any("Skipped vpn" in event.get("line", "") for event in events)
    assert events[-1]["skipped"] == 1


def test_quickstart_rejects_unsupported_non_vpn_choice():
    events = list(make_service().stream_quickstart(values={"USE_VPN": "false"}))

    assert events[-1]["step"] == "error"
    assert "USE_VPN=false is not supported" in events[-1]["error"]


@pytest.mark.parametrize(
    "stack_events",
    [
        [{"error": "Stack not found"}],
        [{"done": True, "returncode": 1}],
    ],
)
def test_quickstart_stops_on_stack_start_failure(stack_events):
    events = list(
        make_service(stack_ops=FakeStackOperationsService(stack_events)).stream_quickstart()
    )

    assert events[-1]["step"] == "error"


def test_quickstart_stops_on_seed_failure():
    seed = FakeSeedService(events=[{"step": "error", "error": "seed failed"}])

    events = list(make_service(seed=seed).stream_quickstart())

    assert events[-1] == {"step": "error", "error": "seed failed"}


def _authed_client(media_quickstart_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(thread_factory=ImmediateThread),
        media_quickstart_service=media_quickstart_service,
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


def test_media_quickstart_route_starts_and_streams_operation():
    service = Mock()
    service.stream_quickstart.return_value = iter(
        [
            {"step": "start", "line": "Starting media quickstart"},
            {"step": "complete", "done": True},
        ]
    )
    client = _authed_client(service)

    response = client.post(
        "/api/media/quickstart",
        data=json.dumps({"stack": "media", "values": {"PUID": "1001"}}),
        content_type="application/json",
    )

    assert response.status_code == 202
    stream = client.get(response.get_json()["stream_url"])
    assert stream.status_code == 200
    assert _parse_sse(stream.get_data(as_text=True)) == [
        {"step": "start", "line": "Starting media quickstart"},
        {"step": "complete", "done": True},
    ]
    service.stream_quickstart.assert_called_once_with(
        stack_name="media",
        values={"PUID": "1001"},
        username="testuser",
    )


def test_media_quickstart_route_rejects_invalid_values_payload():
    response = _authed_client(Mock()).post(
        "/api/media/quickstart",
        data=json.dumps({"values": []}),
        content_type="application/json",
    )

    assert response.status_code == 400
