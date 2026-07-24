"""OB-000: strict persistence for the guided-onboarding storage contract."""

from unittest.mock import Mock

import pytest

from runtime_paths import CONFIG_DIR, STORAGE_CONTRACT_PATH, STORAGE_CONTRACT_SCHEMA_PATH
from storage_contract import StorageContractError
from storage_contract_service import (
    StorageContractReadError,
    StorageContractService,
    StorageContractWriteError,
)


CONFIG_PATH = "/etc/limeos/storage-contract.json"


def valid_contract():
    return {
        "schema_version": "1",
        "profile": "single_disk",
        "media_identity": {"uid": 1000, "gid": 1000},
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
                "filesystem_uuid": "data-uuid",
                "filesystem": "ext4",
                "mountpoint": "/mnt/storage",
            }
        ],
    }


def make_service(*, repository=None, file_exists=None):
    repository = repository or Mock()
    if file_exists is None:
        file_exists = Mock(return_value=False)
    return StorageContractService(
        repository=repository,
        config_path_provider=lambda: CONFIG_PATH,
        file_exists=file_exists,
    )


def test_runtime_paths_publish_contract_and_schema_locations():
    assert STORAGE_CONTRACT_PATH.name == "storage-contract.json"
    assert STORAGE_CONTRACT_PATH.parent == CONFIG_DIR
    assert STORAGE_CONTRACT_SCHEMA_PATH.name == "storage-contract.schema.json"
    assert STORAGE_CONTRACT_SCHEMA_PATH.is_file()


def test_load_returns_none_only_when_contract_file_is_absent():
    repository = Mock()
    repository.read_json.return_value = None
    exists = Mock(return_value=False)

    result = make_service(repository=repository, file_exists=exists).load()

    assert result is None
    repository.read_json.assert_called_once_with(CONFIG_PATH, default=None)
    exists.assert_called_once_with(CONFIG_PATH)


def test_load_models_a_valid_persisted_contract():
    repository = Mock()
    repository.read_json.return_value = valid_contract()

    result = make_service(repository=repository).load()

    assert result is not None
    assert result.profile == "single_disk"
    assert result.devices[0].filesystem_uuid == "data-uuid"


def test_load_fails_closed_when_existing_json_is_malformed():
    repository = Mock()
    repository.read_json.return_value = None

    with pytest.raises(StorageContractReadError, match="invalid"):
        make_service(
            repository=repository,
            file_exists=Mock(return_value=True),
        ).load()


def test_load_maps_invalid_contract_to_bounded_error():
    repository = Mock()
    repository.read_json.return_value = {"schema_version": "2"}

    with pytest.raises(StorageContractReadError, match="invalid") as failure:
        make_service(repository=repository).load()

    assert isinstance(failure.value.__cause__, StorageContractError)


def test_load_maps_repository_failure_without_exposing_detail():
    repository = Mock()
    repository.read_json.side_effect = PermissionError("/secret/path")

    with pytest.raises(StorageContractReadError) as failure:
        make_service(repository=repository).load()

    assert str(failure.value) == "Unable to read the storage configuration"
    assert "/secret/path" not in str(failure.value)


def test_save_validates_before_private_atomic_repository_write():
    repository = Mock()
    raw = valid_contract()

    saved = make_service(repository=repository).save(raw)

    assert saved.as_dict() == raw
    repository.write_json.assert_called_once_with(CONFIG_PATH, raw, mode=0o640)


def test_save_rejects_invalid_contract_without_writing():
    repository = Mock()
    raw = valid_contract()
    raw["locations"]["media_container"] = "/movies"

    with pytest.raises(StorageContractError):
        make_service(repository=repository).save(raw)

    repository.write_json.assert_not_called()


def test_save_maps_repository_failure_to_bounded_error():
    repository = Mock()
    repository.write_json.side_effect = OSError("/private/device")

    with pytest.raises(StorageContractWriteError) as failure:
        make_service(repository=repository).save(valid_contract())

    assert str(failure.value) == "Unable to save the storage configuration"
    assert "/private/device" not in str(failure.value)
