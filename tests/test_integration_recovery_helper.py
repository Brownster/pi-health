from __future__ import annotations

import os

import pytest

import pihealth_helper as helper


@pytest.fixture
def recovery_paths(monkeypatch, tmp_path):
    active_dir = tmp_path / "config"
    recovery_dir = tmp_path / "recovery"
    active_dir.mkdir()
    recovery_dir.mkdir()
    active = active_dir / "mattermost.env"
    recovery = recovery_dir / "mattermost.env"
    monkeypatch.setattr(helper, "MATTERMOST_ACTIVE_CREDENTIAL", str(active))
    monkeypatch.setattr(helper, "MATTERMOST_RECOVERY_DIR", str(recovery_dir))
    monkeypatch.setattr(helper, "MATTERMOST_RECOVERY_CREDENTIAL", str(recovery))
    monkeypatch.setattr(helper.os, "fchown", lambda *_args: None)
    original_reader = helper._read_fixed_credential
    monkeypatch.setattr(
        helper,
        "_read_fixed_credential",
        lambda path, root_owned=False: original_reader(path, root_owned=False),
    )
    original_directory_owner = helper._credential_directory_owner
    monkeypatch.setattr(
        helper,
        "_credential_directory_owner",
        lambda path, root_owned=False: original_directory_owner(
            path,
            root_owned=False,
        ),
    )
    return active, recovery


def write_credential(path, value=b"POSTGRES_PASSWORD=private\n"):
    path.write_bytes(value)
    path.chmod(0o600)


def test_retain_restore_and_discard_are_fixed_idempotent_operations(recovery_paths):
    active, recovery = recovery_paths
    write_credential(active)

    assert helper.cmd_mattermost_recovery_credential_retain({}) == {
        "success": True,
        "credential_retained": True,
    }
    assert not active.exists()
    assert recovery.stat().st_mode & 0o777 == 0o600
    assert helper.cmd_mattermost_recovery_credential_retain({})["success"] is True

    assert helper.cmd_mattermost_recovery_credential_restore({}) == {
        "success": True,
        "credential_restored": True,
    }
    assert active.read_bytes() == b"POSTGRES_PASSWORD=private\n"
    assert not recovery.exists()
    assert helper.cmd_mattermost_recovery_credential_restore({})["success"] is True

    write_credential(recovery)
    assert helper.cmd_mattermost_recovery_credential_discard({}) == {
        "success": True,
        "credential_discarded": True,
    }
    assert not recovery.exists()
    assert helper.cmd_mattermost_recovery_credential_discard({})["success"] is True


def test_transfer_keeps_both_protected_copies_when_they_do_not_match(recovery_paths):
    active, recovery = recovery_paths
    write_credential(active, b"active-secret\n")
    write_credential(recovery, b"recovery-secret\n")

    result = helper.cmd_mattermost_recovery_credential_retain({})

    assert result == {
        "success": False,
        "error": "Mattermost recovery credential could not be retained",
    }
    assert active.exists()
    assert recovery.exists()
    assert "secret" not in result["error"].lower()


def test_commands_reject_fields_links_modes_and_oversized_credentials(recovery_paths):
    active, recovery = recovery_paths
    assert helper.cmd_mattermost_recovery_credential_retain({"path": str(active)}) == {
        "success": False,
        "error": "Invalid recovery credential parameters",
    }

    target = active.parent / "target.env"
    write_credential(target)
    active.symlink_to(target)
    assert helper.cmd_mattermost_recovery_credential_retain({})["success"] is False
    active.unlink()

    write_credential(active)
    active.chmod(0o640)
    assert helper.cmd_mattermost_recovery_credential_retain({})["success"] is False
    active.unlink()

    write_credential(active, b"x" * (helper.MATTERMOST_CREDENTIAL_LIMIT + 1))
    assert helper.cmd_mattermost_recovery_credential_retain({})["success"] is False
    assert not recovery.exists()


def test_root_owned_validation_rejects_an_unprivileged_recovery_file(tmp_path):
    path = tmp_path / "mattermost.env"
    write_credential(path)
    if os.geteuid() == 0:
        pytest.skip("test requires an unprivileged process")
    with pytest.raises(OSError, match="ownership"):
        helper._read_fixed_credential(str(path), root_owned=True)


def test_migration_ownership_repair_restores_root_only_modes(monkeypatch, tmp_path):
    recovery_dir = tmp_path / "recovery"
    recovery_dir.mkdir(mode=0o750)
    recovery = recovery_dir / "mattermost.env"
    write_credential(recovery)
    ownership = []
    monkeypatch.setattr(helper, "MATTERMOST_RECOVERY_DIR", str(recovery_dir))
    monkeypatch.setattr(helper, "MATTERMOST_RECOVERY_CREDENTIAL", str(recovery))
    monkeypatch.setattr(
        helper.os,
        "chown",
        lambda path, uid, gid, **kwargs: ownership.append(
            (path, uid, gid, kwargs)
        ),
    )

    assert helper._restore_mattermost_recovery_ownership() is True
    assert recovery_dir.stat().st_mode & 0o777 == 0o700
    assert recovery.stat().st_mode & 0o777 == 0o600
    assert ownership == [
        (str(recovery_dir), 0, 0, {"follow_symlinks": False}),
        (str(recovery), 0, 0, {"follow_symlinks": False}),
    ]


def test_migration_ownership_repair_rejects_a_recovery_symlink(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    recovery_dir = tmp_path / "recovery"
    recovery_dir.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(helper, "MATTERMOST_RECOVERY_DIR", str(recovery_dir))

    assert helper._restore_mattermost_recovery_ownership() is False
