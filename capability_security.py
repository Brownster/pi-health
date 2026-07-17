"""Server-owned roles and permissions for capability providers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from types import MappingProxyType


CAPABILITY_PERMISSIONS = frozenset(
    {
        "capability.view",
        "capability.configure",
        "extensions.admin",
        "capability.diagnose",
        "capability.operate",
    }
)
ROLE_PERMISSIONS = MappingProxyType(
    {
        "admin": CAPABILITY_PERMISSIONS,
        "operator": frozenset(
            {"capability.view", "capability.diagnose"}
        ),
        "viewer": frozenset({"capability.view"}),
    }
)


class CapabilityRoleConfigurationError(RuntimeError):
    """Raised when capability role assignments are incomplete or invalid."""


def _parse_role_assignments(value: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for entry in value.split(","):
        if ":" not in entry:
            raise CapabilityRoleConfigurationError(
                "PIHEALTH_USER_ROLES entries must use username:role"
            )
        username, role = (part.strip() for part in entry.split(":", 1))
        if not username or username in assignments:
            raise CapabilityRoleConfigurationError(
                "PIHEALTH_USER_ROLES contains an empty or duplicate username"
            )
        assignments[username] = role
    return assignments


def resolve_capability_roles(
    users: Mapping[str, str],
    configured: Mapping[str, str] | str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve a complete role assignment for configured LimeOS users."""
    usernames = tuple(users)
    if not usernames:
        raise CapabilityRoleConfigurationError(
            "Capability roles require at least one configured user"
        )

    if configured is None:
        env = os.environ if environ is None else environ
        configured = env.get("PIHEALTH_USER_ROLES", "").strip() or None

    if configured is None:
        return {
            username: "admin" if index == 0 else "viewer"
            for index, username in enumerate(usernames)
        }

    if isinstance(configured, str):
        assignments = _parse_role_assignments(configured)
    elif isinstance(configured, Mapping):
        assignments = {
            str(username).strip(): str(role).strip()
            for username, role in configured.items()
        }
    else:
        raise CapabilityRoleConfigurationError(
            "Capability role assignments must be a mapping or username:role list"
        )

    unknown_users = set(assignments) - set(usernames)
    missing_users = set(usernames) - set(assignments)
    invalid_roles = set(assignments.values()) - set(ROLE_PERMISSIONS)
    if unknown_users:
        raise CapabilityRoleConfigurationError(
            "Capability roles contain an unknown user"
        )
    if missing_users:
        raise CapabilityRoleConfigurationError(
            "Capability roles must assign every configured user"
        )
    if invalid_roles or any(not username for username in assignments):
        raise CapabilityRoleConfigurationError(
            "Capability roles contain an unknown role"
        )
    return assignments


class CapabilityAuthorizer:
    """Authorize fixed permissions from a server-owned user-to-role map."""

    def __init__(self, roles: Mapping[str, str]) -> None:
        self._roles = dict(roles)

    def role_for(self, username: str) -> str | None:
        role = self._roles.get(username)
        return role if role in ROLE_PERMISSIONS else None

    def permissions_for(self, username: str) -> tuple[str, ...]:
        role = self.role_for(username)
        if role is None:
            return ()
        return tuple(sorted(ROLE_PERMISSIONS[role]))

    def allows(self, username: str, permission: str) -> bool:
        if permission not in CAPABILITY_PERMISSIONS:
            return False
        role = self.role_for(username)
        return role is not None and permission in ROLE_PERMISSIONS[role]
