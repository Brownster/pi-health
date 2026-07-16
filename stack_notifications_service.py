"""Framework-neutral stack notifications: normalize *arr webhooks for Mattermost.

Radarr/Sonarr/Lidarr/Readarr/Prowlarr share a webhook shape: an `eventType` plus a media
object (`movie`/`series`+`episodes`) and quality. This module normalizes those into a
consistent `StackNotification`, applies a forwarding policy (quiet by default — imports,
upgrades, health, and failures; no per-release Grab/Rename/Test spam), and renders a clean
Mattermost attachment. Delivery + the token-gated ingest route live in the blueprint layer;
this core is pure so the mapping is fully testable.

The *arr-supplied text is untrusted: it only ever becomes attachment field *data*, never
markup, and details are length-bounded.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

MAX_DETAIL_CHARS = 500

#: Raw arr eventType (lowercased) -> normalized event name.
_EVENT_MAP = {
    "download": "imported",  # onDownload fires when an import completes
    "import": "imported",
    "upgrade": "upgraded",
    "healthissue": "health",
    "health": "health",
    "healthrestored": "health_restored",
    "downloadfailure": "failed",
    "grabfailure": "failed",
    "importfailure": "failed",
    "manualinteractionrequired": "manual",
    # normalized but suppressed under the quiet policy:
    "grab": "grabbed",
    "rename": "renamed",
    "movieadded": "added",
    "seriesadd": "added",
    "applicationupdate": "app_update",
    "test": "test",
}

#: Default forwarding policy: the events you usually care about.
QUIET_EVENTS = frozenset({"imported", "upgraded", "health", "health_restored", "failed", "manual"})
#: Everything meaningful (still excludes the connection Test).
VERBOSE_EVENTS = QUIET_EVENTS | frozenset({"grabbed", "renamed", "added", "app_update"})

_TITLES = {
    "imported": "Imported",
    "upgraded": "Upgraded",
    "failed": "Download failed",
    "manual": "Manual interaction required",
    "health": "Health issue",
    "health_restored": "Health restored",
    "grabbed": "Grabbed",
    "renamed": "Renamed",
    "added": "Added to library",
    "app_update": "Application updated",
}
_WARNING_EVENTS = frozenset({"failed", "manual", "health"})


@dataclass(frozen=True)
class StackNotification:
    source: str  # e.g. "radarr", "sonarr"
    event: str  # normalized event name
    severity: str  # "info" | "warning" | "critical"
    title: str
    detail: str


def _quality(payload: dict) -> str:
    for key in ("movieFile", "episodeFile", "trackFile", "bookFile"):
        quality = (payload.get(key) or {}).get("quality")
        if isinstance(quality, dict):
            name = quality.get("quality")
            name = name.get("name") if isinstance(name, dict) else name or quality.get("name")
            if name:
                return str(name)
    release = payload.get("release") or {}
    quality = release.get("quality")
    if isinstance(quality, dict):
        inner = quality.get("quality")
        return str((inner.get("name") if isinstance(inner, dict) else None) or quality.get("name") or "")
    return str(release.get("quality") or "") if not isinstance(release.get("quality"), dict) else ""


def _media_label(payload: dict) -> str:
    movie = payload.get("movie")
    if isinstance(movie, dict):
        year = movie.get("year")
        return f"{movie.get('title', '?')}" + (f" ({year})" if year else "")
    series = payload.get("series")
    if isinstance(series, dict):
        episodes = payload.get("episodes") or []
        episode = episodes[0] if isinstance(episodes, list) and episodes else {}
        code = ""
        if isinstance(episode, dict) and episode.get("seasonNumber") is not None:
            try:
                code = f"S{int(episode['seasonNumber']):02d}E{int(episode.get('episodeNumber', 0)):02d}"
            except (TypeError, ValueError):
                code = ""
        return f"{series.get('title', '?')} {code}".strip()
    return ""


def _describe(event: str, payload: dict) -> tuple[str, str]:
    if event in {"health", "health_restored"}:
        return _TITLES[event], str(payload.get("message") or "").strip()
    media = _media_label(payload)
    quality = _quality(payload)
    detail = " — ".join(part for part in (media, quality) if part)
    return _TITLES.get(event, event.replace("_", " ").title()), detail


def normalize(
    payload: object,
    *,
    source_default: str = "stack",
    events: Collection[str] = QUIET_EVENTS,
) -> StackNotification | None:
    """Normalize one *arr webhook payload, or None when it should not be forwarded.

    Returns None for the connection Test, unknown events, and events outside the policy.
    """
    if not isinstance(payload, dict):
        return None
    event = _EVENT_MAP.get(str(payload.get("eventType") or "").strip().lower())
    if event is None or event == "test" or event not in events:
        return None
    if event == "imported" and payload.get("isUpgrade") is True:
        event = "upgraded"
    source = (str(payload.get("instanceName") or "").strip().lower() or source_default)
    title, detail = _describe(event, payload)
    severity = "warning" if event in _WARNING_EVENTS else "info"
    if event == "health" and str(payload.get("level") or "").strip().lower() == "error":
        severity = "critical"
    return StackNotification(
        source=source,
        event=event,
        severity=severity,
        title=title,
        detail=(detail or "(no details)")[:MAX_DETAIL_CHARS],
    )


_COLORS = {"critical": "#d24b4b", "warning": "#e0a13b", "info": "#3a7bd5"}
_EMOJI = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


def render_mattermost(notification: StackNotification) -> dict:
    """A Mattermost incoming-webhook payload for one notification (same style as alerts)."""
    return {
        "attachments": [
            {
                "color": _COLORS.get(notification.severity, _COLORS["info"]),
                "title": f"{_EMOJI.get(notification.severity, '')} {notification.source}: {notification.title}",
                "text": notification.detail,
                "fields": [{"short": True, "title": "Event", "value": notification.event}],
            }
        ]
    }


class StackNotificationsService:
    """Ingest an *arr webhook: authorize by token, normalize, deliver to Mattermost.

    Framework-neutral — the Flask route is a thin adapter. Config and the webhook poster
    are injected. The token gates the endpoint (the webhook is otherwise unauthenticated,
    as *arr apps require); comparison is constant-time. The endpoint always answers 200 for
    a valid token so an *arr connection Test succeeds even when the event is suppressed.
    """

    def __init__(
        self,
        *,
        config_provider: Callable[[], Mapping],
        poster: Callable[[str, dict], None],
        config_writer: Callable[[Mapping], None] | None = None,
    ) -> None:
        self._config_provider = config_provider
        self._poster = poster
        self._config_writer = config_writer

    def status(self) -> dict:
        """Non-secret-except-to-the-authed-admin status for the integrations card.

        `token` is returned so the admin can build the ingest URL to paste into each *arr
        app; the GET route that calls this is authenticated.
        """
        config = self._config_provider() or {}
        return {
            "enabled": bool(config.get("enabled")),
            "configured": bool(config.get("webhook_url")),
            "mode": config.get("mode") or "quiet",
            "source_default": config.get("source_default") or "stack",
            "channel_name": config.get("channel_name") or None,
            "token": config.get("token") or None,
        }

    def set_mode(self, mode: str) -> tuple[dict, int]:
        """Switch the forwarding policy between 'quiet' and 'verbose'."""
        if mode not in {"quiet", "verbose"}:
            return {"error": "mode must be 'quiet' or 'verbose'"}, 400
        config = dict(self._config_provider() or {})
        if not config.get("webhook_url"):
            return {"error": "Stack notifications are not configured"}, 404
        if self._config_writer is None:  # pragma: no cover - always wired in app
            return {"error": "Configuration is read-only"}, 500
        config["mode"] = mode
        self._config_writer(config)
        return self.status(), 200

    def ingest(self, token: str, payload: object) -> tuple[dict, int]:
        config = self._config_provider() or {}
        if not config.get("enabled"):
            return {"error": "Stack notifications are not enabled"}, 404
        expected = str(config.get("token") or "")
        if not expected or not hmac.compare_digest(str(token or ""), expected):
            return {"error": "Unauthorized"}, 401
        events = VERBOSE_EVENTS if config.get("mode") == "verbose" else QUIET_EVENTS
        note = normalize(
            payload, source_default=str(config.get("source_default") or "stack"), events=events
        )
        if note is None:
            return {"status": "ignored"}, 200  # connection test or a suppressed event
        webhook_url = config.get("webhook_url")
        if webhook_url:
            try:
                self._poster(str(webhook_url), render_mattermost(note))
            except Exception:  # noqa: BLE001 - delivery is best-effort; don't fail the arr side
                return {"status": "delivery_failed", "event": note.event}, 200
        return {"status": "forwarded", "event": note.event}, 200
