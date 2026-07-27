"""Host settings LimeOS depends on but cannot set for itself at runtime.

Some things a LimeOS host needs live outside the application: how the kernel was
booted, how systemd is configured. Raspberry Pi OS boots without the memory
cgroup controller, so Docker reports no container memory at all — a gap that
looks exactly like zero usage unless something says otherwise. journald ships
with no size cap, so logs grow to a tenth of the filesystem, which on a Pi means
years of needless SD-card writes.

Detection is a read-only file check and runs in-process. Repair writes to /boot
and /etc and therefore goes through the privileged helper, which chooses the
files itself and takes no caller-supplied paths.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


CGROUP_CONTROLLERS_PATH = Path("/sys/fs/cgroup/cgroup.controllers")
JOURNALD_CONFIG_PATH = Path("/etc/systemd/journald.conf")
JOURNALD_DROPIN_DIR = Path("/etc/systemd/journald.conf.d")
JOURNAL_MAX_USE = "200M"

MEMORY_CGROUP = "memory_cgroup"
JOURNAL_CAP = "journal_cap"

_SYSTEM_MAX_USE = re.compile(r"^\s*SystemMaxUse\s*=\s*(\S+)", re.MULTILINE)


@dataclass(frozen=True)
class Prerequisite:
    """One host setting, why LimeOS wants it, and what repair changes."""

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
    Prerequisite(
        id=JOURNAL_CAP,
        title="Journal size limit",
        detail=(
            "systemd-journald has no size cap, so the journal grows until it takes a "
            "tenth of the filesystem. On a Pi that is continuous SD-card wear."
        ),
        remedy=(
            f"Sets SystemMaxUse={JOURNAL_MAX_USE} in a "
            "/etc/systemd/journald.conf.d drop-in and reclaims the excess."
        ),
        requires_reboot=False,
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


def read_journal_config(
    config_path: Path = JOURNALD_CONFIG_PATH,
    dropin_dir: Path = JOURNALD_DROPIN_DIR,
) -> list[str]:
    """Return the journald config sources, drop-ins last so they win."""
    sources = []
    for path in (config_path, *sorted(dropin_dir.glob("*.conf"))):
        try:
            sources.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return sources


def is_journal_capped(
    config_reader: Callable[[], list[str]] = read_journal_config,
) -> bool | None:
    """Whether journald has any size cap set. None when nothing is readable.

    Any cap counts, not only the one LimeOS would write — an operator who chose
    500M has already made this decision and should not be overruled.
    """
    sources = config_reader()
    if not sources:
        return None
    return any(_SYSTEM_MAX_USE.search(source) for source in sources)


class HostPrerequisiteService:
    """Report and repair the host settings LimeOS depends on."""

    def __init__(
        self,
        *,
        helper=None,
        controller_reader: Callable[[], set[str]] = read_cgroup_controllers,
        journal_config_reader: Callable[[], list[str]] = read_journal_config,
    ) -> None:
        self._helper = helper
        self._controller_reader = controller_reader
        self._journal_config_reader = journal_config_reader

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
        return {
            "id": prerequisite.id,
            "title": prerequisite.title,
            "detail": prerequisite.detail,
            "remedy": prerequisite.remedy,
            "requires_reboot": prerequisite.requires_reboot,
            "satisfied": self._detect(prerequisite.id),
        }

    def _detect(self, prerequisite_id: str) -> bool | None:
        if prerequisite_id == MEMORY_CGROUP:
            return is_memory_cgroup_enabled(self._controller_reader)
        if prerequisite_id == JOURNAL_CAP:
            return is_journal_capped(self._journal_config_reader)
        return None

    def apply(self) -> dict:
        """Ask the helper to repair every prerequisite this host fails.

        Reports which settings were applied and whether any of them only takes
        effect at the next boot, so callers can raise the right notice. An
        already correct host does no work.
        """
        unsatisfied = {
            item["id"] for item in self.status()["requirements"] if item["satisfied"] is False
        }
        if not unsatisfied:
            return self._outcome()
        if self._helper is None:
            return self._outcome(errors=["The privileged helper is unavailable"])

        response = self._call_helper()
        if not response.get("success"):
            return self._outcome(
                errors=[str(response.get("error") or "Host prerequisite repair failed")]
            )

        applied = []
        reboot_required = False
        errors = []
        for entry in response.get("results") or []:
            if not isinstance(entry, Mapping):
                continue
            prerequisite = PREREQUISITES_BY_ID.get(str(entry.get("id") or ""))
            if prerequisite is None or prerequisite.id not in unsatisfied:
                continue
            if entry.get("error"):
                errors.append(f"{prerequisite.title}: {entry['error']}")
                continue
            if entry.get("supported") is False:
                continue
            if entry.get("changed"):
                applied.append(prerequisite.id)
            # A setting already written but not yet in force — the boot file is
            # right while the running kernel is not — owes the same notice as a
            # fresh edit, so both count here.
            if prerequisite.requires_reboot:
                reboot_required = True

        return self._outcome(applied=applied, reboot_required=reboot_required, errors=errors)

    @staticmethod
    def _outcome(*, applied=None, reboot_required=False, errors=None) -> dict:
        applied = applied or []
        return {
            "changed": bool(applied),
            "reboot_required": bool(reboot_required),
            "applied": applied,
            "errors": errors or [],
        }

    def _call_helper(self) -> Mapping:
        try:
            return self._helper.call("host_prerequisites_apply", {}) or {}
        except Exception as error:
            return {"success": False, "error": str(error)}
