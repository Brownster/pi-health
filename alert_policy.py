"""Alert category and resource delivery policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


ALERT_KINDS = ("container", "smart", "mount", "snapraid")


def default_alert_policy() -> dict[str, Any]:
    return {
        "version": 1,
        "categories": {kind: {"enabled": True} for kind in ALERT_KINDS},
        "required_mounts": [],
        "silences": [],
    }


class AlertPolicyError(ValueError):
    """Raised when an alert policy update is invalid."""


def normalize_alert_policy(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and complete a persisted alert policy."""
    policy = default_alert_policy()
    raw = raw or {}

    categories = raw.get("categories", {})
    if not isinstance(categories, Mapping):
        raise AlertPolicyError("categories must be an object")
    for kind in ALERT_KINDS:
        category = categories.get(kind, {})
        if not isinstance(category, Mapping):
            raise AlertPolicyError(f"category must be an object: {kind}")
        enabled = category.get("enabled", True)
        if not isinstance(enabled, bool):
            raise AlertPolicyError(f"category enabled must be a boolean: {kind}")
        policy["categories"][kind]["enabled"] = enabled

    mounts = raw.get("required_mounts", [])
    if not isinstance(mounts, list):
        raise AlertPolicyError("required_mounts must be a list")
    normalized_mounts = []
    for mount in mounts:
        if not isinstance(mount, str) or not mount.startswith("/") or "\x00" in mount:
            raise AlertPolicyError("required mountpoints must be absolute paths")
        if mount not in normalized_mounts:
            normalized_mounts.append(mount)
    policy["required_mounts"] = normalized_mounts

    silences = raw.get("silences", [])
    if not isinstance(silences, list):
        raise AlertPolicyError("silences must be a list")
    policy["silences"] = [_normalize_silence(silence) for silence in silences]
    return policy


def _normalize_silence(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AlertPolicyError("silence must be an object")
    kind = str(raw.get("kind", ""))
    key = str(raw.get("key", "")).strip()
    if kind not in ALERT_KINDS:
        raise AlertPolicyError(f"unknown silence category: {kind}")
    if not key or not key.startswith(f"{kind}:"):
        raise AlertPolicyError("silence key must match its category")

    expires_at = raw.get("expires_at") or None
    if expires_at is not None:
        _parse_time(str(expires_at))
        expires_at = str(expires_at)
    created_at = str(raw.get("created_at") or datetime.now(timezone.utc).isoformat())
    _parse_time(created_at)
    reason = str(raw.get("reason") or "").strip()
    if len(reason) > 200:
        raise AlertPolicyError("silence reason must be 200 characters or fewer")
    return {
        "kind": kind,
        "key": key,
        "created_at": created_at,
        "expires_at": expires_at,
        "reason": reason,
    }


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AlertPolicyError("silence timestamps must use ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AlertPolicyError("silence timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AlertPolicy:
    data: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "AlertPolicy":
        return cls(normalize_alert_policy(raw))

    @property
    def required_mounts(self) -> tuple[str, ...]:
        return tuple(self.data.get("required_mounts", []))

    def allows(self, kind: str, key: str, *, now: datetime | None = None) -> bool:
        category = self.data.get("categories", {}).get(kind, {})
        if not category.get("enabled", False):
            return False
        now = now or datetime.now(timezone.utc)
        for silence in self.data.get("silences", []):
            if silence.get("kind") != kind or silence.get("key") != key:
                continue
            expires_at = silence.get("expires_at")
            if expires_at is None or _parse_time(str(expires_at)) > now:
                return False
        return True

    def without_expired(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        clean = dict(self.data)
        clean["categories"] = {
            kind: dict(value) for kind, value in self.data.get("categories", {}).items()
        }
        clean["required_mounts"] = list(self.required_mounts)
        clean["silences"] = [
            dict(silence)
            for silence in self.data.get("silences", [])
            if silence.get("expires_at") is None
            or _parse_time(str(silence["expires_at"])) > now
        ]
        return clean
