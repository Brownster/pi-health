"""Framework-neutral Docker container resource sampling.

The Docker stats endpoint blocks for roughly a second per container when the
daemon is asked to produce its own CPU baseline, so sampling a media host
serially costs tens of seconds and starves the request that triggered it. This
service asks for one-shot samples instead (returned immediately, with an empty
``precpu_stats``) and derives CPU and byte rates from the previous sample it
holds in memory. A background thread keeps that cache warm so API reads never
wait on Docker.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from ports import DockerPort


DEFAULT_INTERVAL_SECONDS = 5.0
# Beyond this the cached numbers describe a host that has moved on, so a reader
# re-samples inline rather than serving them.
DEFAULT_MAX_AGE_SECONDS = 30.0
# Gap between the two priming samples that establish a CPU baseline on first use.
BASELINE_GAP_SECONDS = 0.25
MAX_WORKERS = 8


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _counter(value) -> int | None:
    number = _finite(value)
    return None if number is None or number < 0 else int(number)


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class _Counters:
    """Monotonic counters read from one Docker stats payload."""

    at: float
    cpu_total: int | None
    cpu_system: int | None
    online_cpus: int | None
    memory_used: int | None
    memory_limit: int | None
    net_rx: int | None
    net_tx: int | None
    block_read: int | None
    block_write: int | None
    pids: int | None


def _memory_used(memory_stats: Mapping) -> int | None:
    """Resident memory, excluding reclaimable page cache like ``docker stats``."""
    usage = _counter(memory_stats.get("usage"))
    if usage is None:
        return None
    detail = _mapping(memory_stats.get("stats"))
    # cgroup v2 reports inactive_file; v1 reports total_inactive_file (or cache).
    for key in ("inactive_file", "total_inactive_file", "cache"):
        cached = _counter(detail.get(key))
        if cached is not None:
            return max(0, usage - cached)
    return usage


def _network_totals(networks: Mapping) -> tuple[int | None, int | None]:
    interfaces = [_mapping(value) for value in networks.values()]
    if not interfaces:
        return None, None
    received = [_counter(item.get("rx_bytes")) for item in interfaces]
    sent = [_counter(item.get("tx_bytes")) for item in interfaces]
    if any(value is None for value in (*received, *sent)):
        return None, None
    return sum(received), sum(sent)


def _block_totals(blkio_stats: Mapping) -> tuple[int | None, int | None]:
    entries = blkio_stats.get("io_service_bytes_recursive")
    if not isinstance(entries, list) or not entries:
        return None, None
    totals = {"read": 0, "write": 0}
    for entry in entries:
        item = _mapping(entry)
        operation = str(item.get("op") or "").lower()
        value = _counter(item.get("value"))
        if operation in totals and value is not None:
            totals[operation] += value
    return totals["read"], totals["write"]


def _read_counters(payload: Mapping, at: float) -> _Counters:
    cpu_stats = _mapping(payload.get("cpu_stats"))
    memory_stats = _mapping(payload.get("memory_stats"))
    net_rx, net_tx = _network_totals(_mapping(payload.get("networks")))
    block_read, block_write = _block_totals(_mapping(payload.get("blkio_stats")))
    limit = _counter(memory_stats.get("limit"))
    return _Counters(
        at=at,
        cpu_total=_counter(_mapping(cpu_stats.get("cpu_usage")).get("total_usage")),
        cpu_system=_counter(cpu_stats.get("system_cpu_usage")),
        online_cpus=_counter(cpu_stats.get("online_cpus")) or None,
        memory_used=_memory_used(memory_stats),
        memory_limit=limit or None,
        net_rx=net_rx,
        net_tx=net_tx,
        block_read=block_read,
        block_write=block_write,
        pids=_counter(_mapping(payload.get("pids_stats")).get("current")),
    )


def _cpu_percent(previous: _Counters | None, current: _Counters) -> float | None:
    if previous is None:
        return None
    values = (previous.cpu_total, current.cpu_total, previous.cpu_system, current.cpu_system)
    if any(value is None for value in values):
        return None
    cpu_delta = current.cpu_total - previous.cpu_total
    system_delta = current.cpu_system - previous.cpu_system
    # A restarted container resets its counters; report unknown until it re-baselines.
    if system_delta <= 0 or cpu_delta < 0:
        return None
    cores = current.online_cpus or previous.online_cpus or 1
    return round(cpu_delta / system_delta * cores * 100.0, 2)


def _rate(previous: _Counters | None, current: _Counters, field: str) -> float | None:
    if previous is None:
        return None
    before = getattr(previous, field)
    after = getattr(current, field)
    seconds = current.at - previous.at
    if before is None or after is None or seconds <= 0 or after < before:
        return None
    return round((after - before) / seconds, 2)


def _percent(used: int | None, limit: int | None) -> float | None:
    if used is None or not limit:
        return None
    return round(used / limit * 100.0, 2)


class ContainerStatsService:
    """Keep a warm cache of per-container resource usage.

    ``docker`` supplies the container list and raw stats payloads; the service
    owns delta maths, cache lifetime, and the background sampling thread.
    """

    def __init__(
        self,
        *,
        docker: DockerPort,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self._docker = docker
        self._interval = max(1.0, float(interval_seconds))
        self._max_age = max(self._interval, float(max_age_seconds))
        self._clock = clock
        self._wall_clock = wall_clock
        self._sleep = sleep
        self._max_workers = max(1, int(max_workers))
        self._lock = threading.Lock()
        self._previous: dict[str, _Counters] = {}
        self._results: dict[str, dict] = {}
        self._sampled_at: float | None = None
        self._sampled_wall: datetime | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Begin background sampling; safe to call more than once."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._run, name="container-stats-sampler", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.sample()
            except Exception:
                # Sampling is best-effort telemetry; never kill the thread.
                pass
            self._stopping.wait(self._interval)

    # --- sampling ----------------------------------------------------------

    def sample(self) -> None:
        """Take one pass over running containers and refresh the cache."""
        if not self._docker.available:
            with self._lock:
                self._results = {}
                self._previous = {}
                self._sampled_at = self._clock()
                self._sampled_wall = self._wall_clock()
            return

        containers = [
            container
            for container in self._docker.list_containers(all=False)
            if getattr(container, "status", None) == "running"
        ]
        payloads = self._collect(containers)
        at = self._clock()

        results: dict[str, dict] = {}
        counters: dict[str, _Counters] = {}
        with self._lock:
            previous_by_id = dict(self._previous)

        for container_id, name, payload in payloads:
            current = _read_counters(payload, at)
            previous = previous_by_id.get(container_id)
            counters[container_id] = current
            results[container_id] = {
                "id": container_id[:12],
                "name": name,
                "cpu_percent": _cpu_percent(previous, current),
                "memory_used": current.memory_used,
                "memory_limit": current.memory_limit,
                "memory_percent": _percent(current.memory_used, current.memory_limit),
                "net_rx": current.net_rx,
                "net_tx": current.net_tx,
                "net_rx_rate": _rate(previous, current, "net_rx"),
                "net_tx_rate": _rate(previous, current, "net_tx"),
                "block_read": current.block_read,
                "block_write": current.block_write,
                "block_read_rate": _rate(previous, current, "block_read"),
                "block_write_rate": _rate(previous, current, "block_write"),
                "pids": current.pids,
            }

        with self._lock:
            self._previous = counters
            self._results = results
            self._sampled_at = at
            self._sampled_wall = self._wall_clock()

    def _collect(self, containers: list) -> list[tuple[str, str, Mapping]]:
        def read(container):
            container_id = str(getattr(container, "id", "") or "")
            if not container_id:
                return None
            try:
                payload = self._docker.container_stats(container_id)
            except Exception:
                return None
            if not isinstance(payload, Mapping):
                return None
            return container_id, str(getattr(container, "name", "") or container_id[:12]), payload

        if not containers:
            return []
        workers = min(self._max_workers, len(containers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            collected = list(pool.map(read, containers))
        return [item for item in collected if item is not None]

    # --- reads -------------------------------------------------------------

    def _ensure_fresh(self) -> None:
        with self._lock:
            sampled_at = self._sampled_at
            primed = bool(self._previous)
        now = self._clock()
        if sampled_at is not None and (now - sampled_at) <= self._max_age:
            return
        self.sample()
        if not primed:
            # One-shot payloads carry no CPU baseline, so a cold cache needs a
            # second reading before any rate can be reported.
            self._sleep(BASELINE_GAP_SECONDS)
            self.sample()

    def snapshot(self) -> dict:
        """Return every sampled container plus the host's accounting capabilities."""
        self._ensure_fresh()
        with self._lock:
            results = {value["id"]: dict(value) for value in self._results.values()}
            sampled_wall = self._sampled_wall
        return {
            "sampled_at": sampled_wall.isoformat().replace("+00:00", "Z")
            if sampled_wall
            else None,
            "interval_seconds": self._interval,
            "capabilities": self._capabilities(results.values()),
            "containers": results,
        }

    @staticmethod
    def _capabilities(results) -> dict:
        values = list(results)
        return {
            # Raspberry Pi OS ships with the memory cgroup off, which makes every
            # container report no usage at all; the UI needs to say so rather than
            # render a convincing 0%.
            "memory": any(item.get("memory_used") is not None for item in values),
            "network": any(item.get("net_rx") is not None for item in values),
            "block_io": any(item.get("block_read") is not None for item in values),
        }

    def stats_for(self, container_id: str) -> dict | None:
        """Legacy-shaped stats for one container, keyed by full or short id."""
        entry = self.get(container_id)
        if entry is None:
            return None
        return {
            "cpu_percent": entry["cpu_percent"],
            "memory": {
                "used": entry["memory_used"],
                "limit": entry["memory_limit"],
                "percent": entry["memory_percent"],
            },
            "network": {"rx": entry["net_rx"], "tx": entry["net_tx"]},
        }

    def get(self, container_id: str) -> dict | None:
        identifier = str(container_id or "").strip()
        if not identifier:
            return None
        self._ensure_fresh()
        with self._lock:
            entry = self._results.get(identifier)
            if entry is None:
                # Callers hold the 12-character id the inventory publishes.
                entry = next(
                    (
                        value
                        for key, value in self._results.items()
                        if key.startswith(identifier)
                    ),
                    None,
                )
            return dict(entry) if entry else None

    def top(self, *, key: str = "cpu_percent", limit: int = 5) -> list[dict]:
        """Highest consumers of ``key``, skipping containers with no reading."""
        snapshot = self.snapshot()
        ranked = [
            item for item in snapshot["containers"].values() if _finite(item.get(key)) is not None
        ]
        ranked.sort(key=lambda item: item[key], reverse=True)
        return ranked[: max(0, int(limit))]
