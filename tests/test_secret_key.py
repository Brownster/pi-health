"""Tests for persisted Flask secret-key handling (review slice B)."""

import os
from pathlib import Path

import app


def test_creates_and_reuses_key(monkeypatch, tmp_path):
    key_file = tmp_path / "secret_key"
    monkeypatch.setattr(app, "SECRET_KEY_FILE", key_file)

    first = app._load_or_create_secret_key()
    second = app._load_or_create_secret_key()

    assert first == second
    assert len(first) == 64  # token_hex(32)
    assert key_file.read_text().strip() == first
    assert oct(key_file.stat().st_mode & 0o777) == oct(0o600)


def test_reads_existing_key(monkeypatch, tmp_path):
    key_file = tmp_path / "secret_key"
    key_file.write_text("preexisting-key\n")
    monkeypatch.setattr(app, "SECRET_KEY_FILE", key_file)

    assert app._load_or_create_secret_key() == "preexisting-key"


def test_resolve_prefers_env_and_does_not_write(monkeypatch, tmp_path):
    key_file = tmp_path / "secret_key"
    monkeypatch.setattr(app, "SECRET_KEY_FILE", key_file)
    monkeypatch.setenv("SECRET_KEY", "env-provided-key")

    assert app._resolve_secret_key() == "env-provided-key"
    assert not key_file.exists()


def test_falls_back_to_ephemeral_when_unwritable(monkeypatch, tmp_path):
    # Point the key file at a path whose parent is a file, so creation fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setattr(app, "SECRET_KEY_FILE", Path(blocker / "secret_key"))
    monkeypatch.delenv("SECRET_KEY", raising=False)

    key = app._load_or_create_secret_key()
    assert len(key) == 64  # still returns a usable key, just not persisted


def test_create_app_persists_key_across_instances(monkeypatch, tmp_path):
    from auth_utils import LoginRateLimiter
    from operation_manager import OperationRegistry
    from werkzeug.security import generate_password_hash

    key_file = tmp_path / "secret_key"
    monkeypatch.setattr(app, "SECRET_KEY_FILE", key_file)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    def build():
        deps = app.AppDependencies(
            users={"u": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
            login_rate_limiter=LoginRateLimiter(),
            docker_client=None,
            operation_registry=OperationRegistry(),
        )
        # No SECRET_KEY in config -> must fall through to the persisted key.
        return app.create_app(
            {"INIT_PLUGINS": False, "START_SCHEDULERS": False}, deps
        )

    first = build().config["SECRET_KEY"]
    second = build().config["SECRET_KEY"]
    assert first == second == key_file.read_text().strip()
    assert os.path.exists(key_file)
