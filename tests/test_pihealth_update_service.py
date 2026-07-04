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
            "restart": {"success": True},
        }
    )
    assert "deps" not in helper.calls
    assert "build" not in helper.calls
    assert helper.calls == ["pull", "migrate", "restart"]


def test_build_runs_only_when_frontend_changed():
    helper, _ = _run(
        {
            "pull": {"success": True, "old_commit": OLD, "new_commit": NEW,
                     "changed_files": ["frontend/package.json"]},
            "migrate": {"success": True},
            "build": {"success": True, "skipped": True, "reason": "npm not installed"},
            "restart": {"success": True},
        }
    )
    assert "build" in helper.calls


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
