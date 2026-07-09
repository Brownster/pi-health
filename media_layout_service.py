"""Framework-neutral canonical media layout management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from media_layout import MediaLayout
from ports import ConfigRepository, HelperPort


class MediaLayoutProvisionError(Exception):
    """Raised when the privileged helper cannot provision the layout."""


class MediaLayoutValidationError(Exception):
    """Raised when a requested media layout is not valid."""


class MediaLayoutService:
    """Read, persist, and provision the canonical media layout."""

    def __init__(
        self,
        *,
        helper: HelperPort,
        repository: ConfigRepository,
        config_path_provider: Callable[[], str],
        defaults: MediaLayout | None = None,
    ) -> None:
        self._helper = helper
        self._repository = repository
        self._config_path_provider = config_path_provider
        self._defaults = defaults or MediaLayout()

    def layout(self) -> MediaLayout:
        """Read persisted layout roots merged over defaults."""
        try:
            configured = self._repository.read_json(
                self._config_path_provider(), default={}
            )
        except Exception:
            configured = {}
        if not isinstance(configured, dict):
            configured = {}
        return MediaLayout(
            storage_root=_root_from(configured, "storage_root", self._defaults.storage_root),
            downloads_root=_root_from(configured, "downloads_root", self._defaults.downloads_root),
            config_root=_root_from(configured, "config_root", self._defaults.config_root),
            backup_root=_root_from(configured, "backup_root", self._defaults.backup_root),
        )

    def save(self, changes: Mapping[str, Any]) -> MediaLayout:
        """Persist selected layout roots after validation."""
        layout = self.layout()
        next_layout = MediaLayout(
            storage_root=_selected_root(changes, "storage_root", layout.storage_root),
            downloads_root=_selected_root(changes, "downloads_root", layout.downloads_root),
            config_root=_selected_root(changes, "config_root", layout.config_root),
            backup_root=_selected_root(changes, "backup_root", layout.backup_root),
        )
        self._repository.write_json(
            self._config_path_provider(), next_layout.as_dict(), mode=0o640
        )
        return next_layout

    def provision(self, *, puid: str | int = "1000", pgid: str | int = "1000") -> dict:
        """Provision library and download directories through the privileged helper."""
        layout = self.layout()
        if not self._helper.available():
            raise MediaLayoutProvisionError("Helper service unavailable")

        result = self._helper.call(
            "media_layout_provision",
            {
                "storage_root": layout.storage_root,
                "downloads_root": layout.downloads_root,
                "puid": str(puid),
                "pgid": str(pgid),
            },
        )
        if not result.get("success"):
            raise MediaLayoutProvisionError(result.get("error", "Provisioning failed"))
        return {"success": True, "layout": layout.as_dict(), **result}


def _root_from(configured: Mapping[str, Any], key: str, fallback: str) -> str:
    value = configured.get(key)
    if isinstance(value, str) and value.startswith("/"):
        return value.rstrip("/") or "/"
    return fallback


def _selected_root(changes: Mapping[str, Any], key: str, fallback: str) -> str:
    if key not in changes:
        return fallback
    value = changes[key]
    if not isinstance(value, str) or not value.startswith("/"):
        raise MediaLayoutValidationError(f"{key} must be an absolute path")
    return value.rstrip("/") or "/"
