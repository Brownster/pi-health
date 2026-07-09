"""Minimal Servarr API client used by the media seed engine."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from typing import Any


class ArrClientError(RuntimeError):
    """Raised when a Servarr API call fails."""


HttpTransport = Callable[[str, str, Mapping[str, str], bytes | None], Any]


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None):
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - local admin API
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ArrClientError(f"{method} {url} failed: {exc.code} {detail}") from exc
    except OSError as exc:
        raise ArrClientError(f"{method} {url} failed: {exc}") from exc
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ArrClientError(f"{method} {url} returned invalid JSON") from exc


def read_api_key(config_xml: str) -> str:
    """Read a Servarr API key from a ``config.xml`` file."""
    try:
        root = ET.parse(config_xml).getroot()  # noqa: S314 - local config file
    except (OSError, ET.ParseError) as exc:
        raise ArrClientError(f"Unable to read API key from {config_xml}: {exc}") from exc
    value = root.findtext("ApiKey")
    if not value:
        raise ArrClientError(f"API key missing in {config_xml}")
    return value


class ArrClient:
    """Small wrapper over the Servarr v3 REST API.

    The methods intentionally expose only the operations the seed engine needs.
    Tests inject a fake transport or a fake client, so no network is required.
    """

    def __init__(
        self,
        *,
        port: int,
        api_key: str,
        host: str = "127.0.0.1",
        transport: HttpTransport = urllib_transport,
    ) -> None:
        self._base_url = f"http://{host}:{port}/api/v3"
        self._headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._transport = transport

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def put(self, path: str, payload: Mapping[str, Any]) -> Any:
        return self._request("PUT", path, payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def list_root_folders(self) -> list[dict]:
        return _as_list(self.get("/rootfolder"))

    def add_root_folder(self, path: str) -> Any:
        return self.post("/rootfolder", {"path": path})

    def delete_root_folder(self, root_folder_id: int | str) -> Any:
        return self.delete(f"/rootfolder/{root_folder_id}")

    def list_download_clients(self) -> list[dict]:
        return _as_list(self.get("/downloadclient"))

    def add_download_client(self, client: Mapping[str, Any]) -> Any:
        return self.post("/downloadclient", client)

    def list_applications(self) -> list[dict]:
        return _as_list(self.get("/applications"))

    def add_application(self, application: Mapping[str, Any]) -> Any:
        return self.post("/applications", application)

    def set_quality_profile_default(self, profile_name: str) -> Any:
        profiles = _as_list(self.get("/qualityprofile"))
        for profile in profiles:
            if profile.get("name") == profile_name:
                return profile
        return None

    def set_naming(self, preset: str) -> Any:
        current = _as_dict(self.get("/config/naming"))
        current["renameEpisodes"] = preset == "standard"
        current["replaceIllegalCharacters"] = True
        return self.put("/config/naming", current)

    def set_media_management(
        self,
        *,
        import_mode: str | None = None,
        recycle_bin: str | None = None,
        completed_download_handling: bool | None = None,
    ) -> Any:
        current = _as_dict(self.get("/config/mediamanagement"))
        if import_mode:
            current["useHardlinks"] = import_mode != "move"
        if recycle_bin:
            current["recycleBin"] = recycle_bin
        if completed_download_handling is not None:
            current["enableCompletedDownloadHandling"] = completed_download_handling
        return self.put("/config/mediamanagement", current)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        normalized = path if path.startswith("/") else f"/{path}"
        return self._transport(method, f"{self._base_url}{normalized}", self._headers, body)


def _as_list(value: Any) -> list[dict]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}
