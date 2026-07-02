"""Framework-neutral seedbox mount configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ports import ConfigRepository, HelperPort


class SeedboxValidationError(Exception):
    """Raised when seedbox settings are invalid."""


class SeedboxUnavailableError(Exception):
    """Raised when a mutation cannot reach the privileged helper."""


class SeedboxOperationError(Exception):
    """Raised when the helper rejects a seedbox mutation."""


class SeedboxService:
    """Validate, apply, and persist seedbox mount settings."""

    def __init__(
        self,
        *,
        helper: HelperPort,
        repository: ConfigRepository,
        config_path_provider: Callable[[], str],
        mount_point_provider: Callable[[], str],
        mounted_reader: Callable[[str], bool],
    ) -> None:
        self._helper = helper
        self._repository = repository
        self._config_path_provider = config_path_provider
        self._mount_point_provider = mount_point_provider
        self._mounted_reader = mounted_reader

    def config(self) -> dict:
        """Read persisted settings or return the disabled defaults."""
        default = self._default_config()
        try:
            config = self._repository.read_json(
                self._config_path_provider(), default=default
            )
        except Exception:
            return default
        return config if isinstance(config, dict) else default

    def save(self, config: Mapping[str, Any]) -> None:
        """Persist non-secret seedbox settings."""
        self._repository.write_json(self._config_path_provider(), dict(config))

    def state(self) -> dict:
        """Return persisted settings with current mount state."""
        return {"config": self.config(), "mounted": self.is_mounted()}

    def is_mounted(self) -> bool:
        try:
            return bool(self._mounted_reader(self._mount_point_provider()))
        except Exception:
            return False

    def configure(self, data: Mapping[str, Any]) -> dict:
        """Apply enabled or disabled state, then persist non-secret settings."""
        if not self._helper.available():
            raise SeedboxUnavailableError("Helper service unavailable")

        enabled = bool(data.get("enabled", False))
        host = str(data.get("host", "")).strip()
        username = str(data.get("username", "")).strip()
        remote_path = str(data.get("remote_path", "")).strip()
        password = data.get("password", "")
        try:
            port = int(data.get("port", 22))
        except (TypeError, ValueError) as exc:
            raise SeedboxValidationError("Invalid port") from exc

        if enabled:
            self._validate_enabled(
                host=host,
                username=username,
                remote_path=remote_path,
                password=password,
                port=port,
            )
            result = self._helper.call(
                "seedbox_configure",
                {
                    "host": host,
                    "username": username,
                    "password": password,
                    "remote_path": remote_path,
                    "port": port,
                },
            )
            fallback_error = "Failed to configure seedbox"
        else:
            result = self._helper.call("seedbox_disable", {})
            fallback_error = "Failed to disable seedbox"

        if not result.get("success"):
            raise SeedboxOperationError(result.get("error", fallback_error))

        config = {
            "enabled": enabled,
            "host": host,
            "username": username,
            "port": port,
            "remote_path": remote_path,
            "mount_point": self._mount_point_provider(),
        }
        self.save(config)
        return {"status": "ok", "config": config, "mounted": self.is_mounted()}

    def _default_config(self) -> dict:
        return {
            "enabled": False,
            "host": "",
            "username": "",
            "port": 22,
            "remote_path": "",
            "mount_point": self._mount_point_provider(),
        }

    @staticmethod
    def _validate_enabled(*, host, username, remote_path, password, port) -> None:
        if not host or not username or not remote_path:
            raise SeedboxValidationError("host, username, and remote_path required")
        if not remote_path.startswith("/") or ".." in remote_path:
            raise SeedboxValidationError("Invalid remote_path")
        if not password:
            raise SeedboxValidationError("Password required")
        if port < 1 or port > 65535:
            raise SeedboxValidationError("Invalid port")
