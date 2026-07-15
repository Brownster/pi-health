import json

import pytest

from alert_evaluator import Notification
from alert_history import AlertEventLedger, MAX_ALERT_EVENTS, MAX_LEDGER_BYTES


def note(event, key="container:jellyfin", at="2026-07-15T12:00:00+00:00"):
    return Notification(
        event=event,
        key=key,
        kind="container",
        severity="warning",
        summary="jellyfin running" if event == "recovery" else "jellyfin stopped",
        at=at,
    )


def test_ledger_records_transitions_and_suppresses_same_state_duplicates(tmp_path):
    ledger = AlertEventLedger(tmp_path / "alert-events.jsonl")

    assert ledger.record(note("incident")) is True
    assert ledger.record(note("incident", at="2026-07-15T12:01:00+00:00")) is False
    assert ledger.record(note("recovery", at="2026-07-15T12:02:00+00:00")) is True

    assert [record["event"] for record in ledger.records()] == ["incident", "recovery"]
    assert ledger.recent(event="recovery") == [ledger.records()[1]]
    assert (tmp_path / "alert-events.jsonl").stat().st_mode & 0o777 == 0o644


def test_ledger_deduplicates_per_resource_when_events_interleave(tmp_path):
    ledger = AlertEventLedger(tmp_path / "events.jsonl")

    ledger.record(note("incident", key="container:a"))
    ledger.record(note("incident", key="container:b"))

    assert ledger.record(note("incident", key="container:a")) is False
    assert [record["key"] for record in ledger.records()] == ["container:a", "container:b"]


def test_ledger_retains_only_latest_bounded_records(tmp_path):
    ledger = AlertEventLedger(tmp_path / "events.jsonl", max_records=4)
    for index in range(8):
        ledger.record(
            note(
                "incident" if index % 2 == 0 else "recovery",
                at=f"2026-07-15T12:{index:02d}:00+00:00",
            )
        )

    assert len(ledger.records()) == 4
    assert ledger.records()[0]["at"] == "2026-07-15T12:04:00+00:00"


def test_ledger_skips_malformed_records_and_rejects_invalid_filters(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        "not-json\n"
        + json.dumps({"event": "recovery", "key": "missing-fields"})
        + "\n"
        + json.dumps(
            {
                "at": "2026-07-15T12:00:00Z",
                "event": "recovery",
                "key": "container:a",
                "kind": "container",
                "severity": "warning",
                "summary": "Recovered",
            }
        )
        + "\n"
    )
    ledger = AlertEventLedger(path)

    assert [record["key"] for record in ledger.records()] == ["container:a"]
    with pytest.raises(ValueError):
        ledger.recent(event="other")
    with pytest.raises(ValueError):
        ledger.recent(limit=51)


def test_oversized_ledger_fails_closed(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"x" * (MAX_LEDGER_BYTES + 1))

    assert AlertEventLedger(path).records() == []


def test_default_record_bound_is_small():
    assert MAX_ALERT_EVENTS == 200
