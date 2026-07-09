"""Tests for the canonical media-stack layout contract."""

from pathlib import Path

import pytest
import yaml

from media_layout import (
    DOWNLOAD_CATEGORIES,
    LIBRARY_KINDS,
    MediaLayout,
    resolve_layout_default,
)


CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"


def test_default_layout_paths_are_lowercase_and_consistent():
    layout = MediaLayout()

    assert layout.library_path("tv") == "/mnt/storage/tv"
    assert layout.library_path("movies") == "/mnt/storage/movies"
    assert layout.library_container_path("tv") == "/tv"
    assert layout.download_incomplete_path() == "/mnt/downloads/incomplete"
    assert layout.download_complete_path("sonarr") == "/mnt/downloads/complete/sonarr"
    assert layout.legacy_media_paths() == {
        "storage": "/mnt/storage",
        "downloads": "/mnt/downloads",
        "config": "/home/pi/docker",
        "backup": "/mnt/backup",
    }


def test_layout_derives_from_existing_media_paths_config():
    layout = MediaLayout.from_media_paths(
        {
            "storage": "/srv/media/",
            "downloads": "/scratch/downloads/",
            "config": "/opt/docker/",
            "backup": "/backup/",
        }
    )

    assert layout.storage_root == "/srv/media"
    assert layout.downloads_root == "/scratch/downloads"
    assert layout.config_root == "/opt/docker"
    assert layout.backup_root == "/backup"
    assert layout.library_path("books") == "/srv/media/books"
    assert layout.download_complete_path("radarr") == "/scratch/downloads/complete/radarr"


def test_layout_reports_all_provisionable_dirs():
    layout = MediaLayout("/media", "/downloads", "/config", "/backup")

    assert layout.all_library_dirs() == [f"/media/{kind}" for kind in LIBRARY_KINDS]
    assert layout.all_download_dirs() == ["/downloads/incomplete"] + [
        f"/downloads/complete/{category}" for category in DOWNLOAD_CATEGORIES
    ]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("config_root", "/cfg"),
        ("storage_root", "/storage"),
        ("downloads_root", "/downloads"),
        ("backup_root", "/backup"),
        ("library:music", "/storage/music"),
        ("library_container:movies", "/movies"),
        ("download_incomplete", "/downloads/incomplete"),
        ("download_complete:lidarr", "/downloads/complete/lidarr"),
    ],
)
def test_resolve_layout_default_tokens(token, expected):
    layout = MediaLayout("/storage", "/downloads", "/cfg", "/backup")

    assert resolve_layout_default(layout, token) == expected


def test_unknown_layout_tokens_fail_fast():
    layout = MediaLayout()

    with pytest.raises(ValueError):
        resolve_layout_default(layout, "library:TV")


def test_media_catalog_layout_defaults_are_valid():
    layout = MediaLayout()
    media_items = {
        "sonarr",
        "radarr",
        "lidarr",
        "sabnzbd",
        "transmission",
        "jellyfin",
        "prowlarr",
        "jackett",
        "rdtclient",
        "get_iplayer",
        "navidrome",
        "audiobookshelf",
        "lazylibrarian",
        "filebrowser",
    }

    for item_id in media_items:
        data = yaml.safe_load((CATALOG_DIR / f"{item_id}.yaml").read_text())
        layout_fields = [
            field for field in data.get("fields", []) if field.get("layout_default")
        ]
        assert layout_fields, f"{item_id} has no layout-backed fields"
        for field in layout_fields:
            assert resolve_layout_default(layout, field["layout_default"]).startswith("/")


def test_arr_catalog_defaults_do_not_hardcode_library_or_download_paths():
    for item_id in ("sonarr", "radarr", "lidarr"):
        data = yaml.safe_load((CATALOG_DIR / f"{item_id}.yaml").read_text())
        fields = {field["key"]: field for field in data["fields"]}

        assert fields["MEDIA_DIR"]["default"] == ""
        assert fields["MEDIA_DIR"]["layout_default"].startswith("library:")
        assert fields["DOWNLOADS_DIR"]["default"] == ""
        assert fields["DOWNLOADS_DIR"]["layout_default"] == "downloads_root"
