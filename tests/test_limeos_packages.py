"""PB-001: the LimeOS package baseline manifest loads, validates, and models correctly."""

import pytest

from limeos_packages import (
    MANAGERS,
    POLICIES,
    PackageManifestError,
    PackageSpec,
    ReconcileAction,
    check_packages,
    compliance_report,
    critical_packages,
    default_version_ge,
    load_manifest,
    parse_manifest,
    plan_actions,
)


def _specs(*entries):
    return [PackageSpec(**entry) for entry in entries]


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


# -- PB-002 reconcile logic -------------------------------------------------------
def _installed(mapping):
    return lambda spec: mapping.get(spec.name)


def test_default_version_ge_handles_numeric_versions():
    assert default_version_ge("2.1.207", "2.1.205") is True
    assert default_version_ge("2.1.205", "2.1.207") is False
    assert default_version_ge("24", "24") is True


def test_check_packages_flags_each_policy():
    specs = _specs(
        {"name": "claude-code", "manager": "apt", "policy": "pinned", "version": "2.1.207",
         "critical": True},
        {"name": "python3-psutil", "manager": "apt", "policy": "present", "critical": True},
        {"name": "docker-ce", "manager": "apt", "policy": "present-min", "version": "24"},
        {"name": "telnetd", "manager": "apt", "policy": "absent", "critical": False},
    )
    statuses = check_packages(
        specs,
        _installed({"claude-code": "2.1.208", "python3-psutil": "5.9",
                    "docker-ce": "20", "telnetd": "1.0"}),
    )
    by_name = {status.name: status for status in statuses}
    assert by_name["claude-code"].compliant is False   # drifted off the pin
    assert "pinned to 2.1.207" in by_name["claude-code"].detail
    assert by_name["python3-psutil"].compliant is True
    assert by_name["docker-ce"].compliant is False      # below minimum
    assert by_name["telnetd"].compliant is False         # present but should be absent


def test_check_packages_reports_missing_and_compliant():
    specs = _specs(
        {"name": "a", "manager": "apt", "policy": "present", "critical": True},
        {"name": "b", "manager": "apt", "policy": "pinned", "version": "1.0", "critical": True},
    )
    statuses = check_packages(specs, _installed({"b": "1.0"}))
    assert statuses[0].compliant is False and statuses[0].installed is None
    assert statuses[1].compliant is True


def test_compliance_report_lists_drift():
    specs = _specs(
        {"name": "a", "manager": "apt", "policy": "present", "critical": True},
        {"name": "b", "manager": "apt", "policy": "present", "critical": True},
    )
    report = compliance_report(check_packages(specs, _installed({"b": "1"})))
    assert report["ok"] is False and report["drift"] == ["a"]
    assert len(report["packages"]) == 2


def test_plan_actions_enforces_pin_hold_min_and_absence():
    specs = _specs(
        {"name": "claude-code", "manager": "apt", "policy": "pinned", "version": "2.1.207",
         "critical": True, "disable_self_update": True},
        {"name": "docker-ce", "manager": "apt", "policy": "present-min", "version": "24"},
        {"name": "python3-psutil", "manager": "apt", "policy": "present", "critical": True},
        {"name": "telnetd", "manager": "apt", "policy": "absent", "critical": False},
    )
    actions = plan_actions(
        specs,
        _installed({"claude-code": "2.1.208", "docker-ce": "24", "telnetd": "1"}),
    )
    assert ReconcileAction("claude-code", "apt", "install_version", "2.1.207") in actions
    assert ReconcileAction("claude-code", "apt", "hold") in actions
    assert ReconcileAction("claude-code", "apt", "disable_self_update") in actions
    assert ReconcileAction("python3-psutil", "apt", "install") in actions  # missing
    assert ReconcileAction("telnetd", "apt", "remove") in actions          # present, forbidden
    # docker-ce already meets the minimum -> no action for it.
    assert not any(action.name == "docker-ce" for action in actions)


def test_plan_actions_holds_a_pin_already_at_version():
    specs = _specs(
        {"name": "claude-code", "manager": "apt", "policy": "pinned", "version": "2.1.207",
         "critical": True},
    )
    actions = plan_actions(specs, _installed({"claude-code": "2.1.207"}))
    # Already at the pin: no reinstall, but still ensure the hold.
    assert actions == [ReconcileAction("claude-code", "apt", "hold")]
