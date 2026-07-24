import os
import stat
import subprocess
from pathlib import Path

from werkzeug.security import generate_password_hash


SCRIPT = Path("scripts/onboarding-credentials.sh")


def _run_script(
    tmp_path: Path,
    *,
    username: str = "admin",
    password_hash: str | None = None,
    stdin=None,
):
    credentials_file = tmp_path / "config" / "credentials.env"
    env = os.environ.copy()
    env.update(
        {
            "LIMEOS_CREDENTIALS_FILE": str(credentials_file),
            "LIMEOS_CREDENTIAL_OWNER": str(os.getuid()),
            "LIMEOS_CREDENTIAL_GROUP": str(os.getgid()),
            "LIMEOS_ADMIN_USER": username,
        }
    )
    if password_hash is None:
        env.pop("LIMEOS_ADMIN_PASSWORD_HASH", None)
    else:
        env["LIMEOS_ADMIN_PASSWORD_HASH"] = password_hash
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        stdin=stdin,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, credentials_file


def test_prehashed_unattended_setup_creates_private_credentials(tmp_path):
    password_hash = generate_password_hash(
        "correct horse battery staple",
        method="pbkdf2:sha256:600000",
    )

    result, credentials_file = _run_script(
        tmp_path,
        username="operator",
        password_hash=password_hash,
    )

    assert result.returncode == 0
    assert credentials_file.read_text() == (
        f"PIHEALTH_USER=operator\nPIHEALTH_PASSWORD_HASH={password_hash}\n"
    )
    assert stat.S_IMODE(credentials_file.stat().st_mode) == 0o640
    assert password_hash not in result.stdout
    assert password_hash not in result.stderr


def test_existing_credentials_are_preserved(tmp_path):
    credentials_file = tmp_path / "config" / "credentials.env"
    credentials_file.parent.mkdir()
    credentials_file.write_text("PIHEALTH_USER=existing\nPIHEALTH_PASSWORD_HASH=keep-me\n")

    result, _ = _run_script(
        tmp_path,
        password_hash="not-a-valid-hash",
    )

    assert result.returncode == 0
    assert credentials_file.read_text() == (
        "PIHEALTH_USER=existing\nPIHEALTH_PASSWORD_HASH=keep-me\n"
    )
    assert "preserving them" in result.stdout


def test_invalid_unattended_hash_is_rejected_without_writing(tmp_path):
    result, credentials_file = _run_script(
        tmp_path,
        password_hash="plaintext-is-not-accepted",
    )

    assert result.returncode == 2
    assert "must be a Werkzeug" in result.stderr
    assert not credentials_file.exists()


def test_invalid_username_is_rejected_without_writing(tmp_path):
    password_hash = generate_password_hash(
        "secret",
        method="pbkdf2:sha256:600000",
    )

    result, credentials_file = _run_script(
        tmp_path,
        username="bad\nPIHEALTH_PASSWORD=injected",
        password_hash=password_hash,
    )

    assert result.returncode == 2
    assert "LIMEOS_ADMIN_USER must contain" in result.stderr
    assert not credentials_file.exists()


def test_noninteractive_setup_requires_prehashed_password(tmp_path):
    result, credentials_file = _run_script(
        tmp_path,
        stdin=subprocess.DEVNULL,
    )

    assert result.returncode == 2
    assert "No terminal is available" in result.stderr
    assert "LIMEOS_ADMIN_PASSWORD_HASH" in result.stderr
    assert not credentials_file.exists()


def test_setup_runs_credential_bootstrap_after_legacy_migration():
    setup = Path("setup.sh").read_text()

    migration = setup.index('"${PYTHON_BIN}" "${REPO_DIR}/scripts/migrate_runtime_state.py"')
    credential_bootstrap = setup.index(
        '"${REPO_DIR}/scripts/onboarding-credentials.sh"'
    )
    dashboard_unit = setup.index('cat > "$SERVICE_FILE"')

    assert migration < credential_bootstrap < dashboard_unit
