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


def test_context_reports_readonly_capabilities_and_operations():
    operations = build_operations(make_deps())
    data = operations["context"].handler({}, None)
    assert data["capabilities"] == "read-only"
    assert "container.logs" in data["operations"]


# -- through the real broker ---------------------------------------------------------
def test_container_status_success_envelope_through_broker():
    broker = make_broker(build_operations(make_deps()))
    response = call(broker, "container.status", {"name": "jellyfin"})
    assert response["ok"] is True
    assert response["data"] == {"name": "jellyfin", "status": "exited"}


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
            actor_username="marc",
            text="@limeos what happened to jellyfin?",
        )
    )
    assert result.text == "jellyfin has exited; want the logs?"
    assert '"status": "exited"' in provider.tool_texts[0]
