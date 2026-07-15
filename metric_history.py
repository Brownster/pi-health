"""Bounded SQLite storage and fixed-range queries for system metric history."""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path


RETENTION_SECONDS = 31 * 24 * 60 * 60
BUSY_TIMEOUT_MS = 3_000
METRIC_COLUMNS = (
    "cpu_percent",
    "memory_percent",
    "temperature_celsius",
    "disk_percent",
)
RANGES = {
    "24h": {"duration": 24 * 60 * 60, "bucket": 5 * 60},
    "7d": {"duration": 7 * 24 * 60 * 60, "bucket": 30 * 60},
    "30d": {"duration": 30 * 24 * 60 * 60, "bucket": 2 * 60 * 60},
}


class InvalidMetricRange(ValueError):
    """Raised when a history request uses an unsupported fixed range."""


def _finite_number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _usage_percent(stats: Mapping, key: str) -> float | None:
    usage = stats.get(key)
    return _finite_number(usage.get("percent")) if isinstance(usage, Mapping) else None


def _iso_timestamp(epoch_seconds: int) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


class MetricHistoryStore:
    """Persist current readings and return bounded chart-ready history."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database_path = Path(database_path)
        self._clock = clock

    def record(self, stats: Mapping, *, sampled_at: int | None = None) -> None:
        """Insert one sample and prune expired rows in a single transaction."""
        timestamp = int(self._clock() if sampled_at is None else sampled_at)
        values = (
            _finite_number(stats.get("cpu_usage_percent")),
            _usage_percent(stats, "memory_usage"),
            _finite_number(stats.get("temperature_celsius")),
            _usage_percent(stats, "disk_usage"),
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        connection = sqlite3.connect(self.database_path, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS metric_samples (
                        sampled_at INTEGER PRIMARY KEY,
                        cpu_percent REAL,
                        memory_percent REAL,
                        temperature_celsius REAL,
                        disk_percent REAL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO metric_samples (
                        sampled_at,
                        cpu_percent,
                        memory_percent,
                        temperature_celsius,
                        disk_percent
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(sampled_at) DO UPDATE SET
                        cpu_percent = excluded.cpu_percent,
                        memory_percent = excluded.memory_percent,
                        temperature_celsius = excluded.temperature_celsius,
                        disk_percent = excluded.disk_percent
                    """,
                    (timestamp, *values),
                )
                connection.execute(
                    "DELETE FROM metric_samples WHERE sampled_at < ?",
                    (timestamp - RETENTION_SECONDS,),
                )
        finally:
            connection.close()

    def query(self, selected_range: str) -> dict:
        """Return ordered fixed buckets plus summaries for one allowed range."""
        config = RANGES.get(selected_range)
        if config is None:
            raise InvalidMetricRange("range must be one of: 24h, 7d, 30d")

        end = int(self._clock())
        start = end - config["duration"]
        response = {
            "range": selected_range,
            "from": _iso_timestamp(start),
            "to": _iso_timestamp(end),
            "bucket_seconds": config["bucket"],
            "points": [],
            "summary": self._empty_summary(),
        }
        if not self.database_path.is_file():
            return response

        rows = self._aggregate(
            start,
            end,
            config["bucket"],
            config["duration"] // config["bucket"],
        )
        if not rows:
            return response

        by_bucket = {int(row[0]): row[1:] for row in rows}
        first_bucket = min(by_bucket)
        last_bucket = max(by_bucket)
        points = []
        for bucket_at in range(first_bucket, last_bucket + config["bucket"], config["bucket"]):
            values = by_bucket.get(bucket_at, (None, None, None, None))
            points.append(
                {
                    "at": _iso_timestamp(bucket_at),
                    **dict(zip(METRIC_COLUMNS, values, strict=True)),
                }
            )
        response["points"] = points
        response["summary"] = self._summaries(points)
        return response

    def _aggregate(
        self,
        start: int,
        end: int,
        bucket_seconds: int,
        max_buckets: int,
    ) -> list[tuple]:
        uri = f"file:{self.database_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA query_only = ON")
            try:
                return connection.execute(
                    """
                    SELECT
                        ? + MIN(CAST((sampled_at - ?) / ? AS INTEGER), ?) * ? AS bucket_at,
                        AVG(cpu_percent),
                        AVG(memory_percent),
                        AVG(temperature_celsius),
                        AVG(disk_percent)
                    FROM metric_samples
                    WHERE sampled_at >= ? AND sampled_at <= ?
                    GROUP BY bucket_at
                    ORDER BY bucket_at ASC
                    LIMIT ?
                    """,
                    (
                        start,
                        start,
                        bucket_seconds,
                        max_buckets - 1,
                        bucket_seconds,
                        start,
                        end,
                        max_buckets,
                    ),
                ).fetchall()
            except sqlite3.OperationalError as error:
                if "no such table" in str(error).lower():
                    return []
                raise
        finally:
            connection.close()

    @staticmethod
    def _empty_summary() -> dict:
        return {
            metric: {"current": None, "min": None, "average": None, "max": None}
            for metric in METRIC_COLUMNS
        }

    @classmethod
    def _summaries(cls, points: list[dict]) -> dict:
        summary = cls._empty_summary()
        for metric in METRIC_COLUMNS:
            values = [point[metric] for point in points if point[metric] is not None]
            if not values:
                continue
            summary[metric] = {
                "current": values[-1],
                "min": min(values),
                "average": sum(values) / len(values),
                "max": max(values),
            }
        return summary
