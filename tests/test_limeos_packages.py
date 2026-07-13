"""PB-001: the LimeOS package baseline manifest loads, validates, and models correctly."""

import pytest

from limeos_packages import (
    MANAGERS,
    POLICIES,
    PackageManifestError,
    PackageSpec,
    critical_packages,
    load_manifest,
    parse_manifest,
)


def _manifest(*packages):
    return {"schema_version": "1", "packages": list(packages)}


def _pkg(**overrides):
    base = {"name": "claude-code", "manager": "apt", "policy": "present", "critical": False}
    base.update(overrides)
    return base


# -- the shipped manifest ---------------------------------------------------------
def test_shipped_manifest_is_valid():
    specs = load_manifest()
    assert specs and all(isinstance(spec, PackageSpec) for spec in specs)
    for spec in specs:
        assert spec.manager in MANAGERS and spec.policy in POLICIES


def test_shipped_manifest_pins_and_self_disables_the_claude_cli():
    by_name = {spec.name: spec for spec in load_manifest()}
    claude = by_name["claude-code"]
    assert claude.policy == "pinned" and claude.critical and claude.disable_self_update
    assert claude.version  # a pinned package must state its version
    # The broker's psutil dependency is tracked as a critical package.
    assert by_name["python3-psutil"].critical


# -- valid parsing ----------------------------------------------------------------
def test_parse_pinned_and_present_and_present_min():
    specs = parse_manifest(
        _manifest(
            _pkg(name="claude-code", policy="pinned", version="2.1.207", critical=True,
                 disable_self_update=True),
            _pkg(name="python3-psutil", policy="present", critical=True),
            _pkg(name="docker-ce", policy="present-min", version="24"),
        )
    )
    assert [s.name for s in specs] == ["claude-code", "python3-psutil", "docker-ce"]
    assert specs[0].version == "2.1.207" and specs[0].disable_self_update
    assert [s.name for s in critical_packages(specs)] == ["claude-code", "python3-psutil"]


# -- rejection cases --------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        {"packages": [_pkg()]},  # missing schema_version
        {"schema_version": "2", "packages": [_pkg()]},  # wrong version
        _manifest(),  # empty packages
        {"schema_version": "1", "packages": {}, "extra": 1},  # unknown top field / wrong type
    ],
)
def test_rejects_bad_manifest_structure(raw):
    with pytest.raises(PackageManifestError):
        parse_manifest(raw)


@pytest.mark.parametrize(
    "pkg",
    [
        _pkg(name="Bad Name"),          # space / uppercase
        _pkg(name="pkg; rm -rf /"),     # shell metacharacters
        _pkg(manager="brew"),           # unknown manager
        _pkg(policy="latest"),          # unknown policy
        _pkg(policy="pinned"),          # pinned without a version
        _pkg(policy="present-min"),     # present-min without a version
        _pkg(policy="pinned", version="2.1.207", critical="yes"),  # non-bool critical
        _pkg(policy="present", version="1.0"),  # version set on an unversioned policy
        _pkg(policy="pinned", version="not a version"),  # bad version chars
        {"name": "x", "manager": "apt", "policy": "present", "surprise": True},  # unknown field
    ],
)
def test_rejects_bad_package_entries(pkg):
    with pytest.raises(PackageManifestError):
        parse_manifest(_manifest(pkg))


def test_rejects_duplicate_package_names():
    with pytest.raises(PackageManifestError):
        parse_manifest(_manifest(_pkg(name="curl"), _pkg(name="curl")))


def test_load_manifest_missing_file_raises_typed_error(tmp_path):
    with pytest.raises(PackageManifestError):
        load_manifest(tmp_path / "nope.json")


def test_published_schema_enums_match_the_validator():
    # The JSON schema mirrors the Python validator; keep the two in step.
    import json
    from pathlib import Path

    schema = json.loads(Path("config/schemas/limeos-packages.schema.json").read_text())
    props = schema["properties"]["packages"]["items"]["properties"]
    assert set(props["manager"]["enum"]) == MANAGERS
    assert set(props["policy"]["enum"]) == POLICIES
