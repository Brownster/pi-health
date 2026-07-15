import sqlite3

import pytest

from metric_history import (
    METRIC_COLUMNS,
    RETENTION_SECONDS,
    InvalidMetricRange,
    MetricHistoryStore,
)


NOW = 2_000_000_000


def _stats(cpu=10.0, memory=20.0, temperature=40.0, disk=30.0):
    return {
        "cpu_usage_percent": cpu,
        "memory_usage": {"percent": memory},
        "temperature_celsius": temperature,
        "disk_usage": {"percent": disk},
    }


def test_record_creates_schema_and_normalizes_unavailable_values(tmp_path):
    database = tmp_path / "state" / "metrics.sqlite3"
    store = MetricHistoryStore(database, clock=lambda: NOW)

    store.record(_stats(cpu=float("nan"), memory="bad", temperature=None, disk=25))

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT sampled_at, cpu_percent, memory_percent, temperature_celsius, disk_percent "
            "FROM metric_samples"
        ).fetchone()
    assert row == (NOW, None, None, None, 25.0)


def test_record_replaces_same_second_and_prunes_expired_rows(tmp_path):
    database = tmp_path / "metrics.sqlite3"
    store = MetricHistoryStore(database, clock=lambda: NOW)
    expired = NOW - RETENTION_SECONDS - 1

    store.record(_stats(cpu=5), sampled_at=expired)
    store.record(_stats(cpu=10), sampled_at=NOW)
    store.record(_stats(cpu=15), sampled_at=NOW)

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT sampled_at, cpu_percent FROM metric_samples ORDER BY sampled_at"
        ).fetchall()
    assert rows == [(NOW, 15.0)]


def test_query_rejects_arbitrary_range(tmp_path):
    store = MetricHistoryStore(tmp_path / "metrics.sqlite3", clock=lambda: NOW)

    with pytest.raises(InvalidMetricRange, match="24h, 7d, 30d"):
        store.query("1y")


def test_missing_database_returns_empty_bounded_contract(tmp_path):
    store = MetricHistoryStore(tmp_path / "missing.sqlite3", clock=lambda: NOW)

    result = store.query("24h")

    assert result["range"] == "24h"
    assert result["bucket_seconds"] == 300
    assert result["points"] == []
    assert set(result["summary"]) == set(METRIC_COLUMNS)
    assert all(values["current"] is None for values in result["summary"].values())


def test_query_aggregates_samples_and_preserves_bucket_gaps(tmp_path):
    store = MetricHistoryStore(tmp_path / "metrics.sqlite3", clock=lambda: NOW)
    store.record(_stats(cpu=10, memory=20), sampled_at=NOW - 900)
    store.record(_stats(cpu=30, memory=40), sampled_at=NOW - 850)
    store.record(_stats(cpu=50, memory=60), sampled_at=NOW)

    result = store.query("24h")

    assert len(result["points"]) == 3
    assert result["points"][0]["cpu_percent"] == 20.0
    assert result["points"][1]["cpu_percent"] is None
    assert result["points"][2]["cpu_percent"] == 50.0
    assert result["summary"]["cpu_percent"] == {
        "current": 50.0,
        "min": 20.0,
        "average": 35.0,
        "max": 50.0,
    }


@pytest.mark.parametrize(
    ("selected_range", "bucket_seconds", "maximum_points"),
    [("24h", 300, 288), ("7d", 1800, 336), ("30d", 7200, 360)],
)
def test_query_ranges_never_exceed_the_fixed_bucket_limit(
    tmp_path,
    selected_range,
    bucket_seconds,
    maximum_points,
):
    database = tmp_path / f"{selected_range}.sqlite3"
    store = MetricHistoryStore(database, clock=lambda: NOW)
    duration = maximum_points * bucket_seconds
    store.record(_stats(), sampled_at=NOW - duration)
    store.record(_stats(cpu=99), sampled_at=NOW)

    result = store.query(selected_range)

    assert result["bucket_seconds"] == bucket_seconds
    assert len(result["points"]) == maximum_points
    assert result["points"][-1]["cpu_percent"] == 99.0


def test_database_without_schema_behaves_as_empty_history(tmp_path):
    database = tmp_path / "metrics.sqlite3"
    sqlite3.connect(database).close()
    store = MetricHistoryStore(database, clock=lambda: NOW)

    assert store.query("7d")["points"] == []
