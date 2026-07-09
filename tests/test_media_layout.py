"""Tests for the canonical media-stack layout contract."""

from pathlib import Path

import pytest
import yaml

from catalog_service import _render_template
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
        "jellyseerr",
    }

    for item_id in media_items:
        data = yaml.safe_load((CATALOG_DIR / f"{item_id}.yaml").read_text())
        layout_fields = [
            field for field in data.get("fields", []) if field.get("layout_default")
        ]
        assert layout_fields, f"{item_id} has no layout-backed fields"
        for field in layout_fields:
            assert resolve_layout_default(layout, field["layout_default"]).startswith("/")


def test_media_server_bundle_references_existing_apps_in_order():
    bundle = yaml.safe_load((CATALOG_DIR / "bundles" / "media-server.yaml").read_text())
    member_ids = [member["id"] for member in bundle["members"]]
    member_orders = [member["order"] for member in bundle["members"]]

    assert bundle["kind"] == "bundle"
    assert bundle["target_stack"] == "media"
    assert member_ids == [
        "vpn",
        "transmission",
        "sabnzbd",
        "prowlarr",
        "sonarr",
        "radarr",
        "lidarr",
        "jellyfin",
    ]
    assert member_orders == sorted(member_orders)
    assert len(member_orders) == len(set(member_orders))
    for item_id in member_ids:
        assert (CATALOG_DIR / f"{item_id}.yaml").exists(), f"{item_id} is not in catalog"
    assert bundle["choices"] == [
        {
            "key": "USE_VPN",
            "label": "Use VPN gateway",
            "type": "boolean",
            "default": "true",
        }
    ]
    assert bundle["shared_fields"]["USE_VPN"] == "true"
    assert bundle["shared_fields"]["CONFIG_DIR"]["layout_default"] == "config_root"
    assert bundle["shared_fields"]["DOWNLOADS_DIR"]["layout_default"] == "downloads_root"
    assert bundle["shared_fields"]["STORAGE_DIR"]["layout_default"] == "storage_root"


def test_arr_catalog_defaults_do_not_hardcode_library_or_download_paths():
    for item_id in ("sonarr", "radarr", "lidarr"):
        data = yaml.safe_load((CATALOG_DIR / f"{item_id}.yaml").read_text())
        fields = {field["key"]: field for field in data["fields"]}

        assert fields["MEDIA_DIR"]["default"] == ""
        assert fields["MEDIA_DIR"]["layout_default"].startswith("library:")
        assert fields["DOWNLOADS_DIR"]["default"] == ""
        assert fields["DOWNLOADS_DIR"]["layout_default"] == "downloads_root"


def _catalog_item(item_id):
    return yaml.safe_load((CATALOG_DIR / f"{item_id}.yaml").read_text())


def _resolved_field_values(item_id, layout=None):
    layout = layout or MediaLayout()
    values = {}
    for field in _catalog_item(item_id).get("fields", []):
        if "layout_default" in field:
            values[field["key"]] = resolve_layout_default(layout, field["layout_default"])
        else:
            values[field["key"]] = field.get("default", "")
    return values


def test_core_media_download_mounts_use_canonical_container_path():
    for item_id in (
        "sonarr",
        "radarr",
        "lidarr",
        "sabnzbd",
        "transmission",
        "rdtclient",
        "jackett",
    ):
        item = _catalog_item(item_id)
        rendered = _render_template(item["service"], _resolved_field_values(item_id))
        volumes = rendered.get("volumes", [])

        assert "/mnt/downloads:/downloads" in volumes


def test_get_iplayer_uses_category_scoped_completed_path():
    rendered = _render_template(
        _catalog_item("get_iplayer")["service"],
        _resolved_field_values("get_iplayer"),
    )

    assert "/mnt/downloads/incomplete:/downloads/incomplete" in rendered["volumes"]
    assert (
        "/mnt/downloads/complete/get_iplayer:/downloads/complete/get_iplayer"
        in rendered["volumes"]
    )


def test_seed_blocks_are_valid_for_core_media_apps():
    seedable = {
        "sonarr",
        "radarr",
        "lidarr",
        "prowlarr",
        "sabnzbd",
        "transmission",
        "rdtclient",
        "jackett",
        "jellyfin",
    }
    allowed_kinds = {"arr", "downloadclient", "indexer", "mediaserver"}

    for item_id in seedable:
        seed = _catalog_item(item_id).get("seed")
        assert seed, f"{item_id} must carry seed metadata"
        assert seed["kind"] in allowed_kinds

        api = seed.get("api", {})
        assert isinstance(api.get("port"), int), f"{item_id} seed api.port must be an int"

        if seed["kind"] == "arr":
            assert seed["root_folders"], f"{item_id} must declare root folders"
            assert "/downloads" in seed.get("forbid_root_under", [])
            assert all(not path.startswith("/downloads") for path in seed["root_folders"])
            assert seed.get("import_mode") == "move"
            assert seed.get("completed_download_handling") is True
            assert seed.get("recycle_bin", "").startswith(seed["root_folders"][0])
            assert seed.get("download_clients"), f"{item_id} must declare download clients"
            for client in seed["download_clients"]:
                assert client["category"] == item_id
                assert client["remove_completed"] is True
                assert client["remove_failed"] is True

        if seed["kind"] == "downloadclient":
            downloads = seed.get("downloads", {})
            assert downloads.get("complete_dir") == "/downloads/complete"
            assert set(seed.get("categories", [])).issubset(set(DOWNLOAD_CATEGORIES))
            assert seed.get("remove_completed") is True
            assert seed.get("remove_failed") is True

        if seed["kind"] == "mediaserver":
            libraries = seed.get("libraries", [])
            assert libraries
            assert {library["kind"] for library in libraries}.issubset(set(LIBRARY_KINDS))
            assert all(library["path"].startswith("/media/") for library in libraries)
