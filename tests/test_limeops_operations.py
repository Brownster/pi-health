"""AA-002 diagnostic operations: redaction, sanitization, validators, broker + gateway
integration behind the frozen AA-001 contract."""

import json

import pytest

from limeops.broker import LimeOpsBroker, PeerIdentity
from limeops.operations import (
    DEFAULT_LOG_LINES,
    MAX_LOG_TEXT_BYTES,
    DiagnosticDependencies,
    bounded_log,
    build_operations,
    redact_text,
    sanitize_stack_details,
)
from limeops.policy import LimeOpsPolicy

PEER = PeerIdentity(pid=123, uid=1001, gid=1001)
ACTOR = {"type": "mattermost", "id": "marc", "username": "marc"}


class RecordingAudit:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(dict(event))
        return True


def make_deps(**overrides):
    values = {
        "system_status": lambda: {"hostname": "wybie"},
        "list_containers": lambda: [{"name": "jellyfin", "status": "exited"}],
        "container_status": lambda name: {"name": name, "status": "exited"},
        "container_logs": lambda name, lines: f"{name} logs ({lines} lines)",
        "list_stacks": lambda: [{"name": "media"}],
        "stack_status": lambda name: {"name": name, "status": {"state": "partial"}},
        "stack_inspect": lambda name: {"name": name, "services": []},
        "service_status": lambda unit: {"unit": unit, "active_state": "active"},
        "service_logs": lambda unit, lines: f"{unit} journal",
        "disk_health": lambda: {"disks": []},
        "mount_status": lambda: {"mounts": []},
        "snapraid_status": lambda: {"status": "healthy"},
        "network_check": lambda target: {"target": target, "ok": True},
        "installation_inventory": lambda: {"units": {}},
        "package_status": lambda: {"ok": True, "drift": [], "packages": []},
        "action_precondition": lambda operation, params: {
            "operation": operation,
            "capability_version": "1",
            "target": params["name"],
            "params": dict(params),
            "precondition_hash": "a" * 64,
        },
    }
    values.update(overrides)
    return DiagnosticDependencies(**values)


def make_broker(operations, *, resources=("jellyfin",), max_output_bytes=131072):
    policy_ops = {}
    for name in operations:
        entry = {"enabled": True, "timeout_seconds": 2, "max_output_bytes": max_output_bytes}
        if name in {"container.status", "container.logs", "stack.status", "stack.inspect"}:
            entry["resources"] = list(resources)
        if name in {"service.status", "service.logs"}:
            entry["resources"] = ["docker", "pi-health"]
        if name == "network.check":
            entry["resources"] = ["gateway", "internet", "mattermost"]
        policy_ops[name] = entry
    policy = LimeOpsPolicy.from_mapping(
        {
            "schema_version": "1",
            "defaults": {"timeout_seconds": 2, "max_output_bytes": max_output_bytes},
            "operations": policy_ops,
        }
    )
    return LimeOpsBroker(policy=policy, operations=operations, audit=RecordingAudit())


def call(broker, operation, params=None):
    return broker.handle(
        {
            "schema_version": "1",
            "request_id": "request-1",
            "operation": operation,
            "params": params or {},
            "actor": ACTOR,
        },
        PEER,
    )


# -- redaction / bounding ---------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("db password=hunter2 retry", "hunter2"),
        ("TOKEN: abc.def-123", "abc.def-123"),
        ("api_key=sk-live-9x", "sk-live-9x"),
        ("Authorization: Bearer eyJhbGciOi", "eyJhbGciOi"),
        ("postgres://mmuser:dbpass@postgres:5432/mm", "dbpass"),
        ("posting to https://mm.lan/hooks/abc123secret", "abc123secret"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA=="),
        (
            "DATABASE_URL=postgresql://lime:password@db.internal/limeos",
            "postgresql://lime:password@db.internal/limeos",
        ),
    ],
)
def test_redact_text_removes_secret_material(raw, must_not_contain):
    assert must_not_contain not in redact_text(raw)


def test_redact_text_keeps_ordinary_log_lines():
    line = "2026-07-12 jellyfin exited with code 1 after 3s"
    assert redact_text(line) == line


def test_redact_text_removes_complete_database_connection_value():
    assert (
        redact_text("DATABASE_URL=postgresql://lime:password@db.internal/limeos")
        == "DATABASE_URL=[redacted]"
    )


def test_bounded_log_truncates_and_flags():
    result = bounded_log("x" * (MAX_LOG_TEXT_BYTES + 500))
    assert result["truncated"] is True
    assert len(result["text"].encode()) <= MAX_LOG_TEXT_BYTES
    assert bounded_log("short password=secret")["text"] == "short password=[redacted]"


# -- stack sanitization -------------------------------------------------------------
def test_sanitize_stack_details_exposes_structure_never_env_values():
    details = {
        "name": "media",
        "compose_file": "compose.yaml",
        "has_env": True,
        "compose_content": "raw yaml with API_KEY=supersecret",
        "env_content": "DB_PASSWORD=supersecret",
        "status": {"state": "running"},
    }
    compose = {
        "services": {
            "jellyfin": {
                "image": "linuxserver/jellyfin:latest",
                "ports": ["8096:8096"],
                "restart": "unless-stopped",
                "environment": {"PUID": "1000", "API_KEY": "supersecret"},
            },
            "vpn": {"image": "qmcgaw/gluetun", "environment": ["WG_KEY=alsosecret"]},
        }
    }
    result = sanitize_stack_details(details, compose)
    blob = json.dumps(result)
    assert "supersecret" not in blob and "alsosecret" not in blob
    assert "compose_content" not in result and "env_content" not in result
    jellyfin = next(s for s in result["services"] if s["name"] == "jellyfin")
    assert jellyfin["environment_keys"] == ["API_KEY", "PUID"]  # keys visible, values gone
    vpn = next(s for s in result["services"] if s["name"] == "vpn")
    assert vpn["environment_keys"] == ["WG_KEY"]


# -- operation registry -----------------------------------------------------------------
def test_build_operations_matches_the_default_policy_exactly():
    with open("config/agent-policy.default.json") as handle:
        policy_operations = set(json.load(handle)["operations"])
    operations = build_operations(make_deps())
    assert set(operations) == policy_operations
    # Resource-scoped operations declare their resource parameter for the broker.
    assert operations["container.logs"].resource_param == "name"
    assert operations["service.status"].resource_param == "unit"
    assert operations["network.check"].resource_param == "target"
    assert operations["disk.health"].resource_param is None


def test_gateway_allowlist_matches_the_shipped_read_only_policy():
    # The broker policy is authoritative, but the gateway forwards only its own allowlist;
    # the two must stay in step so no read op is registered yet unreachable (or vice versa).
    from agent_gateway.gateway import GatewayConfig

    with open("config/agent-policy.default.json") as handle:
        policy_operations = set(json.load(handle)["operations"])
    model_operations = set(GatewayConfig().allowed_operations)
    assert policy_operations - model_operations == {
        "action.approve",
        "action.precondition",
        "action.reject",
    }
    assert model_operations < policy_operations
    assert set(build_operations(make_deps())) == policy_operations


def test_context_reports_read_and_propose_capabilities_and_operations():
    operations = build_operations(make_deps())
    data = operations["context"].handler({}, None)
    assert data["capabilities"] == "read-and-propose"
    assert "container.logs" in data["operations"]
    assert "action.precondition" not in data["operations"]


# -- through the real broker ---------------------------------------------------------
def test_container_status_success_envelope_through_broker():
    broker = make_broker(build_operations(make_deps()))
    response = call(broker, "container.status", {"name": "jellyfin"})
    assert response["ok"] is True
    assert response["data"] == {"name": "jellyfin", "status": "exited"}


def test_packages_status_read_op_returns_compliance_report():
    deps = make_deps(
        package_status=lambda: {"ok": False, "drift": ["claude-code"], "packages": [
            {"name": "claude-code", "compliant": False, "installed": "2.1.208"}
        ]}
    )
    broker = make_broker(build_operations(deps))
    response = call(broker, "packages.status")
    assert response["ok"] is True
    assert response["data"]["drift"] == ["claude-code"]


def test_packages_pending_read_op_returns_held_updates():
    deps = make_deps(
        package_pending=lambda: {"pending": [
            {"name": "claude-code", "installed": "2.1.207-1", "candidate": "2.1.212-1", "critical": True}
        ]}
    )
    broker = make_broker(build_operations(deps))
    response = call(broker, "packages.pending")
    assert response["ok"] is True
    assert response["data"]["pending"][0]["candidate"] == "2.1.212-1"


def test_action_propose_forwards_actor_and_current_audit_as_evidence():
    calls = []

    def propose(params, actor, audit_id):
        calls.append((params, actor, audit_id))
        return {"action": {"id": "action-1", "state": "awaiting_approval"}, "created": True}

    broker = make_broker(build_operations(make_deps(action_propose=propose)))
    response = call(
        broker,
        "action.propose",
        {
            "operation": "container.restart",
            "params": {"name": "jellyfin"},
            "reason": "Container is unhealthy",
            "evidence_ids": ["earlier-audit"],
            "idempotency_key": "mattermost:post-1:restart",
        },
    )

    assert response["ok"] is True
    assert response["data"]["action"]["state"] == "awaiting_approval"
    params, actor, audit_id = calls[0]
    assert params["evidence_ids"] == ["earlier-audit"]
    assert actor == ACTOR
    assert audit_id == response["audit_id"]


def test_action_precondition_returns_only_the_trusted_hash_contract():
    calls = []

    def precondition(operation, params):
        calls.append((operation, params))
        return {
            "operation": operation,
            "capability_version": "1",
            "target": params["name"],
            "params": dict(params),
            "precondition_hash": "b" * 64,
        }

    broker = make_broker(
        build_operations(make_deps(action_precondition=precondition))
    )
    response = call(
        broker,
        "action.precondition",
        {
            "operation": "container.restart",
            "params": {"name": "jellyfin"},
        },
    )

    assert response["ok"] is True
    assert response["data"]["precondition_hash"] == "b" * 64
    assert calls == [
        ("container.restart", {"name": "jellyfin"})
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"operation": "container.restart", "params": []},
        {"operation": "", "params": {"name": "jellyfin"}},
        {
            "operation": "container.restart",
            "params": {"name": "jellyfin"},
            "precondition_hash": "forged",
        },
    ],
)
def test_action_precondition_rejects_malformed_or_forged_fields(params):
    calls = []
    broker = make_broker(
        build_operations(
            make_deps(action_precondition=lambda *args: calls.append(args))
        )
    )

    response = call(broker, "action.precondition", params)

    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_input"
    assert calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"operation": "container.restart", "params": {}, "reason": "needed",
         "idempotency_key": "valid-key", "trigger": "autonomous"},
        {"operation": "container.restart", "params": [], "reason": "needed",
         "idempotency_key": "valid-key"},
        {"operation": "container.restart", "params": {}, "reason": "",
         "idempotency_key": "valid-key"},
    ],
)
def test_action_propose_rejects_malformed_or_authority_bypass_params(params):
    calls = []
    broker = make_broker(
        build_operations(make_deps(action_propose=lambda *args: calls.append(args)))
    )
    response = call(broker, "action.propose", params)
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_input"
    assert calls == []


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_action_decisions_forward_immutable_actor_outside_model_allowlist(decision):
    calls = []

    def decide(action_id, actor):
        calls.append((action_id, actor))
        return {"decision_applied": True, "action": {"id": action_id}}

    broker = make_broker(
        build_operations(make_deps(**{f"action_{decision}": decide}))
    )
    response = call(broker, f"action.{decision}", {"action_id": "action-1"})

    assert response["ok"] is True
    assert response["data"]["decision_applied"] is True
    assert calls == [("action-1", ACTOR)]


def test_action_decision_rejects_unknown_fields_before_handler():
    calls = []
    broker = make_broker(
        build_operations(make_deps(action_approve=lambda *args: calls.append(args)))
    )
    response = call(
        broker,
        "action.approve",
        {"action_id": "action-1", "authority_mode": "autonomous"},
    )
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_input"
    assert calls == []


def test_finding_propose_forwards_only_a_local_draft_and_current_audit():
    calls = []

    def propose(params, actor, audit_id):
        calls.append((params, actor, audit_id))
        return {"finding": {"id": "finding-1", "state": "draft", "publication": None},
                "created": True}

    broker = make_broker(build_operations(make_deps(finding_propose=propose)))
    finding = {
        "kind": "feature_request",
        "title": "Add bounded stack repair",
        "summary": "A typed repair capability is missing.",
        "component": "agent-actions",
        "affected_version": "",
        "expected_behavior": "",
        "actual_behavior": "",
        "reproduction_steps": [],
        "impact": "Operators must repair the stack manually.",
        "frequency": "",
        "workaround": "",
        "confidence": "medium",
        "acceptance_criteria": ["Add verified stack.reconcile."],
        "source_type": "user_discussion",
    }
    response = call(
        broker,
        "finding.propose",
        {"finding": finding, "evidence_ids": ["audit-earlier"]},
    )
    assert response["ok"] is True
    assert response["data"]["finding"]["publication"] is None
    assert calls[0][0] == {"finding": finding, "evidence_ids": ["audit-earlier"]}
    assert calls[0][1] == ACTOR
    assert calls[0][2] == response["audit_id"]


def test_container_logs_flow_redacts_and_defaults_lines():
    deps = make_deps(
        container_logs=lambda name, lines: f"{name} lines={lines} password=hunter2"
    )
    broker = make_broker(build_operations(deps))
    response = call(broker, "container.logs", {"name": "jellyfin"})
    assert response["ok"] is True
    assert f"lines={DEFAULT_LOG_LINES}" in response["data"]["text"]
    assert "hunter2" not in response["data"]["text"]


def test_resource_outside_allowlist_is_denied_before_the_handler():
    calls = []
    deps = make_deps(container_status=lambda name: calls.append(name) or {"name": name})
    broker = make_broker(build_operations(deps), resources=("jellyfin",))
    response = call(broker, "container.status", {"name": "sonarr"})
    assert response["ok"] is False
    assert response["error"]["code"] == "denied_operation"
    assert calls == []


@pytest.mark.parametrize(
    ("operation", "params"),
    [
        ("container.status", {"name": "jellyfin", "extra": True}),
        ("container.logs", {"name": "jellyfin", "lines": 5}),
        ("container.logs", {"name": "jellyfin", "lines": "200"}),
        ("system.status", {"unexpected": 1}),
        ("container.status", {"name": ""}),
    ],
)
def test_invalid_parameters_fail_before_execution(operation, params):
    calls = []
    deps = make_deps(
        system_status=lambda: calls.append("s") or {},
        container_status=lambda name: calls.append(name) or {},
        container_logs=lambda name, lines: calls.append(name) or "",
    )
    broker = make_broker(build_operations(deps))
    response = call(broker, operation, params)
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_input"
    assert calls == []


def test_failing_reader_maps_to_upstream_failure():
    def broken():
        raise ConnectionError("docker socket down")

    broker = make_broker(build_operations(make_deps(disk_health=broken)))
    response = call(broker, "disk.health")
    assert response["ok"] is False
    assert response["error"]["code"] == "upstream_failure"
    assert "docker socket down" not in json.dumps(response)  # internals stay private


# -- full chain: gateway -> broker -> diagnostics -------------------------------------
def test_gateway_tool_call_reaches_diagnostics_through_the_broker(tmp_path):
    from agent_gateway.gateway import AgentGateway, GatewayConfig
    from agent_gateway.provider import FinalAnswer, ToolCall
    from agent_transport.gateway_contract import TurnRequest

    broker = make_broker(build_operations(make_deps()))

    class ChainProvider:
        def __init__(self):
            self.tool_texts = []

        def invoke(self, context, *, timeout_seconds):
            tool_messages = [m for m in context.messages if m.role == "tool"]
            if not tool_messages:
                return ToolCall(operation="container.status", params={"name": "jellyfin"})
            self.tool_texts.append(tool_messages[-1].text)
            return FinalAnswer(text="jellyfin has exited; want the logs?")

    def executor(operation, params, actor):
        return call(broker, operation, params)

    provider = ChainProvider()
    gateway = AgentGateway(
        state_dir=tmp_path,
        provider=provider,
        limeops_executor=executor,
        config=GatewayConfig(),
    )
    result = gateway.handle_turn(
        TurnRequest(
            conversation_id="conv-1",
            channel_id="chan-1",
            root_post_id="root-1",
            post_id="p1",
            actor_id="user-1",
            actor_username="marc",
            text="@limeos what happened to jellyfin?",
        )
    )
    assert result.text == "jellyfin has exited; want the logs?"
    assert '"status": "exited"' in provider.tool_texts[0]
