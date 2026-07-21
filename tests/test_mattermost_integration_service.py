import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from mattermost_integration_service import (
    LIFECYCLE_FAILURE_MESSAGE,
    MattermostIntegrationService,
)
from integration_lifecycle_service import (
    IntegrationLifecycleResolver,
    LifecycleStateRepository,
    load_lifecycle_policy,
)
from operation_manager import OperationRegistry
from ports import JsonFileRepository
from stack_manager import atomic_write_text


class FakeMattermostApi:
    def __init__(self):
        self.calls = []

    def ping(self):
        self.calls.append("ping")

    def ensure_admin(self, **values):
        self.calls.append(
            (
                "admin",
                values["admin_username"]
                if "admin_username" in values
                else values["username"],
            )
        )
        return "user-1"

    def login(self, username, _password):
        self.calls.append(("login", username))
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


class FakeRecoveryCustody:
    def __init__(self, active: Path, recovery: Path):
        self.active = active
        self.recovery = recovery
        self.calls = []

    def retain(self):
        self.calls.append("retain")
        if self.active.exists():
            self.recovery.parent.mkdir(parents=True, exist_ok=True)
            self.active.replace(self.recovery)
        if not self.recovery.exists():
            return {"success": False, "credential_retained": False}
        return {"success": True, "credential_retained": True}

    def restore(self):
        self.calls.append("restore")
        if self.recovery.exists():
            self.active.parent.mkdir(parents=True, exist_ok=True)
            self.recovery.replace(self.active)
        if not self.active.exists():
            return {"success": False, "credential_restored": False}
        return {"success": True, "credential_restored": True}

    def discard(self):
        self.calls.append("discard")
        self.recovery.unlink(missing_ok=True)
        return {"success": True, "credential_discarded": True}


class FakeDockerRunner:
    def __init__(self, policy):
        mattermost = policy["integrations"]["mattermost"]
        project = mattermost["compose_project"]
        self.images = set(mattermost["local_images"])
        self.volumes = {
            f"{project}_{logical}": {
                "com.docker.compose.project": project,
                "com.docker.compose.volume": logical,
            }
            for logical in mattermost["logical_volumes"]
        }
        self.calls = []

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        args = command[1:]
        stdout = ""
        if args[:3] == ["image", "ls", "--format"]:
            stdout = "\n".join(sorted(self.images))
        elif args[:2] == ["image", "rm"]:
            self.images.discard(args[2])
        elif args[:3] == ["volume", "ls", "--format"]:
            stdout = "\n".join(sorted(self.volumes))
        elif args[:2] == ["volume", "ls"] and "--filter" in args:
            label = args[args.index("--filter") + 1]
            project = label.rsplit("=", 1)[-1]
            stdout = "\n".join(
                sorted(
                    name
                    for name, labels in self.volumes.items()
                    if labels.get("com.docker.compose.project") == project
                )
            )
        elif args[:2] == ["volume", "inspect"]:
            labels = self.volumes.get(args[2])
            if labels is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="missing")
            stdout = json.dumps([{"Name": args[2], "Labels": labels}])
        elif args[:2] == ["volume", "rm"]:
            self.volumes.pop(args[2], None)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def make_service(
    tmp_path,
    *,
    lifecycle_resolver=None,
    lifecycle_repository=None,
    lifecycle_policy=None,
    recovery_custody=None,
    agent_snapshot=None,
    docker_runner=None,
    directory_remover=shutil.rmtree,
):
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
        stack_notifications_config_path=tmp_path
        / "config"
        / "stack-notifications.json",
        package_updates_config_path=tmp_path / "config" / "package-updates.json",
        lifecycle_resolver=lifecycle_resolver,
        lifecycle_repository=lifecycle_repository,
        lifecycle_policy=lifecycle_policy,
        recovery_custody=recovery_custody,
        agent_lifecycle_snapshot=agent_snapshot,
        docker_runner=docker_runner or runner,
        directory_remover=directory_remover,
    )
    return service, api, sent, compose_calls


def make_lifecycle_service(tmp_path, *, agent_snapshot=None, purge_enabled=False):
    policy = deepcopy(load_lifecycle_policy(Path("config/integration-lifecycle.json")))
    policy["release_policy"]["mattermost_purge_enabled"] = purge_enabled
    lifecycle = LifecycleStateRepository(
        tmp_path / "state" / "mattermost-lifecycle.json", "mattermost"
    )
    custody = FakeRecoveryCustody(
        tmp_path / "config" / "mattermost.env",
        tmp_path / "recovery" / "mattermost.env",
    )
    docker = FakeDockerRunner(policy)
    service, api, sent, compose_calls = make_service(
        tmp_path,
        lifecycle_resolver=IntegrationLifecycleResolver(lifecycle, policy=policy),
        lifecycle_repository=lifecycle,
        lifecycle_policy=policy,
        recovery_custody=custody,
        agent_snapshot=agent_snapshot
        or (lambda: {"state": "not_installed", "installed": False, "enabled": False}),
        docker_runner=docker,
    )
    return service, lifecycle, custody, docker, api, sent, compose_calls


def _lifecycle_record(*, target_state="disabled"):
    return {
        "schema_version": "1",
        "integration": "mattermost",
        "operation_id": "operation-1",
        "action": "disable" if target_state == "disabled" else "uninstall",
        "phase": "complete",
        "target_state": target_state,
        "started_at": "2026-07-20T20:00:00+00:00",
        "updated_at": "2026-07-20T20:01:00+00:00",
        "completed_steps": [],
        "retained_data": target_state == "retained_data",
        "remove_claude_code": None,
        "failure": None,
        "warning_codes": [],
    }


def test_status_applies_lifecycle_precedence_and_agent_dependency_blocks(tmp_path):
    lifecycle = LifecycleStateRepository(
        tmp_path / "state" / "mattermost-lifecycle.json",
        "mattermost",
    )
    lifecycle.write(_lifecycle_record())
    service, _api, _sent, _compose = make_service(
        tmp_path,
        lifecycle_resolver=IntegrationLifecycleResolver(lifecycle),
        agent_snapshot=lambda: {
            "state": "disabled",
            "installed": True,
            "enabled": False,
        },
    )

    status = service.status()

    assert status["state"] == "disabled"
    assert status["installed"] is True
    assert status["allowed_actions"] == ["enable"]
    assert status["blocked_actions"][0]["dependency_code"] == (
        "agents_must_be_uninstalled"
    )


def test_status_fails_closed_when_agent_dependency_snapshot_is_unavailable(tmp_path):
    lifecycle = LifecycleStateRepository(
        tmp_path / "state" / "mattermost-lifecycle.json",
        "mattermost",
    )
    service, _api, _sent, _compose = make_service(
        tmp_path,
        lifecycle_resolver=IntegrationLifecycleResolver(lifecycle),
        agent_snapshot=lambda: (_ for _ in ()).throw(RuntimeError("private path")),
    )

    status = service.status()

    assert status["allowed_actions"] == ["setup"]
    assert status["blocked_actions"] == []
    assert "private path" not in json.dumps(status)


SETUP = {
    "site_url": "http://mattermost.test:8065",
    "admin_username": "limeadmin",
    "admin_email": "admin@example.test",
    "admin_password": "long-test-password",
    "stack_name": "mattermost",
    "team_name": "limeos",
    "channel_name": "limeos-alerts",
}


def _sn_config(tmp_path):
    return json.loads((tmp_path / "config" / "stack-notifications.json").read_text())


def test_install_provisions_the_stack_notifications_channel_and_config(tmp_path):
    service, api, _sent, _compose = make_service(tmp_path)

    list(service.stream_install(SETUP))

    assert ("channel", "stack-notifications") in api.calls
    config = _sn_config(tmp_path)
    assert config["enabled"] is True
    assert config["mode"] == "quiet"
    assert config["channel_name"] == "stack-notifications"
    assert config["token"] and config["webhook_url"].startswith("http")


def test_install_provisions_the_updates_channel_and_config(tmp_path):
    service, api, _sent, _compose = make_service(tmp_path)

    list(service.stream_install(SETUP))

    assert ("channel", "limeos-updates") in api.calls
    config = json.loads((tmp_path / "config" / "package-updates.json").read_text())
    assert config["enabled"] is True
    assert config["channel_name"] == "limeos-updates"
    assert config["webhook_url"].startswith("http")


def test_enable_flow_provisions_both_channels_for_existing_install(tmp_path):
    service, api, _sent, _compose = make_service(tmp_path)
    list(service.stream_install(SETUP))
    (tmp_path / "config" / "package-updates.json").unlink()

    events = list(
        service.stream_enable_stack_notifications(
            {"admin_password": "long-test-password"}
        )
    )

    assert events[-1]["done"] is True
    assert (tmp_path / "config" / "package-updates.json").exists()


def test_install_preserves_an_existing_stack_notifications_token(tmp_path):
    service, _api, _sent, _compose = make_service(tmp_path)
    path = tmp_path / "config" / "stack-notifications.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": "keep-me", "mode": "verbose"}))

    list(service.stream_install(SETUP))

    config = _sn_config(tmp_path)
    assert config["token"] == "keep-me"  # never rotate a token *arr already uses
    assert config["mode"] == "verbose"


def test_enable_stack_notifications_provisions_for_an_existing_install(tmp_path):
    service, api, _sent, _compose = make_service(tmp_path)
    list(service.stream_install(SETUP))
    (tmp_path / "config" / "stack-notifications.json").unlink()

    events = list(
        service.stream_enable_stack_notifications(
            {"admin_password": "long-test-password"}
        )
    )

    assert events[-1]["done"] is True
    assert ("login", "limeadmin") in api.calls
    assert _sn_config(tmp_path)["enabled"] is True


def test_enable_requires_the_admin_password(tmp_path):
    service, _api, _sent, _compose = make_service(tmp_path)
    list(service.stream_install(SETUP))

    events = list(service.stream_enable_stack_notifications({}))

    assert events[-1]["step"] == "error"
    assert "password" in events[-1]["error"].lower()


def test_enable_requires_an_installed_mattermost(tmp_path):
    service, _api, _sent, _compose = make_service(tmp_path)

    events = list(service.stream_enable_stack_notifications({"admin_password": "pw"}))

    assert events[-1]["step"] == "error"


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
    assert (
        SETUP["admin_password"]
        not in (tmp_path / "config" / "mattermost.env").read_text()
    )
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
    assert (tmp_path / "stacks" / "mattermost" / "alert_history.py").is_file()
    assert "LIMEOS_ALERT_HISTORY_PATH: /var/lib/limeos/alert-events.jsonl" in compose
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "build",
        "limeos-alertd",
    ] in compose_calls
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "up",
        "-d",
        "--no-deps",
        "limeos-alertd",
    ] in compose_calls


def test_install_retry_reuses_database_password(tmp_path):
    service, _api, _sent, _compose_calls = make_service(tmp_path)
    list(service.stream_install(SETUP))
    first = (tmp_path / "config" / "mattermost.env").read_text()

    list(service.stream_install(SETUP))

    second = (tmp_path / "config" / "mattermost.env").read_text()
    first_password = next(
        line for line in first.splitlines() if line.startswith("POSTGRES_PASSWORD=")
    )
    assert first_password in second


def test_install_stays_uninstalled_when_test_delivery_fails(tmp_path):
    service, _api, _sent, _compose_calls = make_service(tmp_path)

    class FailingNotifier:
        def send(self, _notification):
            raise OSError("Mattermost test delivery failed")

    service._notifier_factory = lambda _url: FailingNotifier()

    events = list(service.stream_install(SETUP))

    config = json.loads((tmp_path / "config" / "mattermost.json").read_text())
    assert events[-1] == {"step": "error", "error": "Mattermost test delivery failed"}
    assert config["installed"] is False


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


def test_repair_reconciles_only_the_owned_stack_and_requires_connected_health(tmp_path):
    service, _lifecycle, _custody, _docker, api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    service._container_status_provider = lambda _name: {
        "state": "running",
        "health": "healthy",
    }
    compose_calls.clear()

    result = service.repair()

    assert result == {"status": "repaired", "state": "connected"}
    assert compose_calls == [["docker", "compose", "-f", "compose.yaml", "up", "-d"]]
    assert api.calls[-1] == "ping"


def test_repair_rejects_disabled_lifecycle_before_compose(tmp_path):
    service, lifecycle, _custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    lifecycle.write(_lifecycle_record())
    before = list(compose_calls)

    with pytest.raises(Exception, match="cleanup must finish"):
        service.repair()

    assert compose_calls == before


def test_disable_is_blocked_until_agents_are_disabled(tmp_path):
    service, lifecycle, _custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(
            tmp_path,
            agent_snapshot=lambda: {
                "state": "enabled",
                "installed": True,
                "enabled": True,
            },
        )
    )
    list(service.stream_install(SETUP))
    before = list(compose_calls)

    events = list(service.stream_disable("disable-1"))

    assert events[-1] == {
        "step": "error",
        "error": "Disable AI Agents before stopping Mattermost",
    }
    assert lifecycle.read() is None
    assert compose_calls == before


def test_disable_and_enable_manage_the_full_stack_without_removing_data(tmp_path):
    service, lifecycle, _custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    config_path = tmp_path / "config" / "mattermost.json"
    secrets_path = tmp_path / "config" / "mattermost.env"
    stack_path = tmp_path / "stacks" / "mattermost" / "compose.yaml"

    disabled = list(service.stream_disable("disable-1"))

    assert disabled[-1]["done"] is True
    assert lifecycle.read()["target_state"] == "disabled"
    assert [
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "down",
        "--remove-orphans",
    ] in compose_calls
    assert config_path.exists() and secrets_path.exists() and stack_path.exists()
    assert not any("--volumes" in call or "-v" in call for call in compose_calls)

    enabled = list(service.stream_enable("enable-1"))

    assert enabled[-1]["done"] is True
    assert lifecycle.read() is None
    assert ["docker", "compose", "-f", "compose.yaml", "up", "-d"] in compose_calls


def test_disable_and_enable_failures_are_retryable_and_checkpointed(tmp_path):
    service, lifecycle, _custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    real_runner = service._compose_runner
    disable_attempts = 0

    def fail_disable_once(command, **kwargs):
        nonlocal disable_attempts
        if "down" in command:
            disable_attempts += 1
            if disable_attempts == 1:
                return SimpleNamespace(returncode=1, stdout="", stderr="private")
        return real_runner(command, **kwargs)

    service._compose_runner = fail_disable_once
    failed_disable = list(service.stream_disable("disable-1"))

    assert failed_disable[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert lifecycle.read()["phase"] == "cleanup_required"
    assert list(service.stream_retry_cleanup("disable-retry"))[-1]["done"] is True
    assert lifecycle.read()["target_state"] == "disabled"

    real_wait = service._wait_until_ready
    enable_attempts = 0

    def fail_enable_once(client):
        nonlocal enable_attempts
        enable_attempts += 1
        if enable_attempts == 1:
            raise OSError("private readiness failure")
        real_wait(client)

    service._wait_until_ready = fail_enable_once
    failed_enable = list(service.stream_enable("enable-1"))

    assert failed_enable[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert lifecycle.read()["completed_steps"] == ["start_services"]
    assert list(service.stream_retry_cleanup("enable-retry"))[-1]["done"] is True
    assert lifecycle.read() is None
    full_stack_up = [
        call
        for call in compose_calls
        if call == ["docker", "compose", "-f", "compose.yaml", "up", "-d"]
    ]
    assert len(full_stack_up) == 1


def test_uninstall_is_blocked_while_agents_remain_installed(tmp_path):
    service, lifecycle, _custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(
            tmp_path,
            agent_snapshot=lambda: {
                "state": "disabled",
                "installed": True,
                "enabled": False,
            },
        )
    )
    list(service.stream_install(SETUP))
    before = list(compose_calls)

    events = list(service.stream_uninstall("uninstall-1"))

    assert events[-1] == {
        "step": "error",
        "error": "Uninstall AI Agents before removing Mattermost",
    }
    assert lifecycle.read() is None
    assert compose_calls == before


UNINSTALL_STEPS = [
    "verify_storage_layout",
    "stop_services",
    "retain_database_credential",
    "remove_stack_notification_hook",
    "remove_package_update_hook",
    "remove_runtime_status",
    "remove_alert_history",
    "remove_integration_config",
    "remove_generated_stack",
    "remove_image_1",
    "remove_image_2",
]


@pytest.mark.parametrize("failed_step", UNINSTALL_STEPS)
def test_uninstall_retries_each_failed_checkpoint_without_replaying_successes(
    tmp_path, failed_step
):
    service, lifecycle, custody, docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    (tmp_path / "state" / "mattermost-status.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (tmp_path / "state").chmod(0o750)
    (tmp_path / "state" / "mattermost-status.json").write_text("{}")
    (tmp_path / "state" / "alert-events.jsonl").write_text("event\n")
    original_steps = service._uninstall_steps
    attempts = {failed_step: 0}

    def failing_steps(config):
        wrapped = []
        for name, line, action in original_steps(config):
            if name == failed_step:

                def fail_once(action=action, name=name):
                    attempts[name] += 1
                    if attempts[name] == 1:
                        raise OSError("private failure detail")
                    action()

                action = fail_once
            wrapped.append((name, line, action))
        return wrapped

    service._uninstall_steps = failing_steps

    failed = list(service.stream_uninstall("uninstall-1"))
    failed_record = lifecycle.read()

    assert failed[-1] == {"step": "error", "error": LIFECYCLE_FAILURE_MESSAGE}
    assert "private failure detail" not in json.dumps(failed)
    assert failed_record["phase"] == "cleanup_required"
    assert failed_step not in failed_record["completed_steps"]

    retried = list(service.stream_retry_cleanup("retry-1"))
    complete_record = lifecycle.read()

    assert retried[-1]["done"] is True
    assert complete_record["phase"] == "complete"
    assert complete_record["target_state"] == "retained_data"
    assert attempts[failed_step] == 2
    assert custody.recovery.exists()
    assert not (tmp_path / "config" / "mattermost.json").exists()
    assert not (tmp_path / "stacks" / "mattermost").exists()
    assert docker.images == set()
    down_calls = [call for call in compose_calls if "down" in call]
    assert len(down_calls) == 1
    assert not any("--volumes" in call or "-v" in call for call in compose_calls)


def test_retained_data_reinstall_reuses_database_credential(tmp_path):
    service, lifecycle, custody, _docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    original_secret = (tmp_path / "config" / "mattermost.env").read_text()
    original_password = next(
        line
        for line in original_secret.splitlines()
        if line.startswith("POSTGRES_PASSWORD=")
    )
    assert list(service.stream_uninstall("uninstall-1"))[-1]["done"] is True

    events = list(service.stream_install(SETUP))

    restored_secret = (tmp_path / "config" / "mattermost.env").read_text()
    assert events[-1]["done"] is True
    assert original_password in restored_secret
    assert lifecycle.read() is None
    assert custody.calls == ["retain", "restore"]
    assert not custody.recovery.exists()


def test_uninstall_preserves_volumes_and_removes_only_fixed_local_images(tmp_path):
    service, lifecycle, custody, docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    docker.images.add("docker.io/library/postgres:16-alpine")
    original_volumes = deepcopy(docker.volumes)
    list(service.stream_install(SETUP))

    events = list(service.stream_uninstall("uninstall-1"))

    assert events[-1]["done"] is True
    assert lifecycle.read()["retained_data"] is True
    assert docker.volumes == original_volumes
    assert docker.images == {"docker.io/library/postgres:16-alpine"}
    removed_images = {call[-1] for call in docker.calls if call[1:3] == ["image", "rm"]}
    assert removed_images == {
        "limeos/mattermost-team:11.8.3-arm64",
        "limeos/alertd:local",
    }
    assert custody.recovery.exists()
    assert not any("--volumes" in call or "-v" in call for call in compose_calls)


def test_uninstall_cleanup_resumes_after_service_restart(tmp_path):
    service, lifecycle, custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    real_remover = service._directory_remover
    service._directory_remover = lambda _path: (_ for _ in ()).throw(
        OSError("private restart failure")
    )

    failed = list(service.stream_uninstall("uninstall-1"))

    assert failed[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert lifecycle.read()["completed_steps"][-1] == "remove_integration_config"
    replacement, _api, _sent, _compose_calls = make_service(
        tmp_path,
        lifecycle_resolver=IntegrationLifecycleResolver(
            lifecycle, policy=service._lifecycle_policy
        ),
        lifecycle_repository=lifecycle,
        lifecycle_policy=service._lifecycle_policy,
        recovery_custody=custody,
        agent_snapshot=lambda: {
            "state": "not_installed",
            "installed": False,
            "enabled": False,
        },
        docker_runner=docker,
        directory_remover=real_remover,
    )

    retried = list(replacement.stream_retry_cleanup("restart-retry"))

    assert retried[-1]["done"] is True
    assert lifecycle.read()["target_state"] == "retained_data"
    assert not (tmp_path / "stacks" / "mattermost").exists()


def test_uninstall_rejects_an_edited_or_bind_mounted_data_layout(tmp_path):
    service, lifecycle, custody, _docker, _api, _sent, compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    compose_path = tmp_path / "stacks" / "mattermost" / "compose.yaml"
    compose_path.write_text(
        compose_path.read_text().replace(
            "mattermost-postgres:/var/lib/postgresql/data",
            "/mnt/database:/var/lib/postgresql/data",
        )
    )
    before = list(compose_calls)

    events = list(service.stream_uninstall("uninstall-1"))

    assert events[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert lifecycle.read()["phase"] == "cleanup_required"
    assert compose_calls == before
    assert custody.calls == []


def test_purge_is_hidden_and_blocked_while_release_policy_is_off(tmp_path):
    service, lifecycle, _custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path)
    )
    list(service.stream_install(SETUP))
    list(service.stream_uninstall("uninstall-1"))
    before = list(docker.calls)

    events = list(service.stream_purge("purge-1"))

    assert events[-1]["error"] == (
        "Mattermost data deletion is not enabled in this release"
    )
    assert lifecycle.read()["target_state"] == "retained_data"
    assert service.status()["allowed_actions"] == ["setup"]
    assert docker.calls == before


def test_purge_removes_only_verified_fixed_volumes_and_recovery_credential(tmp_path):
    service, lifecycle, custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path, purge_enabled=True)
    )
    list(service.stream_install(SETUP))
    list(service.stream_uninstall("uninstall-1"))

    events = list(service.stream_purge("purge-1"))

    assert events[-1]["done"] is True
    assert lifecycle.read() is None
    assert docker.volumes == {}
    assert not custody.recovery.exists()
    removed = {call[-1] for call in docker.calls if call[1:3] == ["volume", "rm"]}
    assert removed == {
        "mattermost_mattermost-postgres",
        "mattermost_mattermost-config",
        "mattermost_mattermost-data",
        "mattermost_mattermost-logs",
        "mattermost_mattermost-plugins",
    }


PURGE_STEPS = [
    "verify_volume_ownership",
    "remove_volume_1",
    "remove_volume_2",
    "remove_volume_3",
    "remove_volume_4",
    "remove_volume_5",
    "discard_database_credential",
]


@pytest.mark.parametrize("failed_step", PURGE_STEPS)
def test_purge_retries_each_failed_checkpoint(tmp_path, failed_step):
    service, lifecycle, custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path, purge_enabled=True)
    )
    list(service.stream_install(SETUP))
    list(service.stream_uninstall("uninstall-1"))
    original_steps = service._purge_steps
    attempts = {failed_step: 0}

    def failing_steps():
        wrapped = []
        for name, line, action in original_steps():
            if name == failed_step:

                def fail_once(action=action, name=name):
                    attempts[name] += 1
                    if attempts[name] == 1:
                        raise OSError("private purge failure")
                    action()

                action = fail_once
            wrapped.append((name, line, action))
        return wrapped

    service._purge_steps = failing_steps

    failed = list(service.stream_purge("purge-1"))

    assert failed[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert lifecycle.read()["phase"] == "cleanup_required"
    assert failed_step not in lifecycle.read()["completed_steps"]

    retried = list(service.stream_retry_cleanup("purge-retry"))

    assert retried[-1]["done"] is True
    assert lifecycle.read() is None
    assert attempts[failed_step] == 2
    assert docker.volumes == {}
    assert not custody.recovery.exists()


def test_purge_fails_closed_before_removal_when_volume_labels_do_not_match(tmp_path):
    service, lifecycle, custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path, purge_enabled=True)
    )
    list(service.stream_install(SETUP))
    list(service.stream_uninstall("uninstall-1"))
    docker.volumes["mattermost_mattermost-data"] = {
        "com.docker.compose.project": "other",
        "com.docker.compose.volume": "mattermost-data",
    }

    events = list(service.stream_purge("purge-1"))

    assert events[-1] == {"step": "error", "error": LIFECYCLE_FAILURE_MESSAGE}
    assert lifecycle.read()["phase"] == "cleanup_required"
    assert not any(call[1:3] == ["volume", "rm"] for call in docker.calls)
    assert custody.recovery.exists()


def test_resumed_purge_rechecks_volume_labels_before_each_removal(tmp_path):
    service, lifecycle, custody, docker, _api, _sent, _compose_calls = (
        make_lifecycle_service(tmp_path, purge_enabled=True)
    )
    list(service.stream_install(SETUP))
    list(service.stream_uninstall("uninstall-1"))
    original_remove = service._remove_volume
    attempts = 0

    def interrupt_once(project, logical):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("private interruption")
        original_remove(project, logical)

    service._remove_volume = interrupt_once
    assert list(service.stream_purge("purge-1"))[-1]["step"] == "error"
    assert lifecycle.read()["completed_steps"] == ["verify_volume_ownership"]
    docker.volumes["mattermost_mattermost-postgres"] = {
        "com.docker.compose.project": "other",
        "com.docker.compose.volume": "mattermost-postgres",
    }

    retried = list(service.stream_retry_cleanup("purge-retry"))

    assert retried[-1]["error"] == LIFECYCLE_FAILURE_MESSAGE
    assert not any(call[1:3] == ["volume", "rm"] for call in docker.calls)
    assert custody.recovery.exists()


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

    assert (
        client.get("/api/integrations/mattermost").get_json()["state"]
        == "not_installed"
    )
    install = client.post("/api/integrations/mattermost/install", json=SETUP)
    assert install.status_code == 202
    stream = client.get(install.get_json()["stream_url"])
    assert "Preparing" in stream.get_data(as_text=True)
    assert (
        client.put(
            "/api/integrations/mattermost/policy", json={"categories": {}}
        ).status_code
        == 200
    )
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
