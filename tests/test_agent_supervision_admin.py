from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_actions.ledger import ActionLedger, ActionState, NewAction
from agent_supervision.admin import (
    SupervisionAdminError,
    SupervisionAdminService,
)
from agent_supervision.service import SupervisionService


NOW = datetime(2026, 7, 23, 10, 5, tzinfo=timezone.utc)
RELEASE = "a" * 40


def _schedule(**overrides):
    values = {
        "name": "Recover get_iplayer",
        "enabled": False,
        "operation": "container.restart",
        "params": {"name": "get_iplayer"},
        "service_priority": "normal",
        "window": {
            "cron": "0 10 * * *",
            "timezone": "UTC",
            "duration_minutes": 60,
        },
        "delivery": {
            "channel": "mattermost-alerts",
            "mode": "threaded",
        },
    }
    values.update(overrides)
    return values


def _policy(path):
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "kill_switch": False,
                "defaults": {"proposal_ttl_seconds": 900},
                "operations": {
                    "container.restart": {
                        "enabled": True,
                        "approvers": ["local:admin"],
                        "targets": {
                            "get_iplayer": {
                                "interactive": "approval",
                                "scheduled": "supervised",
                                "event": "observe",
                            }
                        },
                    }
                },
            }
        )
    )


def _admin(tmp_path):
    policy = tmp_path / "policy.json"
    _policy(policy)
    return SupervisionAdminService(
        supervision_path=tmp_path / "supervision.sqlite3",
        ledger_path=tmp_path / "actions.sqlite3",
        policy_path=policy,
        release_commit_provider=lambda: RELEASE,
        clock=lambda: NOW,
        id_factory=lambda: "schedule-1",
    )


def _failed(audit_id):
    return {
        "ok": True,
        "data": {
            "name": "get_iplayer",
            "status": "exited",
            "health": None,
        },
        "error": None,
        "audit_id": audit_id,
    }


def _action(now=NOW):
    return NewAction(
        action_id="action-supervised",
        idempotency_key="scheduled-action-supervised",
        operation="container.restart",
        capability_version="1",
        target="get_iplayer",
        risk="R1",
        trigger="scheduled",
        authority_mode="supervised",
        params={"name": "get_iplayer"},
        evidence_ids=["assessment-1"],
        payload_hash="b" * 64,
        reason="Confirmed code-owned health failure.",
        impact="Restart get_iplayer.",
        precondition_hash="c" * 64,
        actor_type="system",
        actor_id="limeops-supervisor",
        actor_username=None,
        state=ActionState.AUTHORISED,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=2)).isoformat(),
    )


def test_admin_schedule_projection_exposes_read_only_safety_state(tmp_path):
    admin = _admin(tmp_path)

    created = admin.create(
        _schedule(),
        owner={"type": "local", "id": "admin", "username": "admin"},
    )
    listed = admin.list()

    assert created["status"]["configured_authority"] == "supervised"
    assert created["status"]["effective_authority"] == "supervised"
    assert created["status"]["canary"] is None
    assert created["status"]["incident"] is None
    assert created["status"]["budget"] == {
        "rolling_24h": {"used": 0, "limit": 1},
        "window": {"used": 0, "limit": 1},
        "last_charge": None,
        "cooldown_until": None,
    }
    assert listed["limits"] == {
        "max_actions_per_target_24h": 1,
        "max_actions_per_window": 1,
    }
    assert listed["schedules"][0]["id"] == "schedule-1"


def test_admin_incident_detail_keeps_bounded_assessment_and_transition_history(
    tmp_path,
):
    admin = _admin(tmp_path)
    admin.create(
        _schedule(),
        owner={"type": "local", "id": "admin", "username": "admin"},
    )
    admin.enable(
        "schedule-1",
        {"revision": 1, "confirmation": "ENABLE SUPERVISION"},
    )
    service = SupervisionService(store=admin.store, clock=lambda: NOW)
    service.assess(
        "schedule-1",
        _failed("audit-1"),
        assessed_at=NOW - timedelta(minutes=10),
    )
    service.assess(
        "schedule-1",
        _failed("audit-2"),
        assessed_at=NOW,
    )

    incident = admin.incidents()["incidents"][0]
    detail = admin.incident(incident["id"])["incident"]

    assert incident["state"] == "confirmed"
    assert incident["transitions"][0]["type"] == "fault_confirmed"
    assert [item["outcome"] for item in detail["assessments"]] == [
        "failed",
        "failed",
    ]
    assert detail["last_action"] is None


def test_active_demotion_changes_effective_authority_and_clearance_is_strict(
    tmp_path,
):
    admin = _admin(tmp_path)
    admin.create(
        _schedule(),
        owner={"type": "local", "id": "admin", "username": "admin"},
    )
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    ledger.create(_action())
    demotion, _created = ledger.create_demotion(
        operation="container.restart",
        target="get_iplayer",
        cause="execution_failed",
        source_action_id="action-supervised",
        release_commit=RELEASE,
        demoted_at=NOW.isoformat(),
    )

    projected = admin.get("schedule-1")

    assert projected["status"]["configured_authority"] == "supervised"
    assert projected["status"]["effective_authority"] == "approval"
    assert projected["status"]["demotion"]["id"] == demotion.demotion_id
    assert admin.demotions()["demotions"][0]["active"] is True

    with pytest.raises(SupervisionAdminError) as confirmation:
        admin.clear_demotion(
            demotion.demotion_id,
            {
                "revision": 1,
                "recovery_action_id": "action-recovery",
                "confirmation": "clear it",
            },
            actor={
                "type": "local",
                "id": "admin",
                "username": "admin",
            },
        )

    assert confirmation.value.code == "confirmation_required"


def test_schedule_enablement_requires_a_dedicated_confirmed_transition(
    tmp_path,
):
    admin = _admin(tmp_path)

    with pytest.raises(SupervisionAdminError) as create_error:
        admin.create(
            _schedule(enabled=True),
            owner={"type": "local", "id": "admin", "username": "admin"},
        )
    assert create_error.value.code == "confirmation_required"

    admin.create(
        _schedule(),
        owner={"type": "local", "id": "admin", "username": "admin"},
    )
    with pytest.raises(SupervisionAdminError) as update_error:
        admin.update(
            "schedule-1",
            {**_schedule(enabled=True), "revision": 1},
        )
    assert update_error.value.code == "confirmation_required"

    with pytest.raises(SupervisionAdminError) as phrase_error:
        admin.enable(
            "schedule-1",
            {"revision": 1, "confirmation": "enable"},
        )
    assert phrase_error.value.code == "confirmation_required"

    enabled = admin.enable(
        "schedule-1",
        {"revision": 1, "confirmation": "ENABLE SUPERVISION"},
    )
    assert enabled["enabled"] is True
    assert enabled["revision"] == 2
