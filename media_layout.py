"""Canonical media-stack layout helpers.

This module is intentionally pure: no filesystem reads, no writes, and no Flask
or Docker dependencies. Runtime services derive concrete paths from this single
contract so catalog defaults, provisioning, seeding, and backups agree.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


DEFAULT_STORAGE_ROOT = "/mnt/storage"
DEFAULT_DOWNLOADS_ROOT = "/mnt/downloads"
DEFAULT_CONFIG_ROOT = "/home/pi/docker"
DEFAULT_BACKUP_ROOT = "/mnt/backup"

LIBRARY_KINDS = ("movies", "tv", "music", "books", "audiobooks", "podcasts")
DOWNLOAD_CATEGORIES = (
    "sonarr",
    "radarr",
    "lidarr",
    "readarr",
    "sabnzbd",
    "transmission",
    "rdtclient",
    "jackett",
    "get_iplayer",
)

LIBRARY_CONTAINER_PATHS = {
    "movies": "/movies",
    "tv": "/tv",
    "music": "/music",
    "books": "/books",
    "audiobooks": "/audiobooks",
    "podcasts": "/podcasts",
}


def _clean_root(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.startswith("/"):
        return value.rstrip("/") or "/"
    return fallback


def _join(root: str, *parts: str) -> str:
    return str(PurePosixPath(root, *parts))


@dataclass(frozen=True)
class MediaLayout:
    """Concrete roots for the canonical media stack layout."""

    storage_root: str = DEFAULT_STORAGE_ROOT
    downloads_root: str = DEFAULT_DOWNLOADS_ROOT
    config_root: str = DEFAULT_CONFIG_ROOT
    backup_root: str = DEFAULT_BACKUP_ROOT

    @classmethod
    def from_media_paths(cls, media_paths: Mapping[str, Any] | None) -> "MediaLayout":
        paths = media_paths or {}
        return cls(
            storage_root=_clean_root(paths.get("storage"), DEFAULT_STORAGE_ROOT),
            downloads_root=_clean_root(paths.get("downloads"), DEFAULT_DOWNLOADS_ROOT),
            config_root=_clean_root(paths.get("config"), DEFAULT_CONFIG_ROOT),
            backup_root=_clean_root(paths.get("backup"), DEFAULT_BACKUP_ROOT),
        )

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def legacy_media_paths(self) -> dict[str, str]:
        """Return the historical media-path key shape used by disk/catalog APIs."""
        return {
            "storage": self.storage_root,
            "downloads": self.downloads_root,
            "config": self.config_root,
            "backup": self.backup_root,
        }

    def library_path(self, kind: str) -> str:
        _validate_library_kind(kind)
        return _join(self.storage_root, kind)

    def library_container_path(self, kind: str) -> str:
        _validate_library_kind(kind)
        return LIBRARY_CONTAINER_PATHS[kind]

    def download_incomplete_path(self) -> str:
        return _join(self.downloads_root, "incomplete")

    def download_complete_path(self, category: str) -> str:
        _validate_download_category(category)
        return _join(self.downloads_root, "complete", category)

    def all_library_dirs(self) -> list[str]:
        return [self.library_path(kind) for kind in LIBRARY_KINDS]

    def all_download_dirs(self) -> list[str]:
        return [self.download_incomplete_path()] + [
            self.download_complete_path(category) for category in DOWNLOAD_CATEGORIES
        ]


def _validate_library_kind(kind: str) -> None:
    if kind not in LIBRARY_KINDS:
        raise ValueError(f"Unknown media library kind: {kind}")


def _validate_download_category(category: str) -> None:
    if category not in DOWNLOAD_CATEGORIES:
        raise ValueError(f"Unknown download category: {category}")


def resolve_layout_default(layout: MediaLayout, token: str | None) -> str | None:
    """Resolve a catalog ``layout_default`` token into a concrete path.

    Supported tokens:
    - ``config_root``, ``storage_root``, ``downloads_root``, ``backup_root``
    - ``library:<kind>`` where kind is one of :data:`LIBRARY_KINDS`
    - ``library_container:<kind>``
    - ``download_incomplete``
    - ``download_complete:<category>`` where category is one of
      :data:`DOWNLOAD_CATEGORIES`
    """
    if not token:
        return None
    if token == "config_root":
        return layout.config_root
    if token == "storage_root":
        return layout.storage_root
    if token == "downloads_root":
        return layout.downloads_root
    if token == "backup_root":
        return layout.backup_root
    if token == "download_incomplete":
        return layout.download_incomplete_path()
    if token.startswith("library:"):
        return layout.library_path(token.split(":", 1)[1])
    if token.startswith("library_container:"):
        return layout.library_container_path(token.split(":", 1)[1])
    if token.startswith("download_complete:"):
        return layout.download_complete_path(token.split(":", 1)[1])
    raise ValueError(f"Unknown media layout default token: {token}")
