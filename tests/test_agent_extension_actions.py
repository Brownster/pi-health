"""Approval-bound third-party extension repair contracts."""

from types import SimpleNamespace

import pytest

from agent_actions.actuator import build_extension_executors
from agent_actions.capability import AuthorityMode, CapabilityError, RiskClass
from agent_actions.defaults import build_repair_registry
from agent_actions.integrations import extension_repair_job_status


def _status(name="weather", *, healthy=False):
    return {
        "success": True,
        "name": name,
        "type": "github",
        "enabled": True,
        "installed": healthy,
        "source_configured": True,
        "repairable": True,
        "registered": healthy,
        "configured": healthy,
        "status": "healthy" if healthy else "error",
        "healthy": healthy,
        "source": "must-not-enter-ledger",
    }


def _job(*, active_state="inactive", result="success", invocation_id="old"):
    return {
        "active_state": active_state,
        "result": result,
        "invocation_id": invocation_id,
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
        integration_status=lambda: {"units": []},
        integration_job_status=lambda: _job(),
        extension_status=lambda name: _status(name),
        extension_job_status=lambda _name: _job(),
    )


def test_extension_capability_is_allowlisted_approval_bound_r2():
    capability = _registry().require("extension.repair")

    assert capability.risk == RiskClass.MUTATING
    assert capability.eligible_modes == (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
    )
    assert capability.normalize({"name": "weather"}) == {"name": "weather"}
    assert capability.target({"name": "weather"}) == "weather"
    with pytest.raises(CapabilityError, match="only a name"):
        capability.normalize({"name": "weather", "source": "https://evil.test"})
    with pytest.raises(CapabilityError, match="target is invalid"):
        capability.normalize({"name": "../../etc"})
    with pytest.raises(CapabilityError, match="target is invalid"):
        capability.normalize({"name": "."})


def test_extension_precondition_keeps_only_bounded_configured_status():
    before = _registry().require("extension.repair").precondition({"name": "weather"})

    assert before["repairable"] is True
    assert before["job"]["invocation_id"] == "old"
    assert "source" not in before


def test_extension_executor_waits_for_new_healthy_registered_import():
    jobs = iter(
        [
            _job(active_state="activating", invocation_id="new"),
            _job(invocation_id="new"),
        ]
    )
    starts = []
    executor = build_extension_executors(
        start=lambda name: starts.append(name) or {"started": True},
        status_reader=lambda name: _status(name, healthy=True),
        job_status_reader=lambda _name: next(jobs),
    )["extension.repair"]
    params = {"name": "weather"}
    before = {"job": _job(invocation_id="old")}

    assert executor.execute(params) == {"started": True}
    assert executor.verify(params, before)[0] is None
    verified, after = executor.verify(params, before)

    assert verified is True
    assert after["registered"] is True
    assert starts == ["weather"]


def test_extension_job_status_accepts_only_a_valid_instance_name():
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "LoadState=loaded\nActiveState=inactive\nResult=success\n"
                "InvocationID=extension-1\n"
            ),
        )

    assert extension_repair_job_status("weather", runner)["result"] == "success"
    assert calls[0][2] == "limeos-extension-repair@weather.service"
    assert extension_repair_job_status("../../etc", runner)["active_state"] == (
        "unavailable"
    )
    assert len(calls) == 1
