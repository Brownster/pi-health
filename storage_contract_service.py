"""Persistence boundary for the guided-onboarding storage contract."""

from __future__ import annotations

import os
from collections.abc import Callable

from ports import ConfigRepository
from runtime_paths import STORAGE_CONTRACT_PATH
from storage_contract import StorageContract, StorageContractError, parse_storage_contract


class StorageContractReadError(Exception):
    """Raised when configured storage state cannot be read or validated."""


class StorageContractWriteError(Exception):
    """Raised when validated storage state cannot be persisted."""


class StorageContractService:
    """Load and save strict storage state without inferring legacy migrations."""

    def __init__(
        self,
        *,
        repository: ConfigRepository,
        config_path_provider: Callable[[], str | os.PathLike] = (
            lambda: STORAGE_CONTRACT_PATH
        ),
        file_exists: Callable[[str | os.PathLike], bool] = os.path.exists,
    ) -> None:
        self._repository = repository
        self._config_path_provider = config_path_provider
        self._file_exists = file_exists

    def load(self) -> StorageContract | None:
        """Return configured storage, or ``None`` when onboarding has not saved it."""
        path = self._config_path_provider()
        try:
            raw = self._repository.read_json(path, default=None)
        except Exception as exc:
            raise StorageContractReadError(
                "Unable to read the storage configuration"
            ) from exc

        if raw is None:
            try:
                exists = self._file_exists(path)
            except OSError as exc:
                raise StorageContractReadError(
                    "Unable to inspect the storage configuration"
                ) from exc
            if exists:
                raise StorageContractReadError("The storage configuration is invalid")
            return None

        try:
            return parse_storage_contract(raw)
        except StorageContractError as exc:
            raise StorageContractReadError(
                "The storage configuration is invalid"
            ) from exc

    def save(self, raw: object) -> StorageContract:
        """Validate the complete contract before one private atomic write."""
        contract = parse_storage_contract(raw)
        try:
            self._repository.write_json(
                self._config_path_provider(),
                contract.as_dict(),
                mode=0o640,
            )
        except Exception as exc:
            raise StorageContractWriteError(
                "Unable to save the storage configuration"
            ) from exc
        return contract
