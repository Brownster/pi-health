"""AA-003 gateway domain: conversation store, usage ledger, turn orchestration."""

import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from agent_gateway.conversation import ConversationStore
from agent_gateway.gateway import AgentGateway, GatewayConfig
from agent_gateway.provider import (
    FinalAnswer,
    Message,
    ProviderAuthError,
    ProviderTimeoutError,
    ToolCall,
)
from agent_gateway.usage import UsageLedger
from agent_transport.gateway_contract import (
    TurnBusyError,
    TurnError,
    TurnLimitError,
    TurnRequest,
    TurnUnavailableError,
)


def _request(text="why is jellyfin down?", conversation="conv-1"):
    return TurnRequest(
        conversation_id=conversation,
        channel_id="chan-1",
        root_post_id="root-1",
        post_id="p1",
        actor_username="marc",
        text=text,
    )


class ScriptedProvider:
    """Yields scripted replies; can run a side effect per invocation."""

    def __init__(self, replies, side_effect=None):
        self.replies = list(replies)
        self.calls = []
        self.side_effect = side_effect

    def invoke(self, context, *, timeout_seconds):
        self.calls.append((context, timeout_seconds))
        if self.side_effect:
            self.side_effect()
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeExecutor:
    def __init__(self, envelope=None, raises=None):
        self.calls = []
        self.envelope = envelope or {
            "ok": True,
            "data": {"status": "exited"},
            "warnings": [],
            "error": None,
            "audit_id": "audit-1",
        }
        self.raises = raises

    def __call__(self, operation, params, actor):
        self.calls.append((operation, params, actor))
        if self.raises:
            raise self.raises
        return self.envelope


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def _gateway(tmp_path, provider, executor=None, **config_overrides):
    return AgentGateway(
        state_dir=tmp_path,
        provider=provider,
        limeops_executor=executor or FakeExecutor(),
        config=GatewayConfig(**config_overrides),
        context_provider=lambda: "LimeOS canonical context",
    )


# -- conversation store ---------------------------------------------------------
def test_conversation_store_persists_and_bounds_history(tmp_path):
    store = ConversationStore(tmp_path, max_messages=3)
    for index in range(5):
        store.append("conv-1", Message(role="user", text=f"m{index}"))
    reloaded = ConversationStore(tmp_path, max_messages=3).messages("conv-1")
    assert [message.text for message in reloaded] == ["m2", "m3", "m4"]


def test_conversation_store_rejects_invalid_ids(tmp_path):
    with pytest.raises(ValueError):
        ConversationStore(tmp_path).messages("../escape")


# -- usage ledger ------------------------------------------------------------------
def test_usage_ledger_counts_and_rolls_over_daily(tmp_path):
    moment = {"now": datetime(2026, 7, 12, 23, 0, tzinfo=timezone.utc)}
    ledger = UsageLedger(tmp_path, clock=lambda: moment["now"])
    ledger.record_invocation()
    ledger.record_invocation()
    assert ledger.invocations_today() == 2
    moment["now"] += timedelta(hours=2)  # past UTC midnight
    assert ledger.invocations_today() == 0
    ledger.record_invocation()
    assert ledger.totals()["total_invocations"] == 3
    # Persisted across restart.
    assert UsageLedger(tmp_path, clock=lambda: moment["now"]).invocations_today() == 1


# -- gateway turns -------------------------------------------------------------------
def test_final_answer_returns_and_persists_conversation(tmp_path):
    provider = ScriptedProvider([FinalAnswer(text="jellyfin exited at 09:14.")])
    gateway = _gateway(tmp_path, provider)

    result = gateway.handle_turn(_request())

    assert result.text == "jellyfin exited at 09:14."
    stored = ConversationStore(tmp_path).messages("conv-1")
    assert [message.role for message in stored] == ["user", "assistant"]
    assert provider.calls[0][0].system_context == "LimeOS canonical context"
    assert gateway.usage_totals() == {
        "total_turns": 1,
        "total_invocations": 1,
        "invocations_today": 1,
    }


def test_tool_loop_executes_limeops_and_feeds_result_back(tmp_path):
    provider = ScriptedProvider([
        ToolCall(operation="container.status", params={"name": "jellyfin"}),
        FinalAnswer(text="jellyfin is stopped."),
    ])
    executor = FakeExecutor()
    gateway = _gateway(tmp_path, provider, executor)

    result = gateway.handle_turn(_request())

    assert result.text == "jellyfin is stopped."
    operation, params, actor = executor.calls[0]
    assert operation == "container.status" and params == {"name": "jellyfin"}
    # The broker's frozen actor contract: {type, id, username?}.
    assert actor == {"type": "mattermost", "id": "marc", "username": "marc"}
    # The broker audit id is captured for the usage/audit views.
    records = [
        json.loads(line)
        for line in (tmp_path / "usage-records.jsonl").read_text().splitlines()
    ]
    assert records[0]["tool_audit_ids"] == ["audit-1"]
    # The bounded tool result was appended for the second invocation.
    second_context = provider.calls[1][0]
    tool_messages = [m for m in second_context.messages if m.role == "tool"]
    assert "container.status" in tool_messages[0].text
    assert '"status": "exited"' in tool_messages[0].text


def test_disallowed_operation_is_refused_without_reaching_the_broker(tmp_path):
    provider = ScriptedProvider([
        ToolCall(operation="container.restart", params={"name": "jellyfin"}),
        FinalAnswer(text="done"),
    ])
    executor = FakeExecutor()
    gateway = _gateway(tmp_path, provider, executor)

    gateway.handle_turn(_request())

    assert executor.calls == []  # never forwarded
    tool_messages = [
        m for m in provider.calls[1][0].messages if m.role == "tool"
    ]
    assert "denied_operation" in tool_messages[0].text


def test_broker_failure_becomes_a_bounded_tool_result(tmp_path):
    provider = ScriptedProvider([
        ToolCall(operation="disk.health", params={}),
        FinalAnswer(text="could not read disk health"),
    ])
    gateway = _gateway(tmp_path, provider, FakeExecutor(raises=ConnectionError("socket down")))

    result = gateway.handle_turn(_request())

    assert result.text == "could not read disk health"
    tool_messages = [m for m in provider.calls[1][0].messages if m.role == "tool"]
    assert "unavailable_dependency" in tool_messages[0].text
    assert "socket down" not in tool_messages[0].text  # internals never reach the prompt


def test_tool_rounds_exhausted_fails_the_turn(tmp_path):
    provider = ScriptedProvider(
        [ToolCall(operation="system.status", params={})] * 3
    )
    gateway = _gateway(tmp_path, provider, tool_rounds_per_turn=3)

    with pytest.raises(TurnError):
        gateway.handle_turn(_request())
    assert len(provider.calls) == 3


def test_daily_invocation_limit_raises_typed_error(tmp_path):
    provider = ScriptedProvider([
        ToolCall(operation="system.status", params={}),
        FinalAnswer(text="never reached"),
    ])
    gateway = _gateway(tmp_path, provider, invocations_per_day=1)

    with pytest.raises(TurnLimitError):
        gateway.handle_turn(_request())
    assert len(provider.calls) == 1  # the second invocation was blocked


def test_turn_timeout_deadline_is_enforced_across_rounds(tmp_path):
    clock = FakeClock()
    provider = ScriptedProvider(
        [ToolCall(operation="system.status", params={})],
        side_effect=lambda: clock.advance(301),
    )
    gateway = AgentGateway(
        state_dir=tmp_path,
        provider=provider,
        limeops_executor=FakeExecutor(),
        config=GatewayConfig(turn_timeout_seconds=300),
        clock=clock,
    )
    with pytest.raises(TurnError):
        gateway.handle_turn(_request())


@pytest.mark.parametrize(
    ("provider_error", "expected"),
    [
        (ProviderAuthError("expired"), TurnUnavailableError),
        (ProviderTimeoutError("slow"), TurnError),
    ],
)
def test_provider_errors_map_to_typed_turn_errors(tmp_path, provider_error, expected):
    gateway = _gateway(tmp_path, ScriptedProvider([provider_error]))
    with pytest.raises(expected):
        gateway.handle_turn(_request())


def test_failed_turn_is_recorded_as_failed(tmp_path):
    gateway = _gateway(tmp_path, ScriptedProvider([ProviderTimeoutError("slow")]))
    with pytest.raises(TurnError):
        gateway.handle_turn(_request())
    records = [
        json.loads(line)
        for line in (tmp_path / "usage-records.jsonl").read_text().splitlines()
    ]
    assert records[0]["outcome"] == "error"
    assert records[0]["rounds"] == 1


def test_disable_switch_fails_fast_and_aborts_between_rounds(tmp_path):
    gateway_holder = {}

    provider = ScriptedProvider(
        [ToolCall(operation="system.status", params={}), FinalAnswer(text="x")],
        side_effect=lambda: gateway_holder["gateway"].disable(),
    )
    gateway = _gateway(tmp_path, provider)
    gateway_holder["gateway"] = gateway

    with pytest.raises(TurnUnavailableError):
        gateway.handle_turn(_request())  # disabled after round 1 -> aborts before round 2
    with pytest.raises(TurnUnavailableError):
        gateway.handle_turn(_request())  # disabled gateway fails fast
    gateway.enable()
    assert gateway.handle_turn(_request("again")).text == "x"


def test_concurrent_turn_is_busy(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class BlockingProvider:
        def invoke(self, context, *, timeout_seconds):
            started.set()
            release.wait(timeout=5)
            return FinalAnswer(text="slow answer")

    gateway = _gateway(tmp_path, BlockingProvider())
    worker = threading.Thread(target=gateway.handle_turn, args=(_request(),))
    worker.start()
    try:
        assert started.wait(timeout=5)
        with pytest.raises(TurnBusyError):
            gateway.handle_turn(_request(conversation="conv-other"))
    finally:
        release.set()
        worker.join(timeout=5)


def test_final_answer_is_bounded_to_the_output_ceiling(tmp_path):
    gateway = _gateway(tmp_path, ScriptedProvider([FinalAnswer(text="z" * (64 * 1024))]))
    result = gateway.handle_turn(_request())
    assert len(result.text.encode()) == 32 * 1024
