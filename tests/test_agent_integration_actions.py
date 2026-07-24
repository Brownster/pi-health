"""Approval-bound AI Agents integration repair contracts."""

from types import SimpleNamespace

import pytest

from agent_actions.actuator import build_integration_executors
from agent_actions.capability import AuthorityMode, CapabilityError, RiskClass
from agent_actions.defaults import build_repair_registry, safe_integration_precondition
from agent_actions.integrations import (
    AGENT_RUNTIME_UNITS,
    MATTERMOST_REPAIR_UNIT,
    agent_integration_status,
    agent_repair_job_status,
    mattermost_repair_job_status,
    safe_agent_runtime_health,
)


def _integration_status(*, agent_enabled=True, active="active"):
    return {
        "name": "agents",
        "units": [
            {
                "name": name,
                "load_state": "loaded",
                "active_state": active,
                "unit_file_state": (
                    "enabled"
                    if name != "limeos-agent.service" or agent_enabled
                    else "disabled"
                ),
            }
            for name in AGENT_RUNTIME_UNITS
        ],
    }


def _job(*, active_state="inactive", result="success", invocation_id="old"):
    return {
        "active_state": active_state,
        "result": result,
        "invocation_id": invocation_id,
    }


def _runtime_health():
    return {
        "success": True,
        "runtime_installed": True,
        "agent_active": "active",
        "broker_active": "active",
        "action_broker_active": "active",
        "action_worker_active": "active",
        "report_scheduler_active": "active",
        "supervisor_active": "active",
        "claude_installed": True,
        "claude_compatible": True,
        "claude_authenticated": True,
        "configured": True,
        "enabled": True,
        "team_id": "must-not-enter-ledger",
        "bot_token_id": "must-not-enter-ledger",
    }


def _mattermost_status(*, state="connected"):
    return {
        "name": "mattermost",
        "state": state,
        "installed": True,
        "stack_name": "mattermost",
        "webhook_configured": True,
        "services": [
            {"name": name, "state": "running", "health": "healthy"}
            for name in (
                "limeos-alertd",
                "limeos-mattermost",
                "limeos-mattermost-db",
            )
        ],
    }


def _registry():
    return build_repair_registry(
        container_status=lambda name: {"name": name, "status": "running"},
        stack_status=lambda name: {
            "name": name,
            "services": [{"name": "web"}],
            "status": {"status": "running", "containers": []},
        },
        package_status=lambda: {
            "ok": True,
            "drift": [],
            "packages": [{"name": "base"}],
        },
        package_job_status=lambda: _job(),
        integration_status=_integration_status,
        integration_job_status=lambda: _job(),
        mattermost_status=_mattermost_status,
        mattermost_job_status=lambda: _job(),
    )


def test_integration_capability_is_fixed_approval_bound_r2():
    capability = _registry().require("integration.repair")

    assert capability.risk == RiskClass.MUTATING
    assert capability.eligible_modes == (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
    )
    assert capability.normalize({"name": "agents"}) == {"name": "agents"}
    assert capability.normalize({"name": "mattermost"}) == {"name": "mattermost"}
    assert capability.target({"name": "agents"}) == "agents"
    with pytest.raises(CapabilityError, match="agents or mattermost"):
        capability.normalize({"name": "other"})
    with pytest.raises(CapabilityError, match="agents or mattermost"):
        capability.normalize({"name": "agents", "command": "shell"})


def test_integration_precondition_rejects_disabled_or_running_repair():
    before = safe_integration_precondition(_integration_status, lambda: _job())

    assert before["name"] == "agents"
    assert len(before["units"]) == 6
    with pytest.raises(CapabilityError, match="must be enabled"):
        safe_integration_precondition(
            lambda: _integration_status(agent_enabled=False), lambda: _job()
        )
    with pytest.raises(CapabilityError, match="already running"):
        safe_integration_precondition(
            _integration_status,
            lambda: _job(active_state="activating", invocation_id="new"),
        )


def test_integration_executor_waits_for_new_job_then_requires_full_health():
    jobs = iter(
        [
            _job(active_state="activating", invocation_id="new"),
            _job(invocation_id="new"),
        ]
    )
    starts = []
    executor = build_integration_executors(
        start=lambda: starts.append(True) or {"started": True},
        status_reader=_integration_status,
        job_status_reader=lambda: next(jobs),
        runtime_status_reader=_runtime_health,
    )["integration.repair"]
    before = {"job": _job(invocation_id="old")}

    assert executor.execute({"name": "agents"}) == {"started": True}
    assert executor.verify({"name": "agents"}, before)[0] is None
    verified, after = executor.verify({"name": "agents"}, before)

    assert verified is True
    assert after["health"]["action_worker_active"] == "active"
    assert "team_id" not in after["health"]
    assert "bot_token_id" not in after["health"]
    assert starts == [True]


def test_integration_executor_fails_completed_unhealthy_repair():
    runtime = _runtime_health()
    runtime["agent_active"] = "failed"
    executor = build_integration_executors(
        start=lambda: {"started": True},
        status_reader=lambda: _integration_status(active="failed"),
        job_status_reader=lambda: _job(invocation_id="new"),
        runtime_status_reader=lambda: runtime,
    )["integration.repair"]

    verified, _after = executor.verify(
        {"name": "agents"}, {"job": _job(invocation_id="old")}
    )

    assert verified is False


def test_mattermost_executor_requires_new_job_and_connected_service_health():
    jobs = iter(
        [
            _job(active_state="activating", invocation_id="new"),
            _job(invocation_id="new"),
        ]
    )
    starts = []
    executor = build_integration_executors(
        start=lambda: {"started": True},
        status_reader=_integration_status,
        job_status_reader=lambda: _job(),
        runtime_status_reader=_runtime_health,
        mattermost_start=lambda: starts.append(True) or {"started": True},
        mattermost_status_reader=_mattermost_status,
        mattermost_job_status_reader=lambda: next(jobs),
    )["integration.repair"]
    params = {"name": "mattermost"}
    before = {"job": _job(invocation_id="old")}

    assert executor.execute(params) == {"started": True}
    assert executor.verify(params, before)[0] is None
    verified, after = executor.verify(params, before)

    assert verified is True
    assert after["state"] == "connected"
    assert len(after["services"]) == 3
    assert starts == [True]


def test_integration_status_reads_only_fixed_systemd_units():
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n",
        )

    status = agent_integration_status(runner)

    assert [item[2] for item in calls] == list(AGENT_RUNTIME_UNITS)
    assert all(item["active_state"] == "active" for item in status["units"])


def test_integration_job_status_requires_the_fixed_loaded_unit():
    def runner(command, **_kwargs):
        assert command[2] == "limeos-agent-repair.service"
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "LoadState=loaded\nActiveState=inactive\nResult=success\n"
                "InvocationID=abc123\n"
            ),
        )

    assert agent_repair_job_status(runner) == _job(invocation_id="abc123")


def test_mattermost_job_status_reads_only_the_fixed_unit():
    def runner(command, **_kwargs):
        assert command[2] == MATTERMOST_REPAIR_UNIT
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "LoadState=loaded\nActiveState=inactive\nResult=success\n"
                "InvocationID=mattermost-1\n"
            ),
        )

    assert mattermost_repair_job_status(runner) == _job(invocation_id="mattermost-1")


def test_runtime_health_sanitizer_drops_identifiers_and_credentials():
    safe = safe_agent_runtime_health(_runtime_health())

    assert safe["configured"] is True
    assert set(safe) == {
        "runtime_installed",
        "agent_active",
        "broker_active",
        "action_broker_active",
        "action_worker_active",
        "report_scheduler_active",
        "supervisor_active",
        "claude_installed",
        "claude_compatible",
        "claude_authenticated",
        "configured",
        "enabled",
    }
