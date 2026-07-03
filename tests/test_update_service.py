"""Tests for the framework-neutral AutoUpdateService and its route delegation."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from operation_manager import OperationRegistry
from update_service import AutoUpdateService, UpdateConfigError

CONFIG_PATH = "state.json"
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


class FakeRepository:
    def __init__(self, seed=None, path=CONFIG_PATH):
        self.store = {path: dict(seed)} if seed else {}
        self.writes = []
        self.read_error = False

    def read_json(self, path, default=None):
        if self.read_error:
            raise OSError("boom")
        return self.store.get(path, default)

    def write_json(self, path, data, *, mode=0o644):
        self.store[path] = dict(data)
        self.writes.append(dict(data))


class FakeScheduler:
    def __init__(self, running=False):
        self._running = running
        self.jobs = {}
        self.started = False
        self.remove_raises = False

    @property
    def running(self):
        return self._running

    def start(self):
        self._running = True
        self.started = True

    def add_job(self, func, trigger, *, id, replace_existing=True, **kwargs):
        self.jobs[id] = SimpleNamespace(
            func=func,
            trigger=trigger,
            replace_existing=replace_existing,
            next_run_time=kwargs.get("next_run_time"),
            kwargs=kwargs,
        )

    def remove_job(self, job_id):
        if self.remove_raises or job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]

    def get_job(self, job_id):
        return self.jobs.get(job_id)


def make_service(
    *,
    repository=None,
    scheduler=None,
    stacks=None,
    compose=None,
    stack_lister=None,
    compose_runner=None,
    config=None,
):
    repo = repository if repository is not None else FakeRepository(config)
    sched = scheduler if scheduler is not None else FakeScheduler()
    return AutoUpdateService(
        repository=repo,
        scheduler=sched,
        config_path_provider=lambda: CONFIG_PATH,
        stack_lister=stack_lister or (lambda: list(stacks or [])),
        compose_runner=compose_runner or (lambda name, cmd: (compose or {}).get((name, cmd))),
        trigger_factory=lambda cron: f"trigger:{cron}",
        clock=lambda: FIXED_NOW,
        logger=lambda message: None,
    )


# --- Config ------------------------------------------------------------------

def test_load_config_returns_defaults_when_empty():
    config = make_service().load_config()
    assert config["enabled"] is False
    assert config["schedule_preset"] == "disabled"
    assert config["excluded_stacks"] == []


def test_load_config_merges_over_defaults():
    service = make_service(config={"enabled": True, "excluded_stacks": ["a"]})
    config = service.load_config()
    assert config["enabled"] is True
    assert config["excluded_stacks"] == ["a"]
    # Untouched defaults survive the merge.
    assert config["notify_on_update"] is True


def test_load_config_tolerates_repository_error():
    repo = FakeRepository()
    repo.read_error = True
    config = make_service(repository=repo).load_config()
    assert config == dict(make_service().load_config())


def test_save_config_writes_through_repository():
    repo = FakeRepository()
    make_service(repository=repo).save_config({"enabled": True})
    assert repo.store[CONFIG_PATH] == {"enabled": True}


# --- update_config -----------------------------------------------------------

def test_update_config_toggles_enabled_and_persists():
    repo = FakeRepository()
    service = make_service(repository=repo)
    result = service.update_config({"enabled": True, "schedule_preset": "daily_4am"})
    assert result["enabled"] is True
    assert result["schedule_preset"] == "daily_4am"
    assert repo.writes[-1]["enabled"] is True


def test_update_config_rejects_invalid_preset_without_write():
    repo = FakeRepository()
    service = make_service(repository=repo)
    try:
        service.update_config({"schedule_preset": "nope"})
    except UpdateConfigError as exc:
        assert "nope" in str(exc)
    else:
        raise AssertionError("expected UpdateConfigError")
    assert repo.writes == []


def test_update_config_rejects_non_list_excluded():
    service = make_service()
    try:
        service.update_config({"excluded_stacks": "not-a-list"})
    except UpdateConfigError as exc:
        assert "excluded_stacks" in str(exc)
    else:
        raise AssertionError("expected UpdateConfigError")


def test_update_config_enabled_reschedules_job():
    scheduler = FakeScheduler()
    service = make_service(scheduler=scheduler)
    service.update_config({"enabled": True, "schedule_preset": "weekly_sunday_4am"})
    job = scheduler.jobs["auto_update"]
    assert job.trigger == "trigger:0 4 * * 0"
    assert job.kwargs["name"] == "Auto-Update Stacks"


def test_update_config_disabled_removes_job():
    scheduler = FakeScheduler()
    service = make_service(scheduler=scheduler)
    service.apply_schedule("daily_4am")
    assert "auto_update" in scheduler.jobs
    service.update_config({"enabled": False})
    assert "auto_update" not in scheduler.jobs


def test_update_config_persists_excluded_and_notify():
    repo = FakeRepository()
    service = make_service(repository=repo)
    result = service.update_config(
        {"excluded_stacks": ["s1", "s2"], "notify_on_update": False}
    )
    assert result["excluded_stacks"] == ["s1", "s2"]
    assert result["notify_on_update"] is False


# --- Scheduler ---------------------------------------------------------------

def test_init_scheduler_starts_and_schedules_when_enabled():
    scheduler = FakeScheduler()
    service = make_service(
        scheduler=scheduler,
        config={"enabled": True, "schedule_preset": "daily_4am"},
    )
    service.init_scheduler()
    assert scheduler.started is True
    assert "auto_update" in scheduler.jobs


def test_init_scheduler_starts_without_job_when_disabled():
    scheduler = FakeScheduler()
    service = make_service(scheduler=scheduler)
    service.init_scheduler()
    assert scheduler.started is True
    assert "auto_update" not in scheduler.jobs


def test_init_scheduler_does_not_restart_running_scheduler():
    scheduler = FakeScheduler(running=True)
    make_service(scheduler=scheduler).init_scheduler()
    assert scheduler.started is False


def test_apply_schedule_swallows_missing_job_removal():
    scheduler = FakeScheduler()
    scheduler.remove_raises = True
    service = make_service(scheduler=scheduler)
    # Even though remove_job raises, add still runs.
    service.apply_schedule("daily_4am")
    assert scheduler.jobs["auto_update"].trigger == "trigger:0 4 * * *"


def test_next_run_time_reads_job():
    scheduler = FakeScheduler()
    scheduler.jobs["auto_update"] = SimpleNamespace(next_run_time=FIXED_NOW)
    service = make_service(scheduler=scheduler)
    assert service.next_run_time() == FIXED_NOW.isoformat()


def test_next_run_time_returns_none_without_job():
    assert make_service().next_run_time() is None


# --- Execution ---------------------------------------------------------------

def test_run_updates_stack_with_new_images():
    service = make_service(
        stacks=[{"name": "web"}],
        compose={
            ("web", "pull"): {"success": True, "stdout": "Status: Downloaded newer image"},
            ("web", "up"): {"success": True, "stdout": "started"},
        },
    )
    result = service.run()
    assert result["updated"] == ["web"]
    assert result["failed"] == []


def test_run_skips_excluded_stacks():
    service = make_service(
        stacks=[{"name": "web"}, {"name": "db"}],
        compose={("web", "pull"): {"success": True, "stdout": "Image is up to date"}},
        config={"excluded_stacks": ["db"]},
    )
    result = service.run()
    assert "db" in result["skipped"]
    assert "web" in result["skipped"]


def test_run_skips_when_no_new_images():
    service = make_service(
        stacks=[{"name": "web"}],
        compose={("web", "pull"): {"success": True, "stdout": "Image is up to date"}},
    )
    result = service.run()
    assert result["skipped"] == ["web"]
    assert result["updated"] == []


def test_run_records_pull_failure():
    service = make_service(
        stacks=[{"name": "web"}],
        compose={("web", "pull"): {"success": False, "stderr": "network error"}},
    )
    result = service.run()
    assert result["failed"][0]["name"] == "web"
    assert "Pull failed" in result["failed"][0]["error"]


def test_run_records_up_failure():
    service = make_service(
        stacks=[{"name": "web"}],
        compose={
            ("web", "pull"): {"success": True, "stdout": "Downloaded newer image"},
            ("web", "up"): {"success": False, "stderr": "boom"},
        },
    )
    result = service.run()
    assert result["failed"][0]["name"] == "web"
    assert "Up failed" in result["failed"][0]["error"]


def test_run_handles_list_stacks_failure():
    def broken():
        raise RuntimeError("cannot list")

    result = make_service(stack_lister=broken).run()
    assert result["failed"][0]["name"] == "_system"
    assert "cannot list" in result["failed"][0]["error"]


def test_run_persists_last_run_result():
    repo = FakeRepository()
    service = make_service(
        repository=repo,
        stacks=[{"name": "web"}],
        compose={("web", "pull"): {"success": True, "stdout": "up to date"}},
    )
    service.run()
    saved = repo.writes[-1]
    assert saved["last_run"] == FIXED_NOW.isoformat()
    assert saved["last_run_result"]["skipped"] == ["web"]


def test_run_rejects_concurrent_execution():
    service = make_service()
    service._lock.acquire()
    try:
        result = service.run()
    finally:
        service._lock.release()
    assert result == {"error": "Update already in progress"}


# --- Read models -------------------------------------------------------------

def test_status_reports_state_and_running_flag():
    scheduler = FakeScheduler()
    scheduler.jobs["auto_update"] = SimpleNamespace(next_run_time=FIXED_NOW)
    service = make_service(
        scheduler=scheduler,
        config={"enabled": True, "schedule_preset": "daily_4am"},
    )
    status = service.status()
    assert status["enabled"] is True
    assert status["next_run"] == FIXED_NOW.isoformat()
    assert status["update_running"] is False


def test_logs_returns_last_run():
    service = make_service(config={"last_run": "2026-01-01T00:00:00", "last_run_result": {"x": 1}})
    logs = service.logs()
    assert logs["last_run"] == "2026-01-01T00:00:00"
    assert logs["last_run_result"] == {"x": 1}


# --- Route delegation --------------------------------------------------------

def _authed_client(update_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        update_service=update_service,
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


def test_get_config_route_delegates():
    service = Mock()
    service.load_config.return_value = {"enabled": True, "schedule_preset": "daily_4am"}
    client = _authed_client(service)
    response = client.get("/api/auto-update/config")
    assert response.status_code == 200
    assert json.loads(response.data)["enabled"] is True
    service.load_config.assert_called_once()


def test_post_config_route_delegates():
    service = Mock()
    service.update_config.return_value = {"enabled": True}
    client = _authed_client(service)
    response = client.post(
        "/api/auto-update/config",
        data=json.dumps({"enabled": True}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert json.loads(response.data)["status"] == "updated"
    service.update_config.assert_called_once_with({"enabled": True})


def test_post_config_route_maps_validation_error():
    service = Mock()
    service.update_config.side_effect = UpdateConfigError("Invalid schedule preset: x")
    client = _authed_client(service)
    response = client.post(
        "/api/auto-update/config",
        data=json.dumps({"schedule_preset": "x"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "Invalid schedule preset" in json.loads(response.data)["error"]


def test_post_config_route_rejects_empty_body():
    service = Mock()
    client = _authed_client(service)
    response = client.post(
        "/api/auto-update/config",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert response.status_code == 400
    service.update_config.assert_not_called()


def test_status_route_delegates():
    service = Mock()
    service.status.return_value = {"enabled": False, "update_running": False}
    client = _authed_client(service)
    response = client.get("/api/auto-update/status")
    assert response.status_code == 200
    service.status.assert_called_once()


def test_run_now_route_returns_completed():
    service = Mock()
    service.is_running.return_value = False
    service.run.return_value = {"updated": ["web"], "failed": [], "skipped": []}
    client = _authed_client(service)
    response = client.post("/api/auto-update/run-now")
    assert response.status_code == 200
    assert json.loads(response.data)["status"] == "completed"


def test_run_now_route_returns_409_when_running():
    service = Mock()
    service.is_running.return_value = True
    client = _authed_client(service)
    response = client.post("/api/auto-update/run-now")
    assert response.status_code == 409
    service.run.assert_not_called()


def test_logs_route_delegates():
    service = Mock()
    service.logs.return_value = {"last_run": None, "last_run_result": None}
    client = _authed_client(service)
    response = client.get("/api/auto-update/logs")
    assert response.status_code == 200
    service.logs.assert_called_once()
