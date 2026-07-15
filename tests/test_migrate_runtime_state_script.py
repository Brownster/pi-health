from pathlib import Path
from types import SimpleNamespace

import scripts.migrate_runtime_state as migration_script
from scripts.migrate_runtime_state import (
    ensure_agent_runtime_roots,
    ensure_helper_agent_permissions,
    ensure_helper_restart_coupling,
    ensure_metrics_timer,
    resolve_dashboard_user,
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


def test_metrics_timer_skips_when_dashboard_service_is_not_installed(tmp_path: Path):
    units, changed = ensure_metrics_timer(
        tmp_path,
        Path("/home/pi/pi-health"),
        Path("/var/lib/limeos"),
        Path("/etc/limeos/credentials.env"),
        "pi",
    )

    assert units is None
    assert changed is False


def test_metrics_timer_is_created_and_idempotent(tmp_path: Path):
    (tmp_path / "pi-health.service").write_text(
        "[Service]\nUser=holly\n",
        encoding="utf-8",
    )
    repo = tmp_path / "home" / "holly" / "pi-health"
    repo.mkdir(parents=True)

    units, changed = ensure_metrics_timer(
        tmp_path,
        repo,
        Path("/var/lib/limeos"),
        Path("/etc/limeos/credentials.env"),
        "holly",
    )

    assert changed is True
    assert units is not None
    service, timer = units
    service_content = service.read_text(encoding="utf-8")
    assert "User=holly" in service_content
    assert f'ExecStart="{repo.resolve()}/.venv/bin/python"' in service_content
    assert f'"{repo.resolve()}/metric_collector.py"' in service_content
    assert "ReadWritePaths=/var/lib/limeos" in service_content
    assert "ProtectSystem=strict" in service_content
    assert service.stat().st_mode & 0o777 == 0o644
    assert "OnUnitActiveSec=5min" in timer.read_text(encoding="utf-8")
    assert timer.stat().st_mode & 0o777 == 0o644

    same_units, changed = ensure_metrics_timer(
        tmp_path,
        repo,
        Path("/var/lib/limeos"),
        Path("/etc/limeos/credentials.env"),
        "holly",
    )
    assert same_units == units
    assert changed is False


def test_dashboard_user_is_read_from_installed_service(tmp_path: Path):
    (tmp_path / "pi-health.service").write_text(
        "[Unit]\nDescription=test\n[Service]\nUser=holly\n",
        encoding="utf-8",
    )

    assert resolve_dashboard_user(tmp_path, tmp_path) == "holly"


def test_migration_enables_metrics_timer_for_existing_install(monkeypatch, tmp_path: Path):
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    (systemd_dir / "pi-health.service").write_text(
        "[Service]\nUser=holly\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    calls = []
    monkeypatch.setattr(migration_script, "ensure_agent_runtime_roots", lambda: None)
    monkeypatch.setattr(migration_script, "migrate_legacy_runtime_data", lambda **_kwargs: [])
    monkeypatch.setattr(
        migration_script,
        "parse_args",
        lambda: SimpleNamespace(
            source_root=repo,
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            log_dir=tmp_path / "log",
            legacy_credentials=tmp_path / "legacy.env",
            credentials_file=tmp_path / "credentials.env",
            systemd_dir=systemd_dir,
        ),
    )
    monkeypatch.setattr(
        migration_script.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)),
    )

    assert migration_script.main() == 0
    assert (["systemctl", "daemon-reload"], {"check": True}) in calls
    assert (
        ["systemctl", "enable", "--now", "limeos-metrics-collector.timer"],
        {"check": True},
    ) in calls
