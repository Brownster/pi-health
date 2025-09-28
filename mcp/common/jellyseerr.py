from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .api import MCPHTTPError
from .config import load_base_url, load_secret, load_timeout


class JellyseerrClientError(MCPHTTPError):
    ...


class JellyseerrClient:
    def __init__(
        self,
        *,
        base_env: str = "JELLYSEERR_BASE_URL",
        default_base: str = "http://jellyseerr:5055",
        api_key_env: str = "JELLYSEERR_API_KEY",
        timeout_env: str = "JELLYSEERR_HTTP_TIMEOUT",
        default_timeout: float = 10.0,
    ) -> None:
        self.base_url = load_base_url(base_env, default_base)
        api_key = load_secret(api_key_env)
        if not api_key:
            raise JellyseerrClientError("Missing Jellyseerr API key")
        self.headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
        self.timeout = load_timeout(timeout_env, default_timeout)

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(method, url, headers=self.headers, params=params or {}, timeout=self.timeout)
            response.raise_for_status()
            return response.json() if response.text else {}
        except httpx.HTTPError as exc:
            raise JellyseerrClientError(f"{method} {path} failed: {exc}") from exc

    def status(self) -> Any:
        return self._request("GET", "/api/v1/status")

    def requests(self) -> Any:
        return self._request("GET", "/api/v1/request")
