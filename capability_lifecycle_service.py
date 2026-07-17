"""Compatibility lifecycle adapter for installed LimeOS extensions."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

import plugin_manager
from capability_api import CapabilityLifecycleError


logger = logging.getLogger(__name__)


class ExtensionLifecycleService:
    """Apply extension lifecycle operations through the existing plugin store."""

    def __init__(self, *, manager=plugin_manager, operation_lock=None) -> None:
        self._manager = manager
        self._operation_lock = operation_lock or threading.Lock()

    def install(self, values: Mapping[str, Any], *, username: str):
        del username
        with self._operation():
            result = self._manager.install_plugin(
                values["type"],
                values["source"],
                values.get("id"),
                values.get("entry"),
                values.get("class_name"),
            )
            payload = self._require_success(result, "install")
            extension = payload.get("plugin")
            extension_id = extension.get("id") if isinstance(extension, Mapping) else None
            return {
                "status": "installed",
                "id": extension_id,
                "restart_required": True,
            }, 201

    def transition(
        self,
        provider_id: str,
        action: str,
        values: Mapping[str, Any],
        *,
        username: str,
    ) -> dict:
        del values, username
        with self._operation():
            entry = self._manager.get_plugin_entry(provider_id)
            if not isinstance(entry, Mapping):
                raise CapabilityLifecycleError(
                    "Extension was not found.",
                    code="extension_not_found",
                    status_code=404,
                )

            if action in {"enable", "disable"}:
                enabled = action == "enable"
                self._manager.set_enabled(provider_id, enabled)
                return {
                    "status": action,
                    "id": provider_id,
                    "enabled": enabled,
                    "restart_required": True,
                }

            if action == "remove" and bool(entry.get("enabled")):
                raise CapabilityLifecycleError(
                    "Disable the extension before removing it.",
                    code="extension_must_be_disabled",
                    status_code=409,
                )

            operation = {
                "update": self._manager.update_plugin,
                "repair": self._manager.repair_plugin,
                "remove": self._manager.remove_plugin,
            }.get(action)
            if operation is None:
                raise CapabilityLifecycleError(
                    "Extension lifecycle action is unavailable.",
                    code="extension_action_unavailable",
                    status_code=409,
                )
            self._require_success(operation(provider_id), action)
            return {
                "status": action,
                "id": provider_id,
                "restart_required": action != "remove",
                **({"removed": True} if action == "remove" else {}),
            }

    def _operation(self):
        return _LifecycleOperation(self._operation_lock)

    @staticmethod
    def _require_success(result: Any, action: str) -> Mapping[str, Any]:
        if isinstance(result, Mapping) and result.get("success") is True:
            return result
        logger.warning("Extension %s operation failed", action)
        raise CapabilityLifecycleError(
            f"Extension {action} failed.",
            code=f"extension_{action}_failed",
            status_code=409,
        )


class _LifecycleOperation:
    def __init__(self, lock) -> None:
        self._lock = lock

    def __enter__(self):
        if not self._lock.acquire(blocking=False):
            raise CapabilityLifecycleError(
                "Another extension operation is already running.",
                code="extension_busy",
                status_code=409,
            )
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self._lock.release()
