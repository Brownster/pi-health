"""Notification sinks for the alert evaluator (brick B2).

The evaluator emits provider-neutral `Notification`s; a `Notifier` renders and delivers them.
The Mattermost sink posts to a secret-managed incoming webhook — no model, no bot account
needed for detection. Delivery is injected so it is testable without a network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from alert_evaluator import Notification

_INCIDENT_COLOR = {"critical": "#d24b4b", "warning": "#e0a13b"}
_RECOVERY_COLOR = "#3aa657"


class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...


class RecordingNotifier:
    """Collects notifications instead of delivering them (tests / dry runs)."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def send(self, notification: Notification) -> None:
        self.sent.append(notification)


def _title(notification: Notification) -> str:
    if notification.event == "recovery":
        return f"✅ Recovered: {notification.key}"
    prefix = "🔴" if notification.severity == "critical" else "🟠"
    return f"{prefix} {notification.severity.capitalize()}: {notification.key}"


def render_mattermost_payload(notification: Notification) -> dict:
    color = (
        _RECOVERY_COLOR
        if notification.event == "recovery"
        else _INCIDENT_COLOR.get(notification.severity, _INCIDENT_COLOR["warning"])
    )
    return {
        "attachments": [
            {
                "color": color,
                "title": _title(notification),
                "text": notification.summary,
                "fields": [
                    {"short": True, "title": "Kind", "value": notification.kind},
                    {"short": True, "title": "At", "value": notification.at},
                ],
            }
        ]
    }


class MattermostWebhookNotifier:
    """Posts incidents/recoveries to a Mattermost incoming webhook.

    `poster(url, payload)` is injected (default: a small requests.post wrapper) so the sink
    can be unit-tested without a live server. Delivery failures are surfaced to the caller,
    which decides whether to retry on the next evaluation tick.
    """

    def __init__(self, webhook_url: str, *, poster: Callable[[str, dict], None] | None = None) -> None:
        self._webhook_url = webhook_url
        self._poster = poster or _default_poster

    def send(self, notification: Notification) -> None:
        self._poster(self._webhook_url, render_mattermost_payload(notification))


def _default_poster(url: str, payload: dict) -> None:  # pragma: no cover - thin network wrapper
    import requests

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
