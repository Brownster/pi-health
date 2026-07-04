"""Framework-neutral management of auxiliary tools (CopyParty).

Owns the CopyParty configuration and the privileged status/install/configure
operations. The Flask blueprint in :mod:`tools_manager` is a thin transport
adapter that supplies the config path and helper call and maps results to HTTP.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from helper_client import HelperError
from ports import ConfigRepository

DEFAULT_CONFIG = {
    "share_path": "/srv/copyparty",
    "port": 3923,
    "extra_args": "",
}


class ToolsConfigError(Exception):
    """Raised when a tools configuration request is invalid (maps to 400)."""


class ToolsOperationError(Exception):
    """Raised when a privileged tools operation is rejected (maps to 400)."""


class ToolsHelperError(Exception):
    """Raised when the privileged helper is unavailable (maps to 503)."""

    def __init__(self, message: str, *, config: dict | None = None):
        super().__init__(message)
        self.config = config


class ToolsService:
    """Manage CopyParty through an injected config repository and helper call."""

    def __init__(
        self,
        *,
        repository: ConfigRepository,
        helper_call: Callable[[str, dict], dict],
        config_path_provider: Callable[[], Any],
        defaults: Mapping[str, Any] = DEFAULT_CONFIG,
    ) -> None:
        self._repository = repository
        self._helper_call = helper_call
        self._config_path_provider = config_path_provider
        self._defaults = dict(defaults)

    def load_config(self) -> dict:
        try:
            stored = self._repository.read_json(self._config_path_provider(), default=None)
        except Exception:
            stored = None
        config = dict(self._defaults)
        if isinstance(stored, dict):
            config.update(stored)
        return config

    def save_config(self, config: Mapping[str, Any]) -> None:
        self._repository.write_json(self._config_path_provider(), dict(config))

    def status(self) -> dict:
        """Return the CopyParty install/service status and current config."""
        config = self.load_config()
        try:
            status = self._helper_call("copyparty_status", {})
        except HelperError as exc:
            raise ToolsHelperError(str(exc), config=config) from exc
        return {
            "config": config,
            "installed": status.get("installed", False),
            "service_active": status.get("service_active", False),
            "service_status": status.get("service_status", "unknown"),
        }

    def install(self) -> dict:
        """Install CopyParty using the current config."""
        config = self.load_config()
        try:
            result = self._helper_call("copyparty_install", config)
        except HelperError as exc:
            raise ToolsHelperError(str(exc)) from exc
        if not result.get("success"):
            raise ToolsOperationError(result.get("error", "Install failed"))
        return {"status": "installed"}

    def configure(self, data: Mapping[str, Any]) -> dict:
        """Validate, persist, and apply a CopyParty configuration change."""
        share_path = str(data.get("share_path", "")).strip()
        if not share_path.startswith("/"):
            raise ToolsConfigError("share_path must be absolute")

        try:
            port = int(data.get("port", self._defaults["port"]))
        except (TypeError, ValueError):
            raise ToolsConfigError("port must be an integer") from None

        config = {
            "share_path": share_path,
            "port": port,
            "extra_args": str(data.get("extra_args", "")).strip(),
        }
        self.save_config(config)

        try:
            result = self._helper_call("copyparty_configure", config)
        except HelperError as exc:
            raise ToolsHelperError(str(exc)) from exc
        if not result.get("success"):
            raise ToolsOperationError(result.get("error", "Configure failed"))
        return {"status": "configured"}
