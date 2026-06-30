"""BF-002B: framework-neutral ports and thin adapters."""
import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import AppDependencies, create_app  # noqa: E402
from auth_utils import LoginRateLimiter  # noqa: E402
from operation_manager import OperationRegistry  # noqa: E402
from ports import (  # noqa: E402
    ApschedulerAdapter,
    DockerClientAdapter,
    FileAuditWriter,
    HelperClientAdapter,
    JsonFileRepository,
    monotonic_clock,
)

TEST_USERNAME = os.environ["PIHEALTH_USER"]
TEST_PASSWORD_HASH = os.environ["PIHEALTH_PASSWORD_HASH"]


# --- Adapters are framework-neutral and delegate to existing implementations ---

def test_helper_adapter_delegates(monkeypatch):
    captured = {}

    def fake_helper_call(command, params=None):
        captured["args"] = (command, params)
        return {"ok": True}

    monkeypatch.setattr("helper_client.helper_call", fake_helper_call)
    result = HelperClientAdapter().call("smart_info", {"device": "/dev/sda"})
    assert result == {"ok": True}
    assert captured["args"] == ("smart_info", {"device": "/dev/sda"})


def test_docker_adapter_unavailable_when_no_client():
    adapter = DockerClientAdapter(None)
    assert adapter.available is False
    assert adapter.list_containers() == []
    assert adapter.get_container("x") is None
    assert adapter.pull_image("example:latest") is None
    assert adapter.ping() is False


def test_docker_adapter_delegates_to_client():
    class FakeContainers:
        def list(self, all=True):
            return ["c1", "c2"] if all else ["c1"]

        def get(self, container_id):
            return f"got:{container_id}"

    class FakeClient:
        containers = FakeContainers()
        images = type(
            "FakeImages",
            (),
            {"pull": staticmethod(lambda tag: f"pulled:{tag}")},
        )()

        def ping(self):
            return True

    adapter = DockerClientAdapter(FakeClient())
    assert adapter.available is True
    assert adapter.list_containers(all=True) == ["c1", "c2"]
    assert adapter.get_container("abc") == "got:abc"
    assert adapter.pull_image("example:latest") == "pulled:example:latest"
    assert adapter.ping() is True


def test_scheduler_adapter_delegates():
    calls = []

    class FakeScheduler:
        running = False

        def start(self):
            calls.append("start")

        def add_job(self, func, trigger, id, replace_existing, **kwargs):
            calls.append(("add", id))

        def remove_job(self, job_id):
            calls.append(("remove", job_id))

        def get_job(self, job_id):
            return job_id

    adapter = ApschedulerAdapter(FakeScheduler())
    adapter.start()
    adapter.add_job(lambda: None, "cron", id="job1")
    adapter.remove_job("job1")
    assert adapter.get_job("job1") == "job1"
    assert calls == ["start", ("add", "job1"), ("remove", "job1")]


def test_audit_writer_appends_timestamped_json(tmp_path):
    log = tmp_path / "audit.log"
    writer = FileAuditWriter(log)
    assert writer.record({"action": "restart", "actor": "admin"}) is True
    assert writer.record({"action": "stop"}) is True
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["action"] == "restart" and first["actor"] == "admin"
    assert "ts" in first


def test_config_repository_roundtrip_and_default(tmp_path):
    repo = JsonFileRepository()
    path = tmp_path / "sub" / "config.json"
    repo.write_json(path, {"enabled": True, "count": 3})
    assert repo.read_json(path) == {"enabled": True, "count": 3}
    assert os.path.exists(path)
    assert repo.read_json(tmp_path / "missing.json", default={"x": 1}) == {"x": 1}


def test_config_repository_preserves_mode(tmp_path):
    repo = JsonFileRepository()
    path = tmp_path / "secret.json"
    repo.write_json(path, {"a": 1}, mode=0o600)
    assert (os.stat(path).st_mode & 0o777) == 0o600
    repo.write_json(path, {"a": 2})  # overwrite must keep 0o600
    assert (os.stat(path).st_mode & 0o777) == 0o600


# --- Dependency injection through the application factory ---------------------

def _app(dependencies=None):
    return create_app(
        {"TESTING": True, "INIT_PLUGINS": False, "START_SCHEDULERS": False},
        dependencies,
    )


def test_default_factory_wires_ports_and_shared_clock():
    application = _app()
    ext = application.extensions
    assert ext["clock"] is monotonic_clock
    assert isinstance(ext["helper"], HelperClientAdapter)
    assert isinstance(ext["config_repo"], JsonFileRepository)
    assert isinstance(ext["audit"], FileAuditWriter)
    # One clock drives both time-sensitive components.
    assert ext["operation_registry"]._clock is ext["login_rate_limiter"]._clock is monotonic_clock


def test_injected_ports_are_used_without_sockets():
    fake_helper = HelperClientAdapter()
    fake_audit = FileAuditWriter("/tmp/limeos-test-audit.log")
    dependencies = AppDependencies(
        users={TEST_USERNAME: TEST_PASSWORD_HASH},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        helper=fake_helper,
        audit=fake_audit,
    )
    application = _app(dependencies)
    assert application.extensions["helper"] is fake_helper
    assert application.extensions["audit"] is fake_audit
    # docker port falls back to an adapter over the (absent) client.
    assert application.extensions["docker"].available is False
