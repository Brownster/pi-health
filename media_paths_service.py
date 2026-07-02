"""Framework-neutral media-path and startup-service management."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from ports import ConfigRepository, HelperPort


MEDIA_PATH_KEYS = ("downloads", "storage", "backup", "config")
STARTUP_SCRIPT_PATH = "/usr/local/bin/check_mount_and_start.sh"
STARTUP_UNIT_PATH = "/etc/systemd/system/docker-compose-start.service"
STARTUP_UNIT_NAME = "docker-compose-start.service"


class MediaPathValidationError(Exception):
    """Raised when a configured media path is not absolute."""


def startup_service_params(paths: Mapping[str, Any], compose_file: str) -> dict:
    """Build the typed helper parameters for mount-wait startup files."""
    mount_points = []
    for key in ("storage", "downloads", "backup"):
        value = paths.get(key)
        if isinstance(value, str) and value.startswith("/mnt/"):
            mount_points.append(value)
    return {
        "mount_points": mount_points,
        "compose_file": os.path.abspath(compose_file),
    }


class MediaPathsService:
    """Manage media paths and their generated startup service."""

    def __init__(
        self,
        *,
        helper: HelperPort,
        repository: ConfigRepository,
        config_path_provider: Callable[[], str],
        compose_path_provider: Callable[[], str],
        defaults: Mapping[str, str],
        startup_renderer: Callable[[list[str], str], tuple[str, str]],
        file_exists: Callable[[str], bool] = os.path.exists,
        file_reader: Callable[[str], str] | None = None,
    ) -> None:
        self._helper = helper
        self._repository = repository
        self._config_path_provider = config_path_provider
        self._compose_path_provider = compose_path_provider
        self._defaults = dict(defaults)
        self._startup_renderer = startup_renderer
        self._file_exists = file_exists
        self._file_reader = file_reader or self._read_text

    @staticmethod
    def _read_text(path: str) -> str:
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def paths(self) -> dict[str, str]:
        """Read configured paths merged over defaults."""
        try:
            configured = self._repository.read_json(
                self._config_path_provider(), default={}
            )
        except Exception:
            configured = {}
        if not isinstance(configured, dict):
            configured = {}
        return {**self._defaults, **configured}

    def save(self, paths: Mapping[str, str]) -> None:
        """Persist a complete path mapping."""
        self._repository.write_json(self._config_path_provider(), dict(paths))

    def update(self, changes: Mapping[str, Any]) -> dict:
        """Validate and persist selected paths, then refresh startup files."""
        paths = self.paths()
        for key in MEDIA_PATH_KEYS:
            if key not in changes:
                continue
            path = changes[key]
            if not isinstance(path, str) or not path.startswith("/"):
                raise MediaPathValidationError(f"Invalid path for {key}")
            paths[key] = path

        self.save(paths)
        startup_result = self.apply_startup_service(paths)
        response = {"status": "updated", "paths": paths}
        if not startup_result.get("success"):
            response["startup_warning"] = startup_result.get(
                "error", "Startup service not updated"
            )
        return response

    def apply_startup_service(self, paths: Mapping[str, Any] | None = None) -> dict:
        """Generate, reload, and enable the startup service through the helper."""
        if not self._helper.available():
            return {"success": False, "error": "Helper service unavailable"}

        result = self._helper.call(
            "configure_startup_service",
            self._startup_params(paths or self.paths()),
        )
        if not result.get("success"):
            return result

        self._helper.call("systemctl", {"action": "daemon-reload"})
        self._helper.call("systemctl", {"action": "enable", "unit": STARTUP_UNIT_NAME})
        return {"success": True}

    def preview_startup_service(self) -> dict:
        """Preview helper-rendered files, falling back to local rendering."""
        params = self._startup_params(self.paths())
        if self._helper.available():
            try:
                result = self._helper.call("preview_startup_service", params)
                if result.get("success"):
                    return {"script": result["script"], "service": result["service"]}
            except Exception:
                pass

        proposed_script, proposed_service = self._startup_renderer(
            params["mount_points"], params["compose_file"]
        )
        return {
            "script": self._preview_file(STARTUP_SCRIPT_PATH, proposed_script),
            "service": self._preview_file(STARTUP_UNIT_PATH, proposed_service),
        }

    def _startup_params(self, paths: Mapping[str, Any]) -> dict:
        return startup_service_params(paths, self._compose_path_provider())

    def _preview_file(self, path: str, proposed: str) -> dict:
        exists = self._file_exists(path)
        try:
            current = self._file_reader(path)
        except (FileNotFoundError, PermissionError, OSError):
            current = ""
        return {
            "path": path,
            "current": current,
            "proposed": proposed,
            "exists": exists,
            "changed": current != proposed,
        }
