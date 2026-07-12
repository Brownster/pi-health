import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from mattermost_integration_service import MattermostIntegrationService
from operation_manager import OperationRegistry
from ports import JsonFileRepository
from stack_manager import atomic_write_text


class FakeMattermostApi:
    def __init__(self):
        self.calls = []

    def ping(self):
        self.calls.append("ping")

    def ensure_admin(self, **values):
        self.calls.append(("admin", values["admin_username"] if "admin_username" in values else values["username"]))
        return "user-1"

    def ensure_team(self, **values):
        self.calls.append(("team", values["name"]))
        return "team-1"

    def ensure_team_member(self, **_values):
        self.calls.append("membership")

    def ensure_channel(self, **values):
        self.calls.append(("channel", values["name"]))
        return "channel-1"

    def ensure_incoming_webhook(self, **_values):
        self.calls.append("webhook")
        return "http://mattermost.test:8065/hooks/secret-token"


class RecordingNotifier:
    def __init__(self, url, sent):
        self.url = url
        self.sent = sent

    def send(self, notification):
        self.sent.append((self.url, notification))


def make_service(tmp_path):
    api = FakeMattermostApi()
    sent = []
    compose_calls = []

    def runner(*args, **_kwargs):
        compose_calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    service = MattermostIntegrationService(
        config_path=tmp_path / "config" / "mattermost.json",
        secrets_path=tmp_path / "config" / "mattermost.env",
        status_path=tmp_path / "state" / "mattermost-status.json",
        stack_path_provider=lambda name: str(tmp_path / "stacks" / name),
        config_repository=JsonFileRepository(),
        atomic_writer=atomic_write_text,
        compose_runner=runner,
        api_factory=lambda _url: api,
        notifier_factory=lambda url: RecordingNotifier(url, sent),
        sleep=lambda _seconds: None,
        clock=lambda: 1_784_275_200,
    )
    return service, api, sent, compose_calls


SETUP = {
    "site_url": "http://mattermost.test:8065",
    "admin_username": "limeadmin",
    "admin_email": "admin@example.test",
    "admin_password": "long-test-password",
    "stack_name": "mattermost",
    "team_name": "limeos",
    "channel_name": "limeos-alerts",
}


def test_install_builds_stack_bootstraps_and_redacts_admin_password(tmp_path):
    service, api, sent, compose_calls = make_service(tmp_path)

    events = list(service.stream_install(SETUP))

    assert events[-1]["done"] is True
    assert ("team", "limeos") in api.calls
    assert ("channel", "limeos-alerts") in api.calls
    assert len(sent) == 1
    config = json.loads((tmp_path / "config" / "mattermost.json").read_text())
    assert config["installed"] is True
    assert "admin_password" not in config
    assert SETUP["admin_password"] not in (
        tmp_path / "config" / "mattermost.env"
    ).read_text()
    compose = (tmp_path / "stacks" / "mattermost" / "compose.yaml").read_text()
    dockerfile = (
        tmp_path / "stacks" / "mattermost" / "Dockerfile.mattermost"
    ).read_text()
    alertd_dockerfile = (
        tmp_path / "stacks" / "mattermost" / "Dockerfile.alertd"
    ).read_text()
    assert "postgres:" in compose
    assert "mattermost:" in compose
    assert "limeos-alertd:" in compose
    assert "container_name: limeos-mattermost-db" in compose
    assert "container_name: limeos-mattermost\n" in compose
    assert "build:" in compose
    assert "mattermost-team-edition:latest" not in compose
    assert "mattermost-team-${MM_VERSION}-linux-arm64.tar.gz" in dockerfile
    assert "ARG MM_VERSION=11.8.3" in dockerfile
    assert "image: limeos/alertd:local" in compose
    assert "dockerfile: Dockerfile.alertd" in compose
    assert "pi-health-dashboard:latest" not in compose
    assert "COPY alert_daemon.py" in alertd_dockerfile
    assert (tmp_path / "stacks" / "mattermost" / "alert_daemon.py").is_file()
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "build",
        "limeos-alertd",
    ] in compose_calls


def test_install_retry_reuses_database_password(tmp_path):
    service, _api, _sent, _compose_calls = make_service(tmp_path)
    list(service.stream_install(SETUP))
    first = (tmp_path / "config" / "mattermost.env").read_text()

    list(service.stream_install(SETUP))

    second = (tmp_path / "config" / "mattermost.env").read_text()
    first_password = next(line for line in first.splitlines() if line.startswith("POSTGRES_PASSWORD="))
    assert first_password in second


def test_policy_status_and_test_delivery(tmp_path):
    service, _api, sent, _compose_calls = make_service(tmp_path)
    list(service.stream_install(SETUP))

    policy = service.update_policy(
        {
            "categories": {"container": {"enabled": False}},
            "required_mounts": ["/mnt/media"],
        }
    )
    result = service.status()
    service.send_test()

    assert policy["categories"]["container"]["enabled"] is False
    assert result["state"] == "connected"
    assert result["webhook_configured"] is True
    assert len(sent) == 2


def test_status_reports_disconnected_service(tmp_path):
    service, _api, _sent, _compose_calls = make_service(tmp_path)
    list(service.stream_install(SETUP))
    service._container_status_provider = lambda name: {
        "state": "exited" if name == "limeos-mattermost" else "running",
        "health": None,
    }

    result = service.status()

    assert result["state"] == "disconnected"
    assert result["services"]["limeos-mattermost"]["state"] == "exited"


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def _authed_client(service, *, thread_factory=ImmediateThread):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(thread_factory=thread_factory),
        mattermost_integration_service=service,
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


def test_integration_routes_delegate_and_stream():
    service = Mock()
    service.status.return_value = {"state": "not_installed"}
    service.stream_install.return_value = iter(
        [{"step": "prepare", "line": "Preparing"}, {"step": "complete", "done": True}]
    )
    service.update_policy.return_value = {"categories": {}}
    service.send_test.return_value = {"status": "sent"}
    client = _authed_client(service)

    assert client.get("/api/integrations/mattermost").get_json()["state"] == "not_installed"
    install = client.post("/api/integrations/mattermost/install", json=SETUP)
    assert install.status_code == 202
    stream = client.get(install.get_json()["stream_url"])
    assert "Preparing" in stream.get_data(as_text=True)
    assert client.put(
        "/api/integrations/mattermost/policy", json={"categories": {}}
    ).status_code == 200
    assert client.post("/api/integrations/mattermost/test").status_code == 200


def test_install_route_resolves_service_before_background_thread_runs():
    service = Mock()
    service.stream_install.return_value = iter(
        [{"step": "complete", "line": "Mattermost ready", "done": True}]
    )
    client = _authed_client(service, thread_factory=threading.Thread)

    install = client.post("/api/integrations/mattermost/install", json=SETUP)
    stream = client.get(install.get_json()["stream_url"])

    assert "Mattermost ready" in stream.get_data(as_text=True)
    service.stream_install.assert_called_once_with(SETUP)
