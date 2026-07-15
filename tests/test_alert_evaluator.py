from datetime import datetime, timedelta, timezone

from alert_evaluator import (
    AlertEvaluator,
    AlertEvaluatorConfig,
    Signal,
)
from alert_notifier import (
    MattermostWebhookNotifier,
    RecordingNotifier,
    render_mattermost_payload,
)


class Clock:
    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)

    def tick(self, seconds: int = 60):
        self.now += timedelta(seconds=seconds)

    def __call__(self) -> datetime:
        return self.now


def _evaluator(tmp_path, *, threshold=2, clock=None):
    return AlertEvaluator(
        state_path=tmp_path / "alerts.json",
        config=AlertEvaluatorConfig(fail_threshold=threshold),
        clock=clock or Clock(),
    )


def _fail(key="container:jellyfin", **kw):
    return Signal(key=key, ok=False, summary="jellyfin exited", kind="container", **kw)


def _ok(key="container:jellyfin"):
    return Signal(key=key, ok=True, summary="jellyfin running", kind="container")


def test_incident_only_opens_after_threshold_consecutive_failures(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=2)

    assert evaluator.evaluate([_fail()]) == []  # first failure: below threshold, no noise
    notifications = evaluator.evaluate([_fail()])  # second: opens
    assert [n.event for n in notifications] == ["incident"]
    assert notifications[0].key == "container:jellyfin"
    assert len(evaluator.active_incidents) == 1


def test_continuing_fault_is_not_re_notified(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    assert [n.event for n in evaluator.evaluate([_fail()])] == ["incident"]
    # Still broken on the next ticks -> no repeated incidents.
    assert evaluator.evaluate([_fail()]) == []
    assert evaluator.evaluate([_fail()]) == []


def test_recovery_emitted_once_when_fault_clears(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    evaluator.evaluate([_fail()])
    recovery = evaluator.evaluate([_ok()])
    assert [n.event for n in recovery] == ["recovery"]
    assert evaluator.active_incidents == []
    # A subsequent healthy reading does not re-announce recovery.
    assert evaluator.evaluate([_ok()]) == []


def test_transient_failure_below_threshold_then_recovery_is_silent(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=3)
    evaluator.evaluate([_fail()])
    evaluator.evaluate([_fail()])
    # Clears before opening an incident -> nothing to announce.
    assert evaluator.evaluate([_ok()]) == []
    assert evaluator.active_incidents == []


def test_missing_key_does_not_spuriously_recover(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    evaluator.evaluate([_fail()])
    # Signal absent this round (source momentarily unavailable) -> incident stays active.
    assert evaluator.evaluate([]) == []
    assert len(evaluator.active_incidents) == 1


def test_state_persists_across_restart(tmp_path):
    clock = Clock()
    first = _evaluator(tmp_path, threshold=1, clock=clock)
    first.evaluate([_fail()])

    # New instance loads persisted incident state; the fault is not re-opened, and a real
    # recovery still fires exactly once.
    second = _evaluator(tmp_path, threshold=1, clock=clock)
    assert len(second.active_incidents) == 1
    assert second.evaluate([_fail()]) == []
    assert [n.event for n in second.evaluate([_ok()])] == ["recovery"]


def test_independent_keys_tracked_separately(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    notifications = evaluator.evaluate([
        _fail(key="container:jellyfin"),
        Signal(key="smart:/dev/sda", ok=False, summary="SMART FAILING", kind="smart", severity="critical"),
    ])
    assert {n.key for n in notifications} == {"container:jellyfin", "smart:/dev/sda"}
    assert {n.severity for n in notifications} == {"warning", "critical"}


def test_silenced_incident_is_delivered_once_when_policy_allows(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    signal = _fail()

    assert evaluator.evaluate([signal], should_notify=lambda _signal, _event: False) == []
    notifications = evaluator.evaluate(
        [signal], should_notify=lambda _signal, _event: True
    )
    assert [(note.event, note.key) for note in notifications] == [
        ("incident", "container:jellyfin")
    ]
    assert evaluator.evaluate(
        [signal], should_notify=lambda _signal, _event: True
    ) == []


def test_disabled_category_suppresses_recovery(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    evaluator.evaluate([_fail()])

    assert evaluator.evaluate(
        [_ok()], should_notify=lambda _signal, _event: False
    ) == []


def test_transition_callback_records_silenced_incident_and_recovery(tmp_path):
    evaluator = _evaluator(tmp_path, threshold=1)
    transitions = []

    assert evaluator.evaluate(
        [_fail()],
        should_notify=lambda _signal, _event: False,
        on_transition=transitions.append,
    ) == []
    assert evaluator.evaluate(
        [_ok()],
        should_notify=lambda _signal, _event: False,
        on_transition=transitions.append,
    ) == []

    assert [(event.event, event.key) for event in transitions] == [
        ("incident", "container:jellyfin"),
        ("recovery", "container:jellyfin"),
    ]


def test_mattermost_notifier_posts_rendered_payload():
    from alert_evaluator import Notification

    calls = []
    notifier = MattermostWebhookNotifier(
        "https://mm.example/hooks/abc",
        poster=lambda url, payload: calls.append((url, payload)),
    )
    recorder = RecordingNotifier()
    note = Notification(
        event="incident", key="smart:/dev/sda", kind="smart",
        severity="critical", summary="SMART FAILING", at="2026-07-09T12:00:00+00:00",
    )
    notifier.send(note)
    recorder.send(note)

    assert calls[0][0] == "https://mm.example/hooks/abc"
    attachment = calls[0][1]["attachments"][0]
    assert attachment["color"] == "#d24b4b"  # critical
    assert "smart:/dev/sda" in attachment["title"]
    assert attachment["text"] == "SMART FAILING"
    assert recorder.sent == [note]


def test_render_recovery_payload_is_green():
    from alert_evaluator import Notification

    payload = render_mattermost_payload(
        Notification(event="recovery", key="mount:/mnt/data", kind="mount",
                     severity="warning", summary="mount restored", at="t")
    )
    assert payload["attachments"][0]["color"] == "#3aa657"
    assert "Recovered" in payload["attachments"][0]["title"]
