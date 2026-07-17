import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource


SCHEMA_DIR = Path("config/schemas")
FIXTURE_DIR = Path("tests/fixtures/capability_providers")
SCHEMA_FILES = {
    "manifest": "capability-provider-manifest.schema.json",
    "permissions": "capability-provider-permissions.schema.json",
    "renderer": "capability-provider-renderer.schema.json",
    "setup": "capability-provider-setup.schema.json",
    "status": "capability-provider-status.schema.json",
    "actions": "capability-provider-actions.schema.json",
}
SCHEMAS = {
    name: json.loads((SCHEMA_DIR / filename).read_text())
    for name, filename in SCHEMA_FILES.items()
}
SCHEMA_REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema))
    for schema in SCHEMAS.values()
)

SURFACE_BY_CAPABILITY = {
    "storage.pooling": "pools",
    "storage.protection": "protection",
    "integration.chat": "integrations",
}
TAILORED_RENDERERS = {
    ("mergerfs", "storage.pooling", "mergerfs"),
    ("snapraid", "storage.protection", "snapraid"),
    ("mattermost", "integration.chat", "mattermost"),
}


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def schema_errors(contract: str, payload: dict) -> list[str]:
    validator = Draft7Validator(
        SCHEMAS[contract],
        registry=SCHEMA_REGISTRY,
        format_checker=FormatChecker(),
    )
    return [error.message for error in sorted(validator.iter_errors(payload), key=str)]


def manifest_semantic_errors(manifest: dict) -> list[str]:
    errors = []
    capability_ids = set()

    for capability in manifest.get("capabilities", []):
        capability_id = capability.get("id")
        if capability_id in capability_ids:
            errors.append(f"duplicate capability: {capability_id}")
        capability_ids.add(capability_id)

        expected_surface = SURFACE_BY_CAPABILITY.get(capability_id)
        if expected_surface and capability.get("surface") != expected_surface:
            errors.append(f"invalid surface for {capability_id}")

        renderer = capability.get("renderer", {})
        if renderer.get("mode") == "tailored":
            renderer_key = (manifest.get("id"), capability_id, renderer.get("id"))
            if renderer_key not in TAILORED_RENDERERS:
                errors.append(f"unregistered tailored renderer: {renderer.get('id')}")

        action_ids = set()
        for action in capability.get("actions", []):
            action_id = action.get("id")
            if action_id in action_ids:
                errors.append(f"duplicate action: {action_id}")
            action_ids.add(action_id)

            parameter_names = [item.get("name") for item in action.get("parameters", [])]
            if len(parameter_names) != len(set(parameter_names)):
                errors.append(f"duplicate parameter in action: {action_id}")

    return errors


def setup_semantic_errors(setup: dict) -> list[str]:
    errors = []
    fields = setup.get("fields", [])
    field_keys = [field.get("key") for field in fields]
    known_fields = set(field_keys)

    if len(field_keys) != len(known_fields):
        errors.append("duplicate setup field")

    for field in fields:
        minimum = field.get("minimum")
        maximum = field.get("maximum")
        if minimum is not None and maximum is not None and minimum > maximum:
            errors.append(f"invalid range: {field.get('key')}")

    section_ids = [section.get("id") for section in setup.get("sections", [])]
    if len(section_ids) != len(set(section_ids)):
        errors.append("duplicate setup section")

    for section in setup.get("sections", []):
        for field_key in section.get("fields", []):
            if field_key not in known_fields:
                errors.append(f"unknown section field: {field_key}")

    return errors


def action_catalog_semantic_errors(catalog: dict) -> list[str]:
    declarations = [action.get("id") for action in catalog.get("actions", [])]
    availability = [item.get("id") for item in catalog.get("availability", [])]
    errors = []

    if len(declarations) != len(set(declarations)):
        errors.append("duplicate action declaration")
    if len(availability) != len(set(availability)):
        errors.append("duplicate action availability")
    if set(declarations) != set(availability):
        errors.append("action availability does not match declarations")

    for action in catalog.get("actions", []):
        names = [item.get("name") for item in action.get("parameters", [])]
        if len(names) != len(set(names)):
            errors.append(f"duplicate parameter in action: {action.get('id')}")

    return errors


def contract_compatibility(manifest: dict) -> str:
    if manifest.get("manifest_version") != "1":
        return "incompatible"
    if manifest.get("compatibility", {}).get("capability_api") != "1":
        return "incompatible"
    return "compatible"


def effective_health(status: dict) -> str:
    lifecycle = status["lifecycle"]
    if not lifecycle["installed"]:
        return "unavailable"
    if lifecycle["compatibility"] == "incompatible":
        return "incompatible"
    if not lifecycle["enabled"]:
        return "disabled"
    if lifecycle["availability"] == "unavailable":
        return "unavailable"
    if not lifecycle["configured"]:
        return "unconfigured"
    return status["health"]["state"]


def test_all_contract_schemas_are_valid_draft_7():
    for schema in SCHEMAS.values():
        Draft7Validator.check_schema(schema)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "mergerfs.manifest.json",
        "snapraid.manifest.json",
        "generic-pooling.manifest.json",
        "generic-protection.manifest.json",
        "mattermost-adapter.manifest.json",
    ],
)
def test_valid_provider_manifests_satisfy_structural_and_semantic_contracts(fixture_name):
    manifest = load_fixture(fixture_name)
    assert schema_errors("manifest", manifest) == []
    assert manifest_semantic_errors(manifest) == []
    assert contract_compatibility(manifest) == "compatible"


def test_pooling_and_protection_fixtures_have_distinct_owners():
    mergerfs = load_fixture("mergerfs.manifest.json")["capabilities"][0]
    snapraid = load_fixture("snapraid.manifest.json")["capabilities"][0]

    assert (mergerfs["id"], mergerfs["surface"]) == ("storage.pooling", "pools")
    assert (snapraid["id"], snapraid["surface"]) == (
        "storage.protection",
        "protection",
    )


def test_unknown_manifest_fields_fail_closed():
    manifest = load_fixture("invalid-unknown-field.manifest.json")
    errors = schema_errors("manifest", manifest)
    assert any("frontend_bundle" in error for error in errors)


def test_duplicate_capabilities_are_a_semantic_error():
    manifest = load_fixture("invalid-duplicate-capability.manifest.json")
    assert schema_errors("manifest", manifest) == []
    assert manifest_semantic_errors(manifest) == [
        "duplicate capability: storage.pooling"
    ]


def test_unregistered_tailored_renderer_is_a_semantic_error():
    manifest = load_fixture("invalid-renderer.manifest.json")
    assert schema_errors("manifest", manifest) == []
    assert manifest_semantic_errors(manifest) == [
        "unregistered tailored renderer: external-dashboard"
    ]


def test_wrong_capability_surface_is_rejected_semantically():
    manifest = load_fixture("generic-pooling.manifest.json")
    manifest["capabilities"][0]["surface"] = "protection"
    assert schema_errors("manifest", manifest) == []
    assert manifest_semantic_errors(manifest) == [
        "invalid surface for storage.pooling"
    ]


def test_unsupported_contract_versions_are_incompatible_and_fail_schema_validation():
    manifest = load_fixture("incompatible-version.manifest.json")
    assert contract_compatibility(manifest) == "incompatible"
    assert schema_errors("manifest", manifest)

    renderer_manifest = load_fixture("generic-pooling.manifest.json")
    renderer_manifest["capabilities"][0]["renderer"]["schema_version"] = "2"
    assert schema_errors("manifest", renderer_manifest)


def test_integration_adapter_cannot_declare_a_python_entry_point():
    manifest = load_fixture("mattermost-adapter.manifest.json")
    manifest["runtime"]["entry"] = "mattermost.py"
    manifest["runtime"]["class"] = "MattermostAdapter"
    assert schema_errors("manifest", manifest)


def test_generic_setup_fixture_and_secret_reference_are_valid():
    setup = load_fixture("generic-pooling.setup.json")
    assert schema_errors("setup", setup) == []
    assert setup_semantic_errors(setup) == []


def test_secret_reference_rejects_defaults_placeholders_and_patterns():
    setup = load_fixture("generic-pooling.setup.json")
    secret_field = next(
        field for field in setup["fields"] if field["type"] == "secret_reference"
    )

    for forbidden_field in ("default", "placeholder", "pattern"):
        candidate = copy.deepcopy(setup)
        secret = next(
            field
            for field in candidate["fields"]
            if field["type"] == "secret_reference"
        )
        secret[forbidden_field] = "forbidden"
        assert schema_errors("setup", candidate)

    assert "default" not in secret_field


def test_setup_semantics_reject_duplicates_unknown_fields_and_invalid_ranges():
    duplicate = load_fixture("generic-pooling.setup.json")
    duplicate["fields"].append(copy.deepcopy(duplicate["fields"][0]))
    assert setup_semantic_errors(duplicate) == ["duplicate setup field"]

    unknown = load_fixture("generic-pooling.setup.json")
    unknown["sections"][0]["fields"].append("missing_field")
    assert setup_semantic_errors(unknown) == ["unknown section field: missing_field"]

    invalid_range = load_fixture("generic-pooling.setup.json")
    invalid_range["fields"][0]["minimum"] = 10
    invalid_range["fields"][0]["maximum"] = 1
    assert setup_semantic_errors(invalid_range) == ["invalid range: pool_name"]


def test_action_catalog_fixture_satisfies_structural_and_semantic_contracts():
    catalog = load_fixture("generic-pooling.actions.json")
    assert schema_errors("actions", catalog) == []
    assert action_catalog_semantic_errors(catalog) == []


def test_mutating_action_requires_confirmation():
    catalog = load_fixture("generic-pooling.actions.json")
    mount_action = next(action for action in catalog["actions"] if action["id"] == "mount")
    del mount_action["confirmation"]
    assert schema_errors("actions", catalog)


def test_action_availability_must_match_declared_actions():
    catalog = load_fixture("generic-pooling.actions.json")
    catalog["availability"].append({"id": "undeclared", "available": True})
    assert schema_errors("actions", catalog) == []
    assert action_catalog_semantic_errors(catalog) == [
        "action availability does not match declarations"
    ]


@pytest.mark.parametrize(
    "fixture_name, expected",
    [
        ("disabled.status.json", "disabled"),
        ("partial-failure.status.json", "warning"),
    ],
)
def test_status_fixtures_validate_and_apply_health_precedence(fixture_name, expected):
    status = load_fixture(fixture_name)
    assert schema_errors("status", status) == []
    assert effective_health(status) == expected


@pytest.mark.parametrize(
    "lifecycle_changes, expected",
    [
        ({"installed": False}, "unavailable"),
        ({"compatibility": "incompatible"}, "incompatible"),
        ({"enabled": False}, "disabled"),
        ({"availability": "unavailable"}, "unavailable"),
        ({"configured": False}, "unconfigured"),
    ],
)
def test_lifecycle_state_precedes_provider_health(lifecycle_changes, expected):
    status = load_fixture("partial-failure.status.json")
    status["lifecycle"].update(lifecycle_changes)
    assert effective_health(status) == expected


def test_action_event_contract_bounds_progress_and_event_types():
    event_schema = SCHEMAS["actions"]["definitions"]["actionEvent"]
    validator = Draft7Validator(event_schema, format_checker=FormatChecker())
    valid_event = {
        "schema_version": "1",
        "operation_id": "operation-1",
        "sequence": 3,
        "type": "progress",
        "message": "Checking branches",
        "percent": 50,
    }
    assert list(validator.iter_errors(valid_event)) == []

    invalid_event = {**valid_event, "percent": 101, "type": "arbitrary"}
    assert len(list(validator.iter_errors(invalid_event))) == 2
