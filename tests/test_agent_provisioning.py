"""AA-004 fixed helper provisioning and systemd sandbox contracts."""

from __future__ import annotations

import json
import grp
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pihealth_helper as helper

from agent_actions.ledger import ActionLedger, ActionState, NewAction
from agent_provider.claude import ClaudeCodeConfig
from agent_provider.provisioning import (
    ACTION_BROKER_UNIT_PATH,
    ACTION_POLICY_PATH,
    ACTION_SOCKET_DIR,
    ACTION_STATE_DIR,
    ACTION_WORKER_UNIT_PATH,
    AGENT_REPAIR_UNIT_PATH,
    AGENT_RUNTIME_MODULES,
    AGENT_RUNTIME_PACKAGES,
    EXTENSION_REPAIR_UNIT_PATH,
    AGENT_ENV_PATH,
    AGENT_LIB_DIR,
    AGENT_STATE_DIR,
    CLAUDE_CONFIG_DIR,
    LIMEOPS_STATE_DIR,
    MATTERMOST_REPAIR_UNIT_PATH,
    REPORT_SCHEDULER_STATE_DIR,
    REPORT_SCHEDULER_UNIT_PATH,
    REPORT_SCHEDULER_VENV_DIR,
    REPORT_DELIVERY_CONFIG_DIR,
    REPORT_MATTERMOST_WEBHOOK_PATH,
    SUPERVISOR_CONFIG_DIR,
    SUPERVISOR_DELIVERY_CONFIG_PATH,
    SUPERVISOR_MATTERMOST_ENV_PATH,
    SUPERVISOR_STATE_DIR,
    SUPERVISOR_UNIT_PATH,
    SUPERVISOR_VENV_DIR,
    STACK_LOCK_DIR,
    render_agent_unit,
    render_action_broker_unit,
    render_action_worker_unit,
    render_agent_repair_unit,
    render_extension_repair_unit,
    render_limeops_unit,
    render_mattermost_repair_unit,
    render_report_scheduler_unit,
    render_supervisor_unit,
)
from agent_runtime.service import DEFAULT_STATE_DIR


def test_agent_unit_has_no_privileged_sockets_or_source_access():
    unit = render_agent_unit("/opt/pi-health", "/opt/pi-health/.venv/bin/python")
    assert AGENT_STATE_DIR == "/var/lib/lime-agent/state"
    assert DEFAULT_STATE_DIR == AGENT_STATE_DIR
    assert ClaudeCodeConfig().work_dir == Path(AGENT_STATE_DIR)
    assert "User=lime-agent" in unit
    assert "Group=lime-agent" in unit
    assert "SupplementaryGroups=limeops-client" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
    assert "PrivateDevices=true" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
    assert "CapabilityBoundingSet=" in unit
    assert f"ReadWritePaths={AGENT_STATE_DIR} {CLAUDE_CONFIG_DIR}" in unit
    assert f"ReadOnlyPaths={AGENT_LIB_DIR}" in unit
    assert (
        "InaccessiblePaths=/root /opt/pi-health /run/pihealth -/run/limeos-actions "
        "/var/run/docker.sock "
        "/etc/limeos/credentials.env"
    ) in unit
    assert "ANTHROPIC_API_KEY" not in unit
    assert "EnvironmentFile=/etc/limeos/credentials.env" not in unit
    assert f"EnvironmentFile={AGENT_ENV_PATH}" in unit
    assert "LoadCredential=agent-settings:/etc/limeos/integrations/agents.json" in unit
    assert "Environment=LIMEOS_AGENT_CONFIG=%d/agent-settings" in unit
    assert "SupplementaryGroups=docker" not in unit
    assert "SupplementaryGroups=pihealth" not in unit


def test_limeops_unit_owns_privileged_read_boundary():
    unit = render_limeops_unit("/opt/pi-health")
    assert "User=limeops" in unit
    assert "Group=limeops" in unit
    assert "SupplementaryGroups=docker pihealth limeops-client" in unit
    assert "UMask=0007" in unit
    assert "ProtectSystem=strict" in unit
    assert "WorkingDirectory=/var/lib/limeops" in unit
    assert f"Environment=PYTHONPATH={AGENT_LIB_DIR}" in unit
    assert "ExecStart=/usr/bin/python3 -m limeops.server" in unit
    assert "ReadOnlyPaths=/usr/lib/limeos-agent" in unit
    assert "InaccessiblePaths=/root /opt/pi-health" in unit
    assert "/opt/pi-health/.venv/bin/python" not in unit
    assert "ReadWritePaths=/run/limeos /var/log/limeos" in unit
    assert "agent-policy.json" in unit
    assert ACTION_STATE_DIR in unit


def test_action_units_keep_worker_unprivileged_and_socket_separate():
    broker = render_action_broker_unit("/opt/pi-health")
    worker = render_action_worker_unit("/opt/pi-health")
    assert "User=limeops-actuator" in broker
    assert "SupplementaryGroups=docker pihealth limeops-action" in broker
    assert "python3 -m agent_actions.server" in broker
    assert "agent-action-policy.json" in broker
    assert "agent-actuator-policy.json" in broker
    assert ACTION_SOCKET_DIR in broker
    assert f"ReadWritePaths={ACTION_SOCKET_DIR} {ACTION_STATE_DIR} /var/log/limeos {STACK_LOCK_DIR}" in broker
    assert "User=limeops-action-worker" in worker
    assert "SupplementaryGroups=pihealth limeops-action" in worker
    assert "python3 -m agent_actions.worker" in worker
    assert "/var/run/docker.sock" in worker
    assert "SupplementaryGroups=docker" not in worker
    assert "limeops-client" not in broker
    assert "limeops-client" not in worker


def test_report_scheduler_unit_has_read_broker_and_report_state_only():
    unit = render_report_scheduler_unit("/opt/pi-health")

    assert "User=limeops-report" in unit
    assert "Group=limeops-report" in unit
    assert "SupplementaryGroups=limeops-client pihealth" in unit
    assert f"ExecStart={REPORT_SCHEDULER_VENV_DIR}/bin/python -m agent_automation.runner" in unit
    assert f"WorkingDirectory={REPORT_SCHEDULER_STATE_DIR}" in unit
    assert f"ReadWritePaths={ACTION_STATE_DIR}" in unit
    assert REPORT_MATTERMOST_WEBHOOK_PATH in unit
    assert "/etc/limeos/integrations/mattermost.env" not in unit
    assert "/run/limeos-actions" in unit
    assert "/var/run/docker.sock" in unit
    assert "SupplementaryGroups=docker" not in unit
    assert "NoNewPrivileges=true" in unit


def test_supervisor_unit_has_only_read_broker_and_shared_action_state():
    unit = render_supervisor_unit("/opt/pi-health")

    assert "User=limeops-supervisor" in unit
    assert "Group=limeops-supervisor" in unit
    assert "SupplementaryGroups=limeops-client pihealth" in unit
    assert (
        f"ExecStart={SUPERVISOR_VENV_DIR}/bin/python "
        "-m agent_supervision.runner"
    ) in unit
    assert f"WorkingDirectory={SUPERVISOR_STATE_DIR}" in unit
    assert f"ReadWritePaths={ACTION_STATE_DIR}" in unit
    assert SUPERVISOR_DELIVERY_CONFIG_PATH in unit
    assert SUPERVISOR_MATTERMOST_ENV_PATH in unit
    assert AGENT_ENV_PATH in unit
    assert ACTION_SOCKET_DIR in unit
    assert "/var/run/docker.sock" in unit
    assert "SupplementaryGroups=docker" not in unit
    assert "NoNewPrivileges=true" in unit


def test_report_webhook_projection_excludes_other_mattermost_secrets(tmp_path):
    source = tmp_path / "mattermost.env"
    source.write_text(
        "POSTGRES_PASSWORD=private\n"
        "LIMEOS_ALERT_MATTERMOST_WEBHOOK=https://mm.example/hooks/report\n",
        encoding="utf-8",
    )
    source.chmod(0o600)
    destination_dir = tmp_path / "agent-report"
    destination_dir.mkdir()
    destination = destination_dir / "mattermost-webhook.env"
    user = SimpleNamespace(pw_uid=os.getuid())
    group = SimpleNamespace(gr_gid=os.getgid())

    with (
        patch.object(helper, "MATTERMOST_ACTIVE_CREDENTIAL", str(source)),
        patch.object(helper, "REPORT_DELIVERY_CONFIG_DIR", str(destination_dir)),
        patch.object(helper, "REPORT_MATTERMOST_WEBHOOK_PATH", str(destination)),
        patch.object(helper.pwd, "getpwnam", return_value=user),
        patch.object(grp, "getgrnam", return_value=group),
    ):
        assert helper._sync_report_webhook_credential("dashboard") is True

    assert destination.read_text(encoding="utf-8") == (
        "LIMEOS_ALERT_MATTERMOST_WEBHOOK=https://mm.example/hooks/report\n"
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640


def test_supervisor_projection_contains_only_delivery_identity_and_token(
    tmp_path,
):
    settings = tmp_path / "agents.json"
    settings.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "enabled": True,
                "mattermost": {
                    "site_url": "https://mattermost.example",
                    "bot_username": "limeos",
                    "bot_user_id": "bot-1",
                    "allowed_channels": ["channel-1"],
                    "team_id": "team-1",
                    "channel_id": "channel-1",
                    "bot_token_id": "token-1",
                },
                "limits": {},
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "agents.env"
    source.write_text(
        "MATTERMOST_BOT_TOKEN=bot-secret\nUNRELATED_SECRET=private\n",
        encoding="utf-8",
    )
    destination = tmp_path / "agent-supervisor"
    destination.mkdir()
    config = destination / "delivery.json"
    secret = destination / "mattermost.env"

    with (
        patch.object(helper, "AGENT_CONFIG_PATH", str(settings)),
        patch.object(helper, "AGENT_ENV_PATH", str(source)),
        patch.object(helper, "SUPERVISOR_CONFIG_DIR", str(destination)),
        patch.object(
            helper, "SUPERVISOR_DELIVERY_CONFIG_PATH", str(config)
        ),
        patch.object(
            helper, "SUPERVISOR_MATTERMOST_ENV_PATH", str(secret)
        ),
        patch("grp.getgrnam", return_value=SimpleNamespace(gr_gid=os.getgid())),
        patch.object(helper.os, "fchown"),
    ):
        result = helper._sync_supervisor_delivery_projection(required=True)

    assert result == {
        "success": True,
        "configured": True,
        "enabled": True,
    }
    assert json.loads(config.read_text(encoding="utf-8")) == {
        "schema_version": "1",
        "site_url": "https://mattermost.example",
        "channel_id": "channel-1",
    }
    assert secret.read_text(encoding="utf-8") == (
        "MATTERMOST_BOT_TOKEN=bot-secret\n"
    )
    assert "UNRELATED_SECRET" not in secret.read_text(encoding="utf-8")
    assert stat.S_IMODE(config.stat().st_mode) == 0o640
    assert stat.S_IMODE(secret.stat().st_mode) == 0o640


def test_shared_agent_databases_are_fixed_group_files(tmp_path):
    action_state = tmp_path / "agent-actions"
    action_state.mkdir()
    actions = action_state / "actions.sqlite3"
    automation = action_state / "automation.sqlite3"
    actions.write_text("actions", encoding="utf-8")
    automation.write_text("automation", encoding="utf-8")
    supervision = action_state / "supervision.sqlite3"
    supervision.write_text("supervision", encoding="utf-8")
    user = SimpleNamespace(pw_uid=os.getuid())
    group = SimpleNamespace(gr_gid=os.getgid())

    with (
        patch.object(helper, "ACTION_STATE_DIR", str(action_state)),
        patch.object(helper.pwd, "getpwnam", return_value=user),
        patch.object(grp, "getgrnam", return_value=group),
    ):
        assert helper._secure_shared_agent_databases("dashboard") is True

    assert stat.S_IMODE(actions.stat().st_mode) == 0o660
    assert stat.S_IMODE(automation.stat().st_mode) == 0o660
    assert stat.S_IMODE(supervision.stat().st_mode) == 0o660


def test_agent_repair_unit_is_fixed_unprivileged_and_helper_backed():
    unit = render_agent_repair_unit("/opt/pi-health")

    assert "User=limeops-action-worker" in unit
    assert "SupplementaryGroups=pihealth" in unit
    assert 'helper_call("agent_integration_repair", {}, timeout=1800)' in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "ProtectSystem=strict" in unit
    assert "Environment=PYTHONPATH=/usr/lib/limeos-agent" in unit
    assert "InaccessiblePaths=/root /opt/pi-health" in unit
    assert "SupplementaryGroups=docker" not in unit


def test_extension_repair_unit_runs_only_configured_target_as_dashboard_user():
    unit = render_extension_repair_unit("/opt/pi-health", "holly")

    assert "User=holly" in unit
    assert "SupplementaryGroups=pihealth" in unit
    assert "extension-repair --name %i" in unit
    assert "ReadWritePaths=/opt/pi-health/plugins /etc/limeos" in unit
    assert "RestrictAddressFamilies=AF_UNIX" in unit
    assert "SupplementaryGroups=docker" not in unit
    assert "/var/run/docker.sock" in unit


def test_mattermost_repair_unit_runs_fixed_service_as_dashboard_user():
    unit = render_mattermost_repair_unit("/opt/pi-health", "holly")

    assert "User=holly" in unit
    assert "SupplementaryGroups=docker pihealth" in unit
    assert "agent_actions.repair_job mattermost-repair" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
    assert "ReadOnlyPaths=/opt/pi-health /etc/limeos" in unit


def test_helper_agent_commands_reject_all_caller_controlled_parameters():
    for command in (
        helper.cmd_agent_runtime_install,
        helper.cmd_agent_runtime_status,
        helper.cmd_agent_runtime_disable,
        helper.cmd_agent_runtime_uninstall,
        helper.cmd_agent_provider_install,
        helper.cmd_agent_action_policy_write,
        helper.cmd_agent_supervision_enabled,
        helper.cmd_agent_integration_repair,
        helper.cmd_agent_integration_repair_start,
        helper.cmd_agent_mattermost_status,
        helper.cmd_agent_mattermost_repair_start,
        helper.cmd_agent_extension_status,
        helper.cmd_agent_extension_repair_start,
    ):
        result = command({"path": "/tmp/evil"})
        assert result["success"] is False


def test_helper_exposes_only_fixed_agent_operations():
    assert {
        "agent_runtime_install",
        "agent_runtime_status",
        "agent_runtime_disable",
        "agent_runtime_uninstall",
        "agent_provider_install",
        "agent_provider_auth_start",
        "agent_provider_auth_status",
        "agent_provider_auth_submit",
        "agent_provider_auth_cancel",
        "agent_bot_secret_write",
        "agent_configure",
        "agent_action_policy_write",
        "agent_supervision_enabled",
        "agent_runtime_start",
        "agent_integration_repair",
        "agent_integration_repair_start",
        "agent_mattermost_status",
        "agent_mattermost_repair_start",
        "agent_extension_status",
        "agent_extension_repair_start",
        "agent_usage_read",
        "agent_audit_read",
        "agent_delivery_test",
    } <= helper.COMMANDS.keys()
    assert "agent_write_unit" not in helper.COMMANDS
    assert "agent_run_command" not in helper.COMMANDS


def test_helper_agent_repair_runs_only_the_fixed_convergence_sequence():
    healthy = {"configured": True, "claude_authenticated": True}
    calls = []

    def record(name, result):
        def command(params):
            calls.append((name, params))
            return result

        return command

    with (
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(
            helper,
            "cmd_agent_provider_install",
            side_effect=record("provider", {"success": True}),
        ),
        patch.object(
            helper,
            "cmd_agent_runtime_install",
            side_effect=record("runtime", {"success": True}),
        ),
        patch.object(
            helper,
            "cmd_agent_runtime_status",
            side_effect=record("status", healthy),
        ),
        patch.object(
            helper,
            "cmd_agent_runtime_start",
            side_effect=record("start", {"success": True}),
        ),
    ):
        result = helper.cmd_agent_integration_repair({})

    assert result == {"success": True, "repaired": True}
    assert calls == [
        ("provider", {}),
        ("runtime", {}),
        ("status", {}),
        ("start", {}),
    ]


def test_helper_agent_repair_fails_closed_for_lifecycle_cleanup():
    with (
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"reconcile_allowed": False},
        ),
        patch.object(helper, "cmd_agent_provider_install") as provider,
    ):
        result = helper.cmd_agent_integration_repair({})

    assert result["success"] is False
    provider.assert_not_called()


def test_helper_agent_repair_start_uses_only_the_fixed_nonblocking_unit():
    with patch.object(
        helper, "run_command", return_value={"returncode": 0}
    ) as run:
        result = helper.cmd_agent_integration_repair_start({})

    assert result == {"success": True, "started": True}
    assert run.call_args.args[0] == [
        "systemctl",
        "start",
        "--no-block",
        "limeos-agent-repair.service",
    ]


def test_helper_extension_repair_derives_eligibility_then_starts_fixed_instance():
    with (
        patch.object(
            helper,
            "cmd_agent_extension_status",
            return_value={"success": True, "repairable": True},
        ),
        patch.object(helper, "run_command", return_value={"returncode": 0}) as run,
    ):
        result = helper.cmd_agent_extension_repair_start({"name": "weather"})

    assert result == {"success": True, "started": True}
    assert [call.args[0] for call in run.call_args_list] == [
        ["systemctl", "reset-failed", "limeos-extension-repair@weather.service"],
        [
            "systemctl", "start", "--no-block",
            "limeos-extension-repair@weather.service",
        ],
    ]
    assert helper.cmd_agent_extension_repair_start(
        {"name": "weather", "source": "https://evil.test"}
    )["success"] is False


def test_helper_mattermost_repair_starts_only_the_fixed_unit():
    with (
        patch.object(
            helper,
            "cmd_agent_mattermost_status",
            return_value={"success": True, "installed": True, "state": "degraded"},
        ),
        patch.object(helper, "run_command", return_value={"returncode": 0}) as run,
    ):
        result = helper.cmd_agent_mattermost_repair_start({})

    assert result == {"success": True, "started": True}
    assert [call.args[0] for call in run.call_args_list] == [
        ["systemctl", "reset-failed", "limeos-mattermost-repair.service"],
        [
            "systemctl", "start", "--no-block",
            "limeos-mattermost-repair.service",
        ],
    ]


def test_helper_runs_repair_status_as_repository_owner_and_parses_only_json():
    result_payload = {
        "name": "weather",
        "repairable": True,
        "source": "not-returned-by-real-job",
    }
    with (
        patch.object(helper, "_agent_repo_dir", return_value="/opt/pi-health"),
        patch.object(helper, "_agent_dashboard_user", return_value="holly"),
        patch.object(helper.os.path, "isfile", return_value=True),
        patch.object(
            helper,
            "run_command",
            return_value={"returncode": 0, "stdout": json.dumps(result_payload)},
        ) as run,
    ):
        result = helper.cmd_agent_extension_status({"name": "weather"})

    assert result["success"] is True
    assert result["repairable"] is True
    assert run.call_args.args[0] == [
        "runuser",
        "-u",
        "holly",
        "--",
        "/opt/pi-health/.venv/bin/python",
        "-m",
        "agent_actions.repair_job",
        "extension-status",
        "--name",
        "weather",
    ]
    assert run.call_args.kwargs == {"timeout": 60, "cwd": "/opt/pi-health"}


def test_helper_auth_commands_validate_operation_fields():
    assert helper.cmd_agent_provider_auth_status({"operation_id": "x"})["success"] is False
    assert helper.cmd_agent_provider_auth_submit(
        {"operation_id": "x", "code": "ok", "path": "/tmp/evil"}
    )["success"] is False
    assert helper.cmd_agent_provider_auth_cancel({"operation_id": "x", "extra": True})[
        "success"
    ] is False


def test_helper_runs_claude_login_in_a_pseudo_terminal():
    command = helper._agent_auth_manager._command

    assert command[:5] == ["/usr/sbin/runuser", "-u", "lime-agent", "--pty", "--"]


def test_helper_restores_agent_paths_after_service_restart():
    commands = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        return {"returncode": 0, "stdout": "", "stderr": ""}

    with (
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(helper.os.path, "isdir", return_value=True),
    ):
        assert helper._restore_agent_runtime_ownership() is True

    assert ["chown", "-R", "lime-agent:lime-agent", "/var/lib/lime-agent"] in commands
    assert ["chown", "-R", "lime-agent:lime-agent", CLAUDE_CONFIG_DIR] in commands
    assert ["chown", "-R", "lime-agent:lime-agent", AGENT_STATE_DIR] in commands
    assert ["chmod", "0700", CLAUDE_CONFIG_DIR] in commands


def test_runtime_install_creates_fixed_identities_paths_and_units(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config").mkdir()
    (repo / "config" / "agent-policy.default.json").write_text("{}")
    (repo / "config" / "agent-action-policy.default.json").write_text("{}")
    (repo / "config" / "agent-actuator-policy.default.json").write_text("{}")
    (repo / "config" / "agents.default.json").write_text("{}")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").touch()
    commands = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        if argv[:2] == ["getent", "group"] and argv[2] in {"docker", "pihealth"}:
            return {"returncode": 0, "stdout": "exists", "stderr": ""}
        if argv[:2] == ["getent", "group"] or argv[:2] == ["getent", "passwd"]:
            return {"returncode": 2, "stdout": "", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    written = {}

    def fake_write(path, content, mode=0o644):
        written[path] = (content, mode)
        return {"success": True, "path": path}

    with (
        patch.object(helper, "PIHEALTH_REPO_DIR", str(repo)),
        patch.object(helper, "_write_managed_file", side_effect=fake_write),
        patch.object(helper, "_ensure_agent_file", return_value=True) as ensure_file,
        patch.object(
            helper, "_migrate_agent_action_policy", return_value={"success": True}
        ),
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(helper.shutil, "copytree"),
        patch.object(helper.shutil, "copy2") as copy2,
        patch.object(helper.os, "makedirs"),
        patch.object(helper.os.path, "isdir", return_value=True),
        patch.object(helper.os.path, "isfile", return_value=True),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(helper, "_secure_agent_stack_locks", return_value=True),
        patch.object(helper, "_secure_shared_agent_databases", return_value=True),
        patch.object(helper, "_sync_report_webhook_credential", return_value=True),
        patch.object(
            helper,
            "_sync_supervisor_delivery_projection",
            return_value={
                "success": True,
                "configured": True,
                "enabled": True,
            },
        ),
        patch.object(helper, "_check_supervisor_runtime", return_value=True),
        patch.object(helper, "_write_agent_release_marker", return_value=True),
    ):
        result = helper.cmd_agent_runtime_install({})

    assert result["success"] is True
    # The package module + manifest are deployed so the broker can serve packages.status.
    copied_sources = {call.args[0] for call in copy2.call_args_list}
    assert any(src.endswith("limeos_packages.py") for src in copied_sources)
    assert any(src.endswith("config/limeos-packages.json") for src in copied_sources)
    flat = [item for command in commands for item in command]
    assert "lime-agent" in flat and "limeops" in flat and "limeops-client" in flat
    assert "limeops-actuator" in flat and "limeops-action-worker" in flat
    assert "limeops-report" in flat
    assert "limeops-supervisor" in flat
    assert "limeops-action" in flat
    account_commands = [
        command
        for command in commands
        if any(tool in command for tool in ("/usr/sbin/groupadd", "/usr/sbin/useradd", "/usr/sbin/usermod"))
    ]
    assert account_commands
    assert all(command[0] == "systemd-run" for command in account_commands)
    assert "/etc/systemd/system/limeos-agent.service" in written
    assert "/etc/systemd/system/limeopsd.service" in written
    assert ACTION_BROKER_UNIT_PATH in written
    assert ACTION_WORKER_UNIT_PATH in written
    assert REPORT_SCHEDULER_UNIT_PATH in written
    assert SUPERVISOR_UNIT_PATH in written
    assert AGENT_REPAIR_UNIT_PATH in written
    assert EXTENSION_REPAIR_UNIT_PATH in written
    assert MATTERMOST_REPAIR_UNIT_PATH in written
    preserved_paths = {call.args[0] for call in ensure_file.call_args_list}
    assert preserved_paths == {
        "/etc/limeos/agent-policy.json",
        ACTION_POLICY_PATH,
        "/etc/limeos/agent-actuator-policy.json",
        "/etc/limeos/integrations/agents.json",
        "/etc/limeos/integrations/agents.env",
    }
    install_dirs = [command for command in commands if command[:2] == ["install", "-d"]]
    assert any(AGENT_STATE_DIR in command for command in install_dirs)
    assert not any(
        command[-1] == "/etc/limeos/integrations"
        for command in install_dirs
    )
    assert any(CLAUDE_CONFIG_DIR in command for command in install_dirs)
    assert any(LIMEOPS_STATE_DIR in command for command in install_dirs)
    assert any(ACTION_STATE_DIR in command for command in install_dirs)
    assert any(ACTION_STATE_DIR in command and "2770" in command for command in install_dirs)
    assert any(REPORT_SCHEDULER_STATE_DIR in command for command in install_dirs)
    assert any(REPORT_DELIVERY_CONFIG_DIR in command for command in install_dirs)
    assert any(SUPERVISOR_STATE_DIR in command for command in install_dirs)
    assert any(SUPERVISOR_CONFIG_DIR in command for command in install_dirs)
    assert any(STACK_LOCK_DIR in command and "2770" in command for command in install_dirs)
    assert not any(ACTION_SOCKET_DIR in command for command in install_dirs)
    assert ["chmod", "-R", "u=rwX,go=rX", AGENT_LIB_DIR] in commands
    assert ["systemctl", "restart", "limeopsd.service"] in commands
    assert ["systemctl", "restart", "limeops-actuatord.service"] in commands
    assert ["systemctl", "restart", "limeops-action-worker.service"] in commands
    assert ["systemctl", "restart", "limeops-report-scheduler.service"] in commands
    assert [
        "systemctl", "restart", "limeops-supervised-repair.service"
    ] in commands
    assert [
        f"{REPORT_SCHEDULER_VENV_DIR}/bin/pip",
        "install",
        "apscheduler>=3.10,<4",
        "requests>=2.31,<3",
    ] in commands
    assert [
        f"{SUPERVISOR_VENV_DIR}/bin/pip",
        "install",
        "apscheduler>=3.10,<4",
        "requests>=2.31,<3",
    ] in commands
    # psutil is guaranteed for the broker so system.status cannot fail on a fresh install.
    assert [
        "apt-get", "install", "-y", "python3-psutil", "python3-docker"
    ] in commands


def test_installed_runtime_can_import_action_broker_without_dashboard_source(tmp_path):
    repo = Path(__file__).parents[1]
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for package in AGENT_RUNTIME_PACKAGES:
        shutil.copytree(repo / package, runtime / package)
    for module in AGENT_RUNTIME_MODULES:
        shutil.copy2(repo / module, runtime / module)
    shutil.copy2(repo / "limeos_packages.py", runtime / "limeos_packages.py")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(runtime)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from agent_actions.server import _build_actuator; "
                "_build_actuator('policy.json', 'actions.sqlite3')"
            ),
        ],
        cwd=runtime,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_agent_repo_commit_runs_git_as_dashboard_owner():
    with (
        patch.object(helper, "_agent_dashboard_user", return_value="holly"),
        patch.object(
            helper,
            "_git_as",
            return_value={"returncode": 0, "stdout": "abc123\n"},
        ) as git_as,
    ):
        assert helper._agent_repo_commit("/home/holly/pi-health") == "abc123"

    git_as.assert_called_once_with(
        "holly", "/home/holly/pi-health", "rev-parse", "HEAD"
    )


def test_agent_release_marker_is_group_readable_for_isolated_services(
    tmp_path,
):
    with (
        patch.object(helper, "AGENT_LIB_DIR", str(tmp_path)),
        patch.object(helper, "_agent_repo_commit", return_value="a" * 40),
        patch.object(
            helper, "run_command", return_value={"returncode": 0}
        ) as run,
    ):
        assert helper._write_agent_release_marker("/repo") is True

    marker = tmp_path / ".release"
    assert marker.read_text(encoding="utf-8") == f'{"a" * 40}\n'
    assert stat.S_IMODE(marker.stat().st_mode) == 0o640
    run.assert_called_once_with(
        ["chown", "root:pihealth", str(marker)], timeout=30
    )


def test_supervisor_runtime_check_uses_installed_package_environment():
    with (
        patch.object(helper, "AGENT_LIB_DIR", "/usr/lib/fixed-agent"),
        patch.object(helper, "SUPERVISOR_VENV_DIR", "/var/lib/fixed-supervisor/venv"),
        patch.object(helper, "SUPERVISOR_STATE_DIR", "/var/lib/fixed-supervisor"),
        patch.object(
            helper, "run_command", return_value={"returncode": 0}
        ) as run,
    ):
        assert helper._check_supervisor_runtime() is True

    run.assert_called_once_with(
        [
            "runuser",
            "-u",
            "limeops-supervisor",
            "--",
            "env",
            "PYTHONPATH=/usr/lib/fixed-agent",
            "PYTHONDONTWRITEBYTECODE=1",
            "/var/lib/fixed-supervisor/venv/bin/python",
            "-m",
            "agent_supervision.runner",
            "--check",
        ],
        timeout=60,
        cwd="/var/lib/fixed-supervisor",
    )


def test_shared_stack_locks_reject_unexpected_entries(tmp_path):
    valid = tmp_path / "media.lock"
    unexpected = tmp_path / "unexpected"
    valid.touch()
    unexpected.touch()
    entries = [
        SimpleNamespace(name=valid.name, path=str(valid)),
        SimpleNamespace(name=unexpected.name, path=str(unexpected)),
    ]
    with (
        patch.object(helper, "STACK_LOCK_DIR", str(tmp_path)),
        patch.object(helper.os, "scandir", return_value=entries),
        patch.object(helper.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1000)),
        patch("grp.getgrnam", return_value=SimpleNamespace(gr_gid=1001)),
        patch.object(helper.os, "fchown") as fchown,
    ):
        assert helper._secure_agent_stack_locks("holly") is False
    fchown.assert_not_called()


def test_shared_stack_locks_are_group_writable(tmp_path):
    lock = tmp_path / "media.lock"
    lock.touch()
    with (
        patch.object(helper, "STACK_LOCK_DIR", str(tmp_path)),
        patch.object(helper.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=1000)),
        patch("grp.getgrnam", return_value=SimpleNamespace(gr_gid=1001)),
        patch.object(helper.os, "fchown") as fchown,
        patch.object(helper.os, "fchmod") as fchmod,
    ):
        assert helper._secure_agent_stack_locks("holly") is True
    descriptor = fchown.call_args.args[0]
    fchown.assert_called_once_with(descriptor, 1000, 1001)
    fchmod.assert_called_once_with(descriptor, 0o660)


def test_broker_state_requires_the_limeops_socket():
    socket_stat = type("SocketStat", (), {"st_mode": stat.S_IFSOCK | 0o660})()
    with (
        patch.object(helper, "_unit_state", return_value="active"),
        patch.object(helper.os, "stat", return_value=socket_stat),
    ):
        assert helper._agent_broker_state() == "active"

    with (
        patch.object(helper, "_unit_state", return_value="active"),
        patch.object(helper.os, "stat", side_effect=FileNotFoundError),
    ):
        assert helper._agent_broker_state() == "failed"


def test_runtime_start_rejects_an_active_broker_without_its_socket():
    with patch.object(
        helper,
        "cmd_agent_runtime_status",
        return_value={
            "configured": True,
            "claude_authenticated": True,
            "broker_active": "failed",
        },
    ):
        result = helper.cmd_agent_runtime_start({})

    assert result == {"success": False, "error": "LimeOps broker is unavailable"}


def test_runtime_start_checks_and_starts_agent_with_supervisor():
    commands = []

    def run(argv, **_kwargs):
        commands.append(argv)
        return {"returncode": 0}

    with (
        patch.object(
            helper,
            "cmd_agent_runtime_status",
            return_value={
                "configured": True,
                "claude_authenticated": True,
                "broker_active": "active",
            },
        ),
        patch.object(
            helper,
            "_sync_supervisor_delivery_projection",
            return_value={
                "success": True,
                "configured": True,
                "enabled": False,
            },
        ),
        patch.object(helper, "_check_supervisor_runtime", return_value=True),
        patch.object(helper, "_write_managed_file", return_value={"success": True}),
        patch.object(helper, "AGENT_CONFIG_PATH", "/fixed/agents.json"),
        patch.object(
            helper,
            "open",
            create=True,
        ) as opened,
        patch.object(helper, "run_command", side_effect=run),
    ):
        opened.return_value.__enter__.return_value.read.return_value = (
            '{"enabled": false}'
        )
        result = helper.cmd_agent_runtime_start({})

    assert result == {"success": True, "started": True}
    assert [
        "systemctl", "enable", "--now", "limeos-agent.service"
    ] in commands
    assert [
        "systemctl",
        "enable",
        "--now",
        "limeops-supervised-repair.service",
    ] in commands


def test_runtime_disable_stops_supervisor_and_cancels_queued_repairs():
    commands = []

    def run(argv, **_kwargs):
        commands.append(argv)
        return {"returncode": 0}

    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper, "_write_managed_file", return_value={"success": True}),
        patch.object(helper, "AGENT_CONFIG_PATH", "/fixed/agents.json"),
        patch.object(helper, "open", create=True) as opened,
        patch.object(
            helper, "_cancel_pending_supervised_actions", return_value=True
        ) as cancel,
        patch.object(helper, "run_command", side_effect=run),
    ):
        opened.return_value.__enter__.return_value.read.return_value = (
            '{"enabled": true}'
        )
        result = helper.cmd_agent_runtime_disable({})

    assert result == {"success": True, "disabled": True}
    assert commands[-2:] == [
        [
            "systemctl",
            "disable",
            "--now",
            "limeops-supervised-repair.service",
        ],
        ["systemctl", "disable", "--now", "limeos-agent.service"],
    ]
    cancel.assert_called_once_with()


def test_supervision_gate_uses_authoritative_agent_lifecycle_state():
    with patch.object(
        helper,
        "_read_agent_lifecycle_feature_state",
        return_value={"state": "enabled"},
    ):
        assert helper.cmd_agent_supervision_enabled({}) == {
            "success": True,
            "enabled": True,
        }
    with patch.object(
        helper,
        "_read_agent_lifecycle_feature_state",
        return_value={"state": "disabled"},
    ):
        assert helper.cmd_agent_supervision_enabled({}) == {
            "success": True,
            "enabled": False,
        }


def test_agent_repo_dir_resolves_helper_symlink(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "agent-policy.default.json").write_text("{}")
    helper_source = repo / "pihealth_helper.py"
    helper_source.touch()
    helper_link = tmp_path / "bin" / "pihealth_helper.py"
    helper_link.parent.mkdir()
    helper_link.symlink_to(helper_source)

    with (
        patch.object(helper, "PIHEALTH_REPO_DIR", None),
        patch.object(helper, "__file__", str(helper_link)),
    ):
        assert helper._agent_repo_dir() == str(repo)


def _claude_install_run(pinned, *, madison=None, hold_rc=0):
    """A run_command fake for provider-install: madison offers `<pinned>-1`, --version
    reports the upstream pin, everything else succeeds."""
    full = madison if madison is not None else f"{pinned}-1"

    def fake_run(argv, **_kwargs):
        if argv[:2] == ["apt-cache", "madison"]:
            body = f"claude-code | {full} | https://downloads.claude.ai ...\n" if full else ""
            return {"returncode": 0, "stdout": body, "stderr": ""}
        if argv[:2] == ["apt-mark", "hold"]:
            return {"returncode": hold_rc, "stderr": "cannot hold" if hold_rc else ""}
        return {"returncode": 0, "stdout": pinned, "stderr": ""}

    return fake_run


def test_provider_install_resolves_full_debian_version_and_holds():
    from limeos_packages import load_manifest

    pinned = next(spec.version for spec in load_manifest() if spec.name == "claude-code")
    commands = []

    def fake_run(argv, **kwargs):
        commands.append(argv)
        return _claude_install_run(pinned)(argv, **kwargs)

    with (
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(helper, "_install_claude_apt_repository", return_value={"success": True}),
    ):
        result = helper.cmd_agent_provider_install({})

    assert result["success"] is True and result["version"] == pinned
    # Installs the resolved full Debian version, with downgrade + held flags.
    assert [
        "apt-get", "install", "-y", "--allow-downgrades", "--allow-change-held-packages",
        f"claude-code={pinned}-1",
    ] in commands
    assert ["apt-mark", "hold", "claude-code"] in commands
    assert all("curl" not in command and "bash" not in command for command in commands)


def test_provider_install_fails_when_the_hold_cannot_be_set():
    from limeos_packages import load_manifest

    pinned = next(spec.version for spec in load_manifest() if spec.name == "claude-code")
    with (
        patch.object(helper, "run_command", side_effect=_claude_install_run(pinned, hold_rc=1)),
        patch.object(helper, "_install_claude_apt_repository", return_value={"success": True}),
    ):
        result = helper.cmd_agent_provider_install({})
    assert result["success"] is False and "hold" in result["error"].lower()


def test_provider_install_aborts_when_pin_missing_from_manifest():
    with (
        patch.object(helper, "run_command", return_value={"returncode": 0, "stdout": ""}),
        patch.object(helper, "_install_claude_apt_repository", return_value={"success": True}),
        patch("limeos_packages.load_manifest", return_value=[]),
    ):
        result = helper.cmd_agent_provider_install({})
    assert result["success"] is False and "pin" in result["error"].lower()


def test_provider_install_aborts_when_pinned_version_unavailable():
    from limeos_packages import load_manifest

    pinned = next(spec.version for spec in load_manifest() if spec.name == "claude-code")
    # Channel only offers a different upstream (rolled forward) -> no match -> abort.
    with (
        patch.object(helper, "run_command",
                     side_effect=_claude_install_run(pinned, madison="2.1.999-1")),
        patch.object(helper, "_install_claude_apt_repository", return_value={"success": True}),
    ):
        result = helper.cmd_agent_provider_install({})
    assert result["success"] is False and "not available" in result["error"].lower()


def test_claude_repository_tracks_compatible_signed_channel():
    assert helper.CLAUDE_APT_SOURCE == (
        "deb [signed-by=/etc/apt/keyrings/claude-code.asc] "
        "https://downloads.claude.ai/claude-code/apt/latest latest main\n"
    )


def test_claude_signing_key_verification_uses_private_temporary_gpg_home():
    commands = []

    class KeyResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b"armored signing key"

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        return {
            "returncode": 0,
            "stdout": f"fpr:::::::::{helper.CLAUDE_SIGNING_FINGERPRINT}:\n",
            "stderr": "",
        }

    with (
        patch.object(helper.urllib.request, "urlopen", return_value=KeyResponse()),
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(helper, "_write_managed_file", return_value={"success": True}),
    ):
        result = helper._install_claude_apt_repository()

    assert result["success"] is True
    gpg = next(command for command in commands if command[0] == "gpg")
    assert gpg[1] == "--homedir"
    gpg_home = Path(gpg[2])
    assert gpg_home.name.startswith("claude-code-gpg-")
    assert gpg[3:5] == ["--show-keys", "--with-colons"]
    assert Path(gpg[-1]).parent == gpg_home


def test_agent_secret_writer_is_fixed_and_mode_0640(tmp_path):
    target = tmp_path / "agents.env"
    with (
        patch.object(helper, "AGENT_ENV_PATH", str(target)),
        patch.object(
            helper, "run_command", return_value={"returncode": 0, "stdout": "", "stderr": ""}
        ),
    ):
        result = helper.write_agent_bot_secret("safe-token-value")
    assert result["success"] is True
    assert target.read_text() == "MATTERMOST_BOT_TOKEN=safe-token-value\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert helper.write_agent_bot_secret("bad\nINJECT=yes")["success"] is False


def test_runtime_repair_preserves_existing_agent_configuration(tmp_path):
    path = tmp_path / "agents.json"
    path.write_text('{"enabled":true}')
    with (
        patch.object(helper, "run_command", return_value={"returncode": 0}),
        patch.object(helper, "_write_managed_file") as write_file,
    ):
        assert helper._ensure_agent_file(str(path), "defaults", 0o640, "root:limeops")
    assert path.read_text() == '{"enabled":true}'
    write_file.assert_not_called()


def test_action_policy_migration_adds_disabled_operations_and_preserves_choices(
    tmp_path,
):
    default = json.loads(
        Path("config/agent-action-policy.default.json").read_text()
    )
    current = json.loads(json.dumps(default))
    current["kill_switch"] = False
    current["operations"].pop("integration.repair")
    current["operations"]["container.restart"] = {
        "enabled": True,
        "approvers": ["local:admin"],
        "targets": {
            "jellyfin": {
                "interactive": "approval",
                "scheduled": "observe",
                "event": "observe",
            }
        },
    }
    target = tmp_path / "agent-action-policy.json"
    target.write_text(json.dumps(current))
    written = {}
    with (
        patch.object(helper, "ACTION_POLICY_PATH", str(target)),
        patch.object(helper, "PIHEALTH_REPO_DIR", str(Path.cwd())),
        patch.object(
            helper,
            "_write_managed_file",
            side_effect=lambda path, content, mode: written.update(
                path=path, content=content, mode=mode
            )
            or {"success": True},
        ),
        patch.object(helper, "run_command", return_value={"returncode": 0}),
    ):
        result = helper._migrate_agent_action_policy()

    migrated = json.loads(written["content"])
    assert result["added_operations"] == ["integration.repair"]
    assert migrated["kill_switch"] is False
    assert migrated["operations"]["container.restart"] == current["operations"][
        "container.restart"
    ]
    assert migrated["operations"]["integration.repair"] == {
        "enabled": False,
        "approvers": [],
        "targets": {},
    }


def test_agent_configure_validates_both_settings_and_fixed_policy(tmp_path):
    repo = Path(helper._agent_repo_dir())
    settings = json.loads((repo / "config/agents.default.json").read_text())
    settings["enabled"] = True
    settings["mattermost"].update(
        team_id="team-1", channel_id="channel-1", bot_token_id="token-1"
    )
    policy = json.loads((repo / "config/agent-policy.default.json").read_text())
    written = []
    with (
        patch.object(
            helper,
            "_write_managed_file",
            side_effect=lambda path, content, mode: written.append((path, content, mode))
            or {"success": True},
        ),
        patch.object(helper, "run_command", return_value={"returncode": 0}),
        patch.object(
            helper,
            "_sync_supervisor_delivery_projection",
            return_value={
                "success": True,
                "configured": True,
                "enabled": True,
            },
        ),
    ):
        result = helper.cmd_agent_configure({"settings": settings, "policy": policy})
    assert result == {"success": True, "configured": True}
    assert {item[0] for item in written} == {
        "/etc/limeos/agent-policy.json",
        "/etc/limeos/integrations/agents.json",
    }
    policy["operations"]["shell.execute"] = {"enabled": True}
    assert helper.cmd_agent_configure({"settings": settings, "policy": policy})[
        "success"
    ] is False


def test_action_policy_writer_is_fixed_validated_and_canary_gated(tmp_path):
    policy = json.loads(
        Path("config/agent-action-policy.default.json").read_text()
    )
    policy["kill_switch"] = False
    policy["operations"]["container.restart"] = {
        "enabled": True,
        "approvers": ["local:admin"],
        "targets": {
            "jellyfin": {
                "interactive": "approval",
                "scheduled": "observe",
                "event": "observe",
            }
        },
    }
    target = tmp_path / "agent-action-policy.json"
    action_state = tmp_path / "agent-actions"
    written = {}
    with (
        patch.object(helper, "ACTION_POLICY_PATH", str(target)),
        patch.object(helper, "ACTION_STATE_DIR", str(action_state)),
        patch.object(
            helper,
            "_write_managed_file",
            side_effect=lambda path, content, mode: written.update(
                path=path, content=content, mode=mode
            )
            or {"success": True},
        ),
        patch.object(helper, "run_command", return_value={"returncode": 0}) as run,
    ):
        result = helper.cmd_agent_action_policy_write({"policy": policy})
    assert result["success"] is True
    assert written["path"] == str(target) and written["mode"] == 0o640
    run.assert_called_once_with(["chown", "root:pihealth", str(target)])

    automatic = json.loads(json.dumps(policy))
    automatic["operations"]["container.restart"]["targets"]["jellyfin"][
        "interactive"
    ] = "autonomous"
    with patch.object(helper, "ACTION_STATE_DIR", str(action_state)):
        assert helper.cmd_agent_action_policy_write({"policy": automatic}) == {
            "success": False,
            "error": "Action policy is not authorised by the repair canary gate",
        }

    now = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
    ledger = ActionLedger(action_state / "actions.sqlite3")
    source = NewAction(
        action_id="action-1",
        idempotency_key="canary:action-1",
        operation="container.restart",
        capability_version="1",
        target="jellyfin",
        risk="R1",
        trigger="interactive",
        authority_mode="approval",
        params={"name": "jellyfin"},
        evidence_ids=["audit-1"],
        payload_hash="a" * 64,
        reason="Jellyfin remained unhealthy after repeated checks.",
        impact="Restart container jellyfin",
        precondition_hash="b" * 64,
        actor_type="mattermost",
        actor_id="user-1",
        actor_username="marc",
        state=ActionState.AWAITING_APPROVAL,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=15)).isoformat(),
    )
    ledger.create(source)
    ledger.approve(
        "action-1",
        payload_hash=source.payload_hash,
        approver_type="mattermost",
        approver_id="user-1",
        approver_username="marc",
        approved_at=now.isoformat(),
    )
    ledger.claim_execution(
        "action-1",
        payload_hash=source.payload_hash,
        approval_required=True,
        claimed_at=now.isoformat(),
    )
    ledger.begin_verification("action-1")
    ledger.finish_execution(
        "action-1",
        state=ActionState.SUCCEEDED,
        terminal_code="verified",
    )
    ledger.record_event(
        "action-1",
        phase="succeeded",
        created_at=now.isoformat(),
        details={"action_audit_id": "audit-1", "after": {"status": "running"}},
    )
    ledger.attest_canary(
        attestation_id="canary-1",
        source_action_id="action-1",
        operation="container.restart",
        target="jellyfin",
        capability_version="1",
        risk="R1",
        release_commit="a" * 40,
        attested_by_type="local",
        attested_by_id="admin",
        attested_by_username="admin",
        attested_at=now.isoformat(),
    )
    supervised = json.loads(json.dumps(policy))
    supervised["operations"]["container.restart"]["targets"]["jellyfin"][
        "scheduled"
    ] = "supervised"
    agent_lib = tmp_path / "agent-lib"
    agent_lib.mkdir()
    (agent_lib / ".release").write_text("a" * 40 + "\n")
    (agent_lib / ".release").chmod(0o644)
    with (
        patch.object(helper, "ACTION_POLICY_PATH", str(target)),
        patch.object(helper, "ACTION_STATE_DIR", str(action_state)),
        patch.object(helper, "AGENT_LIB_DIR", str(agent_lib)),
        patch.object(helper, "_write_managed_file", return_value={"success": True}),
        patch.object(helper, "run_command", return_value={"returncode": 0}),
    ):
        assert helper.cmd_agent_action_policy_write({"policy": supervised})[
            "success"
        ] is True

    unknown = json.loads(json.dumps(policy))
    unknown["operations"]["shell.execute"] = {"enabled": False, "approvers": [], "targets": {}}
    assert helper.cmd_agent_action_policy_write({"policy": unknown})["success"] is False


def test_agent_usage_and_audit_reads_are_bounded_and_field_allowlisted(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "usage-counters.json").write_text(
        json.dumps({"total_turns": 2, "total_invocations": 3, "secret": "NO"})
    )
    (state / "usage-records.jsonl").write_text(
        json.dumps({"at": "now", "outcome": "ok", "secret": "NO"}) + "\n"
    )
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        json.dumps({"operation": "system.status", "audit_id": "a1", "params": "NO"})
        + "\n"
    )
    with (
        patch.object(helper, "AGENT_STATE_DIR", str(state)),
        patch.object(helper, "LIMEOPS_AUDIT_PATH", str(audit)),
    ):
        usage = helper.cmd_agent_usage_read({"limit": 10})
        records = helper.cmd_agent_audit_read({"limit": 10})
    assert usage["totals"]["total_turns"] == 2
    assert usage["records"] == [{"at": "now", "outcome": "ok"}]
    assert records["records"] == [{"audit_id": "a1", "operation": "system.status"}]
    assert "NO" not in json.dumps({"usage": usage, "audit": records})


def test_agent_bot_secret_command_accepts_only_fixed_token_field():
    with patch.object(helper, "write_agent_bot_secret", return_value={"success": True}) as writer:
        assert helper.cmd_agent_bot_secret_write({"token": "abc"})["success"] is True
    writer.assert_called_once_with("abc")
    assert helper.cmd_agent_bot_secret_write({"token": "abc", "path": "/tmp/x"})[
        "success"
    ] is False


def test_update_agent_step_skips_when_agent_not_installed():
    with patch.object(helper.os.path, "exists", return_value=False):
        result = helper._pihealth_update_agent(ctx={})
    assert result["success"] is True and result["skipped"] is True


def test_policy_migration_adds_new_operations_and_preserves_resources(tmp_path):
    # Deployed policy predates packages.status and carries host-specific resources.
    policy_path = tmp_path / "agent-policy.json"
    policy_path.write_text(json.dumps({
        "schema_version": "1",
        "defaults": {"timeout_seconds": 30, "max_output_bytes": 262144},
        "operations": {
            "context": {"enabled": True},
            "container.status": {"enabled": True, "resources": ["jellyfin", "sonarr"]},
        },
    }))
    written = {}

    def fake_write(path, content, mode=0o644):
        written[path] = content
        return {"success": True, "path": path}

    with (
        patch.object(helper, "AGENT_POLICY_PATH", str(policy_path)),
        patch.object(helper, "_agent_repo_dir", return_value="."),
        patch.object(helper, "_write_managed_file", side_effect=fake_write),
        patch.object(helper, "run_command", return_value={"returncode": 0}),
    ):
        result = helper._migrate_agent_policy()

    assert result["success"] is True
    assert "packages.status" in result["added_operations"]
    merged = json.loads(written[str(policy_path)])
    # New op added...
    assert "packages.status" in merged["operations"]
    # ...and the host resource allowlist preserved.
    assert merged["operations"]["container.status"]["resources"] == ["jellyfin", "sonarr"]


def test_policy_migration_skips_when_not_installed(tmp_path):
    with patch.object(helper, "AGENT_POLICY_PATH", str(tmp_path / "absent.json")):
        assert helper._migrate_agent_policy()["skipped"] is True


def test_update_agent_step_reports_reconcile_failure():
    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(helper, "_migrate_agent_policy", return_value={"success": True}),
        patch.object(helper, "cmd_agent_runtime_install", return_value={"success": True}),
        patch.object(helper, "cmd_packages_reconcile",
                     return_value={"success": False, "failed": ["x"], "drift": ["x"]}),
        patch.object(helper, "run_command", return_value={"returncode": 0}),
    ):
        result = helper._pihealth_update_agent(ctx={})
    assert result["success"] is False and result["failed"] == ["x"]


def test_update_agent_step_reports_restart_failure():
    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(helper, "_migrate_agent_policy", return_value={"success": True}),
        patch.object(helper, "cmd_agent_runtime_install", return_value={"success": True}),
        patch.object(helper, "cmd_packages_reconcile", return_value={"success": True}),
        patch.object(helper, "run_command", return_value={"returncode": 1}),
    ):
        result = helper._pihealth_update_agent(ctx={})
    assert result["success"] is False and "restart" in result["error"].lower()


def test_converge_if_stale_skips_when_up_to_date(tmp_path):
    (tmp_path / ".release").write_text("abc123\n")
    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper.os.path, "isfile", return_value=True),
        patch.object(helper, "AGENT_LIB_DIR", str(tmp_path)),
        patch.object(helper, "_agent_repo_dir", return_value="/repo"),
        patch.object(helper, "_agent_repo_commit", return_value="abc123"),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(
            helper,
            "_unit_state",
            side_effect=lambda _unit, action: (
                "enabled" if action == "is-enabled" else "active"
            ),
        ),
    ):
        result = helper.cmd_agent_converge_if_stale({})
    assert result["skipped"] is True and "current" in result["reason"]


def test_converge_if_stale_repairs_current_release_without_supervisor(
    tmp_path,
):
    (tmp_path / ".release").write_text("abc123\n")

    def installed(path):
        return path != helper.SUPERVISOR_UNIT_PATH

    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper.os.path, "isfile", side_effect=installed),
        patch.object(helper, "AGENT_LIB_DIR", str(tmp_path)),
        patch.object(helper, "_agent_repo_dir", return_value="/repo"),
        patch.object(helper, "_agent_repo_commit", return_value="abc123"),
        patch.object(
            helper,
            "_pihealth_update_agent",
            return_value={"success": True, "refreshed": True},
        ) as step,
    ):
        result = helper.cmd_agent_converge_if_stale({})

    assert result["refreshed"] is True
    step.assert_called_once_with(ctx={})


def test_converge_if_stale_repairs_enabled_but_inactive_supervisor(
    tmp_path,
):
    (tmp_path / ".release").write_text("abc123\n")

    def unit_state(_unit, action):
        return "disabled" if action == "is-enabled" else "inactive"

    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper.os.path, "isfile", return_value=True),
        patch.object(helper, "AGENT_LIB_DIR", str(tmp_path)),
        patch.object(helper, "_agent_repo_dir", return_value="/repo"),
        patch.object(helper, "_agent_repo_commit", return_value="abc123"),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"state": "enabled", "reconcile_allowed": True},
        ),
        patch.object(helper, "_unit_state", side_effect=unit_state),
        patch.object(
            helper,
            "_pihealth_update_agent",
            return_value={"success": True, "refreshed": True},
        ) as step,
    ):
        result = helper.cmd_agent_converge_if_stale({})

    assert result["refreshed"] is True
    step.assert_called_once_with(ctx={})


def test_converge_if_stale_runs_agent_step_when_behind(tmp_path):
    (tmp_path / ".release").write_text("old000\n")
    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper, "AGENT_LIB_DIR", str(tmp_path)),
        patch.object(helper, "_agent_repo_dir", return_value="/repo"),
        patch.object(helper, "_agent_repo_commit", return_value="new999"),
        patch.object(helper, "_pihealth_update_agent",
                     return_value={"success": True, "refreshed": True}) as step,
    ):
        result = helper.cmd_agent_converge_if_stale({})
    assert result["refreshed"] is True
    step.assert_called_once()


def test_converge_if_stale_skips_when_agent_not_installed():
    with patch.object(helper.os.path, "exists", return_value=False):
        assert helper.cmd_agent_converge_if_stale({})["skipped"] is True


def test_converge_if_stale_skips_when_any_lifecycle_tombstone_exists(tmp_path):
    lifecycle = tmp_path / "agents-lifecycle.json"
    lifecycle.write_text("{corrupt", encoding="utf-8")
    with patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle)):
        result = helper.cmd_agent_converge_if_stale({})
    assert result == {
        "success": True,
        "skipped": True,
        "reason": "agent lifecycle state blocks convergence",
    }


def test_converge_if_stale_rejects_parameters():
    assert helper.cmd_agent_converge_if_stale({"force": True})["success"] is False


def test_helper_pull_change_triggers_agent_convergence():
    from pihealth_update_service import _AGENT_UPDATE_PREFIXES

    assert any("pihealth_helper.py".startswith(p) for p in _AGENT_UPDATE_PREFIXES)
