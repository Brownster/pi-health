"""Short-lived system metric collector invoked by the systemd timer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from metric_history import MetricHistoryStore
from pi_monitor import get_pi_metrics
from runtime_paths import STATE_DIR
from system_service import SystemService
from system_stats import _collect_disk_usage, get_cpu_usage_delta


def collect_once(database_path: str | Path | None = None) -> None:
    service = SystemService(
        cpu_reader=get_cpu_usage_delta,
        disk_collector=_collect_disk_usage,
        pi_metrics_reader=get_pi_metrics,
    )
    path = database_path or os.getenv("LIMEOS_METRICS_DB", str(STATE_DIR / "metrics.sqlite3"))
    MetricHistoryStore(path).record(service.stats())


def main() -> int:
    try:
        collect_once()
    except Exception as error:
        print(f"Metric collection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
