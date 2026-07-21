"""Approval-bound retry for the fixed failed package reconciliation job."""

import pytest

from agent_actions.actuator import build_job_retry_executors
from agent_actions.capability import AuthorityMode, CapabilityError, RiskClass
from agent_actions.defaults import build_repair_registry, safe_job_retry_precondition


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


def _job(*, active_state="failed", result="exit-code", invocation_id="old"):
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
        integration_job_status=lambda: {"active_state": "inactive"},
    )


def test_job_retry_capability_is_fixed_approval_bound_r2():
    capability = _registry().require("job.retry")

    assert capability.risk == RiskClass.MUTATING
    assert capability.eligible_modes == (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
    )
    params = {"name": "package-reconcile"}
    assert capability.normalize(params) == params
    assert capability.target(params) == "package-reconcile"
    with pytest.raises(CapabilityError, match="only the package-reconcile target"):
        capability.normalize({"name": "ssh.service"})
    with pytest.raises(CapabilityError, match="only the package-reconcile target"):
        capability.normalize({"name": "package-reconcile", "unit": "ssh.service"})


def test_job_retry_requires_a_failed_job_with_remaining_drift():
    before = safe_job_retry_precondition(lambda: _status(), lambda: _job())

    assert before["name"] == "package-reconcile"
    assert before["drift"] == ["python3-psutil"]
    with pytest.raises(CapabilityError, match="has not failed"):
        safe_job_retry_precondition(
            lambda: _status(),
            lambda: _job(active_state="inactive", result="success"),
        )
    with pytest.raises(CapabilityError, match="no remaining drift"):
        safe_job_retry_precondition(lambda: _status(ok=True), lambda: _job())


def test_job_retry_waits_then_requires_new_successful_compliant_invocation():
    jobs = iter(
        [
            _job(active_state="activating", result="success", invocation_id="new"),
            _job(active_state="inactive", result="success", invocation_id="new"),
        ]
    )
    starts = []
    executor = build_job_retry_executors(
        start=lambda name: starts.append(name) or {"started": True},
        status_reader=lambda: _status(ok=True),
        job_status_reader=lambda: next(jobs),
    )["job.retry"]
    params = {"name": "package-reconcile"}
    before = {"job": _job(invocation_id="old")}

    assert executor.execute(params) == {"started": True}
    assert executor.verify(params, before)[0] is None
    verified, after = executor.verify(params, before)

    assert verified is True
    assert after["ok"] is True
    assert starts == ["package-reconcile"]


def test_job_retry_fails_when_the_new_invocation_fails():
    executor = build_job_retry_executors(
        start=lambda _name: {"started": True},
        status_reader=lambda: _status(),
        job_status_reader=lambda: _job(invocation_id="new"),
    )["job.retry"]

    verified, _after = executor.verify(
        {"name": "package-reconcile"}, {"job": _job(invocation_id="old")}
    )

    assert verified is False
