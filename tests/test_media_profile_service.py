"""Tests for media profile persistence."""

from unittest.mock import Mock

from media_profile_service import MediaProfileService


def test_profile_returns_empty_dict_when_missing_or_invalid():
    repository = Mock()
    repository.read_json.return_value = []
    service = MediaProfileService(
        repository=repository,
        profile_path_provider=lambda: "/config/media_profile.json",
    )

    assert service.profile() == {}
    repository.read_json.assert_called_once_with("/config/media_profile.json", default={})


def test_save_persists_profile_with_private_mode():
    repository = Mock()
    service = MediaProfileService(
        repository=repository,
        profile_path_provider=lambda: "/config/media_profile.json",
    )

    profile = service.save({"version": 1, "stack_name": "media"})

    assert profile == {"version": 1, "stack_name": "media"}
    repository.write_json.assert_called_once_with(
        "/config/media_profile.json",
        {"version": 1, "stack_name": "media"},
        mode=0o640,
    )
