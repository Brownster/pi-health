#!/usr/bin/env python3
"""Migrate legacy Pi-Health runtime files into LimeOS-owned directories."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime_paths import migrate_legacy_runtime_data


HELPER_RESTART_DROPIN = "restart-with-pi-health.conf"


def ensure_helper_restart_coupling(
    systemd_dir: Path, app_service: str = "pi-health.service"
) -> tuple[Path | None, bool]:
    """Make dashboard restarts propagate to an installed privileged helper."""
    helper_unit = systemd_dir / "pihealth-helper.service"
    if not helper_unit.is_file():
        return None, False

    dropin = systemd_dir / "pihealth-helper.service.d" / HELPER_RESTART_DROPIN
    content = f"[Unit]\nPartOf={app_service}\n"
    if dropin.is_file() and dropin.read_text(encoding="utf-8") == content:
        return dropin, False

    dropin.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    temporary = dropin.with_suffix(".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(dropin)
    return dropin, True


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
    dropin, changed = ensure_helper_restart_coupling(args.systemd_dir)
    if changed:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        print(f"Installed {dropin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
