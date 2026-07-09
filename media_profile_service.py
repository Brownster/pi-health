"""Persist the portable media stack profile."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ports import ConfigRepository


class MediaProfileService:
    """Read and persist the resolved media-stack profile."""

    def __init__(
        self,
        *,
        repository: ConfigRepository,
        profile_path_provider: Callable[[], str],
    ) -> None:
        self._repository = repository
        self._profile_path_provider = profile_path_provider

    def profile(self) -> dict[str, Any]:
        """Return the persisted profile, or an empty profile if none exists."""
        try:
            stored = self._repository.read_json(self._profile_path_provider(), default={})
        except Exception:
            stored = {}
        return stored if isinstance(stored, dict) else {}

    def save(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        """Persist a resolved profile with private file permissions."""
        data = dict(profile)
        self._repository.write_json(self._profile_path_provider(), data, mode=0o640)
        return data
