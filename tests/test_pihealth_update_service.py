"""Unit tests for the framework-neutral self-update orchestration generator."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pihealth_update_service import stream_update

OLD = "a" * 40
NEW = "b" * 40


class FakeHelper:
    """Record requested steps and return canned per-step results."""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def __call__(self, command, params):
        assert command == "pihealth_update"
        step = params["step"]
        self.calls.append(step)
        return self.results[step]


def _run(results, config=None):
    helper = FakeHelper(results)
    events = list(stream_update(helper, config or {"user": "pi"}))
    return helper, events


def _steps(events):
    return [event["step"] for event in events]


def test_full_run_streams_every_step_and_ends_restarting():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["requirements.txt", "frontend/src/app.tsx"]},
            "deps": {"success": True},
            "migrate": {"success": True},
            "build": {"success": True},
            "restart": {"success": True, "scheduled": True},
        }
    )
    assert helper.calls == ["pull", "deps", "migrate", "build", "restart"]
    terminal = events[-1]
    assert terminal["restarting"] is True
    assert terminal["done"] is True
    assert terminal["new_commit"] == NEW
    # Exactly one terminal event overall.
    assert sum(1 for event in events if event.get("done") or event.get("error")) == 1


def test_up_to_date_skips_work_and_does_not_restart():
    helper, events = _run(
        {"pull": {"success": True, "old_commit": NEW, "new_commit": NEW, "changed_files": []}}
    )
    assert helper.calls == ["pull"]
    assert events[-1]["done"] is True
    assert "restarting" not in events[-1]
    assert "Already up to date" in events[-1]["line"]


def test_deps_skipped_when_requirements_unchanged():
    helper, _ = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["app.py"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert "deps" not in helper.calls
    assert helper.calls == ["pull", "migrate", "build", "restart"]


def test_build_always_runs_and_reports_when_current():
    # The build step now runs every update (the helper decides whether to rebuild), so a
    # bundle left stale by an earlier pull is still caught rather than skipped.
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["app.py"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert "build" in helper.calls
    assert any(e["step"] == "build" and "already up to date" in e.get("line", "") for e in events)


def test_stale_bundle_without_toolchain_warns_but_continues():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["frontend/src/app.tsx"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "stale": True,
                      "reason": "npm not installed and the committed web UI bundle is stale"},
            "restart": {"success": True},
        }
    )
    assert any(
        e["step"] == "build" and "⚠" in e.get("line", "") and "stale" in e.get("line", "")
        for e in events
    )
    assert helper.calls[-1] == "restart"  # non-fatal: the update still completes


def test_pull_failure_stops_with_error():
    helper, events = _run({"pull": {"success": False, "error": "Not possible to fast-forward"}})
    assert helper.calls == ["pull"]
    assert events[-1]["error"] == "Not possible to fast-forward"
    assert "restart" not in helper.calls


def test_step_failure_stops_before_restart():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["app.py"]},
            "migrate": {"success": False, "error": "migration failed"},
        }
    )
    assert helper.calls == ["pull", "migrate"]
    assert events[-1]["error"] == "migration failed"
    assert "restart" not in helper.calls


def test_helper_exception_becomes_step_error():
    class Boom:
        def __call__(self, command, params):
            raise RuntimeError("helper offline")

    events = list(stream_update(Boom(), {"user": "pi"}))
    assert events[-1]["error"] == "helper offline"


def test_agent_changes_defer_convergence_until_services_restart():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["agent_gateway/gateway.py", "config/limeos-packages.json"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert helper.calls == ["pull", "migrate", "build", "restart"]
    assert any(
        event["step"] == "agent"
        and "after service restart" in event.get("line", "").lower()
        for event in events
    )


def test_agent_changes_do_not_run_with_the_pre_pull_helper():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["limeos_packages.py"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert "agent" not in helper.calls
    assert helper.calls[-1] == "restart"
    assert any(
        event["step"] == "agent" and "automatically" in event.get("line", "")
        for event in events
    )


def test_agent_step_not_called_without_agent_changes():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["app.py"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert "agent" not in helper.calls  # only a "No agent changes" event, no helper call
    assert any(e["step"] == "agent" and "No agent changes" in e.get("line", "") for e in events)


def test_agent_changes_cannot_block_the_release_restart():
    helper, events = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["agent_transport/listener.py"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "web UI already up to date"},
            "restart": {"success": True},
        }
    )
    assert "agent" not in helper.calls
    assert helper.calls[-1] == "restart"
    assert events[-1]["step"] == "restart"
    assert events[-1]["done"] is True


class FakePrerequisites:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "changed": True,
            "reboot_required": True,
            "applied": ["memory_cgroup"],
            "errors": [],
        }
        self.error = error
        self.calls = 0

    def apply(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakePendingActions:
    def __init__(self):
        self.records = []

    def record(self, action_id, **fields):
        self.records.append((action_id, fields))
        return {"id": action_id, **fields}


def _successful_results():
    return {
        "pull": {
            "success": True,
            "old_commit": OLD,
            "new_commit": NEW,
            "changed_files": ["app.py"],
        },
        "migrate": {"success": True},
        "build": {"success": True, "skipped": True, "reason": "Web UI already current."},
        "restart": {"success": True},
    }


def _run_with_prerequisites(prerequisites, pending_actions=None):
    helper = FakeHelper(_successful_results())
    return list(
        stream_update(
            helper,
            {"user": "pi"},
            prerequisite_service=prerequisites,
            pending_actions=pending_actions,
        )
    )


def test_an_applied_prerequisite_records_the_reboot_and_still_restarts():
    prerequisites = FakePrerequisites()
    pending = FakePendingActions()

    events = _run_with_prerequisites(prerequisites, pending)

    assert "prerequisites" in _steps(events)
    assert any(event.get("reboot_required") for event in events)
    assert pending.records[0][0] == "reboot_required"
    assert pending.records[0][1]["command"] == "sudo reboot"
    # The reboot is the user's to schedule; the update finishes regardless.
    assert events[-1]["restarting"] is True
    assert events[-1]["done"] is True


def test_a_satisfied_host_records_nothing():
    prerequisites = FakePrerequisites(
        {"changed": False, "reboot_required": False, "applied": [], "errors": []}
    )
    pending = FakePendingActions()

    events = _run_with_prerequisites(prerequisites, pending)

    assert pending.records == []
    assert any("already met" in event.get("line", "") for event in events)
    assert events[-1]["done"] is True


def test_a_prerequisite_failure_never_fails_the_update():
    prerequisites = FakePrerequisites(error=RuntimeError("helper unavailable"))
    pending = FakePendingActions()

    events = _run_with_prerequisites(prerequisites, pending)

    assert any("helper unavailable" in event.get("line", "") for event in events)
    assert not any("error" in event for event in events)
    assert events[-1]["done"] is True
    assert pending.records == []


def test_prerequisite_errors_are_surfaced_as_warning_lines():
    prerequisites = FakePrerequisites(
        {
            "changed": False,
            "reboot_required": False,
            "applied": [],
            "errors": ["The privileged helper is unavailable"],
        }
    )

    events = _run_with_prerequisites(prerequisites)

    assert any(
        "The privileged helper is unavailable" in event.get("line", "") for event in events
    )
    assert events[-1]["done"] is True


def test_the_step_is_skipped_when_no_prerequisite_service_is_wired():
    helper = FakeHelper(_successful_results())
    events = list(stream_update(helper, {"user": "pi"}))

    assert "prerequisites" not in _steps(events)
    assert events[-1]["done"] is True
