"""Framework-neutral auto-update scheduling and execution.

Owns the auto-update configuration, the schedule job on an injected scheduler, and
the pull/recreate run loop. The Flask blueprint in ``update_scheduler`` is a thin
transport adapter over this service.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from ports import ConfigRepository, SchedulerPort

JOB_ID = "auto_update"
JOB_NAME = "Auto-Update Stacks"

# Default configuration merged under any persisted state.
DEFAULT_CONFIG = {
    "version": 1,
    "enabled": False,
    "schedule_preset": "disabled",
    "excluded_stacks": [],
    "notify_on_update": True,
    "last_run": None,
    "last_run_result": None,
}

# Schedule presets mapped to cron expressions (None disables the job).
SCHEDULE_PRESETS = {
    "disabled": None,
    "daily_4am": "0 4 * * *",
    "weekly_sunday_4am": "0 4 * * 0",
}


class UpdateConfigError(Exception):
    """Raised when an auto-update configuration change is invalid."""


def get_schedule_cron(preset: str) -> str | None:
    """Convert a schedule preset to a cron expression."""
    return SCHEDULE_PRESETS.get(preset)


def has_new_images(pull_output: str | None) -> bool:
    """Return True when a compose pull downloaded new image layers."""
    if not pull_output:
        return False

    new_image_indicators = [
        "Downloaded newer image",
        "Pull complete",
        "Downloading",
        "Extracting",
        "Download complete",
        "Status: Downloaded",
    ]

    output_lower = pull_output.lower()
    for indicator in new_image_indicators:
        if indicator.lower() in output_lower:
            return True
    return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutoUpdateService:
    """Schedule and run automatic stack image updates through injected ports."""

    def __init__(
        self,
        *,
        repository: ConfigRepository,
        scheduler: SchedulerPort,
        config_path_provider: Callable[[], str],
        stack_lister: Callable[[], list],
        compose_runner: Callable[[str, str], Any],
        trigger_factory: Callable[[str], Any],
        clock: Callable[[], datetime] = _utcnow,
        logger: Callable[[str], None] = print,
    ) -> None:
        self._repository = repository
        self._scheduler = scheduler
        self._config_path_provider = config_path_provider
        self._stack_lister = stack_lister
        self._compose_runner = compose_runner
        self._trigger_factory = trigger_factory
        self._clock = clock
        self._log = logger
        self._lock = threading.Lock()
        self._running = False

    # -- Config --------------------------------------------------------------

    def load_config(self) -> dict:
        """Read persisted state merged over defaults."""
        try:
            stored = self._repository.read_json(self._config_path_provider(), default={})
        except Exception:
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(stored)
        return merged

    def save_config(self, config: Mapping[str, Any]) -> None:
        """Persist the full configuration through the repository (atomic write)."""
        self._repository.write_json(self._config_path_provider(), dict(config))

    def update_config(self, changes: Mapping[str, Any]) -> dict:
        """Validate and persist selected fields, then reschedule the job."""
        config = self.load_config()

        if "enabled" in changes:
            config["enabled"] = bool(changes["enabled"])

        if "schedule_preset" in changes:
            preset = changes["schedule_preset"]
            if preset not in SCHEDULE_PRESETS:
                raise UpdateConfigError(f"Invalid schedule preset: {preset}")
            config["schedule_preset"] = preset

        if "excluded_stacks" in changes:
            if not isinstance(changes["excluded_stacks"], list):
                raise UpdateConfigError("excluded_stacks must be a list")
            config["excluded_stacks"] = list(changes["excluded_stacks"])

        if "notify_on_update" in changes:
            config["notify_on_update"] = bool(changes["notify_on_update"])

        self.save_config(config)

        if config["enabled"]:
            self.apply_schedule(config["schedule_preset"])
        else:
            self.apply_schedule("disabled")
        return config

    # -- Scheduler -----------------------------------------------------------

    def init_scheduler(self) -> None:
        """Register the job from current config and start the scheduler."""
        config = self.load_config()
        if config["enabled"] and config["schedule_preset"] != "disabled":
            self.apply_schedule(config["schedule_preset"])
        if not self._scheduler.running:
            self._scheduler.start()
        self._log(f"Auto-update scheduler initialized (enabled: {config['enabled']})")

    def apply_schedule(self, preset: str) -> None:
        """Replace the scheduled job with one derived from ``preset``."""
        try:
            self._scheduler.remove_job(JOB_ID)
        except Exception:
            pass  # Job doesn't exist, that's fine.

        cron = get_schedule_cron(preset)
        if cron:
            self._scheduler.add_job(
                self.run,
                self._trigger_factory(cron),
                id=JOB_ID,
                name=JOB_NAME,
                replace_existing=True,
            )
            self._log(f"Auto-update scheduled: {preset} ({cron})")
        else:
            self._log("Auto-update disabled")

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
        """Return whether an update is currently in progress."""
        return self._running

    # -- Read models ---------------------------------------------------------

    def status(self) -> dict:
        """Return scheduler status and the last run summary."""
        config = self.load_config()
        return {
            "enabled": config["enabled"],
            "schedule_preset": config["schedule_preset"],
            "next_run": self.next_run_time(),
            "last_run": config.get("last_run"),
            "last_run_result": config.get("last_run_result"),
            "update_running": self.is_running(),
        }

    def logs(self) -> dict:
        """Return the last run timestamp and result."""
        config = self.load_config()
        return {
            "last_run": config.get("last_run"),
            "last_run_result": config.get("last_run_result"),
        }

    # -- Execution -----------------------------------------------------------

    def run(self) -> dict:
        """Run the update once, guarded against concurrent execution."""
        if not self._lock.acquire(blocking=False):
            self._log("Auto-update already running, skipping")
            return {"error": "Update already in progress"}
        try:
            self._running = True
            return self._run_locked()
        finally:
            self._running = False
            self._lock.release()

    def _run_locked(self) -> dict:
        config = self.load_config()
        results = {
            "updated": [],
            "failed": [],
            "skipped": [],
            "timestamp": self._clock().isoformat(),
        }

        try:
            stacks = self._stack_lister()
        except Exception as error:
            results["failed"].append(
                {"name": "_system", "error": f"Failed to list stacks: {error}"}
            )
            return results

        self._log(f"Auto-update starting: {len(stacks)} stacks found")
        excluded = config.get("excluded_stacks", [])

        for stack in stacks:
            stack_name = stack.get("name", "unknown")

            if stack_name in excluded:
                results["skipped"].append(stack_name)
                self._log(f"  Skipping {stack_name} (excluded)")
                continue

            try:
                self._log(f"  Processing {stack_name}...")

                pull_result = self._compose_runner(stack_name, "pull")
                if not pull_result or not pull_result.get("success"):
                    error_msg = (
                        pull_result.get("stderr", "Unknown error")
                        if pull_result
                        else "No result"
                    )
                    results["failed"].append(
                        {"name": stack_name, "error": f"Pull failed: {error_msg}"}
                    )
                    self._log(f"    Pull failed: {error_msg[:100]}")
                    continue

                if has_new_images(pull_result.get("stdout", "")):
                    self._log("    New images detected, recreating services...")
                    up_result = self._compose_runner(stack_name, "up")
                    if up_result and up_result.get("success"):
                        results["updated"].append(stack_name)
                        self._log("    Updated successfully")
                    else:
                        error_msg = (
                            up_result.get("stderr", "Unknown error")
                            if up_result
                            else "No result"
                        )
                        results["failed"].append(
                            {"name": stack_name, "error": f"Up failed: {error_msg}"}
                        )
                        self._log(f"    Up failed: {error_msg[:100]}")
                else:
                    results["skipped"].append(stack_name)
                    self._log("    No new images, skipping")

            except Exception as error:
                results["failed"].append({"name": stack_name, "error": str(error)})
                self._log(f"    Error: {error}")

        config["last_run"] = results["timestamp"]
        config["last_run_result"] = results
        self.save_config(config)

        self._log(
            f"Auto-update complete: {len(results['updated'])} updated, "
            f"{len(results['failed'])} failed, {len(results['skipped'])} skipped"
        )
        return results
