"""Host process sampling for the "what is using this box" panels.

``psutil.Process.cpu_percent()`` measures against its own previous call, so the
first read of every process is always 0.0 and a correct one-shot answer costs a
blocking sleep. This sampler keeps the previous CPU-time reading per process and
derives usage from the delta, which stays accurate without stalling a request.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass


DEFAULT_TTL_SECONDS = 4.0
DEFAULT_LIMIT = 5
MAX_LIMIT = 25
# Kernel worker threads and the sampler's own bookkeeping add noise without
# telling anyone anything about their workload.
IGNORED_NAMES = frozenset({"", "kthreadd"})


@dataclass(frozen=True)
class _ProcessSample:
    cpu_seconds: float
    started_at: float


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _default_process_reader() -> Iterable[Mapping]:
    import psutil

    fields = ["pid", "name", "username", "cpu_times", "memory_info", "create_time"]
    for process in psutil.process_iter(fields):
        info = process.info
        cpu_times = info.get("cpu_times")
        memory_info = info.get("memory_info")
        yield {
            "pid": info.get("pid"),
            "name": info.get("name"),
            "username": info.get("username"),
            "cpu_seconds": (getattr(cpu_times, "user", 0.0) + getattr(cpu_times, "system", 0.0))
            if cpu_times
            else None,
            "memory_bytes": getattr(memory_info, "rss", None) if memory_info else None,
            "started_at": info.get("create_time"),
        }


class ProcessSampler:
    """Rank host processes by CPU and resident memory."""

    def __init__(
        self,
        *,
        process_reader: Callable[[], Iterable[Mapping]] = _default_process_reader,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._process_reader = process_reader
        self._clock = clock
        self._ttl = max(0.0, float(ttl_seconds))
        self._lock = threading.Lock()
        self._previous: dict[int, _ProcessSample] = {}
        self._results: list[dict] = []
        self._sampled_at: float | None = None

    def sample(self) -> list[dict]:
        """Read every visible process and refresh per-process CPU shares."""
        at = self._clock()
        with self._lock:
            previous = dict(self._previous)
            elapsed = at - self._sampled_at if self._sampled_at is not None else None

        current: dict[int, _ProcessSample] = {}
        results: list[dict] = []
        for entry in self._process_reader():
            pid = entry.get("pid")
            name = str(entry.get("name") or "")
            if not isinstance(pid, int) or name in IGNORED_NAMES:
                continue
            cpu_seconds = _finite(entry.get("cpu_seconds"))
            started_at = _finite(entry.get("started_at")) or 0.0
            if cpu_seconds is not None:
                current[pid] = _ProcessSample(cpu_seconds=cpu_seconds, started_at=started_at)
            results.append(
                {
                    "pid": pid,
                    "name": name,
                    "user": str(entry.get("username") or ""),
                    "cpu_percent": self._cpu_percent(
                        previous.get(pid), cpu_seconds, started_at, elapsed
                    ),
                    "memory_bytes": _finite(entry.get("memory_bytes")),
                }
            )

        with self._lock:
            self._previous = current
            self._results = results
            self._sampled_at = at
        return results

    @staticmethod
    def _cpu_percent(
        previous: _ProcessSample | None,
        cpu_seconds: float | None,
        started_at: float,
        elapsed: float | None,
    ) -> float | None:
        if previous is None or cpu_seconds is None or not elapsed or elapsed <= 0:
            return None
        # A recycled pid restarts the CPU clock; wait for a fresh baseline.
        if previous.started_at != started_at or cpu_seconds < previous.cpu_seconds:
            return None
        return round((cpu_seconds - previous.cpu_seconds) / elapsed * 100.0, 2)

    def _fresh_results(self) -> list[dict]:
        with self._lock:
            sampled_at = self._sampled_at
            results = list(self._results)
        if sampled_at is not None and (self._clock() - sampled_at) <= self._ttl:
            return results
        return self.sample()

    def top(self, *, limit: int = DEFAULT_LIMIT) -> dict:
        """Return the heaviest processes by CPU and by resident memory."""
        limit = max(0, min(int(limit), MAX_LIMIT))
        results = self._fresh_results()

        def rank(key: str) -> list[dict]:
            ranked = [item for item in results if _finite(item.get(key)) is not None]
            ranked.sort(key=lambda item: item[key], reverse=True)
            return [dict(item) for item in ranked[:limit] if item[key] > 0]

        return {
            "by_cpu": rank("cpu_percent"),
            "by_memory": rank("memory_bytes"),
            "total": len(results),
        }
