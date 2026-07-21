"""IL-003 fixed agent cleanup and feature-scoped package ownership."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pihealth_helper as helper
from limeos_packages import load_manifest


def _run_ok(argv, **_kwargs):
    if argv[:3] in (
        ["systemctl", "is-active", "--quiet"],
        ["systemctl", "is-enabled", "--quiet"],
    ):
        return {"returncode": 1, "stdout": ""}
    if argv[:2] == ["apt-mark", "showhold"]:
        return {"returncode": 0, "stdout": "claude-code\n"}
    if argv[:2] == ["dpkg-query", "-W"]:
        return {"returncode": 0, "stdout": "install ok installed"}
    return {"returncode": 0, "stdout": ""}


def _runtime_paths(tmp_path: Path):
    units = (
        ("limeos-agent.service", str(tmp_path / "limeos-agent.service")),
        ("limeopsd.service", str(tmp_path / "limeopsd.service")),
    )
    files = tuple(str(tmp_path / name) for name in ("agents.json", "agents.env", "policy.json"))
    directories = tuple(str(tmp_path / name) for name in ("lib", "state", "claude", "venv", "limeops"))
    for _unit, path in units:
        Path(path).write_text("unit", encoding="utf-8")
    for path in files:
        Path(path).write_text("config", encoding="utf-8")
    for path in directories:
        Path(path).mkdir()
        (Path(path) / "owned").write_text("state", encoding="utf-8")
    return units, files, directories


def _lifecycle(*, phase: str, target_state: str):
    return {
        "schema_version": "1",
        "integration": "agents",
        "operation_id": "op-1",
        "action": "uninstall" if target_state == "not_installed" else "disable",
        "phase": phase,
        "target_state": target_state,
        "started_at": "2026-07-20T12:00:00+00:00",
        "updated_at": "2026-07-20T12:00:01+00:00",
        "completed_steps": [],
        "retained_data": False,
        "remove_claude_code": target_state == "not_installed",
        "failure": None,
        "warning_codes": [],
    }


def test_agent_uninstall_requires_exactly_one_boolean():
    for params in ({}, {"remove_claude_code": "yes"}, {"remove_claude_code": True, "path": "/"}):
        result = helper.cmd_agent_runtime_uninstall(params)
        assert result["success"] is False
        assert "boolean" in result["error"]


def test_agent_uninstall_removes_only_fixed_owned_paths_and_is_idempotent(tmp_path):
    units, files, directories = _runtime_paths(tmp_path)
    source = tmp_path / "claude-code.list"
    key = tmp_path / "claude-code.asc"
    source.write_text("source", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    audit = tmp_path / "agent-audit.jsonl"
    mattermost = tmp_path / "mattermost-data"
    audit.write_text("audit", encoding="utf-8")
    mattermost.mkdir()

    with (
        patch.object(helper, "AGENT_CLEANUP_UNITS", units),
        patch.object(helper, "AGENT_CLEANUP_FILES", files),
        patch.object(helper, "AGENT_CLEANUP_DIRECTORIES", directories),
        patch.object(helper, "CLAUDE_APT_SOURCE_PATH", str(source)),
        patch.object(helper, "CLAUDE_APT_KEY_PATH", str(key)),
        patch.object(helper, "run_command", side_effect=_run_ok) as run,
    ):
        first = helper.cmd_agent_runtime_uninstall({"remove_claude_code": True})
        second = helper.cmd_agent_runtime_uninstall({"remove_claude_code": True})

    assert first["success"] is True and second["success"] is True
    assert all(not Path(path).exists() for _unit, path in units)
    assert all(not Path(path).exists() for path in (*files, *directories, str(source), str(key)))
    assert audit.read_text(encoding="utf-8") == "audit"
    assert mattermost.is_dir()
    assert not any(call.args[0][0] in {"userdel", "groupdel"} for call in run.call_args_list)
    assert [step["name"] for step in first["steps"]] == [
        "stop_services",
        "remove_units",
        "remove_runtime",
        "remove_claude_hold",
        "remove_claude_package",
        "remove_claude_source",
        "remove_claude_key",
    ]
    repeated = {step["name"]: step for step in second["steps"]}
    for name in ("stop_services", "remove_units", "remove_runtime", "remove_claude_source", "remove_claude_key"):
        assert repeated[name]["changed"] is False


def test_agent_uninstall_retains_every_claude_owned_artifact_when_requested(tmp_path):
    units, files, directories = _runtime_paths(tmp_path)
    with (
        patch.object(helper, "AGENT_CLEANUP_UNITS", units),
        patch.object(helper, "AGENT_CLEANUP_FILES", files),
        patch.object(helper, "AGENT_CLEANUP_DIRECTORIES", directories),
        patch.object(helper, "_remove_claude_hold") as hold,
        patch.object(helper, "_remove_claude_package") as package,
        patch.object(helper, "run_command", side_effect=_run_ok),
    ):
        result = helper.cmd_agent_runtime_uninstall({"remove_claude_code": False})

    assert result["success"] is True
    assert result["steps"][-1] == {
        "name": "retain_claude_code",
        "success": True,
        "changed": False,
        "skipped": True,
    }
    hold.assert_not_called()
    package.assert_not_called()


def test_agent_uninstall_reports_failed_step_and_retry_resumes_safely():
    with (
        patch.object(helper, "_stop_agent_cleanup_units", return_value=False),
        patch.object(helper, "_remove_agent_cleanup_units", return_value=False),
        patch.object(helper, "_remove_agent_runtime_paths", side_effect=[OSError(), False]),
        patch.object(helper, "_remove_claude_hold", return_value=False),
        patch.object(helper, "_remove_claude_package", return_value=False),
        patch.object(helper, "_remove_agent_owned_path", return_value=False),
    ):
        failed = helper.cmd_agent_runtime_uninstall({"remove_claude_code": True})
        retried = helper.cmd_agent_runtime_uninstall({"remove_claude_code": True})

    assert failed["success"] is False and failed["failed_step"] == "remove_runtime"
    assert retried["success"] is True


def test_agent_cleanup_rejects_substituted_directory_symlink(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "owned"
    link.symlink_to(target, target_is_directory=True)

    try:
        helper._remove_agent_owned_path(str(link))
    except OSError:
        pass
    else:
        raise AssertionError("cleanup followed an unsafe symlink")
    assert target.is_dir() and link.is_symlink()


def test_feature_state_excludes_completed_uninstall_and_all_incomplete_states(tmp_path):
    lifecycle = tmp_path / "agents-lifecycle.json"
    lifecycle.write_text(
        json.dumps(_lifecycle(phase="complete", target_state="not_installed")),
        encoding="utf-8",
    )
    with patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle)):
        assert helper._read_agent_lifecycle_feature_state()["reconcile_allowed"] is False

    lifecycle.write_text(
        json.dumps(_lifecycle(phase="running", target_state="not_installed")),
        encoding="utf-8",
    )
    with patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle)):
        state = helper._read_agent_lifecycle_feature_state()
    assert state["state"] == "cleanup_required" and state["reconcile_allowed"] is False


def test_feature_state_allows_disabled_install_and_legacy_runtime(tmp_path):
    lifecycle = tmp_path / "agents-lifecycle.json"
    lifecycle.write_text(
        json.dumps(_lifecycle(phase="complete", target_state="disabled")),
        encoding="utf-8",
    )
    with patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle)):
        assert helper._read_agent_lifecycle_feature_state()["reconcile_allowed"] is True

    lifecycle.unlink()
    agent_unit = tmp_path / "agent.service"
    broker_unit = tmp_path / "broker.service"
    config = tmp_path / "agents.json"
    agent_unit.write_text("unit", encoding="utf-8")
    broker_unit.write_text("unit", encoding="utf-8")
    config.write_text('{"enabled": true}', encoding="utf-8")
    with (
        patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle)),
        patch.object(helper, "AGENT_UNIT_PATH", str(agent_unit)),
        patch.object(helper, "LIMEOPS_UNIT_PATH", str(broker_unit)),
        patch.object(helper, "AGENT_CONFIG_PATH", str(config)),
        patch.object(helper, "ACTION_BROKER_UNIT_PATH", str(tmp_path / "no-broker")),
        patch.object(helper, "ACTION_WORKER_UNIT_PATH", str(tmp_path / "no-worker")),
        patch.object(helper, "ACTION_POLICY_PATH", str(tmp_path / "no-action-policy")),
        patch.object(
            helper,
            "ACTION_BROKER_POLICY_PATH",
            str(tmp_path / "no-actuator-policy"),
        ),
    ):
        state = helper._read_agent_lifecycle_feature_state()
    assert state["state"] == "enabled" and state["reconcile_allowed"] is True


def test_feature_state_rejects_partial_action_runtime(tmp_path):
    paths = {
        "AGENT_UNIT_PATH": tmp_path / "agent.service",
        "LIMEOPS_UNIT_PATH": tmp_path / "broker.service",
        "AGENT_CONFIG_PATH": tmp_path / "agents.json",
        "ACTION_BROKER_UNIT_PATH": tmp_path / "action-broker.service",
        "ACTION_WORKER_UNIT_PATH": tmp_path / "missing-worker.service",
        "ACTION_POLICY_PATH": tmp_path / "missing-action-policy.json",
        "ACTION_BROKER_POLICY_PATH": tmp_path / "missing-actuator-policy.json",
    }
    paths["AGENT_UNIT_PATH"].write_text("unit")
    paths["LIMEOPS_UNIT_PATH"].write_text("unit")
    paths["AGENT_CONFIG_PATH"].write_text('{"enabled": true}')
    paths["ACTION_BROKER_UNIT_PATH"].write_text("partial")
    lifecycle = tmp_path / "no-lifecycle.json"
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(helper, "AGENT_LIFECYCLE_TOMBSTONE", str(lifecycle))
        )
        for name, path in paths.items():
            stack.enter_context(patch.object(helper, name, str(path)))
        state = helper._read_agent_lifecycle_feature_state()
    assert state == {
        "feature": "ai_agents",
        "state": "cleanup_required",
        "reconcile_allowed": False,
    }


def test_package_reconcile_never_queries_retained_or_removed_claude():
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        return {"returncode": 1, "stdout": ""}

    with (
        patch.object(helper, "run_command", side_effect=run),
        patch.object(
            helper,
            "_read_agent_lifecycle_feature_state",
            return_value={"feature": "ai_agents", "state": "not_installed", "reconcile_allowed": False},
        ),
    ):
        result = helper.cmd_packages_reconcile({"mode": "apply"})

    assert result["success"] is False  # baseline installs were attempted and failed
    assert all("claude-code" not in call for call in calls)


def test_nightly_and_pending_paths_exclude_uninstalled_claude():
    feature = {"feature": "ai_agents", "state": "not_installed", "reconcile_allowed": False}
    reported_specs = []

    def capture_updates(specs):
        reported_specs.extend(specs)
        return {"skipped": True}

    with (
        patch("limeos_packages.load_manifest", return_value=load_manifest()),
        patch.object(helper, "_read_agent_lifecycle_feature_state", return_value=feature),
        patch.object(helper.shutil, "which", return_value=None),
        patch.object(helper, "run_command", return_value={"returncode": 0, "stdout": ""}) as run,
        patch.object(helper, "cmd_packages_reconcile", return_value={"success": True}),
        patch.object(helper, "_post_package_updates", side_effect=capture_updates),
    ):
        nightly = helper.cmd_packages_nightly_reconcile({})
        pending = helper.cmd_packages_pending({})

    assert nightly["success"] is True and pending["success"] is True
    assert all(spec.name != "claude-code" for spec in reported_specs)
    assert all("claude-code" not in call.args[0] for call in run.call_args_list)
    assert all(item["name"] != "claude-code" for item in pending["pending"])


def test_self_update_does_not_reinstall_runtime_during_agent_cleanup():
    feature = {"feature": "ai_agents", "state": "cleanup_required", "reconcile_allowed": False}
    with (
        patch.object(helper.os.path, "exists", return_value=True),
        patch.object(helper, "_read_agent_lifecycle_feature_state", return_value=feature),
        patch.object(helper, "cmd_agent_runtime_install") as install,
    ):
        result = helper._pihealth_update_agent(ctx={})

    assert result == {
        "success": True,
        "skipped": True,
        "reason": "agent lifecycle state blocks update convergence",
    }
    install.assert_not_called()
