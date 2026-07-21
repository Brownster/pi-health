"""AO-006 package reconciliation capability and executor contracts."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_actions.actuator import build_package_executors
from agent_actions.capability import AuthorityMode, CapabilityError, RiskClass
from agent_actions.defaults import build_repair_registry, safe_package_precondition
from agent_actions.packages import package_job_status, package_repair_status


def _status(*, ok=False):
    return {
        "ok": ok,
        "drift": [] if ok else ["python3-psutil"],
        "packages": [
            {
                "name": "python3-psutil",
                "policy": "present",
                "expected": None,
                "installed": "5.9" if ok else None,
                "compliant": ok,
            }
        ],
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
        package_status=lambda: _status(),
        package_job_status=lambda: _job(),
        integration_status=lambda: {"units": []},
        integration_job_status=lambda: _job(),
    )


def test_package_capability_is_fixed_approval_bound_r2():
    capability = _registry().require("packages.reconcile")

    assert capability.risk == RiskClass.MUTATING
    assert capability.eligible_modes == (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
    )
    assert capability.normalize({}) == {}
    assert capability.target({}) == "shipped-manifest"
    with pytest.raises(CapabilityError, match="accepts no parameters"):
        capability.normalize({"package": "curl"})


def test_shipped_action_policy_covers_every_registered_operation():
    policy = json.loads(Path("config/agent-action-policy.default.json").read_text())

    assert set(policy["operations"]) == set(_registry().operations)


def test_package_precondition_is_bounded_and_rejects_active_job():
    before = safe_package_precondition(lambda: _status(), lambda: _job())

    assert before["target"] == "shipped-manifest"
    assert before["drift"] == ["python3-psutil"]
    assert before["packages"][0]["installed"] == ""
    with pytest.raises(CapabilityError, match="already running"):
        safe_package_precondition(
            lambda: _status(), lambda: _job(active_state="activating")
        )


def test_package_executor_waits_then_requires_compliance_and_new_invocation():
    jobs = iter(
        [
            _job(active_state="activating", result="success", invocation_id="new"),
            _job(invocation_id="new"),
        ]
    )
    starts = []
    executor = build_package_executors(
        start=lambda: starts.append(True) or {"started": True},
        status_reader=lambda: _status(ok=True),
        job_status_reader=lambda: next(jobs),
    )["packages.reconcile"]
    before = {"job": _job(invocation_id="old")}

    assert executor.execute({}) == {"started": True}
    assert executor.verify({}, before)[0] is None
    verified, after = executor.verify({}, before)

    assert verified is True
    assert after["ok"] is True
    assert starts == [True]


def test_package_status_uses_only_repair_managed_manifest_entries(monkeypatch):
    monkeypatch.setattr(
        "agent_actions.packages.load_manifest",
        lambda: [
            SimpleNamespace(
                name="claude-code",
                manager="apt",
                policy="pinned",
                version="2.1.207",
                feature="ai_agents",
            ),
            SimpleNamespace(
                name="python3-psutil",
                manager="apt",
                policy="present",
                version=None,
                feature=None,
            ),
        ],
    )
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="5.9")

    status = package_repair_status(runner)

    assert status["ok"] is True
    assert [item["name"] for item in status["packages"]] == ["python3-psutil"]
    assert all("claude-code" not in command for command in calls)


def test_package_job_status_maps_only_fixed_systemd_properties():
    def runner(command, **_kwargs):
        assert command[2] == "limeos-package-reconcile-action.service"
        return SimpleNamespace(
            returncode=0,
            stdout="ActiveState=inactive\nResult=success\nInvocationID=abc123\n",
        )

    assert package_job_status(runner) == _job(invocation_id="abc123")
