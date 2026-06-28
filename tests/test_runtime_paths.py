import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime_paths import migrate_legacy_runtime_data


def test_migration_routes_config_state_logs_and_credentials(tmp_path):
    source_root = tmp_path / "source"
    legacy_config = source_root / "config"
    legacy_plugins = legacy_config / "storage_plugins"
    legacy_logs = legacy_plugins / "snapraid-logs"
    legacy_logs.mkdir(parents=True)

    (legacy_config / "media_paths.json").write_text('{"storage": "/mnt/data"}\n')
    (legacy_config / "auto_update.json").write_text('{"enabled": true}\n')
    (legacy_plugins / "snapraid.json").write_text('{"drives": []}\n')
    (legacy_plugins / "snapraid_state.json").write_text('{"running": false}\n')
    (legacy_logs / "sync.log").write_text("sync complete\n")
    legacy_credentials = tmp_path / "pi-health.env"
    legacy_credentials.write_text("PIHEALTH_PASSWORD_HASH=hash\n")

    config_dir = tmp_path / "etc" / "limeos"
    state_dir = tmp_path / "var" / "lib" / "limeos"
    log_dir = tmp_path / "var" / "log" / "limeos"
    credentials_file = config_dir / "credentials.env"

    copied = migrate_legacy_runtime_data(
        source_root=source_root,
        config_dir=config_dir,
        state_dir=state_dir,
        log_dir=log_dir,
        legacy_credentials=legacy_credentials,
        credentials_file=credentials_file,
    )

    assert config_dir / "media_paths.json" in copied
    assert json.loads((config_dir / "storage_plugins" / "snapraid.json").read_text()) == {
        "drives": []
    }
    assert json.loads(
        (state_dir / "storage_plugins" / "snapraid_state.json").read_text()
    ) == {"running": False}
    assert (log_dir / "snapraid" / "sync.log").read_text() == "sync complete\n"
    assert credentials_file.read_text() == "PIHEALTH_PASSWORD_HASH=hash\n"
    assert credentials_file.stat().st_mode & 0o777 == 0o640


def test_migration_is_idempotent_and_never_overwrites(tmp_path):
    source_root = tmp_path / "source"
    legacy_config = source_root / "config"
    legacy_config.mkdir(parents=True)
    (legacy_config / "media_paths.json").write_text('{"storage": "legacy"}\n')

    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "log"
    config_dir.mkdir()
    destination = config_dir / "media_paths.json"
    destination.write_text('{"storage": "current"}\n')

    first = migrate_legacy_runtime_data(
        source_root=source_root,
        config_dir=config_dir,
        state_dir=state_dir,
        log_dir=log_dir,
        legacy_credentials=tmp_path / "missing.env",
        credentials_file=config_dir / "credentials.env",
    )
    second = migrate_legacy_runtime_data(
        source_root=source_root,
        config_dir=config_dir,
        state_dir=state_dir,
        log_dir=log_dir,
        legacy_credentials=tmp_path / "missing.env",
        credentials_file=config_dir / "credentials.env",
    )

    assert first == []
    assert second == []
    assert json.loads(destination.read_text()) == {"storage": "current"}
