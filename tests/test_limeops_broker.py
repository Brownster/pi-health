import json
import os
import stat
import time

from limeops.broker import (
    JsonlAuditWriter,
    LimeOpsBroker,
    OperationDefinition,
    PeerIdentity,
)
from limeops.policy import LimeOpsPolicy


def make_policy(**overrides):
    operation = {
        "enabled": True,
        "timeout_seconds": 1,
        "max_output_bytes": 4096,
        **overrides,
    }
    return LimeOpsPolicy.from_mapping(
        {
            "schema_version": "1",
            "defaults": {"timeout_seconds": 1, "max_output_bytes": 4096},
            "operations": {"system.status": operation},
        }
    )


def request(**overrides):
    return {
        "schema_version": "1",
        "request_id": "request-1",
        "operation": "system.status",
        "params": {},
        "actor": {"type": "mattermost", "id": "user-1", "username": "holly"},
        **overrides,
    }


class RecordingAudit:
    def __init__(self, results=None):
        self.events = []
        self.results = list(results or [])

    def record(self, event):
        self.events.append(dict(event))
        return self.results.pop(0) if self.results else True


PEER = PeerIdentity(pid=123, uid=1001, gid=1001)


def test_broker_returns_versioned_success_envelope_and_audits_metadata():
    audit = RecordingAudit()
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={
            "system.status": OperationDefinition(
                handler=lambda params, context: {"healthy": True, "peer": context.peer.uid},
                validate_params=lambda params: params,
            )
        },
        audit=audit,
        id_factory=lambda: "audit-1",
        clock=lambda: 10.0,
    )

    result = broker.handle(request(), PEER)

    assert result == {
        "schema_version": "1",
        "request_id": "request-1",
        "ok": True,
        "operation": "system.status",
        "data": {"healthy": True, "peer": 1001},
        "warnings": [],
        "error": None,
        "audit_id": "audit-1",
    }
    assert [event["phase"] for event in audit.events] == ["request", "result"]
    assert audit.events[0]["peer_uid"] == 1001
    assert audit.events[0]["actor_id"] == "user-1"
    assert "params" not in audit.events[0]
    assert "data" not in audit.events[1]


def test_broker_rejects_unknown_request_fields_before_handler():
    called = []
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={
            "system.status": OperationDefinition(
                handler=lambda *_args: called.append(True),
                validate_params=lambda params: params,
            )
        },
        audit=RecordingAudit(),
        id_factory=lambda: "audit-1",
    )
    result = broker.handle(request(extra=True), PEER)
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_input"
    assert called == []


def test_broker_rejects_bad_actor_and_params_shapes():
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={},
        audit=RecordingAudit(),
        id_factory=lambda: "audit-1",
    )
    assert broker.handle(request(actor={"type": "root"}), PEER)["error"]["code"] == "invalid_input"
    assert broker.handle(request(params=[]), PEER)["error"]["code"] == "invalid_input"


def test_broker_denies_operation_before_dispatch():
    audit = RecordingAudit()
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={},
        audit=audit,
        id_factory=lambda: "audit-1",
    )
    result = broker.handle(request(operation="stack.delete"), PEER)
    assert result["error"]["code"] == "denied_operation"
    assert audit.events[-1]["error_code"] == "denied_operation"


def test_broker_enforces_operation_resource_allowlist_before_dispatch():
    called = []
    policy = LimeOpsPolicy.from_mapping(
        {
            "schema_version": "1",
            "defaults": {"timeout_seconds": 1, "max_output_bytes": 4096},
            "operations": {
                "container.logs": {
                    "enabled": True,
                    "resources": ["plex"],
                }
            },
        }
    )
    broker = LimeOpsBroker(
        policy=policy,
        operations={
            "container.logs": OperationDefinition(
                handler=lambda params, _context: called.append(params),
                validate_params=lambda params: params,
                resource_param="name",
            )
        },
        audit=RecordingAudit(),
        id_factory=lambda: "audit-1",
    )
    denied = broker.handle(
        request(operation="container.logs", params={"name": "sonarr"}),
        PEER,
    )
    assert denied["error"]["code"] == "denied_operation"
    assert called == []

    allowed = broker.handle(
        request(operation="container.logs", params={"name": "plex"}),
        PEER,
    )
    assert allowed["ok"] is True
    assert called == [{"name": "plex"}]


def test_broker_reports_policy_allowed_but_unavailable_handler():
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={},
        audit=RecordingAudit(),
        id_factory=lambda: "audit-1",
    )
    result = broker.handle(request(), PEER)
    assert result["error"]["code"] == "unavailable_dependency"


def test_broker_fails_closed_when_request_audit_cannot_persist():
    called = []
    broker = LimeOpsBroker(
        policy=make_policy(),
        operations={
            "system.status": OperationDefinition(
                handler=lambda *_args: called.append(True),
                validate_params=lambda params: params,
            )
        },
        audit=RecordingAudit(results=[False]),
        id_factory=lambda: "audit-1",
    )
    result = broker.handle(request(), PEER)
    assert result["error"]["code"] == "audit_failure"
    assert called == []


def test_broker_converts_validation_and_handler_failures_to_stable_errors():
    def invalid(_params):
        raise ValueError("lines must be between 20 and 500")

    invalid_broker = LimeOpsBroker(
        policy=make_policy(),
        operations={"system.status": OperationDefinition(handler=lambda *_: {}, validate_params=invalid)},
        audit=RecordingAudit(),
        id_factory=lambda: "audit-1",
    )
    assert invalid_broker.handle(request(), PEER)["error"] == {
        "code": "invalid_input",
        "message": "lines must be between 20 and 500",
    }

    failed_broker = LimeOpsBroker(
        policy=make_policy(),
        operations={
            "system.status": OperationDefinition(
                handler=lambda *_args: (_ for _ in ()).throw(RuntimeError("secret detail")),
                validate_params=lambda params: params,
            )
        },
        audit=RecordingAudit(),
        id_factory=lambda: "audit-2",
    )
    failure = failed_broker.handle(request(), PEER)
    assert failure["error"] == {
        "code": "upstream_failure",
        "message": "Operation failed",
    }


def test_broker_enforces_timeout_and_output_limit():
    timeout_broker = LimeOpsBroker(
        policy=make_policy(timeout_seconds=0.01),
        operations={
            "system.status": OperationDefinition(
                handler=lambda *_args: time.sleep(0.05),
                validate_params=lambda params: params,
            )
        },
        audit=RecordingAudit(),
        id_factory=lambda: "audit-timeout",
    )
    assert timeout_broker.handle(request(), PEER)["error"]["code"] == "timeout"

    output_broker = LimeOpsBroker(
        policy=make_policy(max_output_bytes=64),
        operations={
            "system.status": OperationDefinition(
                handler=lambda *_args: {"value": "x" * 100},
                validate_params=lambda params: params,
            )
        },
        audit=RecordingAudit(),
        id_factory=lambda: "audit-output",
    )
    assert output_broker.handle(request(), PEER)["error"]["code"] == "output_limit"


def test_jsonl_audit_writer_appends_durable_private_records(tmp_path):
    path = tmp_path / "logs" / "agent-audit.jsonl"
    writer = JsonlAuditWriter(path, clock=lambda: "2026-07-12T12:00:00+00:00")
    assert writer.record({"phase": "request", "audit_id": "audit-1"}) is True
    assert writer.record({"phase": "result", "audit_id": "audit-1"}) is True

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["phase"] for record in records] == ["request", "result"]
    assert records[0]["ts"] == "2026-07-12T12:00:00+00:00"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640


def test_jsonl_audit_writer_reports_failure(tmp_path):
    writer = JsonlAuditWriter(tmp_path / "missing-parent" / "audit.jsonl", create_parent=False)
    assert writer.record({"phase": "request"}) is False
