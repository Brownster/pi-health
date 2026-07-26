"""Read service API keys from the config directories Docker already mounts.

Every service LimeOS reports on keeps its own credential on disk inside the
host directory bound to the container's ``/config``. Reading it there means the
activity panel works without the operator copying keys into a second place.
Keys are held in memory only: nothing here writes them to LimeOS config, and
callers must keep them out of logs and API responses.
"""

from __future__ import annotations

import configparser
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path


# Relative to the host path bound to the container's /config.
JELLYFIN_DATABASE_CANDIDATES = (
    "data/data/jellyfin.db",
    "data/jellyfin.db",
    "jellyfin.db",
)
SABNZBD_CONFIG_CANDIDATES = ("sabnzbd.ini", "config/sabnzbd.ini")
ARR_CONFIG_CANDIDATES = ("config.xml",)


class CredentialUnavailable(Exception):
    """Raised when a service credential cannot be read from its config directory."""


def _first_existing(root: Path, candidates: tuple[str, ...], exists: Callable[[Path], bool]) -> Path:
    for candidate in candidates:
        path = root / candidate
        if exists(path):
            return path
    raise CredentialUnavailable(f"No config file found under {root}")


def read_arr_api_key(
    config_root: str | Path,
    *,
    exists: Callable[[Path], bool] = Path.is_file,
    read_text: Callable[[Path], str] = lambda path: path.read_text(encoding="utf-8"),
) -> str:
    """Read a Servarr ``config.xml`` API key."""
    path = _first_existing(Path(config_root), ARR_CONFIG_CANDIDATES, exists)
    try:
        root = ET.fromstring(read_text(path))  # noqa: S314 - local, operator-owned config
    except (OSError, ET.ParseError) as error:
        raise CredentialUnavailable(f"Unreadable Servarr config at {path}: {error}") from error
    value = (root.findtext("ApiKey") or "").strip()
    if not value:
        raise CredentialUnavailable(f"No ApiKey element in {path}")
    return value


def read_sabnzbd_api_key(
    config_root: str | Path,
    *,
    exists: Callable[[Path], bool] = Path.is_file,
    read_text: Callable[[Path], str] = lambda path: path.read_text(encoding="utf-8"),
) -> str:
    """Read the API key from ``sabnzbd.ini``."""
    path = _first_existing(Path(config_root), SABNZBD_CONFIG_CANDIDATES, exists)
    try:
        raw = read_text(path)
    except OSError as error:
        raise CredentialUnavailable(f"Unreadable SABnzbd config at {path}: {error}") from error
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        # sabnzbd.ini opens with a bare "__version__" line before any section.
        parser.read_string("[__preamble__]\n" + raw)
    except configparser.Error as error:
        raise CredentialUnavailable(f"Unparsable SABnzbd config at {path}: {error}") from error
    value = (parser.get("misc", "api_key", fallback="") or "").strip()
    if not value:
        raise CredentialUnavailable(f"No api_key in {path}")
    return value


def _default_query(database: Path, statement: str) -> list[tuple]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=3)
    try:
        return list(connection.execute(statement))
    finally:
        connection.close()


def read_jellyfin_api_key(
    config_root: str | Path,
    *,
    exists: Callable[[Path], bool] = Path.is_file,
    query: Callable[[Path, str], list[tuple]] = _default_query,
) -> str:
    """Read an existing Jellyfin API key from its SQLite database, read-only."""
    path = _first_existing(Path(config_root), JELLYFIN_DATABASE_CANDIDATES, exists)
    try:
        rows = query(path, "SELECT AccessToken FROM ApiKeys")
    except Exception as error:
        raise CredentialUnavailable(f"Unreadable Jellyfin database at {path}: {error}") from error
    for row in rows:
        token = str(row[0] or "").strip() if row else ""
        if token:
            return token
    raise CredentialUnavailable(
        f"No API key stored in {path}. Create one in Jellyfin under Dashboard > API Keys."
    )
