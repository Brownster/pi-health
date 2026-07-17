import pytest

from capability_security import (
    CAPABILITY_PERMISSIONS,
    CapabilityAuthorizer,
    CapabilityRoleConfigurationError,
    resolve_capability_roles,
)


USERS = {"alice": "hash-a", "bob": "hash-b"}


def test_default_roles_preserve_single_admin_and_limit_additional_users():
    roles = resolve_capability_roles(USERS, environ={})

    assert roles == {"alice": "admin", "bob": "viewer"}


def test_explicit_role_assignments_are_complete_and_server_owned():
    roles = resolve_capability_roles(
        USERS,
        environ={"PIHEALTH_USER_ROLES": "alice:admin,bob:operator"},
    )
    authorizer = CapabilityAuthorizer(roles)

    assert authorizer.role_for("alice") == "admin"
    assert set(authorizer.permissions_for("alice")) == CAPABILITY_PERMISSIONS
    assert authorizer.allows("alice", "extensions.admin") is True
    assert authorizer.allows("bob", "capability.diagnose") is True
    assert authorizer.allows("bob", "capability.operate") is False
    assert authorizer.allows("missing", "capability.view") is False
    assert authorizer.allows("alice", "provider.granted.permission") is False


@pytest.mark.parametrize(
    "configured,message",
    [
        ({"alice": "admin"}, "every configured user"),
        ({"alice": "admin", "bob": "owner"}, "unknown role"),
        ({"alice": "admin", "mallory": "viewer"}, "unknown user"),
        ("alice:admin,alice:viewer", "duplicate username"),
        ("alice", "username:role"),
    ],
)
def test_invalid_role_assignments_fail_startup(configured, message):
    with pytest.raises(CapabilityRoleConfigurationError, match=message):
        resolve_capability_roles(USERS, configured, environ={})


def test_explicit_mapping_cannot_assign_empty_user():
    with pytest.raises(CapabilityRoleConfigurationError, match="unknown user"):
        resolve_capability_roles(
            USERS,
            {"": "viewer", "alice": "admin", "bob": "viewer"},
            environ={},
        )
