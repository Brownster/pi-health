from __future__ import annotations

import json

import pytest

from integration_lifecycle_service import (
    AgentLifecycleSnapshotService,
    IntegrationLifecycleResolver,
    LifecycleStateError,
    LifecycleStateRepository,
    RecoveryCredentialCustody,
    RecoveryCredentialError,
)


def record(
    *,
    integration="mattermost",
    action="uninstall",
    phase="running",
    target_state=None,
    retained_data=None,
    remove_claude_code=None,
):
    if target_state is None:
        target_state = "retained_data" if integration == "mattermost" else "not_installed"
    if retained_data is None:
        retained_data = target_state == "retained_data"
    if integration == "agents" and action == "uninstall" and remove_claude_code is None:
        remove_claude_code = True
    return {
        "schema_version": "1",
        "integration": integration,
        "operation_id": "operation-1",
        "action": action,
        "phase": phase,
        "target_state": target_state,
        "started_at": "2026-07-20T20:00:00+00:00",
        "updated_at": "2026-07-20T20:01:00+00:00",
        "completed_steps": [],
        "retained_data": retained_data,
        "remove_claude_code": remove_claude_code,
        "failure": None,
        "warning_codes": [],
    }


def repository(tmp_path, integration="mattermost"):
    return LifecycleStateRepository(
        tmp_path / f"{integration}-lifecycle.json",
        integration,
    )


def legacy(state="connected", installed=True):
    return {
        "state": state,
        "installed": installed,
        "site_url": "http://mattermost.test:8065" if installed else None,
    }


def test_missing_tombstone_uses_legacy_state_without_creating_a_file(tmp_path):
    repo = repository(tmp_path)
    status = IntegrationLifecycleResolver(repo).status(legacy())

    assert repo.read() is None
    assert not repo.path.exists()
    assert status["state"] == "connected"
    assert status["allowed_actions"] == ["disable", "uninstall"]
    assert status["retained_data"] is False
    assert status["cleanup_required"] is False


def test_repository_writes_atomically_with_fixed_mode_and_deletes_idempotently(tmp_path):
    repo = repository(tmp_path)
    value = record(phase="complete")

    repo.write(value)

    assert repo.read() == value
    assert repo.path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.glob(".*.tmp")) == []
    repo.delete()
    repo.delete()
    assert not repo.path.exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(schema_version="2"),
        lambda value: value.update(integration="agents"),
        lambda value: value.update(database_password="secret"),
    ],
)
def test_invalid_tombstones_fail_closed(tmp_path, mutate):
    repo = repository(tmp_path)
    value = record()
    mutate(value)
    repo.path.write_text(json.dumps(value), encoding="utf-8")
    repo.path.chmod(0o640)

    with pytest.raises(LifecycleStateError, match="invalid"):
        repo.read()

    status = IntegrationLifecycleResolver(repo).status(legacy())
    assert status["state"] == "cleanup_required"
    assert status["allowed_actions"] == ["retry_cleanup"]
    assert status["cleanup_operation"]["id"] == "lifecycle-state"
    assert "secret" not in json.dumps(status).lower()


def test_corrupt_json_unsafe_mode_and_symlink_fail_closed(tmp_path):
    repo = repository(tmp_path)
    repo.path.write_text("{", encoding="utf-8")
    repo.path.chmod(0o640)
    with pytest.raises(LifecycleStateError, match="invalid"):
        repo.read()

    repo.path.write_text(json.dumps(record()), encoding="utf-8")
    repo.path.chmod(0o644)
    with pytest.raises(LifecycleStateError, match="unsafe permissions"):
        repo.read()

    repo.path.unlink()
    target = tmp_path / "target.json"
    target.write_text(json.dumps(record()), encoding="utf-8")
    target.chmod(0o640)
    repo.path.symlink_to(target)
    with pytest.raises(LifecycleStateError, match="invalid"):
        repo.read()


def test_missing_tombstone_under_a_symlinked_directory_fails_closed(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    repo = LifecycleStateRepository(linked / "mattermost-lifecycle.json", "mattermost")

    with pytest.raises(LifecycleStateError, match="unsafe"):
        repo.read()


def test_complete_and_interrupted_records_have_authoritative_precedence(tmp_path):
    repo = repository(tmp_path)
    resolver = IntegrationLifecycleResolver(repo)

    repo.write(record(phase="complete"))
    retained = resolver.status(legacy())
    assert retained["state"] == "retained_data"
    assert retained["installed"] is False
    assert retained["retained_data"] is True
    assert retained["allowed_actions"] == ["setup"]
    assert "purge" not in retained["allowed_actions"]

    repo.write(record(phase="running"))
    interrupted = resolver.status(legacy())
    assert interrupted["state"] == "cleanup_required"
    assert interrupted["cleanup_operation"] == {
        "id": "operation-1",
        "action": "uninstall",
        "state": "interrupted",
        "started_at": "2026-07-20T20:00:00+00:00",
        "updated_at": "2026-07-20T20:01:00+00:00",
        "retryable": True,
    }


def test_disabled_and_uninstalled_agent_records_override_legacy_runtime(tmp_path):
    repo = repository(tmp_path, "agents")
    resolver = IntegrationLifecycleResolver(repo)

    repo.write(
        record(
            integration="agents",
            action="disable",
            phase="complete",
            target_state="disabled",
            retained_data=False,
        )
    )
    disabled = resolver.status({"state": "connected", "installed": True})
    assert disabled["state"] == "disabled"
    assert disabled["allowed_actions"] == ["enable", "uninstall"]

    repo.write(record(integration="agents", phase="complete"))
    uninstalled = resolver.status({"state": "connected", "installed": True})
    assert uninstalled["state"] == "not_installed"
    assert uninstalled["installed"] is False
    assert uninstalled["allowed_actions"] == ["setup"]


def test_mattermost_dependency_actions_use_only_independent_agent_facts(tmp_path):
    resolver = IntegrationLifecycleResolver(repository(tmp_path))
    status = resolver.status(legacy())

    active = resolver.apply_mattermost_dependencies(
        status, {"state": "enabled", "installed": True, "enabled": True}
    )
    assert active["allowed_actions"] == []
    assert [item["dependency_code"] for item in active["blocked_actions"]] == [
        "agents_must_be_disabled",
        "agents_must_be_uninstalled",
    ]

    disabled = resolver.apply_mattermost_dependencies(
        status, {"state": "disabled", "installed": True, "enabled": False}
    )
    assert disabled["allowed_actions"] == ["disable"]
    assert disabled["blocked_actions"][0]["dependency_code"] == (
        "agents_must_be_uninstalled"
    )

    absent = resolver.apply_mattermost_dependencies(
        status, {"state": "not_installed", "installed": False, "enabled": False}
    )
    assert absent["allowed_actions"] == ["disable", "uninstall"]
    assert absent["blocked_actions"] == []


def snapshot_service(tmp_path):
    return AgentLifecycleSnapshotService(
        lifecycle_repository=repository(tmp_path, "agents"),
        config_path=tmp_path / "agents.json",
        agent_unit_path=tmp_path / "limeos-agent.service",
        broker_unit_path=tmp_path / "limeopsd.service",
    )


def test_agent_snapshot_derives_legacy_state_without_mattermost(tmp_path):
    service = snapshot_service(tmp_path)
    assert service.status() == {
        "state": "not_installed",
        "installed": False,
        "enabled": False,
    }

    (tmp_path / "limeos-agent.service").write_text("unit", encoding="utf-8")
    (tmp_path / "limeopsd.service").write_text("unit", encoding="utf-8")
    (tmp_path / "agents.json").write_text('{"enabled": false}', encoding="utf-8")
    assert service.status() == {
        "state": "disabled",
        "installed": True,
        "enabled": False,
    }

    (tmp_path / "agents.json").write_text('{"enabled": true}', encoding="utf-8")
    assert service.status() == {
        "state": "enabled",
        "installed": True,
        "enabled": True,
    }


def test_agent_snapshot_fails_closed_for_partial_runtime_and_tombstone(tmp_path):
    service = snapshot_service(tmp_path)
    (tmp_path / "limeos-agent.service").write_text("unit", encoding="utf-8")
    assert service.status()["state"] == "cleanup_required"

    lifecycle_path = tmp_path / "agents-lifecycle.json"
    lifecycle_path.write_text("{", encoding="utf-8")
    lifecycle_path.chmod(0o640)
    assert service.status()["state"] == "cleanup_required"


def test_agent_snapshot_exposes_package_reconciliation_feature_state(tmp_path):
    service = snapshot_service(tmp_path)
    assert service.package_feature_state() == {
        "feature": "ai_agents",
        "state": "not_installed",
        "managed": False,
        "reconcile_allowed": False,
    }

    (tmp_path / "limeos-agent.service").write_text("unit", encoding="utf-8")
    (tmp_path / "limeopsd.service").write_text("unit", encoding="utf-8")
    (tmp_path / "agents.json").write_text('{"enabled": false}', encoding="utf-8")
    assert service.package_feature_state() == {
        "feature": "ai_agents",
        "state": "disabled",
        "managed": True,
        "reconcile_allowed": True,
    }

def test_recovery_credential_custody_uses_fixed_parameter_free_commands():
    calls = []

    def helper(command, params):
        calls.append((command, params))
        field = {
            "mattermost_recovery_credential_retain": "credential_retained",
            "mattermost_recovery_credential_restore": "credential_restored",
            "mattermost_recovery_credential_discard": "credential_discarded",
        }[command]
        return {"success": True, field: True, "path": "/private/path"}

    custody = RecoveryCredentialCustody(helper)
    assert custody.retain() == {"success": True, "credential_retained": True}
    assert custody.restore() == {"success": True, "credential_restored": True}
    assert custody.discard() == {"success": True, "credential_discarded": True}
    assert all(params == {} for _command, params in calls)
    assert "/private/path" not in json.dumps(
        [custody.retain(), custody.restore(), custody.discard()]
    )


def test_recovery_credential_custody_bounds_helper_failures():
    custody = RecoveryCredentialCustody(
        lambda *_args: {"success": False, "error": "password at /private/path"}
    )
    with pytest.raises(
        RecoveryCredentialError,
        match="Mattermost recovery credential operation failed",
    ) as failure:
        custody.retain()
    assert "/private/path" not in str(failure.value)
