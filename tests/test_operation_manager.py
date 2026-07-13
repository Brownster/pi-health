import pytest

from operation_manager import OperationCapacityError, OperationRegistry


class FakeClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class DormantThread:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        pass


def immediate_registry(**kwargs):
    return OperationRegistry(thread_factory=ImmediateThread, **kwargs)


def test_registry_replays_trimmed_events_with_monotonic_ids():
    registry = immediate_registry(event_limit=2)
    operation = registry.create(
        owner="opaque-owner",
        username="alice",
        kind="stack",
        target="media",
        producer=lambda: iter(
            [
                {"line": "one"},
                {"line": "two"},
                {"done": True},
            ]
        ),
    )

    batch = registry.events_since(
        operation.operation_id,
        expected_kind="stack",
        owner="opaque-owner",
        cursor=0,
    )

    assert [event.event_id for event in batch.events] == [1, 2]
    assert [event.payload for event in batch.events] == [
        {"line": "two"},
        {"done": True},
    ]
    assert batch.next_cursor == 3
    assert batch.complete is True


def test_registry_rejects_wrong_owner_and_kind():
    registry = immediate_registry()
    operation = registry.create(
        owner="opaque-owner",
        username="alice",
        kind="stack",
        target="media",
        producer=lambda: iter([{"done": True}]),
    )

    assert not registry.is_owner(
        operation.operation_id,
        expected_kind="stack",
        owner="different-owner",
    )
    assert registry.events_since(
        operation.operation_id,
        expected_kind="catalog-install",
        owner="opaque-owner",
    ) is None


def test_registry_prunes_completed_operations_after_ttl():
    clock = FakeClock()
    registry = immediate_registry(clock=clock, ttl_seconds=10)
    operation = registry.create(
        owner="opaque-owner",
        username="alice",
        kind="stack",
        target="media",
        producer=lambda: iter([{"done": True}]),
    )
    clock.value = 11

    assert not registry.is_owner(
        operation.operation_id,
        expected_kind="stack",
        owner="opaque-owner",
    )


def test_registry_rejects_capacity_when_all_operations_are_active():
    registry = OperationRegistry(
        thread_factory=DormantThread,
        operation_limit=1,
    )
    registry.create(
        owner="opaque-owner",
        username="alice",
        kind="stack",
        target="one",
        producer=lambda: iter(()),
    )

    with pytest.raises(OperationCapacityError, match="Too many"):
        registry.create(
            owner="opaque-owner",
            username="alice",
            kind="stack",
            target="two",
            producer=lambda: iter(()),
        )


@pytest.mark.parametrize(
    ("producer", "expected_error"),
    [
        (lambda: iter([{"line": "no terminal event"}]), "ended without a result"),
        (lambda: (_ for _ in ()).throw(RuntimeError("producer failed")), "producer failed"),
    ],
)
def test_registry_records_terminal_error(producer, expected_error):
    registry = immediate_registry()
    operation = registry.create(
        owner="opaque-owner",
        username="alice",
        kind="stack",
        target="media",
        producer=producer,
    )

    batch = registry.events_since(
        operation.operation_id,
        expected_kind="stack",
        owner="opaque-owner",
    )

    assert batch.complete is True
    assert expected_error in batch.events[-1].payload["error"]


def test_ephemeral_events_are_redacted_when_operation_finishes():
    registry = immediate_registry()
    operation = registry.create(
        owner="owner",
        username="admin",
        kind="agent-auth",
        target="claude",
        producer=lambda: iter(
            [
                {"authorization_url": "https://claude.ai/secret", "_ephemeral": True},
                {"done": True},
            ]
        ),
    )
    batch = registry.events_since(
        operation.operation_id,
        expected_kind="agent-auth",
        owner="owner",
    )
    assert batch.events[0].payload == {"expired": True}


def test_agent_operation_unexpected_exception_is_bounded_and_private():
    registry = immediate_registry()
    operation = registry.create(
        owner="owner",
        username="admin",
        kind="agent-repair",
        target="claude",
        producer=lambda: (_ for _ in ()).throw(
            RuntimeError("token=SECRET /etc/limeos/integrations/agents.env")
        ),
    )
    batch = registry.events_since(
        operation.operation_id,
        expected_kind="agent-repair",
        owner="owner",
    )
    assert batch.events[-1].payload == {"error": "AI Agents operation failed"}
