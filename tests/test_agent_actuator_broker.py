"""Separate action-broker and trusted-worker boundary tests."""

from datetime import datetime, timedelta, timezone

from agent_actions.broker import build_actuator_operations
from agent_actions.ledger import ActionLedger, ActionState, NewAction
from agent_actions.worker import run_once
from limeops.broker import LimeOpsBroker, PeerIdentity
from limeops.policy import LimeOpsPolicy


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


class Audit:
    def record(self, event):
        return True


class Actuator:
    def __init__(self):
        self.calls = []

    def execute(self, action_id, *, audit_id):
        self.calls.append((action_id, audit_id))
        return {"id": action_id, "state": "succeeded"}


def _broker(actuator):
    policy = LimeOpsPolicy.from_mapping(
        {
            "schema_version": "1",
            "defaults": {"timeout_seconds": 2, "max_output_bytes": 65536},
            "operations": {"action.execute": {"enabled": True}},
        }
    )
    return LimeOpsBroker(
        policy=policy,
        operations=build_actuator_operations(actuator),
        audit=Audit(),
        id_factory=lambda: "action-audit-1",
    )


def _request(params):
    return {
        "schema_version": "1",
        "request_id": "worker-request-1",
        "operation": "action.execute",
        "params": params,
        "actor": {"type": "system", "id": "limeops-action-worker"},
    }


def test_action_broker_accepts_only_an_action_id_and_supplies_its_audit_id():
    actuator = Actuator()
    broker = _broker(actuator)
    peer = PeerIdentity(pid=10, uid=100, gid=100)

    response = broker.handle(_request({"action_id": "action-1"}), peer)
    assert response["ok"] is True
    assert actuator.calls == [("action-1", "action-audit-1")]

    denied = broker.handle(
        _request({"action_id": "action-2", "operation": "container.restart"}), peer
    )
    assert denied["ok"] is False
    assert denied["error"]["code"] == "invalid_input"
    assert actuator.calls == [("action-1", "action-audit-1")]


def test_shipped_action_broker_policy_matches_its_single_operation():
    policy = LimeOpsPolicy.from_file("config/agent-actuator-policy.default.json")
    assert policy.operations == ("action.execute",)
    assert set(build_actuator_operations(Actuator())) == set(policy.operations)


def test_worker_forwards_oldest_authorised_id_without_mutation_params(tmp_path):
    ledger = ActionLedger(tmp_path / "actions.sqlite3")
    for index, state in enumerate(
        (ActionState.AUTHORISED, ActionState.AUTHORISED, ActionState.SUCCEEDED), start=1
    ):
        ledger.create(
            NewAction(
                action_id=f"action-{index}",
                idempotency_key=f"idempotency-{index}",
                operation="container.restart",
                capability_version="1",
                target="jellyfin",
                risk="R1",
                trigger="interactive",
                authority_mode="approval",
                params={"name": "jellyfin"},
                evidence_ids=[],
                payload_hash=str(index) * 64,
                reason="Repair required",
                impact="Restart container",
                precondition_hash="b" * 64,
                actor_type="mattermost",
                actor_id="user-1",
                actor_username="marc",
                state=state,
                created_at=(NOW + timedelta(seconds=index)).isoformat(),
                expires_at=(NOW + timedelta(minutes=15)).isoformat(),
            )
        )

    class Client:
        def __init__(self):
            self.calls = []

        def request(self, operation, params, actor):
            self.calls.append((operation, params, actor))
            return {"ok": True}

    client = Client()
    assert run_once(ledger, client) is True
    assert client.calls == [
        (
            "action.execute",
            {"action_id": "action-1"},
            {"type": "system", "id": "limeops-action-worker"},
        )
    ]
