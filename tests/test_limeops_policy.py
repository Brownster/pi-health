import pytest

from limeops.policy import LimeOpsPolicy, PolicyError


POLICY = {
    "schema_version": "1",
    "defaults": {"timeout_seconds": 10, "max_output_bytes": 4096},
    "operations": {
        "system.status": {"enabled": True},
        "container.logs": {
            "enabled": True,
            "timeout_seconds": 20,
            "max_output_bytes": 8192,
            "resources": ["jellyfin", "plex"],
        },
        "stack.inspect": {"enabled": False},
    },
}


def test_policy_applies_defaults_and_operation_overrides():
    policy = LimeOpsPolicy.from_mapping(POLICY)

    system = policy.require("system.status")
    logs = policy.require("container.logs")

    assert system.timeout_seconds == 10
    assert system.max_output_bytes == 4096
    assert system.resources == ()
    assert logs.timeout_seconds == 20
    assert logs.max_output_bytes == 8192
    assert logs.resources == ("jellyfin", "plex")
    assert logs.require_resource("plex") == "plex"


def test_policy_denies_resources_not_explicitly_allowlisted():
    policy = LimeOpsPolicy.from_mapping(POLICY)
    with pytest.raises(PolicyError) as error:
        policy.require("container.logs").require_resource("sonarr")
    assert error.value.code == "denied_operation"
    with pytest.raises(PolicyError):
        policy.require("system.status").require_resource("anything")


@pytest.mark.parametrize("operation", ["unknown.operation", "stack.inspect"])
def test_policy_denies_unknown_or_disabled_operations(operation):
    policy = LimeOpsPolicy.from_mapping(POLICY)
    with pytest.raises(PolicyError) as error:
        policy.require(operation)
    assert error.value.code == "denied_operation"


@pytest.mark.parametrize(
    "value",
    [
        {},
        {**POLICY, "schema_version": "2"},
        {**POLICY, "unexpected": True},
        {**POLICY, "defaults": {"timeout_seconds": 0, "max_output_bytes": 10}},
        {**POLICY, "operations": {"Bad Operation": {"enabled": True}}},
        {**POLICY, "operations": {"system.status": {"enabled": "yes"}}},
        {**POLICY, "operations": {"system.status": {"enabled": True, "extra": 1}}},
        {**POLICY, "operations": {"system.status": {"enabled": True, "resources": "all"}}},
    ],
)
def test_policy_rejects_malformed_or_unknown_configuration(value):
    with pytest.raises(PolicyError) as error:
        LimeOpsPolicy.from_mapping(value)
    assert error.value.code == "invalid_policy"


def test_policy_rejects_duplicate_resources():
    value = {
        **POLICY,
        "operations": {
            "container.logs": {
                "enabled": True,
                "resources": ["plex", "plex"],
            }
        },
    }
    with pytest.raises(PolicyError, match="duplicate"):
        LimeOpsPolicy.from_mapping(value)


def test_policy_can_load_from_json_file(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        '{"schema_version":"1","defaults":{"timeout_seconds":5,'
        '"max_output_bytes":1024},"operations":{"system.status":{"enabled":true}}}'
    )
    policy = LimeOpsPolicy.from_file(path)
    assert policy.require("system.status").timeout_seconds == 5


def test_policy_file_error_is_typed(tmp_path):
    with pytest.raises(PolicyError) as error:
        LimeOpsPolicy.from_file(tmp_path / "missing.json")
    assert error.value.code == "invalid_policy"
