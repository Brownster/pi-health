import copy
import json
from pathlib import Path

from jsonschema import Draft7Validator, FormatChecker


CONFIG_PATH = Path("config/integration-lifecycle.json")
SCHEMA_DIR = Path("config/schemas")
STATUS_SCHEMA_PATH = SCHEMA_DIR / "integration-lifecycle-status.schema.json"
TOMBSTONE_SCHEMA_PATH = SCHEMA_DIR / "integration-lifecycle-tombstone.schema.json"

CONTRACT = json.loads(CONFIG_PATH.read_text())
STATUS_SCHEMA = json.loads(STATUS_SCHEMA_PATH.read_text())
TOMBSTONE_SCHEMA = json.loads(TOMBSTONE_SCHEMA_PATH.read_text())


def errors(schema: dict, payload: dict) -> list[str]:
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(payload), key=str)]


def connected_status() -> dict:
    return {
        "state": "connected",
        "installed": True,
        "retained_data": False,
        "cleanup_required": False,
        "allowed_actions": ["disable", "uninstall"],
        "blocked_actions": [],
        "cleanup_operation": None,
        "warnings": [],
    }


def tombstone(*, integration: str = "mattermost", action: str = "uninstall") -> dict:
    return {
        "schema_version": "1",
        "integration": integration,
        "operation_id": "abc123",
        "action": action,
        "phase": "running",
        "target_state": "retained_data" if integration == "mattermost" else "not_installed",
        "started_at": "2026-07-20T20:00:00+00:00",
        "updated_at": "2026-07-20T20:00:01+00:00",
        "completed_steps": [],
        "retained_data": integration == "mattermost",
        "remove_claude_code": True if integration == "agents" else None,
        "failure": None,
        "warning_codes": [],
    }


def test_lifecycle_schemas_are_valid_draft_7():
    Draft7Validator.check_schema(STATUS_SCHEMA)
    Draft7Validator.check_schema(TOMBSTONE_SCHEMA)


def test_state_and_action_order_are_frozen_in_the_public_schema():
    assert STATUS_SCHEMA["properties"]["state"]["enum"] == CONTRACT["state_precedence"]
    assert STATUS_SCHEMA["definitions"]["action"]["enum"] == CONTRACT["action_order"]

    order = {action: index for index, action in enumerate(CONTRACT["action_order"])}
    for integration in CONTRACT["integrations"].values():
        actions = integration["allowed_actions"]
        assert actions == sorted(actions, key=order.__getitem__)


def test_connected_and_legacy_not_installed_projections_are_valid_without_tombstones():
    assert errors(STATUS_SCHEMA, connected_status()) == []

    not_installed = connected_status()
    not_installed.update(
        state="not_installed",
        installed=False,
        allowed_actions=["setup"],
    )
    assert errors(STATUS_SCHEMA, not_installed) == []


def test_retained_data_is_distinct_from_installed_and_not_installed():
    retained = connected_status()
    retained.update(
        state="retained_data",
        installed=False,
        retained_data=True,
        allowed_actions=["setup"],
    )
    assert errors(STATUS_SCHEMA, retained) == []

    contradictory = copy.deepcopy(retained)
    contradictory["installed"] = True
    assert errors(STATUS_SCHEMA, contradictory)


def test_cleanup_required_has_a_bounded_retryable_operation_projection():
    status = connected_status()
    status.update(
        state="cleanup_required",
        cleanup_required=True,
        allowed_actions=["retry_cleanup"],
        cleanup_operation={
            "id": "abc123",
            "action": "uninstall",
            "state": "interrupted",
            "started_at": "2026-07-20T20:00:00+00:00",
            "updated_at": "2026-07-20T20:01:00+00:00",
            "retryable": True,
        },
    )
    assert errors(STATUS_SCHEMA, status) == []

    missing_operation = copy.deepcopy(status)
    missing_operation["cleanup_operation"] = None
    assert errors(STATUS_SCHEMA, missing_operation)

    leaked_detail = copy.deepcopy(status)
    leaked_detail["cleanup_operation"]["error"] = "/etc/limeos/integrations/mattermost.env"
    assert errors(STATUS_SCHEMA, leaked_detail)


def test_blocked_actions_are_bounded_and_use_only_the_internal_agents_route():
    status = connected_status()
    blocked = CONTRACT["blocked_actions"]["agents_must_be_disabled"]
    status["blocked_actions"] = [
        {"dependency_code": "agents_must_be_disabled", **blocked}
    ]
    assert errors(STATUS_SCHEMA, status) == []

    external = copy.deepcopy(status)
    external["blocked_actions"][0]["route"] = "https://example.invalid/agents"
    assert errors(STATUS_SCHEMA, external)

    unknown = copy.deepcopy(status)
    unknown["blocked_actions"][0]["dependency_code"] = "arbitrary_dependency"
    assert errors(STATUS_SCHEMA, unknown)


def test_warnings_use_a_fixed_code_and_message_catalog():
    status = connected_status()
    code, message = next(iter(CONTRACT["warnings"].items()))
    status["warnings"] = [{"code": code, "message": message}]
    assert errors(STATUS_SCHEMA, status) == []

    raw_exception = copy.deepcopy(status)
    raw_exception["warnings"][0]["detail"] = "token=secret"
    assert errors(STATUS_SCHEMA, raw_exception)


def test_tombstones_are_versioned_secret_free_and_fail_closed_structurally():
    assert errors(TOMBSTONE_SCHEMA, tombstone()) == []
    assert errors(TOMBSTONE_SCHEMA, tombstone(integration="agents")) == []

    unsupported = tombstone()
    unsupported["schema_version"] = "2"
    assert errors(TOMBSTONE_SCHEMA, unsupported)

    leaked_secret = tombstone()
    leaked_secret["database_password"] = "secret"
    assert errors(TOMBSTONE_SCHEMA, leaked_secret)

    cleanup_required = tombstone()
    cleanup_required["phase"] = "cleanup_required"
    assert errors(TOMBSTONE_SCHEMA, cleanup_required)
    cleanup_required["failure"] = {
        "code": "compose_cleanup_failed",
        "message": "Mattermost cleanup did not complete.",
    }
    assert errors(TOMBSTONE_SCHEMA, cleanup_required) == []


def test_agent_uninstall_records_the_claude_choice_but_mattermost_never_can():
    agent = tombstone(integration="agents")
    assert errors(TOMBSTONE_SCHEMA, agent) == []
    agent["remove_claude_code"] = None
    assert errors(TOMBSTONE_SCHEMA, agent)

    mattermost = tombstone()
    mattermost["remove_claude_code"] = False
    assert errors(TOMBSTONE_SCHEMA, mattermost)


def test_recovery_credential_is_root_custodied_with_parameter_free_helper_commands():
    recovery = CONTRACT["recovery_credential"]
    assert recovery["custody"] == "helper_only"
    assert recovery["directory_mode"] == "0700"
    assert recovery["file_mode"] == "0600"
    assert recovery["active_path"] != recovery["recovery_path"]
    assert recovery["transfer_strategy"] == (
        "destination-temp-fsync-replace-then-source-unlink"
    )
    assert [command["name"] for command in recovery["commands"].values()] == [
        "mattermost_recovery_credential_retain",
        "mattermost_recovery_credential_restore",
        "mattermost_recovery_credential_discard",
    ]
    assert all(not command["parameters"] for command in recovery["commands"].values())
    assert all(
        "path" not in field and "secret" not in field and "password" not in field
        for field in recovery["public_result_fields"]
    )


def test_destructive_ownership_is_fixed_and_purge_starts_unreleased():
    mattermost = CONTRACT["integrations"]["mattermost"]
    agents = CONTRACT["integrations"]["agents"]

    assert CONTRACT["release_policy"]["mattermost_purge_enabled"] is False
    assert mattermost["compose_project"] == "mattermost"
    assert mattermost["logical_volumes"] == [
        "mattermost-postgres",
        "mattermost-config",
        "mattermost-data",
        "mattermost-logs",
        "mattermost-plugins",
    ]
    assert "docker.io/library/postgres:16-alpine" in mattermost["never_owned"]
    assert "/var/log/limeos/agent-audit.jsonl" in agents["preserved_on_uninstall"]
    assert agents["optional_package_cleanup"] == {
        "package": "claude-code",
        "source": "/etc/apt/sources.list.d/claude-code.list",
        "signing_key": "/etc/apt/keyrings/claude-code.asc",
        "default_remove": True,
    }


def test_tombstones_are_not_part_of_legacy_state_derivation():
    tombstone_paths = set(CONTRACT["tombstone"]["paths"].values())
    owned_paths = {
        path
        for integration in CONTRACT["integrations"].values()
        for key in ("owned_files", "owned_directories")
        for path in integration.get(key, [])
    }
    assert tombstone_paths.isdisjoint(owned_paths)
    assert CONTRACT["tombstone"]["create_when"] == "operation_started"
