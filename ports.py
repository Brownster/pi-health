"""Framework-neutral service ports and thin adapters (BF-002B).

These define the seams between domain logic and infrastructure (privileged helper,
Docker, scheduler, clock, audit, config repository). Adapters wrap the *existing*
implementations without changing their behavior; call-site migration into services
is deferred to BF-003. Nothing here imports Flask.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from runtime_paths import LOG_DIR

# A clock is an injectable monotonic source, matching the callable convention already
# used by OperationRegistry and LoginRateLimiter (BF-002A).
Clock = Callable[[], float]
monotonic_clock: Clock = time.monotonic


# --- Privileged helper -------------------------------------------------------

@runtime_checkable
class HelperPort(Protocol):
    def call(self, command: str, params: dict | None = None) -> dict: ...


class HelperClientAdapter:
    """Wraps helper_client.helper_call; preserves its framing, timeouts, and HelperError."""

    def call(self, command: str, params: dict | None = None) -> dict:
        from helper_client import helper_call

        return helper_call(command, params)


# --- Docker ------------------------------------------------------------------

@runtime_checkable
class DockerPort(Protocol):
    @property
    def available(self) -> bool: ...
    def list_containers(self, all: bool = True) -> list: ...
    def get_container(self, container_id: str): ...
    def ping(self) -> bool: ...


class DockerClientAdapter:
    """Wraps a docker SDK client (or None when Docker is unavailable)."""

    def __init__(self, client: Any | None):
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None

    def list_containers(self, all: bool = True) -> list:
        if self._client is None:
            return []
        return self._client.containers.list(all=all)

    def get_container(self, container_id: str):
        if self._client is None:
            return None
        return self._client.containers.get(container_id)

    def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False


# --- Scheduler ---------------------------------------------------------------

@runtime_checkable
class SchedulerPort(Protocol):
    @property
    def running(self) -> bool: ...
    def start(self) -> None: ...
    def add_job(self, func, trigger, *, id: str, replace_existing: bool = True, **kwargs): ...
    def remove_job(self, job_id: str) -> None: ...
    def get_job(self, job_id: str): ...


class ApschedulerAdapter:
    """Thin wrapper over an apscheduler BackgroundScheduler."""

    def __init__(self, scheduler):
        self._scheduler = scheduler

    @property
    def running(self) -> bool:
        return bool(getattr(self._scheduler, "running", False))

    def start(self) -> None:
        if not self.running:
            self._scheduler.start()

    def add_job(self, func, trigger, *, id: str, replace_existing: bool = True, **kwargs):
        return self._scheduler.add_job(
            func, trigger, id=id, replace_existing=replace_existing, **kwargs
        )

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)

    def get_job(self, job_id: str):
        return self._scheduler.get_job(job_id)


# --- Audit -------------------------------------------------------------------

@runtime_checkable
class AuditPort(Protocol):
    def record(self, event: Mapping[str, Any]) -> bool: ...


class FileAuditWriter:
    """Append one JSON object per audit event to an append-only log.

    Minimal groundwork: domains keep their own audit calls until BF-003 routes them
    here. Each record is timestamped (UTC) and never raises into the caller.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self._path = os.fspath(path) if path is not None else os.path.join(LOG_DIR, "audit.log")

    def record(self, event: Mapping[str, Any]) -> bool:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            entry = {"ts": datetime.now(timezone.utc).isoformat(), **dict(event)}
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True) + "\n")
            return True
        except Exception:
            return False


# --- Config repository -------------------------------------------------------

@runtime_checkable
class ConfigRepository(Protocol):
    def read_json(self, path: str | os.PathLike, default: Any = None) -> Any: ...
    def write_json(self, path: str | os.PathLike, data: Any, *, mode: int = 0o644) -> None: ...


class JsonFileRepository:
    """Durable JSON config/state I/O: read with a default, write atomically (tmp + fsync + replace)."""

    def read_json(self, path: str | os.PathLike, default: Any = None) -> Any:
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, ValueError):
            return default

    def write_json(self, path: str | os.PathLike, data: Any, *, mode: int = 0o644) -> None:
        target = os.fspath(path)
        directory = os.path.dirname(os.path.abspath(target))
        os.makedirs(directory, exist_ok=True)
        if os.path.exists(target):
            mode = os.stat(target).st_mode & 0o777
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(target)}.", suffix=".tmp")
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
            dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
