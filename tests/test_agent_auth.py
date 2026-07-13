"""AA-004 guided subscription authentication operation."""

from __future__ import annotations

import sys
import time

import pytest

from agent_provider.auth import AuthInputError, GuidedAuthManager


def _wait_for(manager, operation_id, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status(operation_id)
        if predicate(status):
            return status
        time.sleep(0.01)
    raise AssertionError("authentication state did not arrive")


def test_guided_auth_streams_only_public_events_and_discards_url_on_completion(tmp_path):
    script = (
        "import sys; "
        "print('Open https://claude.ai/oauth/authorize?code=short-lived', flush=True); "
        "print('Paste code here if prompted:', flush=True); "
        "code=sys.stdin.readline().strip(); "
        "print('access_token=SECRET', flush=True); "
        "print('Authenticated successfully' if code == 'approved-code' else 'failed', flush=True); "
        "raise SystemExit(0 if code == 'approved-code' else 1)"
    )
    manager = GuidedAuthManager(
        [sys.executable, "-u", "-c", script],
        cwd=tmp_path,
        timeout_seconds=3,
        id_factory=lambda: "auth-1",
    )
    operation_id = manager.start()
    running = _wait_for(
        manager,
        operation_id,
        lambda status: any(event["type"] == "input_required" for event in status["events"]),
    )
    assert any(event["type"] == "authorization_url" for event in running["events"])
    assert "SECRET" not in str(running)

    manager.submit(operation_id, "approved-code")
    complete = _wait_for(manager, operation_id, lambda status: status["state"] == "complete")
    assert all(event["type"] != "authorization_url" for event in complete["events"])
    assert any(event.get("message") == "Claude authentication completed." for event in complete["events"])
    assert "SECRET" not in str(complete)


def test_guided_auth_rejects_multiline_authorization_response(tmp_path):
    manager = GuidedAuthManager(
        [sys.executable, "-u", "-c", "import time; time.sleep(1)"],
        cwd=tmp_path,
        timeout_seconds=2,
    )
    operation_id = manager.start()
    with pytest.raises(AuthInputError):
        manager.submit(operation_id, "code\nINJECT")
    manager.cancel(operation_id)


def test_guided_auth_times_out_and_returns_no_raw_output(tmp_path):
    manager = GuidedAuthManager(
        [sys.executable, "-u", "-c", "import time; print('debug SECRET', flush=True); time.sleep(5)"],
        cwd=tmp_path,
        timeout_seconds=0.05,
        id_factory=lambda: "auth-timeout",
    )
    operation_id = manager.start()
    status = _wait_for(manager, operation_id, lambda value: value["state"] == "timeout")
    assert status["events"] == [
        {"type": "status", "message": "Claude authentication timed out."}
    ]
    assert "SECRET" not in str(status)


def test_guided_auth_timeout_kills_children_after_parent_exits(tmp_path):
    marker = tmp_path / "orphan-auth-ran"
    child = (
        "import time; from pathlib import Path; time.sleep(0.4); "
        f"Path({str(marker)!r}).write_text('survived')"
    )
    parent = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}])"
    )
    manager = GuidedAuthManager(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        timeout_seconds=0.05,
        id_factory=lambda: "auth-orphan",
    )
    operation_id = manager.start()
    _wait_for(manager, operation_id, lambda value: value["state"] == "timeout")
    time.sleep(0.5)
    assert not marker.exists()
