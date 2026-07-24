"""OB-000: compatibility projections for existing storage consumers."""

from unittest.mock import Mock

from werkzeug.security import generate_password_hash

from app import AppDependencies, create_app
from auth_utils import LoginRateLimiter
from operation_manager import OperationRegistry
from storage_compatibility import (
    media_identity_from_contract,
    media_layout_from_contract,
    media_paths_from_contract,
)
from storage_contract import parse_storage_contract


def _contract():
    return parse_storage_contract(
        {
            "schema_version": "1",
            "profile": "single_disk",
            "media_identity": {"uid": 1200, "gid": 1300},
            "locations": {
                "media_host": "/mnt/storage/media",
                "downloads_host": "/mnt/storage/downloads",
                "application_config_host": "/var/lib/limeos/apps",
                "backup_host": "/mnt/backup/limeos",
                "media_container": "/data/media",
                "downloads_container": "/data/downloads",
                "config_container": "/config",
            },
            "devices": [
                {
                    "id": "storage",
                    "role": "data",
                    "filesystem_uuid": "storage-uuid",
                    "filesystem": "ext4",
                    "mountpoint": "/mnt/storage",
                }
            ],
        }
    )


def test_contract_projects_into_legacy_media_path_shape():
    assert media_paths_from_contract(_contract()) == {
        "storage": "/mnt/storage/media",
        "downloads": "/mnt/storage/downloads",
        "config": "/var/lib/limeos/apps",
        "backup": "/mnt/backup/limeos",
    }


def test_contract_projects_into_existing_layout_model():
    layout = media_layout_from_contract(_contract())

    assert layout.storage_root == "/mnt/storage/media"
    assert layout.library_path("movies") == "/mnt/storage/media/movies"
    assert layout.downloads_root == "/mnt/storage/downloads"
    assert layout.config_root == "/var/lib/limeos/apps"
    assert layout.backup_root == "/mnt/backup/limeos"


def test_contract_projects_media_identity_into_catalog_variables():
    assert media_identity_from_contract(_contract()) == {
        "PUID": "1200",
        "PGID": "1300",
    }


def test_default_app_services_share_the_authoritative_contract_projection():
    contract_service = Mock()
    contract_service.load.return_value = _contract()
    dependencies = AppDependencies(
        users={
            "testuser": generate_password_hash(
                "pw", method="pbkdf2:sha256:600000"
            )
        },
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
        storage_contract_service=contract_service,
    )
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "INIT_PLUGINS": False,
            "START_SCHEDULERS": False,
        },
        dependencies,
    )
    client = application.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "testuser"
        session["csrf_token"] = "test-csrf-token"

    media_paths = client.get("/api/disks/media-paths").get_json()["paths"]
    media_layout = client.get("/api/media/layout").get_json()["layout"]
    catalog_item = client.get(
        "/api/catalog/jellyfin?apply_media_paths=true"
    ).get_json()["item"]
    fields = {field["key"]: field["default"] for field in catalog_item["fields"]}

    assert media_paths["storage"] == "/mnt/storage/media"
    assert media_layout["storage_root"] == "/mnt/storage/media"
    assert fields["CONFIG_DIR"] == "/var/lib/limeos/apps"
    assert fields["STORAGE_DIR"] == "/mnt/storage/media"
    assert fields["PUID"] == "1200"
    assert fields["PGID"] == "1300"
