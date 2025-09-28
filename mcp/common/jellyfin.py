from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .api import MCPHTTPError
from .config import load_base_url, load_secret, load_timeout


class JellyfinClientError(MCPHTTPError):
    ...


class JellyfinClient:
    def __init__(
        self,
        *,
        base_env: str = "JELLYFIN_BASE_URL",
        default_base: str = "http://jellyfin:8096",
        api_key_env: str = "JELLYFIN_API_KEY",
        user_id_env: str = "JELLYFIN_USER_ID",
        timeout_env: str = "JELLYFIN_HTTP_TIMEOUT",
        default_timeout: float = 15.0,
    ) -> None:
        self.base_url = load_base_url(base_env, default_base)
        api_key = load_secret(api_key_env)
        if not api_key:
            raise JellyfinClientError("Missing Jellyfin API key")
        self.headers = {
            "X-Emby-Token": api_key,
            "X-MediaBrowser-Token": api_key,
            "Content-Type": "application/json",
        }
        self.user_id = load_secret(user_id_env)
        if not self.user_id:
            raise JellyfinClientError("Missing Jellyfin user id")
        self.timeout = load_timeout(timeout_env, default_timeout)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = httpx.get(url, headers=self.headers, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
        except httpx.HTTPError as exc:
            raise JellyfinClientError(f"GET {path} failed: {exc}") from exc

    def system_info(self) -> Any:
        return self._get("System/Info")

    def libraries(self) -> Any:
        return self._get(f"Users/{self.user_id}/Views")

    def sessions(self) -> Any:
        return self._get("Sessions")

    def scheduled_tasks(self) -> Any:
        return self._get("ScheduledTasks")
