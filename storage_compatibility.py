"""Compatibility projections from guided storage into legacy media-path views."""

from __future__ import annotations

from media_layout import MediaLayout
from storage_contract import StorageContract


def media_paths_from_contract(contract: StorageContract) -> dict[str, str]:
    """Project the authoritative contract into the historical API key shape."""
    locations = contract.locations
    return {
        "storage": locations.media_host,
        "downloads": locations.downloads_host,
        "config": locations.application_config_host,
        "backup": locations.backup_host,
    }


def media_layout_from_contract(contract: StorageContract) -> MediaLayout:
    """Project the authoritative contract into the canonical layout model."""
    return MediaLayout.from_media_paths(media_paths_from_contract(contract))


def media_identity_from_contract(contract: StorageContract) -> dict[str, str]:
    """Project the managed identity into existing catalog variable names."""
    return {
        "PUID": str(contract.media_identity.uid),
        "PGID": str(contract.media_identity.gid),
    }
