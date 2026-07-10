from datetime import datetime, timedelta, timezone

import pytest

from alert_policy import AlertPolicy, AlertPolicyError, normalize_alert_policy


def test_policy_defaults_all_categories_enabled():
    policy = AlertPolicy.from_mapping({})

    assert policy.allows("container", "container:jellyfin") is True
    assert policy.required_mounts == ()


def test_policy_disables_category_and_silences_one_resource():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    policy = AlertPolicy.from_mapping(
        {
            "categories": {"smart": {"enabled": False}},
            "silences": [
                {
                    "kind": "container",
                    "key": "container:jellyfin",
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "reason": "upgrade",
                }
            ],
        }
    )

    assert policy.allows("smart", "smart:/dev/sda", now=now) is False
    assert policy.allows("container", "container:jellyfin", now=now) is False
    assert policy.allows("container", "container:sonarr", now=now) is True
    assert policy.allows(
        "container", "container:jellyfin", now=now + timedelta(hours=2)
    ) is True


def test_policy_removes_expired_silences():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    policy = AlertPolicy.from_mapping(
        {
            "silences": [
                {
                    "kind": "mount",
                    "key": "mount:/mnt/media",
                    "created_at": (now - timedelta(hours=2)).isoformat(),
                    "expires_at": (now - timedelta(hours=1)).isoformat(),
                }
            ]
        }
    )

    assert policy.without_expired(now=now)["silences"] == []


@pytest.mark.parametrize(
    "raw",
    [
        {"required_mounts": ["relative"]},
        {"categories": {"container": {"enabled": "yes"}}},
        {"silences": [{"kind": "smart", "key": "container:x"}]},
    ],
)
def test_policy_rejects_invalid_updates(raw):
    with pytest.raises(AlertPolicyError):
        normalize_alert_policy(raw)
