"""Framework-neutral SMART health reads and self-test operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ports import HelperPort


SMART_TEST_TYPES = frozenset({"short", "long", "conveyance"})


class SmartValidationError(Exception):
    """Raised when a SMART device or self-test type is invalid."""


class SmartOperationError(Exception):
    """Raised when the privileged helper rejects a SMART operation."""


def validate_device_name(device: str) -> str:
    """Return a /dev path for one safe block-device name."""
    if not device or not all(
        character.isalnum() or character in "-_" for character in device
    ):
        raise SmartValidationError("Invalid device name")
    return f"/dev/{device}"


class SmartService:
    """Read and mutate SMART state through an injected privileged helper."""

    def __init__(
        self,
        *,
        helper: HelperPort,
        parser: Callable[[dict], Any],
    ) -> None:
        self._helper = helper
        self._parser = parser

    def all_devices(self) -> dict:
        result = self._helper.call("smart_all_devices", {})
        if not result.get("success"):
            raise SmartOperationError(result.get("error", "Failed to get SMART data"))

        disks = []
        for item in result.get("devices", []):
            device = item.get("device", "unknown")
            raw_data = item.get("data", {})
            if raw_data:
                data = self._parser(raw_data).to_dict()
            else:
                data = {
                    "device": device,
                    "error_message": item.get("error", "No SMART data"),
                }
            disks.append({"device": device, "data": data})
        return {"disks": disks}

    def device(self, device: str, *, use_sat: bool = False) -> dict:
        device_path = validate_device_name(device)
        result = self._helper.call(
            "smart_info", {"device": device_path, "use_sat": use_sat}
        )
        if not result.get("success"):
            raise SmartOperationError(result.get("error", "Failed to get SMART data"))
        return self._parser(result.get("data", {})).to_dict()

    def start_test(
        self,
        device: str,
        *,
        test_type: str = "short",
        use_sat: bool = False,
    ) -> dict:
        device_path = validate_device_name(device)
        if test_type not in SMART_TEST_TYPES:
            raise SmartValidationError(
                "Invalid test type. Use: short, long, or conveyance"
            )

        result = self._helper.call(
            "smart_test",
            {
                "device": device_path,
                "test_type": test_type,
                "use_sat": use_sat,
            },
        )
        if not result.get("success"):
            raise SmartOperationError(result.get("error", "Failed to start SMART test"))
        return {
            "status": "started",
            "test_type": test_type,
            "message": result.get("message", "SMART test started"),
        }
