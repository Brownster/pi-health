"""Host boot settings LimeOS depends on but cannot set at runtime.

Some LimeOS features need a kernel that was booted a particular way. Raspberry
Pi OS, for one, ships with the memory cgroup controller disabled, which makes
Docker report no memory usage at all for every container — a gap that looks
exactly like zero usage unless something says otherwise.

Detection is a read-only file check and runs in-process. Repair rewrites the
kernel command line and therefore goes through the privileged helper, which
owns the file and takes no caller-supplied paths.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


CGROUP_CONTROLLERS_PATH = Path("/sys/fs/cgroup/cgroup.controllers")
MEMORY_CGROUP = "memory_cgroup"


@dataclass(frozen=True)
class Prerequisite:
    """One host boot setting, why LimeOS wants it, and what repair changes."""

    id: str
    title: str
    detail: str
    remedy: str
    requires_reboot: bool


PREREQUISITES: tuple[Prerequisite, ...] = (
    Prerequisite(
        id=MEMORY_CGROUP,
        title="Container memory accounting",
        detail=(
            "The kernel was booted without the memory cgroup controller, so Docker "
            "cannot report memory usage for any container."
        ),
        remedy=(
            "Adds cgroup_enable=memory cgroup_memory=1 to the kernel command line "
            "in /boot/firmware/cmdline.txt."
        ),
        requires_reboot=True,
    ),
)

PREREQUISITES_BY_ID = {item.id: item for item in PREREQUISITES}


def read_cgroup_controllers(path: Path = CGROUP_CONTROLLERS_PATH) -> set[str]:
    """Return the cgroup v2 controllers this kernel exposes."""
    try:
        return set(path.read_text(encoding="utf-8").split())
    except OSError:
        return set()


def is_memory_cgroup_enabled(
    controller_reader: Callable[[], set[str]] = read_cgroup_controllers,
) -> bool | None:
    """True/False when the controller list is readable, None when it is not.

    A cgroup v1 host has no ``cgroup.controllers`` file; reporting unknown there
    keeps LimeOS from claiming a problem it has not actually observed.
    """
    controllers = controller_reader()
    if not controllers:
        return None
    return "memory" in controllers


class HostPrerequisiteService:
    """Report and repair the host boot settings LimeOS depends on."""

    def __init__(
        self,
        *,
        helper=None,
        controller_reader: Callable[[], set[str]] = read_cgroup_controllers,
    ) -> None:
        self._helper = helper
        self._controller_reader = controller_reader

    def status(self) -> dict:
        """Describe every prerequisite and whether this host satisfies it."""
        requirements = [self._requirement(item) for item in PREREQUISITES]
        return {
            "satisfied": all(item["satisfied"] is not False for item in requirements),
            "reboot_required": any(
                item["satisfied"] is False and item["requires_reboot"] for item in requirements
            ),
            "requirements": requirements,
        }

    def _requirement(self, prerequisite: Prerequisite) -> dict:
        satisfied = self._detect(prerequisite.id)
        return {
            "id": prerequisite.id,
            "title": prerequisite.title,
            "detail": prerequisite.detail,
            "remedy": prerequisite.remedy,
            "requires_reboot": prerequisite.requires_reboot,
            "satisfied": satisfied,
        }

    def _detect(self, prerequisite_id: str) -> bool | None:
        if prerequisite_id == MEMORY_CGROUP:
            return is_memory_cgroup_enabled(self._controller_reader)
        return None

    def apply(self) -> dict:
        """Ask the helper to repair every prerequisite this host fails.

        Returns what changed so callers can record a reboot notice. An already
        correct host reports ``changed: False`` and is left alone.
        """
        unsatisfied = [
            item for item in self.status()["requirements"] if item["satisfied"] is False
        ]
        if not unsatisfied:
            return {"changed": False, "reboot_required": False, "applied": [], "errors": []}
        if self._helper is None:
            return {
                "changed": False,
                "reboot_required": False,
                "applied": [],
                "errors": ["The privileged helper is unavailable"],
            }

        result = self._call_helper()
        if not result.get("success"):
            return {
                "changed": False,
                "reboot_required": False,
                "applied": [],
                "errors": [str(result.get("error") or "Host prerequisite repair failed")],
            }

        changed = bool(result.get("changed"))
        # "Not changed" here means the boot file already carried the settings while
        # the running kernel still does not — configured on disk, pending a reboot.
        # That state needs the same notice as a fresh edit, so both report it.
        configured = result.get("supported") is not False
        return {
            "changed": changed,
            "reboot_required": configured
            and any(item["requires_reboot"] for item in unsatisfied),
            "applied": [item["id"] for item in unsatisfied] if changed else [],
            "backup": result.get("backup"),
            "errors": [],
        }

    def _call_helper(self) -> Mapping:
        try:
            return self._helper.call("host_prerequisites_apply", {}) or {}
        except Exception as error:
            return {"success": False, "error": str(error)}
