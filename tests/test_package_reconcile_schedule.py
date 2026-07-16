"""PB-003 slice 1: nightly package-reconcile timer + run composition."""

import importlib
import logging
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helper_templates import render_package_reconcile_schedule

with patch("logging.FileHandler", return_value=logging.StreamHandler()):
    helper = importlib.import_module("pihealth_helper")


# -- systemd template ------------------------------------------------------------
def test_render_schedule_produces_oneshot_service_and_timer():
    service, timer = render_package_reconcile_schedule(
        "daily",
        "/usr/bin/python3 -c 'pass'",
        user="pihealth",
        working_dir="/opt/pi-health",
        pythonpath="/opt/pi-health",
    )
    assert "Type=oneshot" in service
    assert "User=pihealth" in service
    assert "Environment=PYTHONPATH=/opt/pi-health" in service
    assert "ExecStart=/usr/bin/python3 -c 'pass'" in service
    assert "OnCalendar=daily" in timer
    assert "RandomizedDelaySec=" in timer
    assert "WantedBy=timers.target" in timer


# -- nightly reconcile composition ----------------------------------------------
def _specs():
    return [
        SimpleNamespace(name="claude-code", manager="apt", critical=True),
        SimpleNamespace(name="unattended-upgrades", manager="apt", critical=False),
    ]


def test_nightly_rejects_parameters():
    result = helper.cmd_packages_nightly_reconcile({"mode": "apply"})
    assert result["success"] is False


def test_nightly_holds_criticals_applies_security_then_reconciles():
    with patch("limeos_packages.load_manifest", return_value=_specs()):
        with patch("pihealth_helper.shutil.which", return_value="/usr/bin/unattended-upgrade"):
            with patch("pihealth_helper.run_command", return_value={"returncode": 0}) as run:
                with patch("pihealth_helper.cmd_packages_reconcile",
                           return_value={"success": True, "applied": [], "failed": []}) as reconcile:
                    result = helper.cmd_packages_nightly_reconcile({})
    assert result["success"] is True
    assert result["held"] == ["claude-code"]  # only the critical entry is held
    assert result["security"] == {"skipped": False, "ok": True}
    reconcile.assert_called_once_with({"mode": "apply"})
    # the critical package was apt-mark hold'd
    assert any(call.args[0] == ["apt-mark", "hold", "claude-code"] for call in run.call_args_list)


def test_nightly_skips_security_when_tool_absent_but_still_reconciles():
    with patch("limeos_packages.load_manifest", return_value=_specs()):
        with patch("pihealth_helper.shutil.which", return_value=None):
            with patch("pihealth_helper.run_command", return_value={"returncode": 0}):
                with patch("pihealth_helper.cmd_packages_reconcile",
                           return_value={"success": True}):
                    result = helper.cmd_packages_nightly_reconcile({})
    assert result["success"] is True
    assert result["security"]["skipped"] is True


def test_nightly_fails_when_a_critical_hold_fails():
    with patch("limeos_packages.load_manifest", return_value=_specs()):
        with patch("pihealth_helper.shutil.which", return_value=None):
            with patch("pihealth_helper.run_command", return_value={"returncode": 1}):
                with patch("pihealth_helper.cmd_packages_reconcile",
                           return_value={"success": True}):
                    result = helper.cmd_packages_nightly_reconcile({})
    assert result["success"] is False
    assert result["hold_failed"] == ["claude-code"]


def test_nightly_fails_when_reconcile_fails():
    with patch("limeos_packages.load_manifest", return_value=_specs()):
        with patch("pihealth_helper.shutil.which", return_value=None):
            with patch("pihealth_helper.run_command", return_value={"returncode": 0}):
                with patch("pihealth_helper.cmd_packages_reconcile",
                           return_value={"success": False, "failed": ["install:x"]}):
                    result = helper.cmd_packages_nightly_reconcile({})
    assert result["success"] is False


# -- schedule installer ---------------------------------------------------------
def test_configure_schedule_writes_units_and_enables_timer():
    with patch("pihealth_helper._write_managed_file", return_value={"success": True}) as write:
        with patch("pihealth_helper.run_command", return_value={"returncode": 0}):
            result = helper.cmd_configure_package_reconcile_schedule(
                {"app_dir": "/opt/pi-health", "user": "pihealth"}
            )
    assert result["success"] is True
    assert result["timer_path"].endswith("limeos-package-reconcile.timer")
    written = [call.args[0] for call in write.call_args_list]
    assert any(p.endswith(".service") for p in written)
    assert any(p.endswith(".timer") for p in written)


def test_configure_schedule_rejects_relative_app_dir_and_bad_user():
    assert helper.cmd_configure_package_reconcile_schedule(
        {"app_dir": "relative", "user": "pihealth"})["success"] is False
    assert helper.cmd_configure_package_reconcile_schedule(
        {"app_dir": "/opt/pi-health", "user": "bad user!"})["success"] is False
    assert helper.cmd_configure_package_reconcile_schedule(
        {"app_dir": "/opt/pi-health", "user": "pihealth", "on_calendar": "bad;rm -rf"})["success"] is False
