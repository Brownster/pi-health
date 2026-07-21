"""AO-006 stack reconciliation capability and verification contracts."""

import pytest

from agent_actions.actuator import build_stack_executors
from agent_actions.capability import AuthorityMode, CapabilityError, RiskClass
from agent_actions.defaults import build_repair_registry, safe_stack_precondition


def _stack_status(*, state="partial", api_state="exited", api_health=""):
    return {
        "name": "media",
        "compose_file": "compose.yaml",
        "services": [{"name": "web"}, {"name": "api"}],
        "status": {
            "status": state,
            "containers": [
                {
                    "name": "media-web-1",
                    "service": "web",
                    "status": "running",
                    "health": "healthy",
                },
                {
                    "name": "media-api-1",
                    "service": "api",
                    "status": api_state,
                    "health": api_health,
                },
            ],
        },
    }


def test_stack_capability_is_exact_approval_bound_r2():
    registry = build_repair_registry(
        container_status=lambda name: {"name": name, "status": "running"},
        stack_status=lambda _name: _stack_status(),
        package_status=lambda: {"ok": True, "drift": [], "packages": [{"name": "base"}]},
        package_job_status=lambda: {"active_state": "inactive"},
    )
    capability = registry.require("stack.reconcile")

    assert capability.risk == RiskClass.MUTATING
    assert capability.eligible_modes == (
        AuthorityMode.PROPOSE,
        AuthorityMode.APPROVAL,
    )
    assert capability.normalize({"name": "media"}) == {"name": "media"}
    assert "same-project orphan containers" in capability.impact({"name": "media"})


@pytest.mark.parametrize("name", [".", "..", ".hidden", "-media", "a" * 65])
def test_stack_capability_rejects_names_disallowed_by_stack_manager(name):
    capability = build_repair_registry(
        container_status=lambda value: {"name": value, "status": "running"},
        stack_status=lambda _name: _stack_status(),
        package_status=lambda: {"ok": True, "drift": [], "packages": [{"name": "base"}]},
        package_job_status=lambda: {"active_state": "inactive"},
    ).require("stack.reconcile")

    with pytest.raises(CapabilityError, match="Stack name is invalid"):
        capability.normalize({"name": name})


def test_stack_precondition_contains_only_stable_definition_and_runtime_health():
    before = safe_stack_precondition(lambda _name: _stack_status(), "media")

    assert before == {
        "name": "media",
        "compose_file": "compose.yaml",
        "expected_services": ["api", "web"],
        "status": "partial",
        "containers": [
            {
                "name": "media-api-1",
                "service": "api",
                "status": "exited",
                "health": "",
            },
            {
                "name": "media-web-1",
                "service": "web",
                "status": "running",
                "health": "healthy",
            },
        ],
    }


def test_stack_reconcile_waits_for_every_declared_service_to_be_healthy():
    statuses = [
        _stack_status(),
        _stack_status(state="running", api_state="running", api_health="healthy"),
    ]
    reconciled = []
    sleeps = []
    executor = build_stack_executors(
        reconcile=lambda name: reconciled.append(name) or {"reconciled": True},
        status_reader=lambda _name: statuses.pop(0),
        attempts=2,
        interval_seconds=0.25,
        sleeper=sleeps.append,
    )["stack.reconcile"]
    before = safe_stack_precondition(lambda _name: _stack_status(), "media")

    assert executor.execute({"name": "media"}) == {"reconciled": True}
    verified, after = executor.verify({"name": "media"}, before)

    assert verified is True
    assert after["status"] == "running"
    assert reconciled == ["media"]
    assert sleeps == [0.25]


def test_stack_reconcile_fails_for_unhealthy_or_changed_definition():
    unhealthy = _stack_status(
        state="running", api_state="running", api_health="unhealthy"
    )
    changed = _stack_status(state="running", api_state="running", api_health="healthy")
    changed["services"].append({"name": "worker"})
    statuses = [unhealthy, changed]
    executor = build_stack_executors(
        reconcile=lambda _name: {"reconciled": True},
        status_reader=lambda _name: statuses.pop(0),
        attempts=2,
        interval_seconds=0,
        sleeper=lambda _seconds: None,
    )["stack.reconcile"]
    before = safe_stack_precondition(lambda _name: _stack_status(), "media")

    verified, after = executor.verify({"name": "media"}, before)

    assert verified is False
    assert after["expected_services"] == ["api", "web", "worker"]
