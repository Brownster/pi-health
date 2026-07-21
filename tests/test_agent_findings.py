"""Private finding draft validation, redaction, deduplication, and editing."""

import json
import os

import pytest

from agent_findings.service import FindingError, FindingsService


def _finding(**overrides):
    value = {
        "kind": "bug",
        "title": "Container repair reports success too early",
        "summary": "A restart is marked complete before health verification.",
        "component": "agent-actions",
        "affected_version": "0.9.0",
        "expected_behavior": "Wait for a healthy container.",
        "actual_behavior": "The operation returns immediately.",
        "reproduction_steps": ["Restart an unhealthy canary container."],
        "impact": "Operators receive a false recovery report.",
        "frequency": "Every restart",
        "workaround": "Check container health manually.",
        "confidence": "high",
        "acceptance_criteria": ["Require a verified healthy state."],
        "source_type": "failed_action",
    }
    value.update(overrides)
    return value


def test_finding_is_private_redacted_and_deduplicated(tmp_path):
    store = FindingsService(tmp_path / "findings.sqlite3")
    finding = _finding(
        summary="Restart failed with password=hunter2 and token=abc.def"
    )
    first, created = store.propose(
        finding=finding,
        actor={"type": "mattermost", "id": "user-1", "username": "marc"},
        evidence_ids=["audit-1"],
        finding_id="finding-1",
    )
    replay, replay_created = store.propose(
        finding=finding,
        actor={"type": "mattermost", "id": "user-1", "username": "renamed"},
        evidence_ids=["audit-2"],
        finding_id="finding-2",
    )

    assert created is True and replay_created is False
    assert replay["id"] == first["id"]
    assert first["redaction_applied"] is True
    assert "hunter2" not in json.dumps(first)
    assert first["publication"] is None
    assert os.stat(tmp_path / "findings.sqlite3").st_mode & 0o777 == 0o660


def test_finding_can_be_edited_then_rejected_but_never_published(tmp_path):
    store = FindingsService(tmp_path / "findings.sqlite3")
    draft, _ = store.propose(
        finding=_finding(),
        actor={"type": "local", "id": "admin"},
        evidence_ids=[],
        finding_id="finding-1",
    )
    updated = store.update(draft["id"], _finding(impact="Affects all repair reports."))
    assert updated["impact"] == "Affects all repair reports."
    rejected = store.reject(draft["id"])
    assert rejected["state"] == "rejected"
    with pytest.raises(FindingError) as closed:
        store.update(draft["id"], _finding())
    assert closed.value.code == "invalid_state"


@pytest.mark.parametrize(
    "finding",
    [
        {},
        _finding(kind="pull_request"),
        _finding(source_type="raw_chat_export"),
        _finding(reproduction_steps="run it"),
        _finding(extra="untrusted"),
    ],
)
def test_finding_schema_rejects_unknown_or_unbounded_shapes(tmp_path, finding):
    store = FindingsService(tmp_path / "findings.sqlite3")
    with pytest.raises(FindingError):
        store.propose(
            finding=finding,
            actor={"type": "local", "id": "admin"},
            evidence_ids=[],
        )
