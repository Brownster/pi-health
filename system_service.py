"""Framework-neutral system telemetry service."""

from __future__ import annotations

from collections.abc import Callable

from system_stats import get_system_stats as compose_system_stats


class SystemService:
    """Compose system telemetry from injected metric readers."""

    def __init__(
        self,
        *,
        cpu_reader: Callable,
        disk_collector: Callable,
        pi_metrics_reader: Callable,
    ):
        self._cpu_reader = cpu_reader
        self._disk_collector = disk_collector
        self._pi_metrics_reader = pi_metrics_reader

    def stats(self) -> dict:
        return compose_system_stats(
            cpu_reader=self._cpu_reader,
            disk_collector=self._disk_collector,
            pi_metrics_reader=self._pi_metrics_reader,
        )
