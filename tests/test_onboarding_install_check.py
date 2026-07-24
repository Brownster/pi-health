import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/onboarding-install-check.sh")


def _write_command(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -Eeuo pipefail\n{body}\n")
    path.chmod(0o755)


def _run_check(
    tmp_path: Path,
    *,
    systemctl_body: str = "exit 0",
    docker_body: str = "exit 0",
    curl_body: str = """printf '%s\\n' '{"status":"ok"}'""",
    extra_args: tuple[str, ...] = (),
    socket_available: bool = True,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_command(bin_dir, "systemctl", systemctl_body)
    _write_command(bin_dir, "docker", docker_body)
    _write_command(bin_dir, "curl", curl_body)
    _write_command(
        bin_dir,
        "socket-test",
        "exit 0" if socket_available else "exit 1",
    )

    socket_path = tmp_path / "helper.sock"

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "LIMEOS_HELPER_SOCKET": str(socket_path),
            "LIMEOS_SOCKET_TEST_BIN": str(bin_dir / "socket-test"),
            "LIMEOS_READY_ATTEMPTS": "1",
            "LIMEOS_READY_DELAY_SECONDS": "0",
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT), *extra_args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_ready_install_passes_all_checks(tmp_path):
    result = _run_check(tmp_path)

    assert result.returncode == 0
    assert "[PASS] docker: Docker daemon and Compose plugin are available" in result.stdout
    assert "[PASS] helper-connectivity:" in result.stdout
    assert "[PASS] dashboard-health:" in result.stdout
    assert "Result: READY" in result.stdout


def test_missing_compose_blocks_install(tmp_path):
    result = _run_check(
        tmp_path,
        docker_body="""
if [[ "${1:-}" == "compose" ]]; then
    exit 1
fi
exit 0
""",
    )

    assert result.returncode == 2
    assert "[BLOCK] docker-compose: Docker Compose plugin is unavailable" in result.stderr
    assert "Result: BLOCKED (1 failed check(s))" in result.stderr


def test_inactive_unit_blocks_install(tmp_path):
    result = _run_check(
        tmp_path,
        systemctl_body="""
if [[ "${1:-}" == "is-active" && "${3:-}" == "pi-health.service" ]]; then
    exit 1
fi
exit 0
""",
    )

    assert result.returncode == 2
    assert "[BLOCK] pi-health.service: Unit is not active" in result.stderr


def test_unhealthy_dashboard_blocks_install(tmp_path):
    result = _run_check(
        tmp_path,
        curl_body="""printf '%s\\n' '{"status":"starting"}'""",
    )

    assert result.returncode == 2
    assert "[BLOCK] dashboard-health:" in result.stderr


def test_missing_helper_socket_blocks_install(tmp_path):
    result = _run_check(tmp_path, socket_available=False)

    assert result.returncode == 2
    assert "[BLOCK] helper-connectivity:" in result.stderr


def test_explicit_docker_skip_is_visible(tmp_path):
    result = _run_check(
        tmp_path,
        docker_body="exit 127",
        extra_args=("--skip-docker",),
    )

    assert result.returncode == 0
    assert "[WARN] docker: Verification skipped explicitly" in result.stdout


def test_setup_starts_helper_first_and_runs_verifier_before_success():
    setup = Path("setup.sh").read_text()

    helper_start = setup.index("systemctl enable --now pihealth-helper.service")
    dashboard_start = setup.index("systemctl enable --now pi-health.service")
    verifier = setup.index('"${INSTALL_CHECK_SCRIPT}" "${install_check_args[@]}"')
    success = setup.index('echo ">>> Pi-Health is running."')

    assert helper_start < dashboard_start < verifier < success
    assert "Requires=pihealth-helper.service" in setup
    assert "After=network.target docker.service pihealth-helper.service" in setup


def test_setup_uses_managed_config_root_and_preserves_legacy_reruns():
    setup = Path("setup.sh").read_text()

    assert 'CONFIG_DIR="${LIMEOS_STATE_DIR}/apps"' in setup
    assert 'CONFIG_DIR="/home/pi/docker"' in setup
    assert (
        "Environment=DOCKER_COMPOSE_PATH=/home/pi/docker/docker-compose.yml"
        in setup
    )
    assert '"${CONFIG_DIR}" "${STACKS_PATH}"' in setup


def test_setup_prints_recovery_commands_after_success():
    setup = Path("setup.sh").read_text()

    success = setup.index('echo ">>> Pi-Health is running."')
    recovery = setup.index('echo "Recovery commands:"')

    assert success < recovery
    assert "systemctl status pihealth-helper.service pi-health.service" in setup
    assert "journalctl -u pihealth-helper.service -u pi-health.service" in setup
    assert "systemctl restart pihealth-helper.service pi-health.service" in setup
    assert "sudo ${INSTALL_CHECK_SCRIPT}" in setup
