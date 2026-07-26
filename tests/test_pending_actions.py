from datetime import datetime, timedelta, timezone

from pending_actions import MAX_ACTIONS, REBOOT_REQUIRED, PendingActionStore
from ports import JsonFileRepository


class SteppingClock:
    def __init__(self):
        self.now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        self.now += timedelta(minutes=1)
        return self.now


def make_store(tmp_path, clock=None):
    return PendingActionStore(
        repository=JsonFileRepository(),
        path=tmp_path / "pending-actions.json",
        clock=clock or SteppingClock(),
    )


def test_a_recorded_action_survives_a_new_store_instance(tmp_path):
    """The update that raises a notice also restarts the service."""
    make_store(tmp_path).record(
        REBOOT_REQUIRED, title="Reboot required", detail="Applies at next boot", command="sudo reboot"
    )

    actions = make_store(tmp_path).list()

    assert len(actions) == 1
    assert actions[0]["id"] == REBOOT_REQUIRED
    assert actions[0]["title"] == "Reboot required"
    assert actions[0]["command"] == "sudo reboot"
    assert actions[0]["severity"] == "attention"


def test_recording_the_same_action_twice_keeps_the_first_timestamp(tmp_path):
    store = make_store(tmp_path)
    first = store.record(REBOOT_REQUIRED, title="Reboot required")
    second = store.record(REBOOT_REQUIRED, title="Reboot required again")

    assert second["created_at"] == first["created_at"]
    assert second["title"] == "Reboot required"
    assert len(store.list()) == 1


def test_dismiss_removes_the_action_and_reports_whether_it_was_there(tmp_path):
    store = make_store(tmp_path)
    store.record(REBOOT_REQUIRED, title="Reboot required")

    assert store.dismiss(REBOOT_REQUIRED) is True
    assert store.list() == []
    assert store.dismiss(REBOOT_REQUIRED) is False


def test_actions_are_listed_most_severe_first(tmp_path):
    store = make_store(tmp_path)
    store.record("a", title="Info", severity="info")
    store.record("b", title="Critical", severity="critical")
    store.record("c", title="Attention", severity="attention")

    assert [item["id"] for item in store.list()] == ["b", "c", "a"]


def test_an_unknown_severity_falls_back_to_attention(tmp_path):
    store = make_store(tmp_path)
    store.record("a", title="Odd", severity="apocalyptic")

    assert store.list()[0]["severity"] == "attention"


def test_the_store_is_bounded(tmp_path):
    store = make_store(tmp_path)
    for index in range(MAX_ACTIONS + 5):
        store.record(f"action-{index}", title=f"Action {index}")

    actions = store.list()
    assert len(actions) == MAX_ACTIONS
    assert not any(item["id"] == "action-0" for item in actions)


def test_an_empty_action_id_is_rejected(tmp_path):
    store = make_store(tmp_path)

    assert store.record("   ", title="Nameless") is None
    assert store.list() == []


def test_a_corrupt_store_reads_as_empty(tmp_path):
    path = tmp_path / "pending-actions.json"
    path.write_text("not json at all")

    store = PendingActionStore(repository=JsonFileRepository(), path=path)

    assert store.list() == []
    assert store.record("a", title="Works anyway") is not None
