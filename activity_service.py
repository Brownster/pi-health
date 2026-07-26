"""Live media-service activity for the LimeOS dashboard.

Container CPU and memory say how hard the box is working; they do not say what
it is working *on*. This service answers that by asking the services themselves:
who is streaming from Jellyfin, what SABnzbd and Transmission are pulling down,
and which Servarr queues are stuck. Services are discovered from the container
inventory and their API keys are read from the config directories Docker already
mounts, so nothing needs configuring by hand.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone

from activity_credentials import (
    CredentialUnavailable,
    read_arr_api_key,
    read_jellyfin_api_key,
    read_sabnzbd_api_key,
)


DEFAULT_TTL_SECONDS = 8.0
DEFAULT_TIMEOUT_SECONDS = 4.0
MAX_WORKERS = 6
MAX_STREAMS = 12
MAX_DOWNLOADS = 12
MAX_QUEUES = 12
MAX_SERVICES = 24
TICKS_PER_SECOND = 10_000_000

# Transmission torrent status codes that mean "moving data right now".
TRANSMISSION_DOWNLOADING = 4
TRANSMISSION_SEEDING = 6


@dataclass(frozen=True)
class _Provider:
    family: str
    label: str
    default_port: int


# Matched against the container name first, then the image reference.
PROVIDERS: dict[str, _Provider] = {
    "jellyfin": _Provider("jellyfin", "Jellyfin", 8096),
    "emby": _Provider("jellyfin", "Emby", 8096),
    "sabnzbd": _Provider("sabnzbd", "SABnzbd", 8080),
    "transmission": _Provider("transmission", "Transmission", 9091),
    "sonarr": _Provider("arr", "Sonarr", 8989),
    "radarr": _Provider("arr", "Radarr", 7878),
    "lidarr": _Provider("arr", "Lidarr", 8686),
    "readarr": _Provider("arr", "Readarr", 8787),
}


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


def urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> HttpResponse:
    """Perform one loopback HTTP call, returning error responses rather than raising."""
    request = urllib.request.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback admin API
            return HttpResponse(response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as error:
        # Transmission answers the first call with 409 plus a session id header.
        return HttpResponse(error.code, dict(error.headers or {}), error.read())


@dataclass(frozen=True)
class _Target:
    container_id: str
    name: str
    label: str
    family: str
    port: int | None
    config_root: str | None


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _text(value, default: str = "", limit: int = 200) -> str:
    return (value.strip() if isinstance(value, str) else default)[:limit]


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _listing(value) -> list:
    return value if isinstance(value, list) else []


def _percent(part, whole) -> float | None:
    numerator = _finite(part)
    denominator = _finite(whole)
    if numerator is None or not denominator:
        return None
    return round(max(0.0, min(numerator / denominator * 100.0, 100.0)), 1)


def _match_provider(name: str, image: str) -> tuple[str, _Provider] | None:
    haystack_name = name.lower()
    haystack_image = image.lower()
    for token, provider in PROVIDERS.items():
        if token in haystack_name or token in haystack_image:
            return token, provider
    return None


def _resolve_port(ports, default_port: int) -> int | None:
    """Pick the host port that reaches this service, including via a VPN sidecar."""
    entries = [_mapping(port) for port in _listing(ports)]
    published = [item for item in entries if isinstance(item.get("host_port"), int)]
    for item in published:
        if item.get("container_port") == default_port:
            return item["host_port"]
    for item in published:
        if item.get("protocol") != "udp":
            return item["host_port"]
    return None


def _config_root(mounts) -> str | None:
    for mount in _listing(mounts):
        item = _mapping(mount)
        if _text(item.get("destination")) == "/config":
            source = _text(item.get("source"), limit=4096)
            return source or None
    return None


class ActivityService:
    """Collect a bounded, best-effort view of what the media stack is doing."""

    def __init__(
        self,
        *,
        container_provider: Callable[[], list[dict]],
        inspect_reader: Callable[[str], Mapping],
        transport: Callable[..., HttpResponse] = urllib_transport,
        credential_readers: Mapping[str, Callable[[str], str]] | None = None,
        host: str = "127.0.0.1",
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_workers: int = MAX_WORKERS,
    ) -> None:
        self._container_provider = container_provider
        self._inspect_reader = inspect_reader
        self._transport = transport
        self._credential_readers = dict(
            credential_readers
            or {
                "arr": read_arr_api_key,
                "sabnzbd": read_sabnzbd_api_key,
                "jellyfin": read_jellyfin_api_key,
            }
        )
        self._host = host
        self._ttl = max(0.0, float(ttl_seconds))
        self._timeout = max(0.5, float(timeout_seconds))
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_workers = max(1, int(max_workers))
        self._lock = threading.Lock()
        self._cached: dict | None = None
        self._cached_at: float | None = None

    # --- public ------------------------------------------------------------

    def snapshot(self) -> dict:
        """Return the current activity view, refreshing at most once per TTL."""
        with self._lock:
            cached, cached_at = self._cached, self._cached_at
        if cached is not None and cached_at is not None and (self._clock() - cached_at) <= self._ttl:
            return cached

        result = self._collect()
        with self._lock:
            self._cached = result
            self._cached_at = self._clock()
        return result

    # --- collection --------------------------------------------------------

    def _collect(self) -> dict:
        from concurrent.futures import ThreadPoolExecutor

        targets = self._discover()
        reports: list[dict] = []
        if targets:
            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(targets))) as pool:
                reports = list(pool.map(self._poll, targets))

        streams: list[dict] = []
        downloads: list[dict] = []
        queues: list[dict] = []
        services: list[dict] = []
        for report in reports:
            streams.extend(report.get("streams", []))
            downloads.extend(report.get("downloads", []))
            queues.extend(report.get("queues", []))
            services.append(report["service"])

        streams.sort(key=lambda item: (item.get("is_paused", False), item.get("title", "")))
        downloads.sort(key=lambda item: -(item.get("speed_bytes") or 0))
        queues.sort(key=lambda item: item.get("source", ""))
        services.sort(key=lambda item: item.get("name", ""))

        return {
            "collected_at": self._wall_clock().isoformat().replace("+00:00", "Z"),
            "streams": streams[:MAX_STREAMS],
            "downloads": downloads[:MAX_DOWNLOADS],
            "queues": queues[:MAX_QUEUES],
            "services": services[:MAX_SERVICES],
            "totals": {
                "streams": len(streams),
                "transcodes": sum(1 for item in streams if item.get("is_transcoding")),
                "downloads": len(downloads),
                "download_speed": round(
                    sum(item.get("speed_bytes") or 0 for item in downloads), 2
                ),
                "queued": sum(item.get("total") or 0 for item in queues),
                "queue_problems": sum(item.get("problems") or 0 for item in queues),
            },
        }

    def _discover(self) -> list[_Target]:
        try:
            containers = self._container_provider()
        except Exception:
            return []

        targets = []
        for container in _listing(containers):
            item = _mapping(container)
            if _text(item.get("status")) != "running":
                continue
            name = _text(item.get("name"))
            matched = _match_provider(name, _text(item.get("image")))
            if matched is None:
                continue
            _token, provider = matched
            container_id = _text(item.get("id"))
            targets.append(
                _Target(
                    container_id=container_id,
                    name=name,
                    label=provider.label,
                    family=provider.family,
                    port=_resolve_port(item.get("ports"), provider.default_port),
                    config_root=self._read_config_root(container_id),
                )
            )
        return targets

    def _read_config_root(self, container_id: str) -> str | None:
        if not container_id:
            return None
        try:
            return _config_root(_mapping(self._inspect_reader(container_id)).get("mounts"))
        except Exception:
            return None

    def _poll(self, target: _Target) -> dict:
        service = {
            "id": target.container_id,
            "name": target.name,
            "label": target.label,
            "family": target.family,
            "reachable": False,
            "detail": None,
        }
        if target.port is None:
            service["detail"] = "No reachable host port is published for this container"
            return {"service": service}

        try:
            handler = {
                "jellyfin": self._poll_jellyfin,
                "sabnzbd": self._poll_sabnzbd,
                "transmission": self._poll_transmission,
                "arr": self._poll_arr,
            }[target.family]
            result = handler(target)
        except CredentialUnavailable as error:
            service["detail"] = str(error)
            return {"service": service}
        except Exception as error:
            service["detail"] = f"{target.label} did not respond: {error}"
            return {"service": service}

        service["reachable"] = True
        return {**result, "service": service}

    # --- transport helpers -------------------------------------------------

    def _base_url(self, target: _Target) -> str:
        return f"http://{self._host}:{target.port}"

    def _json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ):
        response = self._transport(method, url, headers, body, self._timeout)
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")
        if not response.body:
            return None
        return json.loads(response.body.decode("utf-8", errors="replace"))

    def _credential(self, target: _Target) -> str:
        if not target.config_root:
            raise CredentialUnavailable(
                f"{target.label} has no /config mount, so its API key cannot be read"
            )
        reader = self._credential_readers.get(target.family)
        if reader is None:
            raise CredentialUnavailable(f"No credential reader for {target.family}")
        return reader(target.config_root)

    # --- per-service polling ----------------------------------------------

    def _poll_jellyfin(self, target: _Target) -> dict:
        token = self._credential(target)
        sessions = _listing(
            self._json(f"{self._base_url(target)}/Sessions", headers={"X-Emby-Token": token})
        )
        streams = []
        for entry in sessions:
            session = _mapping(entry)
            item = _mapping(session.get("NowPlayingItem"))
            if not item:
                continue
            play_state = _mapping(session.get("PlayState"))
            transcoding = _mapping(session.get("TranscodingInfo"))
            position = _finite(play_state.get("PositionTicks"))
            runtime = _finite(item.get("RunTimeTicks"))
            streams.append(
                {
                    "source": target.name,
                    "label": target.label,
                    "title": _text(item.get("Name"), "Unknown title"),
                    "subtitle": self._jellyfin_subtitle(item),
                    "user": _text(session.get("UserName")),
                    "client": _text(session.get("Client")),
                    "device": _text(session.get("DeviceName")),
                    "play_method": _text(play_state.get("PlayMethod")) or None,
                    "is_paused": bool(play_state.get("IsPaused")),
                    "is_transcoding": bool(transcoding)
                    or _text(play_state.get("PlayMethod")).lower() == "transcode",
                    "transcode_reason": ", ".join(
                        _text(reason) for reason in _listing(transcoding.get("TranscodeReasons"))
                    )
                    or None,
                    "bitrate": _finite(transcoding.get("Bitrate")),
                    "progress_percent": _percent(position, runtime),
                    "position_seconds": None if position is None else round(position / TICKS_PER_SECOND),
                    "duration_seconds": None if runtime is None else round(runtime / TICKS_PER_SECOND),
                }
            )
        return {"streams": streams}

    @staticmethod
    def _jellyfin_subtitle(item: Mapping) -> str:
        if _text(item.get("Type")) != "Episode":
            year = item.get("ProductionYear")
            return str(year) if isinstance(year, int) else ""
        series = _text(item.get("SeriesName"))
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        if isinstance(season, int) and isinstance(episode, int):
            return f"{series} · S{season:02d}E{episode:02d}".strip(" ·")
        return series

    def _poll_sabnzbd(self, target: _Target) -> dict:
        key = self._credential(target)
        payload = self._json(
            f"{self._base_url(target)}/api?mode=queue&output=json&limit={MAX_DOWNLOADS}&apikey={key}"
        )
        queue = _mapping(_mapping(payload).get("queue"))
        # SABnzbd reports its overall rate in kB/s as a string.
        overall_speed = _finite(_number(queue.get("kbpersec")))
        downloads = []
        for entry in _listing(queue.get("slots"))[:MAX_DOWNLOADS]:
            slot = _mapping(entry)
            megabytes_left = _finite(_number(slot.get("mbleft")))
            megabytes = _finite(_number(slot.get("mb")))
            downloads.append(
                {
                    "source": target.name,
                    "label": target.label,
                    "name": _text(slot.get("filename"), "Unknown item"),
                    "state": _text(slot.get("status"), "queued").lower(),
                    "progress_percent": _finite(_number(slot.get("percentage"))),
                    "size_bytes": None if megabytes is None else round(megabytes * 1024 * 1024),
                    "remaining_bytes": None
                    if megabytes_left is None
                    else round(megabytes_left * 1024 * 1024),
                    # Only the head of the queue is actually moving.
                    "speed_bytes": round((overall_speed or 0) * 1024, 2)
                    if _text(slot.get("status")).lower() == "downloading"
                    else 0.0,
                    "eta": _text(slot.get("timeleft")) or None,
                }
            )
        return {"downloads": downloads}

    def _poll_transmission(self, target: _Target) -> dict:
        url = f"{self._base_url(target)}/transmission/rpc"
        fields = ["name", "status", "rateDownload", "rateUpload", "percentDone", "eta", "totalSize"]
        body = json.dumps(
            {"method": "torrent-get", "arguments": {"fields": fields}}, separators=(",", ":")
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        response = self._transport("POST", url, headers, body, self._timeout)
        if response.status == 409:
            # Transmission's CSRF guard: retry once with the session id it just issued.
            session_id = response.headers.get("X-Transmission-Session-Id")
            if not session_id:
                raise RuntimeError("Transmission withheld a session id")
            response = self._transport(
                "POST", url, {**headers, "X-Transmission-Session-Id": session_id}, body, self._timeout
            )
        if response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}")

        payload = json.loads(response.body.decode("utf-8", errors="replace"))
        torrents = _listing(_mapping(_mapping(payload).get("arguments")).get("torrents"))
        downloads = []
        for entry in torrents:
            torrent = _mapping(entry)
            status = torrent.get("status")
            if status not in (TRANSMISSION_DOWNLOADING, TRANSMISSION_SEEDING):
                continue
            done = _finite(torrent.get("percentDone"))
            size = _finite(torrent.get("totalSize"))
            downloading = status == TRANSMISSION_DOWNLOADING
            rate = _finite(torrent.get("rateDownload" if downloading else "rateUpload")) or 0.0
            eta = _finite(torrent.get("eta"))
            downloads.append(
                {
                    "source": target.name,
                    "label": target.label,
                    "name": _text(torrent.get("name"), "Unknown torrent"),
                    "state": "downloading" if downloading else "seeding",
                    "progress_percent": None if done is None else round(done * 100, 1),
                    "size_bytes": None if size is None else round(size),
                    "remaining_bytes": None
                    if size is None or done is None
                    else round(size * (1 - done)),
                    "speed_bytes": rate,
                    "eta": None if eta is None or eta < 0 else _duration(int(eta)),
                }
            )
        return {"downloads": downloads}

    def _poll_arr(self, target: _Target) -> dict:
        key = self._credential(target)
        payload = _mapping(
            self._json(
                f"{self._base_url(target)}/api/v3/queue?pageSize={MAX_DOWNLOADS}",
                headers={"X-Api-Key": key},
            )
        )
        records = [_mapping(record) for record in _listing(payload.get("records"))]
        problems = sum(
            1
            for record in records
            if _text(record.get("trackedDownloadStatus")).lower() in {"warning", "error"}
            or _text(record.get("status")).lower() in {"warning", "failed", "error"}
        )
        return {
            "queues": [
                {
                    "source": target.name,
                    "label": target.label,
                    "total": int(_finite(payload.get("totalRecords")) or len(records)),
                    "problems": problems,
                    "items": [
                        {
                            "title": _text(record.get("title"), "Unknown item"),
                            "state": _text(record.get("trackedDownloadState"), "queued"),
                            "status": _text(record.get("status"), "unknown"),
                        }
                        for record in records[:3]
                    ],
                }
            ]
        }


def _number(value):
    """Coerce the numeric strings SABnzbd returns (``"12.5"``) into floats."""
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip() or "nan")
        except ValueError:
            return None
    return value


def _duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
