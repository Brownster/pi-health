"""OB-100: read-only fresh-host onboarding preflight."""

import os
import pwd
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/onboarding-preflight.sh").resolve()
CURRENT_USER = pwd.getpwuid(os.getuid()).pw_name


def _run(
    tmp_path,
    *,
    os_id="debian",
    codename="bookworm",
    arguments=None,
    **overrides,
):
    os_release = tmp_path / "os-release"
    os_release.write_text(f'ID="{os_id}"\nVERSION_CODENAME={codename}\n')
    env = {
        **os.environ,
        "LIMEOS_OS_RELEASE_FILE": str(os_release),
        "LIMEOS_MACHINE": "x86_64",
        "LIMEOS_OPERATOR": str(overrides.pop("operator", CURRENT_USER)),
        "LIMEOS_CAN_ESCALATE": "1",
        "LIMEOS_USB_DEVICE_COUNT": "2",
        **overrides,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *(arguments or [])],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_supported_bookworm_x86_host_is_ready(tmp_path):
    result = _run(tmp_path)

    assert result.returncode == 0
    assert "[PASS] operating-system: Debian bookworm" in result.stdout
    assert "[PASS] architecture: amd64 (x86_64)" in result.stdout
    assert "[INFO] usb-storage: 2 USB disk(s) detected" in result.stdout
    assert result.stdout.endswith("Result: READY\n")


def test_supported_bookworm_arm_host_is_ready(tmp_path):
    result = _run(tmp_path, LIMEOS_MACHINE="aarch64")

    assert result.returncode == 0
    assert "[PASS] architecture: arm64 (aarch64)" in result.stdout


def test_non_bookworm_host_is_blocked_with_remediation(tmp_path):
    result = _run(tmp_path, codename="trixie")

    assert result.returncode == 2
    assert (
        "[BLOCK] operating-system: Requires Debian bookworm; "
        "found debian trixie"
    ) in result.stdout
    assert "Result: BLOCKED (1 issue(s))" in result.stdout


def test_unsupported_architecture_is_blocked(tmp_path):
    result = _run(tmp_path, LIMEOS_MACHINE="riscv64")

    assert result.returncode == 2
    assert "[BLOCK] architecture: Requires arm64 or amd64; found riscv64" in result.stdout


def test_unresolvable_operator_is_blocked(tmp_path):
    result = _run(tmp_path, operator="")

    assert result.returncode == 2
    assert "[BLOCK] operator: Unable to resolve the interactive SSH user" in result.stdout


def test_explicit_unsupported_override_is_visible_and_successful(tmp_path):
    result = _run(
        tmp_path,
        codename="trixie",
        arguments=["--allow-unsupported"],
    )

    assert result.returncode == 0
    assert "[WARN] compatibility: Unsupported-host override accepted" in result.stdout
    assert "Result: OVERRIDDEN (1 unsupported check(s))" in result.stdout


def test_existing_install_override_preserves_legacy_reruns(tmp_path):
    result = _run(
        tmp_path,
        os_id="ubuntu",
        codename="jammy",
        arguments=["--allow-existing-install"],
    )

    assert result.returncode == 0
    assert "Continuing an existing installation on an unsupported host" in result.stdout
    assert "Result: LEGACY-RERUN (1 unsupported check(s))" in result.stdout


def test_help_is_read_only_and_successful():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Read-only Debian Bookworm onboarding preflight." in result.stdout


def test_setup_runs_preflight_before_first_package_mutation():
    setup = Path("setup.sh").read_text()

    assert setup.index("\nfct_run_onboarding_preflight\n") < setup.index("apt-get update")
    assert "--allow-existing-install" in setup
    assert "LIMEOS_ALLOW_UNSUPPORTED_HOST" in setup
