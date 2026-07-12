"""AA-004 fixed helper provisioning and systemd sandbox contracts."""

from __future__ import annotations

import stat
from unittest.mock import patch

import pihealth_helper as helper

from agent_provider.provisioning import (
    AGENT_ENV_PATH,
    AGENT_LIB_DIR,
    AGENT_STATE_DIR,
    CLAUDE_CONFIG_DIR,
    render_agent_unit,
    render_limeops_unit,
)


def test_agent_unit_has_no_privileged_sockets_or_source_access():
    unit = render_agent_unit("/opt/pi-health", "/opt/pi-health/.venv/bin/python")
    assert "User=lime-agent" in unit
    assert "Group=lime-agent" in unit
    assert "SupplementaryGroups=limeops-client" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
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


def test_limeops_unit_owns_privileged_read_boundary():
    unit = render_limeops_unit("/opt/pi-health", "/opt/pi-health/.venv/bin/python")
    assert "User=limeops" in unit
    assert "Group=limeops" in unit
    assert "SupplementaryGroups=docker pihealth" in unit
    assert "UMask=0007" in unit
    assert "ProtectSystem=strict" in unit
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
    assert any(CLAUDE_CONFIG_DIR in command for command in install_dirs)


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
