"""Central filesystem ownership contract for LimeOS runtime data."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent
STATIC_CONFIG_DIR = SOURCE_ROOT / "config"
STATIC_SCHEMA_DIR = STATIC_CONFIG_DIR / "schemas"
STATIC_CATALOG_DIR = SOURCE_ROOT / "catalog"

CONFIG_DIR = Path(os.getenv("LIMEOS_CONFIG_DIR", "/etc/limeos"))
STATE_DIR = Path(os.getenv("LIMEOS_STATE_DIR", "/var/lib/limeos"))
LOG_DIR = Path(os.getenv("LIMEOS_LOG_DIR", "/var/log/limeos"))
CREDENTIALS_FILE = Path(
    os.getenv("LIMEOS_CREDENTIALS_FILE", str(CONFIG_DIR / "credentials.env"))
)

STORAGE_PLUGIN_CONFIG_DIR = CONFIG_DIR / "storage_plugins"
STORAGE_PLUGIN_STATE_DIR = STATE_DIR / "storage_plugins"
SNAPRAID_LOG_DIR = LOG_DIR / "snapraid"
RETIRED_ENV_KEYS = frozenset({"PIHEALTH_UI_MODE", "PIHEALTH_UI_V2_PAGES", "THEME"})


def ensure_runtime_directories(
    config_dir: Path = CONFIG_DIR,
    state_dir: Path = STATE_DIR,
    log_dir: Path = LOG_DIR,
) -> None:
    """Create runtime roots with service-private directory permissions."""
    for path in (config_dir, state_dir, log_dir):
        path.mkdir(parents=True, exist_ok=True, mode=0o750)
        path.chmod(0o750)


def _copy_file_if_missing(source: Path, destination: Path, mode: int) -> bool:
    if not source.is_file() or destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as target, source.open("rb") as current:
            shutil.copyfileobj(current, target)
            target.flush()
            os.fsync(target.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return True


def _copy_credentials_if_missing(source: Path, destination: Path, mode: int) -> bool:
    """Copy credentials while dropping retired UI configuration."""
    if not source.is_file() or destination.exists():
        return False

    retained_lines = []
    for line in source.read_text().splitlines(keepends=True):
        assignment = line.strip()
        if assignment.startswith("export "):
            assignment = assignment.removeprefix("export ").lstrip()
        key = assignment.partition("=")[0].strip() if "=" in assignment else None
        if key not in RETIRED_ENV_KEYS:
            retained_lines.append(line)

    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w") as target:
            target.writelines(retained_lines)
            target.flush()
            os.fsync(target.fileno())
        temporary_path.chmod(mode)
        os.replace(temporary_path, destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return True


def _copy_tree_files_if_missing(
    source: Path,
    destination: Path,
    mode: int,
) -> list[Path]:
    copied = []
    if not source.is_dir():
        return copied
    for source_file in sorted(path for path in source.rglob("*") if path.is_file()):
        relative = source_file.relative_to(source)
        destination_file = destination / relative
        if _copy_file_if_missing(source_file, destination_file, mode):
            copied.append(destination_file)
    return copied


def migrate_legacy_runtime_data(
    *,
    source_root: Path = SOURCE_ROOT,
    config_dir: Path = CONFIG_DIR,
    state_dir: Path = STATE_DIR,
    log_dir: Path = LOG_DIR,
    legacy_credentials: Path = Path("/etc/pi-health.env"),
    credentials_file: Path = CREDENTIALS_FILE,
) -> list[Path]:
    """Copy legacy checkout-local data into owned runtime roots without overwrite."""
    source_root = Path(source_root)
    config_dir = Path(config_dir)
    state_dir = Path(state_dir)
    log_dir = Path(log_dir)
    credentials_file = Path(credentials_file)
    ensure_runtime_directories(config_dir, state_dir, log_dir)

    copied = []
    legacy_config = source_root / "config"
    file_migrations = (
        (legacy_config / "media_paths.json", config_dir / "media_paths.json", 0o640),
        (legacy_config / "seedbox_mount.json", config_dir / "seedbox_mount.json", 0o640),
        (legacy_config / "plugins.json", config_dir / "plugins.json", 0o640),
        (legacy_config / "copyparty.json", config_dir / "copyparty.json", 0o640),
        (legacy_config / "pihealth_update.json", config_dir / "pihealth_update.json", 0o640),
        (legacy_config / "auto_update.json", state_dir / "auto_update.json", 0o640),
        (legacy_config / "backup_config.json", state_dir / "backup_config.json", 0o640),
    )
    for source, destination, mode in file_migrations:
        if _copy_file_if_missing(source, destination, mode):
            copied.append(destination)
    if _copy_credentials_if_missing(Path(legacy_credentials), credentials_file, 0o640):
        copied.append(credentials_file)

    legacy_plugins = legacy_config / "storage_plugins"
    if legacy_plugins.is_dir():
        for source in sorted(path for path in legacy_plugins.iterdir() if path.is_file()):
            if source.name == "snapraid_state.json":
                destination = state_dir / "storage_plugins" / source.name
            else:
                destination = config_dir / "storage_plugins" / source.name
            if _copy_file_if_missing(source, destination, 0o640):
                copied.append(destination)
    copied.extend(
        _copy_tree_files_if_missing(
            legacy_plugins / "snapraid-logs",
            log_dir / "snapraid",
            0o640,
        )
    )
    return copied
