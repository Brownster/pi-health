#!/usr/bin/env python3
"""Migrate legacy Pi-Health runtime files into LimeOS-owned directories."""

from __future__ import annotations

import argparse
import pwd
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime_paths import migrate_legacy_runtime_data
from agent_provider.provisioning import STACK_LOCK_DIR


HELPER_RESTART_DROPIN = "restart-with-pi-health.conf"
HELPER_AGENT_DROPIN = "agent-provisioning.conf"
HELPER_INTEGRATION_LIFECYCLE_DROPIN = "integration-lifecycle.conf"
METRICS_SERVICE = "limeos-metrics-collector.service"
METRICS_TIMER = "limeos-metrics-collector.timer"


def ensure_agent_runtime_roots() -> None:
    """Seed mount-sandbox paths before the helper restarts into its new unit."""
    subprocess.run(
        [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            "/usr/bin/mkdir",
            "-p",
            "/var/lib/lime-agent",
            "/var/lib/limeops",
        ],
        check=True,
    )
    subprocess.run(
        [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            "/usr/bin/install",
            "-d",
            "-o",
            "root",
            "-g",
            "pihealth",
            "-m",
            "2770",
            STACK_LOCK_DIR,
        ],
        check=True,
    )


def ensure_integration_lifecycle_roots() -> None:
    """Create the fixed root-only Mattermost recovery directory."""
    subprocess.run(
        [
            "systemd-run",
            "--quiet",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            "/usr/bin/install",
            "-d",
            "-o",
            "root",
            "-g",
            "root",
            "-m",
            "0700",
            "/var/lib/limeos/integration-recovery",
        ],
        check=True,
    )


def _ensure_helper_dropin(
    systemd_dir: Path, filename: str, content: str
) -> tuple[Path | None, bool]:
    helper_unit = systemd_dir / "pihealth-helper.service"
    if not helper_unit.is_file():
        return None, False

    dropin = systemd_dir / "pihealth-helper.service.d" / filename
    if dropin.is_file() and dropin.read_text(encoding="utf-8") == content:
        return dropin, False

    dropin.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = dropin.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(dropin)
    return dropin, True


def _write_unit_if_changed(path: Path, content: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return False
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(path)
    return True


def _unit_quote(value: Path | str) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("systemd unit values cannot contain newlines")
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def resolve_dashboard_user(systemd_dir: Path, repo_dir: Path) -> str:
    """Read the installed dashboard user, falling back to checkout ownership."""
    app_unit = systemd_dir / "pi-health.service"
    if app_unit.is_file():
        for line in app_unit.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "User" and value.strip():
                return value.strip()
    return pwd.getpwuid(repo_dir.resolve().stat().st_uid).pw_name


def ensure_metrics_timer(
    systemd_dir: Path,
    repo_dir: Path,
    state_dir: Path,
    credentials_file: Path,
    service_user: str,
) -> tuple[tuple[Path, Path] | None, bool]:
    """Install the bounded metric collector units for an existing dashboard."""
    if not (systemd_dir / "pi-health.service").is_file():
        return None, False
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", service_user):
        raise ValueError("invalid dashboard service user")

    systemd_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    repo_dir = repo_dir.resolve()
    python_bin = repo_dir / ".venv" / "bin" / "python"
    collector = repo_dir / "metric_collector.py"
    service_path = systemd_dir / METRICS_SERVICE
    timer_path = systemd_dir / METRICS_TIMER
    service_content = (
        "[Unit]\n"
        "Description=LimeOS system metric collector\n"
        "After=local-fs.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"User={service_user}\n"
        "Group=pihealth\n"
        f"WorkingDirectory={repo_dir}\n"
        f"EnvironmentFile=-{credentials_file}\n"
        f"Environment=\"LIMEOS_STATE_DIR={state_dir}\"\n"
        f"ExecStart={_unit_quote(python_bin)} {_unit_quote(collector)}\n"
        "NoNewPrivileges=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=read-only\n"
        "PrivateTmp=true\n"
        f"ReadWritePaths={state_dir}\n"
        "UMask=0027\n"
        "StateDirectory=limeos\n"
        "StateDirectoryMode=0750\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    timer_content = (
        "[Unit]\n"
        "Description=Collect LimeOS system metrics every five minutes\n\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        "OnUnitActiveSec=5min\n"
        "AccuracySec=30s\n"
        "RandomizedDelaySec=15s\n"
        "Persistent=true\n"
        f"Unit={METRICS_SERVICE}\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    changed = _write_unit_if_changed(service_path, service_content)
    changed = _write_unit_if_changed(timer_path, timer_content) or changed
    return (service_path, timer_path), changed


def ensure_helper_restart_coupling(
    systemd_dir: Path, app_service: str = "pi-health.service"
) -> tuple[Path | None, bool]:
    """Make dashboard restarts propagate to an installed privileged helper."""
    content = f"[Unit]\nPartOf={app_service}\n"
    return _ensure_helper_dropin(systemd_dir, HELPER_RESTART_DROPIN, content)


def ensure_helper_agent_permissions(
    systemd_dir: Path, repo_dir: Path
) -> tuple[Path | None, bool]:
    """Grant existing helper units the fixed paths used for agent provisioning."""
    content = (
        "[Service]\n"
        f"Environment=PIHEALTH_REPO_DIR={repo_dir.resolve()}\n"
        "ReadWritePaths=/etc/apt\n"
        "ReadWritePaths=/usr /var/lib/apt /var/lib/dpkg /var/cache/apt\n"
        "ReadWritePaths=-/var/lib/lime-agent -/var/lib/limeops "
        f"-{STACK_LOCK_DIR}\n"
    )
    return _ensure_helper_dropin(systemd_dir, HELPER_AGENT_DROPIN, content)


def ensure_helper_integration_lifecycle_permissions(
    systemd_dir: Path,
) -> tuple[Path | None, bool]:
    """Grant only the fixed active and recovery credential paths."""
    content = (
        "[Service]\n"
        "ReadWritePaths=-/etc/limeos/integrations/mattermost.env\n"
        "ReadWritePaths=-/var/lib/limeos/integration-recovery\n"
    )
    return _ensure_helper_dropin(
        systemd_dir,
        HELPER_INTEGRATION_LIFECYCLE_DROPIN,
        content,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=Path("/etc/limeos"))
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/limeos"))
    parser.add_argument("--log-dir", type=Path, default=Path("/var/log/limeos"))
    parser.add_argument(
        "--legacy-credentials",
        type=Path,
        default=Path("/etc/pi-health.env"),
    )
    parser.add_argument(
        "--credentials-file",
        type=Path,
        default=Path("/etc/limeos/credentials.env"),
    )
    parser.add_argument(
        "--systemd-dir",
        type=Path,
        default=Path("/etc/systemd/system"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_agent_runtime_roots()
    ensure_integration_lifecycle_roots()
    copied = migrate_legacy_runtime_data(
        source_root=args.source_root,
        config_dir=args.config_dir,
        state_dir=args.state_dir,
        log_dir=args.log_dir,
        legacy_credentials=args.legacy_credentials,
        credentials_file=args.credentials_file,
    )
    for path in copied:
        print(f"Migrated {path}")
    if not copied:
        print("No legacy runtime files required migration")
    dropins = (
        ensure_helper_restart_coupling(args.systemd_dir),
        ensure_helper_agent_permissions(args.systemd_dir, args.source_root),
        ensure_helper_integration_lifecycle_permissions(args.systemd_dir),
    )
    service_user = resolve_dashboard_user(args.systemd_dir, args.source_root)
    metric_units, metrics_changed = ensure_metrics_timer(
        args.systemd_dir,
        args.source_root,
        args.state_dir,
        args.credentials_file,
        service_user,
    )
    if metrics_changed or any(changed for _dropin, changed in dropins):
        subprocess.run(["systemctl", "daemon-reload"], check=True)
    for dropin, changed in dropins:
        if changed:
            print(f"Installed {dropin}")
    if metric_units:
        subprocess.run(
            ["systemctl", "enable", "--now", METRICS_TIMER],
            check=True,
        )
        if metrics_changed:
            for unit in metric_units:
                print(f"Installed {unit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
