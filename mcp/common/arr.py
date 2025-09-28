from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .api import MCPHTTPError
from .config import load_base_url, load_secret, load_timeout


class ArrClientError(MCPHTTPError):
    ...


class ArrClient:
    """Simple wrapper around Sonarr/Radarr/Lidarr HTTP API."""

    def __init__(
        self,
        *,
        base_env: str,
        default_base: str,
        api_key_env: str,
        timeout_env: str = "ARR_HTTP_TIMEOUT",
        default_timeout: float = 10.0,
    ) -> None:
        self.base_url = load_base_url(base_env, default_base)
        api_key = load_secret(api_key_env)
        if not api_key:
            raise ArrClientError(f"Missing API key for {base_env} (set {api_key_env} or {api_key_env}_FILE)")
        self.headers = {"X-Api-Key": api_key}
        self.timeout = load_timeout(timeout_env, default_timeout)

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self.headers,
                params=params or {},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:  # pragma: no cover - passthrough
            raise ArrClientError(f"{method} {url} failed: {exc}") from exc

    def get(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post_command(self, payload: Dict[str, Any]) -> Any:
        url = f"{self.base_url}/command"
        try:
            response = httpx.post(url, headers=self.headers, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json() if response.text else {"status": "queued"}
        except httpx.HTTPError as exc:
            raise ArrClientError(f"POST {url} failed: {exc}") from exc
