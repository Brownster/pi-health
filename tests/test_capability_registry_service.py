import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from capability_registry_service import (
    CapabilityContractIncompatibleError,
    CapabilityContractInvalidError,
    CapabilityContractValidator,
    CapabilityRegistryService,
    ProviderCandidate,
)


FIXTURE_DIR = Path("tests/fixtures/capability_providers")
SCHEMA_DIR = Path("config/schemas")
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


def fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def status_payload(
    provider_id: str,
    capability_id: str,
    *,
    state: str = "healthy",
    configured: bool = True,
) -> dict:
    status = fixture("partial-failure.status.json")
    status["provider_id"] = provider_id
    status["capability_id"] = capability_id
    status["lifecycle"]["configured"] = configured
    status["health"] = {
        "state": state,
        "message": f"Provider is {state}.",
        "issues": [],
    }
    return status


def registry(candidates, *, limeos_version: str = "1.0.0", schema_dir=SCHEMA_DIR):
    return CapabilityRegistryService(
        candidate_reader=lambda: candidates,
        limeos_version=limeos_version,
        schema_dir=schema_dir,
        clock=lambda: NOW,
    )


def test_contract_validator_distinguishes_invalid_and_incompatible_manifests():
    validator = CapabilityContractValidator(schema_dir=SCHEMA_DIR)

    with pytest.raises(CapabilityContractIncompatibleError) as incompatible:
        validator.validate_manifest(fixture("incompatible-version.manifest.json"))
    assert incompatible.value.details == ("manifest_version",)

    with pytest.raises(CapabilityContractInvalidError) as invalid:
        validator.validate_manifest(fixture("invalid-renderer.manifest.json"))
    assert invalid.value.details == (
        "unregistered_tailored_renderer:external-dashboard",
    )


def test_missing_or_malformed_version_fields_are_invalid_not_future_contracts():
    validator = CapabilityContractValidator(schema_dir=SCHEMA_DIR)
    missing = fixture("generic-pooling.manifest.json")
    del missing["manifest_version"]
    malformed = fixture("generic-pooling.manifest.json")
    malformed["compatibility"] = []

    for manifest in (missing, malformed):
        with pytest.raises(CapabilityContractInvalidError):
            validator.validate_manifest(manifest)


def test_contract_validator_rejects_inverted_version_and_parameter_ranges():
    validator = CapabilityContractValidator(schema_dir=SCHEMA_DIR)
    manifest = fixture("snapraid.manifest.json")
    manifest["compatibility"].update(
        {"limeos_min": "2.0.0", "limeos_max": "1.0.0"}
    )
    manifest["capabilities"][0]["actions"][1]["parameters"][0].update(
        {"minimum": 100, "maximum": 1}
    )

    with pytest.raises(CapabilityContractInvalidError) as invalid:
        validator.validate_manifest(manifest)

    assert invalid.value.details == (
        "invalid_compatibility_range",
        "invalid_action_parameter_range:scrub:percent",
    )


def test_snapshot_discovers_providers_and_builds_capability_health_index():
    candidates = [
        ProviderCandidate(
            fixture("mergerfs.manifest.json"),
            configured=True,
            status_reader=lambda _capability_id: fixture(
                "partial-failure.status.json"
            ),
        ),
        ProviderCandidate(
            fixture("generic-pooling.manifest.json"),
            enabled=False,
            configured=True,
        ),
        ProviderCandidate(
            fixture("snapraid.manifest.json"),
            configured=True,
            status_reader=lambda capability_id: status_payload(
                "snapraid", capability_id
            ),
        ),
    ]

    snapshot = registry(candidates).snapshot()

    assert [provider["id"] for provider in snapshot["providers"]] == [
        "mergerfs",
        "snapraid",
        "unionfs-provider",
    ]
    assert snapshot["errors"] == []
    capabilities = {item["id"]: item for item in snapshot["capabilities"]}
    assert capabilities["storage.pooling"]["counts"] == {
        "providers": 2,
        "enabled": 1,
        "operational": 1,
    }
    assert capabilities["storage.pooling"]["health"]["state"] == "warning"
    assert capabilities["storage.protection"]["health"]["state"] == "healthy"


def test_disabled_provider_remains_discoverable_without_reading_runtime_status():
    calls = []

    def status_reader(_capability_id):
        calls.append("called")
        raise AssertionError("disabled provider status must not be read")

    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        enabled=False,
        configured={"storage.pooling": True},
        status_reader=status_reader,
    )
    snapshot = registry([candidate]).snapshot()
    provider = snapshot["providers"][0]
    status = provider["capabilities"][0]["status"]

    assert calls == []
    assert provider["contract_state"] == "valid"
    assert status["lifecycle"]["configured"] is True
    assert status["health"]["state"] == "disabled"
    assert provider["capabilities"][0]["operational"] is False


def test_status_reader_failure_isolated_and_public_error_is_redacted():
    def status_reader(_capability_id):
        raise RuntimeError("token=super-secret")

    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        configured=True,
        status_reader=status_reader,
    )
    snapshot = registry([candidate]).snapshot()
    serialized = json.dumps(snapshot)

    assert snapshot["providers"][0]["health"]["state"] == "unavailable"
    assert snapshot["errors"] == [
        {
            "code": "provider_status_unavailable",
            "message": "Provider status is unavailable.",
            "provider_id": "unionfs-provider",
        }
    ]
    assert "super-secret" not in serialized
    assert "token=" not in serialized


def test_status_payload_redacts_sensitive_keys_and_text():
    status = status_payload("unionfs-provider", "storage.pooling")
    status["details"] = {
        "password": "secret-value",
        "diagnostic": "request failed token=private-value",
        "nested": {"authorization": "Bearer private-value"},
    }
    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        configured=True,
        status_reader=lambda _capability_id: status,
    )
    details = registry([candidate]).snapshot()["providers"][0]["capabilities"][0][
        "status"
    ]["details"]

    assert details == {
        "password": "[redacted]",
        "diagnostic": "request failed token=[redacted]",
        "nested": {"authorization": "[redacted]"},
    }


def test_oversized_status_fails_closed():
    status = status_payload("unionfs-provider", "storage.pooling")
    status["details"] = {"diagnostic": "x" * 300_000}
    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        configured=True,
        status_reader=lambda _capability_id: status,
    )
    snapshot = registry([candidate]).snapshot()

    assert snapshot["providers"][0]["health"]["state"] == "unavailable"
    assert snapshot["errors"][0]["code"] == "provider_status_invalid"


def test_invalid_status_identity_fails_closed_without_hiding_provider():
    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        configured=True,
        status_reader=lambda capability_id: status_payload(
            "different-provider", capability_id
        ),
    )
    snapshot = registry([candidate]).snapshot()
    provider = snapshot["providers"][0]

    assert provider["contract_state"] == "valid"
    assert provider["health"]["state"] == "unavailable"
    assert snapshot["errors"][0]["code"] == "provider_status_invalid"


def test_invalid_manifest_does_not_hide_a_valid_provider():
    candidates = [
        ProviderCandidate(fixture("invalid-unknown-field.manifest.json")),
        ProviderCandidate(
            fixture("generic-protection.manifest.json"),
            enabled=False,
        ),
    ]
    snapshot = registry(candidates).snapshot()
    providers = {provider["id"]: provider for provider in snapshot["providers"]}

    assert providers["unsafe-provider"]["contract_state"] == "invalid"
    assert providers["unsafe-provider"]["capabilities"] == []
    assert providers["backup-provider"]["contract_state"] == "valid"
    assert [item["id"] for item in snapshot["capabilities"]] == [
        "storage.protection"
    ]


def test_incompatible_manifest_is_visible_but_exposes_no_capabilities():
    snapshot = registry(
        [ProviderCandidate(fixture("incompatible-version.manifest.json"))]
    ).snapshot()
    provider = snapshot["providers"][0]

    assert provider["contract_state"] == "incompatible"
    assert provider["compatibility"] == "incompatible"
    assert provider["health"]["state"] == "incompatible"
    assert snapshot["capabilities"] == []


def test_limeos_version_range_marks_valid_provider_incompatible():
    manifest = fixture("generic-pooling.manifest.json")
    manifest["compatibility"]["limeos_min"] = "2.0.0"
    snapshot = registry([ProviderCandidate(manifest)], limeos_version="1.9.9").snapshot()
    provider = snapshot["providers"][0]
    capability = provider["capabilities"][0]

    assert provider["contract_state"] == "valid"
    assert provider["compatibility"] == "incompatible"
    assert capability["status"]["health"]["state"] == "incompatible"
    assert capability["operational"] is False


def test_candidate_lifecycle_facts_override_provider_status_claims():
    status = status_payload("unionfs-provider", "storage.pooling")
    status["lifecycle"].update(
        {
            "installed": False,
            "enabled": False,
            "configured": False,
            "compatibility": "incompatible",
        }
    )
    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        installed=True,
        enabled=True,
        configured=True,
        status_reader=lambda _capability_id: status,
    )
    lifecycle = registry([candidate]).snapshot()["providers"][0]["capabilities"][0][
        "status"
    ]["lifecycle"]

    assert lifecycle["installed"] is True
    assert lifecycle["enabled"] is True
    assert lifecycle["configured"] is True
    assert lifecycle["compatibility"] == "compatible"


def test_duplicate_provider_id_keeps_first_and_reports_second():
    first = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        enabled=False,
        source="first",
    )
    second = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        enabled=False,
        source="second",
    )
    snapshot = registry([first, second]).snapshot()

    assert len(snapshot["providers"]) == 1
    assert snapshot["providers"][0]["source"] == "first"
    assert snapshot["errors"][-1]["code"] == "duplicate_provider"


def test_provider_source_url_drops_credentials_query_and_fragment():
    candidate = ProviderCandidate(
        fixture("generic-pooling.manifest.json"),
        enabled=False,
        source="https://user:secret@github.com/example/provider?token=secret#readme",
    )
    provider = registry([candidate]).snapshot()["providers"][0]
    assert provider["source"] == "https://github.com/example/provider"


def test_manifest_reader_failure_isolated_by_provider_hint():
    def broken_manifest():
        raise OSError("private filesystem detail")

    candidates = [
        ProviderCandidate(broken_manifest, provider_id_hint="broken-provider"),
        ProviderCandidate(
            fixture("generic-protection.manifest.json"),
            enabled=False,
        ),
    ]
    snapshot = registry(candidates).snapshot()

    assert [provider["id"] for provider in snapshot["providers"]] == [
        "backup-provider"
    ]
    assert snapshot["errors"][0]["provider_id"] == "broken-provider"
    assert "private filesystem detail" not in json.dumps(snapshot)


def test_candidate_discovery_failure_returns_bounded_empty_snapshot():
    service = CapabilityRegistryService(
        candidate_reader=lambda: (_ for _ in ()).throw(RuntimeError("secret")),
        limeos_version="1.0.0",
        schema_dir=SCHEMA_DIR,
        clock=lambda: NOW,
    )

    assert service.snapshot() == {
        "schema_version": "1",
        "providers": [],
        "capabilities": [],
        "errors": [
            {
                "code": "provider_discovery_unavailable",
                "message": "Provider discovery is unavailable.",
            }
        ],
    }


def test_malformed_candidate_isolated_from_valid_candidates():
    candidates = [
        object(),
        ProviderCandidate(
            fixture("generic-protection.manifest.json"),
            enabled=False,
        ),
    ]
    snapshot = registry(candidates).snapshot()

    assert [provider["id"] for provider in snapshot["providers"]] == [
        "backup-provider"
    ]
    assert snapshot["errors"] == [
        {
            "code": "provider_candidate_invalid",
            "message": "Provider candidate is invalid.",
        }
    ]


def test_contract_schema_failure_does_not_raise_from_snapshot(tmp_path):
    service = registry([], schema_dir=tmp_path)
    assert service.snapshot()["errors"] == [
        {
            "code": "contract_schemas_unavailable",
            "message": "Capability contracts are unavailable.",
        }
    ]


def test_default_schema_path_does_not_depend_on_working_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    service = CapabilityRegistryService(
        candidate_reader=lambda: [],
        limeos_version="1.0.0",
        clock=lambda: NOW,
    )
    assert service.snapshot() == {
        "schema_version": "1",
        "providers": [],
        "capabilities": [],
        "errors": [],
    }


def test_registry_performs_no_discovery_or_status_work_until_snapshot():
    discovery_calls = []
    status_calls = []

    def candidate_reader():
        discovery_calls.append("discover")
        return [
            ProviderCandidate(
                fixture("generic-protection.manifest.json"),
                configured=True,
                status_reader=lambda capability_id: (
                    status_calls.append(capability_id)
                    or status_payload("backup-provider", capability_id)
                ),
            )
        ]

    service = CapabilityRegistryService(
        candidate_reader=candidate_reader,
        limeos_version="1.0.0",
        schema_dir=SCHEMA_DIR,
        clock=lambda: NOW,
    )
    assert discovery_calls == []
    assert status_calls == []

    service.snapshot()
    assert discovery_calls == ["discover"]
    assert status_calls == ["storage.protection"]


def test_duplicate_capability_manifest_is_invalid_in_registry():
    snapshot = registry(
        [ProviderCandidate(fixture("invalid-duplicate-capability.manifest.json"))]
    ).snapshot()
    provider = snapshot["providers"][0]

    assert provider["contract_state"] == "invalid"
    assert provider["capabilities"] == []
    assert snapshot["errors"][0]["code"] == "contract_invalid"


def test_snapshot_returns_copies_not_provider_owned_payloads():
    manifest = fixture("generic-pooling.manifest.json")
    status = status_payload("unionfs-provider", "storage.pooling")
    candidate = ProviderCandidate(
        manifest,
        configured=True,
        status_reader=lambda _capability_id: status,
    )

    snapshot = registry([candidate]).snapshot()
    snapshot["providers"][0]["capabilities"][0]["renderer"]["id"] = "changed"
    snapshot["providers"][0]["capabilities"][0]["status"]["details"]["changed"] = True

    assert manifest["capabilities"][0]["renderer"]["id"] == "generic"
    assert "changed" not in status["details"]


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.0.0"])
def test_registry_rejects_ambiguous_limeos_versions(version):
    with pytest.raises(ValueError, match="major.minor.patch"):
        registry([], limeos_version=version)
