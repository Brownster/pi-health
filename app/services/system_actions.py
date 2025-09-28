from __future__ import annotations

import os
import subprocess
from typing import Any

from flask import current_app


_DISABLED_MESSAGE = "System actions are disabled by configuration."


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def _actions_enabled() -> bool:
    try:
        config_value = current_app.config.get('ENABLE_SYSTEM_ACTIONS')  # type: ignore[attr-defined]
    except RuntimeError:
        config_value = None
    if config_value is None:
        config_value = os.getenv('ENABLE_SYSTEM_ACTIONS')
    return _to_bool(config_value, default=True)


def system_action(action: str):
    if not _actions_enabled():
        return {"error": _DISABLED_MESSAGE}

    try:
        if action == "shutdown":
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])
            return {"status": "Shutdown initiated"}
        if action == "reboot":
            subprocess.Popen(['sudo', 'reboot'])
            return {"status": "Reboot initiated"}
        return {"error": "Invalid system action"}
    except Exception as e:
        return {"error": str(e)}
