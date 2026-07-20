from __future__ import annotations

import pytest

from app import _start_agent_convergence


@pytest.mark.parametrize("state", ["disabled", "not_installed", "cleanup_required"])
def test_startup_convergence_skips_non_enabled_lifecycle_states(state):
    calls = []
    thread = _start_agent_convergence(
        snapshot_reader=lambda: {"state": state},
        helper=lambda *args: calls.append(args),
    )
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert calls == []


def test_startup_convergence_runs_for_an_enabled_agent():
    calls = []
    thread = _start_agent_convergence(
        snapshot_reader=lambda: {"state": "enabled"},
        helper=lambda *args: calls.append(args),
    )
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert calls == [("agent_converge_if_stale", {})]
