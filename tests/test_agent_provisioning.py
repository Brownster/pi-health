"""AA-004 fixed helper provisioning and systemd sandbox contracts."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import patch

import pihealth_helper as helper

from agent_provider.claude import ClaudeCodeConfig
from agent_provider.provisioning import (
    AGENT_ENV_PATH,
    AGENT_LIB_DIR,
    AGENT_STATE_DIR,
    CLAUDE_CONFIG_DIR,
    LIMEOPS_STATE_DIR,
    render_agent_unit,
    render_limeops_unit,
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
        "InaccessiblePaths=/root /opt/pi-health /run/pihealth /var/run/docker.sock "
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


def test_helper_agent_commands_reject_all_caller_controlled_parameters():
    for command in (
        helper.cmd_agent_runtime_install,
        helper.cmd_agent_runtime_status,
        helper.cmd_agent_runtime_disable,
        helper.cmd_agent_provider_install,
    ):
        assert command({"path": "/tmp/evil"}) == {
            "success": False,
            "error": "Agent operation does not accept parameters",
        }


def test_helper_exposes_only_fixed_agent_operations():
    assert {
        "agent_runtime_install",
        "agent_runtime_status",
        "agent_runtime_disable",
        "agent_provider_install",
        "agent_provider_auth_start",
        "agent_provider_auth_status",
        "agent_provider_auth_submit",
        "agent_provider_auth_cancel",
        "agent_bot_secret_write",
        "agent_configure",
        "agent_runtime_start",
        "agent_usage_read",
        "agent_audit_read",
        "agent_delivery_test",
    } <= helper.COMMANDS.keys()
    assert "agent_write_unit" not in helper.COMMANDS
    assert "agent_run_command" not in helper.COMMANDS


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
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(helper.shutil, "copytree"),
        patch.object(helper.os.path, "isdir", return_value=True),
        patch.object(helper.os.path, "isfile", return_value=True),
    ):
        result = helper.cmd_agent_runtime_install({})

    assert result["success"] is True
    flat = [item for command in commands for item in command]
    assert "lime-agent" in flat and "limeops" in flat and "limeops-client" in flat
    account_commands = [
        command
        for command in commands
        if any(tool in command for tool in ("/usr/sbin/groupadd", "/usr/sbin/useradd", "/usr/sbin/usermod"))
    ]
    assert account_commands
    assert all(command[0] == "systemd-run" for command in account_commands)
    assert "/etc/systemd/system/limeos-agent.service" in written
    assert "/etc/systemd/system/limeopsd.service" in written
    preserved_paths = {call.args[0] for call in ensure_file.call_args_list}
    assert preserved_paths == {
        "/etc/limeos/agent-policy.json",
        "/etc/limeos/integrations/agents.json",
        "/etc/limeos/integrations/agents.env",
    }
    install_dirs = [command for command in commands if command[:2] == ["install", "-d"]]
    assert any(AGENT_STATE_DIR in command for command in install_dirs)
    assert not any("/etc/limeos/integrations" in command for command in install_dirs)
    assert any(CLAUDE_CONFIG_DIR in command for command in install_dirs)
    assert any(LIMEOPS_STATE_DIR in command for command in install_dirs)
    assert ["chmod", "-R", "u=rwX,go=rX", AGENT_LIB_DIR] in commands


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


def test_provider_install_uses_only_signed_apt_repository_commands():
    commands = []

    def fake_run(argv, **_kwargs):
        commands.append(argv)
        return {"returncode": 0, "stdout": "2.1.205", "stderr": ""}

    with (
        patch.object(helper, "run_command", side_effect=fake_run),
        patch.object(
            helper, "_install_claude_apt_repository", return_value={"success": True}
        ),
    ):
        result = helper.cmd_agent_provider_install({})

    assert result["success"] is True
    assert any(command[:2] == ["apt-get", "update"] for command in commands)
    assert any(command[:4] == ["apt-get", "install", "-y", "claude-code"] for command in commands)
    assert all("curl" not in command and "bash" not in command for command in commands)


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
