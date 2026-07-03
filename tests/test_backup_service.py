"""Tests for the framework-neutral BackupService and its route delegation."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from backup_service import (
    BackupConfigError,
    BackupHelperUnavailable,
    BackupNotFound,
    BackupOperationError,
    BackupService,
)
from helper_client import HelperError
from operation_manager import OperationRegistry

CONFIG_PATH = "backup.json"
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

BASE_DEFAULTS = {
    "enabled": False,
    "schedule_preset": "disabled",
    "retention_count": 7,
    "plugin_retention_count": 10,
    "dest_dir": "/mnt/backup",
    "config_dir": "/home/pi/docker",
    "stacks_path": "/opt/stacks",
    "include_env": True,
    "compression": "zst",
    "plugin_backup_enabled": True,
}


class FakeRepository:
    def __init__(self, seed=None, path=CONFIG_PATH):
        self.store = {path: dict(seed)} if seed else {}
        self.writes = []

    def read_json(self, path, default=None):
        return self.store.get(path, default)

    def write_json(self, path, data, *, mode=0o644):
        self.store[path] = dict(data)
        self.writes.append(dict(data))


class FakeScheduler:
    def __init__(self, running=False):
        self._running = running
        self.jobs = {}
        self.started = False

    @property
    def running(self):
        return self._running

    def start(self):
        self._running = True
        self.started = True

    def add_job(self, func, trigger, *, id, replace_existing=True, **kwargs):
        self.jobs[id] = SimpleNamespace(func=func, trigger=trigger, kwargs=kwargs)

    def remove_job(self, job_id):
        if job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]

    def get_job(self, job_id):
        return self.jobs.get(job_id)


class FakeHelper:
    def __init__(self, available=True, responses=None, raises=None):
        self._available = available
        self._responses = list(responses or [])
        self._raises = raises
        self.calls = []

    def available(self):
        return self._available

    def call(self, command, params=None):
        self.calls.append((command, params))
        if self._raises:
            raise self._raises
        if self._responses:
            return self._responses.pop(0)
        return {"success": True}


def make_service(
    *,
    repository=None,
    scheduler=None,
    helper=None,
    stacks=(([], None)),
    compose=None,
    archive_exists=None,
    config=None,
):
    repo = repository if repository is not None else FakeRepository(config)
    return BackupService(
        repository=repo,
        scheduler=scheduler if scheduler is not None else FakeScheduler(),
        helper=helper if helper is not None else FakeHelper(),
        config_path_provider=lambda: CONFIG_PATH,
        default_config_provider=lambda: dict(BASE_DEFAULTS),
        sources_provider=lambda cfg: ["/src", str(cfg.get("config_dir"))],
        plugin_sources_provider=lambda: ["/plugins"],
        stack_lister=lambda: stacks,
        compose_runner=compose or (lambda name, cmd: {"success": True}),
        trigger_factory=lambda cron: f"trigger:{cron}",
        excludes=["*.log"],
        archive_exists=archive_exists or (lambda path: True),
        clock=lambda: FIXED_NOW,
    )


# --- Config ------------------------------------------------------------------

def test_load_config_merges_defaults_and_stored():
    service = make_service(config={"enabled": True, "retention_count": 3})
    config = service.load_config()
    assert config["enabled"] is True
    assert config["retention_count"] == 3
    assert config["dest_dir"] == "/mnt/backup"


def test_update_config_persists_and_reschedules():
    scheduler = FakeScheduler()
    service = make_service(scheduler=scheduler)
    config = service.update_config({"enabled": True, "schedule_preset": "daily_2am"})
    assert config["enabled"] is True
    assert scheduler.jobs["pihealth_backup"].trigger == "trigger:0 2 * * *"


def test_update_config_disabled_removes_job():
    scheduler = FakeScheduler()
    service = make_service(scheduler=scheduler)
    service.apply_schedule("daily_2am")
    service.update_config({"enabled": False})
    assert "pihealth_backup" not in scheduler.jobs


def test_update_config_rejects_zero_retention():
    try:
        make_service().update_config({"retention_count": 0})
    except BackupConfigError as exc:
        assert "retention_count" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_update_config_rejects_non_integer_retention():
    try:
        make_service().update_config({"retention_count": "lots"})
    except BackupConfigError as exc:
        assert "Invalid retention_count" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_update_config_rejects_relative_dest_dir():
    try:
        make_service().update_config({"dest_dir": "relative/path"})
    except BackupConfigError as exc:
        assert "absolute" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_update_config_rejects_traversal_dest_dir():
    try:
        make_service().update_config({"dest_dir": "/mnt/../etc"})
    except BackupConfigError as exc:
        assert "invalid" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_update_config_rejects_unknown_schedule():
    try:
        make_service().update_config({"schedule_preset": "never"})
    except BackupConfigError as exc:
        assert "schedule_preset" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


# --- Run ---------------------------------------------------------------------

def test_run_backup_reports_helper_unavailable():
    service = make_service(helper=FakeHelper(available=False))
    result = service.run_backup()
    assert result["primary"]["success"] is False
    assert result["plugins"]["success"] is False


def test_run_backup_runs_primary_and_plugins():
    helper = FakeHelper(responses=[{"success": True}, {"success": True}])
    repo = FakeRepository()
    service = make_service(repository=repo, helper=helper)
    result = service.run_backup()
    assert result["primary"]["success"] is True
    assert result["plugins"]["success"] is True
    assert [c[0] for c in helper.calls] == ["backup_create", "backup_create"]
    assert repo.writes[-1]["last_run"] == FIXED_NOW.isoformat()


def test_run_backup_skips_plugins_when_disabled():
    helper = FakeHelper(responses=[{"success": True}])
    service = make_service(helper=helper, config={"plugin_backup_enabled": False})
    result = service.run_backup()
    assert result["primary"]["success"] is True
    assert result["plugins"]["success"] is False
    assert "disabled" in result["plugins"]["error"]
    assert len(helper.calls) == 1


def test_run_backup_maps_helper_error_to_failed_results():
    helper = FakeHelper(raises=HelperError("socket down"))
    result = make_service(helper=helper).run_backup()
    assert result["primary"]["success"] is False
    assert "socket down" in result["primary"]["error"]


def test_run_backup_rejects_concurrent_execution():
    service = make_service()
    service._lock.acquire()
    try:
        result = service.run_backup()
    finally:
        service._lock.release()
    assert result == {"error": "Backup already in progress"}


# --- Restore -----------------------------------------------------------------

def test_restore_stops_and_starts_stacks():
    helper = FakeHelper(responses=[{"success": True}])
    service = make_service(
        helper=helper,
        stacks=([{"name": "alpha"}], None),
        compose=lambda name, cmd: {"success": True},
    )
    result = service.restore("pi-health-backup-20240101.tar.zst")
    assert result["stopped"] == ["alpha"]
    assert result["started"] == ["alpha"]
    assert ("backup_restore", {"archive_path": "/mnt/backup/pi-health-backup-20240101.tar.zst"}) in helper.calls


def test_restore_rejects_traversal_name():
    try:
        make_service().restore("../evil.tar.zst")
    except BackupConfigError as exc:
        assert "Invalid archive name" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_restore_missing_archive_raises_not_found():
    service = make_service(archive_exists=lambda path: False)
    try:
        service.restore("pi-health-backup-20240101.tar.zst")
    except BackupNotFound:
        pass
    else:
        raise AssertionError("expected BackupNotFound")


def test_restore_helper_unavailable_raises():
    service = make_service(helper=FakeHelper(available=False))
    try:
        service.restore("pi-health-backup-20240101.tar.zst")
    except BackupHelperUnavailable:
        pass
    else:
        raise AssertionError("expected BackupHelperUnavailable")


def test_restore_stack_list_error_raises_operation_error():
    service = make_service(stacks=([], "cannot list"))
    try:
        service.restore("pi-health-backup-20240101.tar.zst")
    except BackupOperationError as exc:
        assert "cannot list" in str(exc)
    else:
        raise AssertionError("expected BackupOperationError")


def test_restore_unsuccessful_result_raises_operation_error():
    helper = FakeHelper(responses=[{"success": False, "error": "bad archive"}])
    service = make_service(helper=helper, stacks=([], None))
    try:
        service.restore("pi-health-backup-20240101.tar.zst", stop_stacks=False)
    except BackupOperationError as exc:
        assert "bad archive" in str(exc)
    else:
        raise AssertionError("expected BackupOperationError")


def test_restore_plugins_rejects_wrong_prefix():
    try:
        make_service().restore_plugins("pi-health-backup-20240101.tar.zst")
    except BackupConfigError as exc:
        assert "plugin archive" in str(exc)
    else:
        raise AssertionError("expected BackupConfigError")


def test_restore_plugins_success_persists_result():
    helper = FakeHelper(responses=[{"success": True}])
    repo = FakeRepository()
    service = make_service(repository=repo, helper=helper)
    result = service.restore_plugins("storage-plugins-20240101.tar.zst")
    assert result["success"] is True
    assert repo.writes[-1]["last_plugin_backup"] == FIXED_NOW.isoformat()


# --- Read models -------------------------------------------------------------

def test_status_reports_running_flag_and_next_run():
    scheduler = FakeScheduler()
    scheduler.jobs["pihealth_backup"] = SimpleNamespace(next_run_time=FIXED_NOW)
    service = make_service(scheduler=scheduler, config={"enabled": True})
    status = service.status()
    assert status["enabled"] is True
    assert status["next_run"] == FIXED_NOW.isoformat()
    assert status["backup_running"] is False


# --- Route delegation --------------------------------------------------------

def _authed_client(backup_service):
    dependencies = AppDependencies(
        users={"testuser": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        backup_service=backup_service,
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


def test_config_route_delegates():
    service = Mock()
    service.load_config.return_value = {"dest_dir": "/mnt/backup", "retention_count": 7}
    response = _authed_client(service).get("/api/backups/config")
    assert response.status_code == 200
    service.load_config.assert_called_once()


def test_config_update_route_maps_validation_error():
    service = Mock()
    service.update_config.side_effect = BackupConfigError("Invalid schedule_preset")
    response = _authed_client(service).post(
        "/api/backups/config",
        data=json.dumps({"schedule_preset": "never"}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_run_route_maps_failed_primary_to_500():
    service = Mock()
    service.run_backup.return_value = {"primary": {"success": False, "error": "boom"}, "plugins": {}}
    response = _authed_client(service).post("/api/backups/run")
    assert response.status_code == 500
    assert json.loads(response.data)["error"] == "boom"


def test_restore_route_maps_not_found_to_404():
    service = Mock()
    service.restore.side_effect = BackupNotFound("Backup not found")
    response = _authed_client(service).post(
        "/api/backups/restore",
        data=json.dumps({"archive_name": "missing.tar.zst"}),
        content_type="application/json",
    )
    assert response.status_code == 404


def test_restore_route_maps_helper_error_to_503():
    service = Mock()
    service.restore.side_effect = HelperError("socket down")
    response = _authed_client(service).post(
        "/api/backups/restore",
        data=json.dumps({"archive_name": "pi-health-backup.tar.zst"}),
        content_type="application/json",
    )
    assert response.status_code == 503


def test_restore_route_returns_result_on_success():
    service = Mock()
    service.restore.return_value = {"restore": {"success": True}, "stopped": [], "started": []}
    response = _authed_client(service).post(
        "/api/backups/restore",
        data=json.dumps({"archive_name": "pi-health-backup.tar.zst"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    assert json.loads(response.data)["status"] == "ok"
