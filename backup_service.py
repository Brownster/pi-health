"""Framework-neutral backup scheduling, execution, and restore.

Owns backup configuration, the scheduled job on an injected scheduler, the
helper-driven backup/restore operations, and stack stop/start orchestration. The
Flask blueprint in :mod:`backup_scheduler` is a thin transport adapter over this
service and supplies the environment-specific providers.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from helper_client import HelperError
from ports import ConfigRepository, HelperPort, SchedulerPort

JOB_ID = "pihealth_backup"
JOB_NAME = "Pi-Health Backup"

DEFAULT_CONFIG = {
    "version": 1,
    "enabled": False,
    "schedule_preset": "disabled",
    "retention_count": 7,
    "dest_dir": "/mnt/backup",
    "config_dir": "/home/pi/docker",
    "stacks_path": "/opt/stacks",
    "include_env": True,
    "compression": "zst",
    "last_run": None,
    "last_run_result": None,
    "plugin_backup_enabled": True,
    "plugin_retention_count": 10,
    "last_plugin_backup": None,
    "last_plugin_backup_result": None,
    "last_restore": None,
    "last_restore_result": None,
}

# Default patterns excluded from backups (media, cache, logs, temp files).
DEFAULT_EXCLUDES = [
    "*.mp3",
    "*.mp4",
    "*.mkv",
    "*.avi",
    "*.mov",
    "*.flac",
    "*.wav",
    "*.m4a",
    "*.webm",
    "*/MediaCover/*",
    "*/MediaCover",
    "*/cache/*",
    "*/Cache/*",
    "*/.cache/*",
    "*/logs/*",
    "*.log",
    "*.log.*",
    "*-shm",
    "*-wal",
    "*.db-journal",
    "*/transcode/*",
    "*/Transcode/*",
    "*/temp/*",
    "*/tmp/*",
]

SCHEDULE_PRESETS = {
    "disabled": None,
    "daily_2am": "0 2 * * *",
    "weekly_sunday_2am": "0 2 * * 0",
}

BACKUP_PREFIXES = ("pi-health-backup-", "storage-plugins-")
BACKUP_SUFFIXES = (".tar.zst", ".tar.gz")


class BackupConfigError(Exception):
    """Raised when a backup configuration or request is invalid (maps to 400)."""


class BackupNotFound(Exception):
    """Raised when a requested archive does not exist (maps to 404)."""


class BackupHelperUnavailable(Exception):
    """Raised when the privileged helper is unavailable (maps to 503)."""


class BackupOperationError(Exception):
    """Raised when a backup or restore operation fails (maps to 500)."""


def list_backups(dest_dir: str | None) -> list[dict]:
    """List primary and plugin archives in ``dest_dir``, newest first."""
    entries: list[dict] = []
    if not dest_dir or not os.path.isdir(dest_dir):
        return entries

    for name in sorted(os.listdir(dest_dir)):
        if not any(name.startswith(prefix) for prefix in BACKUP_PREFIXES):
            continue
        if not name.endswith(BACKUP_SUFFIXES):
            continue
        path = os.path.join(dest_dir, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        entries.append({"name": name, "size": stat.st_size, "mtime": stat.st_mtime})

    entries.sort(key=lambda item: item["mtime"], reverse=True)
    return entries


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BackupService:
    """Schedule and run backups/restores through injected ports."""

    def __init__(
        self,
        *,
        repository: ConfigRepository,
        scheduler: SchedulerPort,
        helper: HelperPort,
        config_path_provider: Callable[[], str],
        default_config_provider: Callable[[], dict],
        sources_provider: Callable[[Mapping[str, Any]], list[str]],
        plugin_sources_provider: Callable[[], list[str]],
        stack_lister: Callable[[], tuple],
        compose_runner: Callable[[str, str], Any],
        trigger_factory: Callable[[str], Any],
        excludes: Sequence[str] = tuple(DEFAULT_EXCLUDES),
        archive_exists: Callable[[str], bool] = os.path.exists,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repository = repository
        self._scheduler = scheduler
        self._helper = helper
        self._config_path_provider = config_path_provider
        self._default_config_provider = default_config_provider
        self._sources_provider = sources_provider
        self._plugin_sources_provider = plugin_sources_provider
        self._stack_lister = stack_lister
        self._compose_runner = compose_runner
        self._trigger_factory = trigger_factory
        self._excludes = list(excludes)
        self._archive_exists = archive_exists
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False

    # -- Config --------------------------------------------------------------

    def load_config(self) -> dict:
        """Read persisted state merged over environment-aware defaults."""
        try:
            stored = self._repository.read_json(self._config_path_provider(), default=None)
        except Exception:
            stored = None
        config = self._default_config_provider()
        if isinstance(stored, dict):
            config.update(stored)
        return config

    def save_config(self, config: Mapping[str, Any]) -> None:
        """Persist the full configuration through the repository (atomic write)."""
        self._repository.write_json(self._config_path_provider(), dict(config))

    def update_config(self, changes: Mapping[str, Any]) -> dict:
        """Validate and persist selected fields, then reschedule the job."""
        config = self.load_config()

        for key in (
            "enabled",
            "schedule_preset",
            "retention_count",
            "dest_dir",
            "config_dir",
            "stacks_path",
            "include_env",
            "plugin_backup_enabled",
            "plugin_retention_count",
        ):
            if key in changes:
                config[key] = changes[key]

        config["retention_count"] = self._validate_retention(
            config.get("retention_count", 7), "retention_count"
        )
        config["plugin_retention_count"] = self._validate_retention(
            config.get("plugin_retention_count", 10), "plugin_retention_count"
        )

        dest_dir = str(config.get("dest_dir", "")).strip()
        if not dest_dir.startswith("/"):
            raise BackupConfigError("dest_dir must be absolute")
        if ".." in dest_dir:
            raise BackupConfigError("dest_dir invalid")

        config_dir = str(config.get("config_dir", "")).strip()
        if config_dir and (not config_dir.startswith("/") or ".." in config_dir):
            raise BackupConfigError("config_dir invalid")

        stacks_path = str(config.get("stacks_path", "")).strip()
        if stacks_path and (not stacks_path.startswith("/") or ".." in stacks_path):
            raise BackupConfigError("stacks_path invalid")

        schedule = config.get("schedule_preset", "disabled")
        if schedule not in SCHEDULE_PRESETS:
            raise BackupConfigError("Invalid schedule_preset")

        self.save_config(config)

        if config.get("enabled") and schedule != "disabled":
            self.apply_schedule(schedule)
        else:
            self.apply_schedule("disabled")
        return config

    @staticmethod
    def _validate_retention(value: Any, field: str) -> int:
        try:
            retention = int(value)
        except (TypeError, ValueError):
            raise BackupConfigError(f"Invalid {field}") from None
        if retention < 1:
            raise BackupConfigError(f"{field} must be >= 1")
        return retention

    # -- Scheduler -----------------------------------------------------------

    def init_scheduler(self) -> None:
        """Register the job from current config and start the scheduler."""
        config = self.load_config()
        if config.get("enabled") and config.get("schedule_preset") != "disabled":
            self.apply_schedule(config["schedule_preset"])
        if not self._scheduler.running:
            self._scheduler.start()

    def apply_schedule(self, preset: str) -> None:
        """Replace the scheduled job with one derived from ``preset``."""
        try:
            self._scheduler.remove_job(JOB_ID)
        except Exception:
            pass  # Job doesn't exist, that's fine.

        cron = SCHEDULE_PRESETS.get(preset)
        if cron:
            self._scheduler.add_job(
                self.run_backup,
                self._trigger_factory(cron),
                id=JOB_ID,
                name=JOB_NAME,
                replace_existing=True,
            )

    def next_run_time(self) -> str | None:
        """Return the next scheduled run time, if any."""
        try:
            job = self._scheduler.get_job(JOB_ID)
            if job and job.next_run_time:
                return job.next_run_time.isoformat()
        except Exception:
            pass
        return None

    def is_running(self) -> bool:
        """Return whether a backup is currently in progress."""
        return self._running

    def status(self) -> dict:
        """Return scheduler status and the last run/plugin summaries."""
        config = self.load_config()
        return {
            "enabled": config.get("enabled", False),
            "next_run": self.next_run_time(),
            "backup_running": self.is_running(),
            "last_run": config.get("last_run"),
            "last_run_result": config.get("last_run_result"),
            "last_plugin_backup": config.get("last_plugin_backup"),
            "last_plugin_backup_result": config.get("last_plugin_backup_result"),
        }

    def list_backups(self) -> list[dict]:
        """List archives in the configured destination directory."""
        return list_backups(self.load_config().get("dest_dir"))

    # -- Execution -----------------------------------------------------------

    def run_backup(self) -> dict:
        """Run primary and plugin backups, guarded against concurrent runs."""
        if not self._lock.acquire(blocking=False):
            return {"error": "Backup already in progress"}
        try:
            self._running = True
            return self._run_locked()
        finally:
            self._running = False
            self._lock.release()

    def _run_locked(self) -> dict:
        config = self.load_config()

        if not self._helper.available():
            result = {"success": False, "error": "Helper service unavailable"}
            plugin_result = {"success": False, "error": "Helper service unavailable"}
        else:
            try:
                result = self._helper.call(
                    "backup_create",
                    {
                        "sources": self._sources_provider(config),
                        "dest_dir": config.get("dest_dir"),
                        "retention_count": config.get("retention_count", 7),
                        "compression": config.get("compression", "zst"),
                        "archive_prefix": "pi-health-backup",
                        "excludes": self._excludes,
                    },
                )
                if config.get("plugin_backup_enabled", True):
                    plugin_result = self._helper.call(
                        "backup_create",
                        {
                            "sources": self._plugin_sources_provider(),
                            "dest_dir": config.get("dest_dir"),
                            "retention_count": config.get("plugin_retention_count", 10),
                            "compression": config.get("compression", "zst"),
                            "archive_prefix": "storage-plugins",
                        },
                    )
                else:
                    plugin_result = {"success": False, "error": "Plugin backup disabled"}
            except HelperError as exc:
                result = {"success": False, "error": str(exc)}
                plugin_result = {"success": False, "error": str(exc)}

        now = self._clock().isoformat()
        config["last_run"] = now
        config["last_run_result"] = result
        config["last_plugin_backup"] = now
        config["last_plugin_backup_result"] = plugin_result
        self.save_config(config)
        return {"primary": result, "plugins": plugin_result}

    # -- Restore -------------------------------------------------------------

    def restore(
        self, archive_name: str, *, stop_stacks: bool = True, start_stacks: bool = True
    ) -> dict:
        """Restore a primary archive, optionally stopping and restarting stacks."""
        name = self._validate_archive_name(archive_name)
        archive_path = self._locate_archive(name)

        stacks_stopped: list[str] = []
        stacks_started: list[str] = []

        if stop_stacks:
            stacks, error = self._stack_lister()
            if error:
                raise BackupOperationError(error)
            for stack in stacks:
                name = stack.get("name")
                if not name:
                    continue
                result = self._compose_runner(name, "stop")
                if result and result.get("success"):
                    stacks_stopped.append(name)

        restore_result = self._helper.call("backup_restore", {"archive_path": archive_path})
        if not restore_result.get("success"):
            raise BackupOperationError(restore_result.get("error", "Restore failed"))

        if start_stacks and stacks_stopped:
            for name in stacks_stopped:
                result = self._compose_runner(name, "up")
                if result and result.get("success"):
                    stacks_started.append(name)

        config = self.load_config()
        config["last_restore"] = self._clock().isoformat()
        config["last_restore_result"] = {
            "restore": restore_result,
            "stopped": stacks_stopped,
            "started": stacks_started,
        }
        self.save_config(config)
        return config["last_restore_result"]

    def restore_plugins(self, archive_name: str) -> dict:
        """Restore a storage-plugins archive."""
        name = self._validate_archive_name(archive_name)
        if not name.startswith("storage-plugins-"):
            raise BackupConfigError("Invalid plugin archive")
        archive_path = self._locate_archive(name)

        restore_result = self._helper.call("backup_restore", {"archive_path": archive_path})
        if not restore_result.get("success"):
            raise BackupOperationError(restore_result.get("error", "Restore failed"))

        config = self.load_config()
        config["last_plugin_backup"] = self._clock().isoformat()
        config["last_plugin_backup_result"] = restore_result
        self.save_config(config)
        return restore_result

    @staticmethod
    def _validate_archive_name(archive_name: str) -> str:
        name = (archive_name or "").strip()
        if not name or "/" in name or ".." in name:
            raise BackupConfigError("Invalid archive name")
        return name

    def _locate_archive(self, name: str) -> str:
        dest_dir = self.load_config().get("dest_dir", "")
        archive_path = os.path.join(dest_dir, name)
        if not self._archive_exists(archive_path):
            raise BackupNotFound("Backup not found")
        if not self._helper.available():
            raise BackupHelperUnavailable("Helper service unavailable")
        return archive_path
