from pathlib import Path

from scripts.migrate_runtime_state import (
    ensure_agent_runtime_roots,
    ensure_helper_agent_permissions,
    ensure_helper_restart_coupling,
)


def test_helper_restart_coupling_skips_when_helper_is_not_installed(tmp_path: Path):
    dropin, changed = ensure_helper_restart_coupling(tmp_path)

    assert dropin is None
    assert changed is False


def test_agent_runtime_roots_are_seeded_outside_helper_mount_sandbox(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "scripts.migrate_runtime_state.subprocess.run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    ensure_agent_runtime_roots()

    argv, kwargs = calls[0]
    assert argv[:6] == [
        "systemd-run",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--service-type=exec",
    ]
    assert argv[-3:] == ["-p", "/var/lib/lime-agent", "/var/lib/limeops"]
    assert kwargs == {"check": True}


def test_helper_restart_coupling_is_created_and_idempotent(tmp_path: Path):
    (tmp_path / "pihealth-helper.service").write_text("[Unit]\n", encoding="utf-8")

    dropin, changed = ensure_helper_restart_coupling(tmp_path)

    assert changed is True
    assert dropin == (
        tmp_path
        / "pihealth-helper.service.d"
        / "restart-with-pi-health.conf"
    )
    assert dropin.read_text(encoding="utf-8") == "[Unit]\nPartOf=pi-health.service\n"
    assert dropin.stat().st_mode & 0o777 == 0o644

    same_dropin, changed = ensure_helper_restart_coupling(tmp_path)
    assert same_dropin == dropin
    assert changed is False


def test_helper_agent_permissions_are_created_and_idempotent(tmp_path: Path):
    (tmp_path / "pihealth-helper.service").write_text("[Unit]\n", encoding="utf-8")
    repo = Path("/home/pi/pi-health")

    dropin, changed = ensure_helper_agent_permissions(tmp_path, repo)

    assert changed is True
    assert dropin == (
        tmp_path
        / "pihealth-helper.service.d"
        / "agent-provisioning.conf"
    )
    content = dropin.read_text(encoding="utf-8")
    assert content.startswith("[Service]\n")
    assert "Environment=PIHEALTH_REPO_DIR=/home/pi/pi-health" in content
    assert "ReadWritePaths=/etc/apt" in content
    assert "/etc/passwd" not in content
    assert "ReadWritePaths=/usr /var/lib/apt /var/lib/dpkg /var/cache/apt" in content
    assert "ReadWritePaths=-/var/lib/lime-agent -/var/lib/limeops -/run/limeos" in content
    assert "StateDirectory=" not in content
    assert "RuntimeDirectory=" not in content
    assert dropin.stat().st_mode & 0o777 == 0o644

    same_dropin, changed = ensure_helper_agent_permissions(tmp_path, repo)
    assert same_dropin == dropin
    assert changed is False
