"""PB-002: the helper-owned package reconcile command (check / apply)."""

from unittest.mock import patch

import pihealth_helper as helper


class FakeRun:
    """Stubs run_command by argv prefix; records every call."""

    def __init__(self, installed):
        self.installed = installed  # name -> version or None
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[:3] == ["dpkg-query", "-W", "-f"]:
            name = argv[-1]
            version = self.installed.get(name)
            return {"returncode": 0 if version is not None else 1, "stdout": version or ""}
        if argv[:2] == ["dpkg", "--compare-versions"]:
            a, _op, b = argv[2], argv[3], argv[4]
            return {"returncode": 0 if a >= b else 1}
        return {"returncode": 0, "stdout": ""}


def test_reconcile_rejects_unknown_params_and_modes():
    assert helper.cmd_packages_reconcile({"mode": "delete"})["success"] is False
    assert helper.cmd_packages_reconcile({"package": "x"})["success"] is False


def test_reconcile_check_reports_drift_without_changing_anything():
    fake = FakeRun({"claude-code": "2.1.208", "python3-psutil": "5.9",
                    "unattended-upgrades": "2.9"})
    with patch.object(helper, "run_command", side_effect=fake):
        result = helper.cmd_packages_reconcile({"mode": "check"})
    assert result["success"] is True and result["mode"] == "check"
    assert "claude-code" in result["drift"]  # 2.1.208 != pinned 2.1.207
    # check never mutates.
    assert all(call[0] not in {"apt-get", "apt-mark"} for call in fake.calls)


def test_reconcile_apply_pins_the_cli_and_installs_missing():
    # claude drifted; psutil missing; unattended-upgrades present.
    fake = FakeRun({"claude-code": "2.1.208", "unattended-upgrades": "2.9"})
    with patch.object(helper, "run_command", side_effect=fake):
        result = helper.cmd_packages_reconcile({"mode": "apply"})
    assert result["mode"] == "apply"
    assert ["apt-get", "update"] in fake.calls
    assert [
        "apt-get", "install", "-y", "--allow-downgrades", "--allow-change-held-packages",
        "claude-code=2.1.207",
    ] in fake.calls
    assert ["apt-mark", "hold", "claude-code"] in fake.calls
    assert ["apt-get", "install", "-y", "python3-psutil"] in fake.calls
    # Only manifest packages are ever touched — no arbitrary names.
    touched = {call[-1].split("=")[0] for call in fake.calls if call[0] in {"apt-get", "apt-mark"}
               and call[-1] not in {"update"}}
    assert touched <= {"claude-code", "python3-psutil", "unattended-upgrades"}
