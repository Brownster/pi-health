from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .api import MCPHTTPError
from .config import load_base_url, load_secret, load_timeout


class SabnzbdClientError(MCPHTTPError):
    ...


class SabnzbdClient:
    def __init__(
        self,
        *,
        base_env: str = "SABNZBD_BASE_URL",
        default_base: str = "http://sabnzbd:8080",
        api_key_env: str = "SABNZBD_API_KEY",
        timeout_env: str = "SABNZBD_HTTP_TIMEOUT",
        default_timeout: float = 10.0,
    ) -> None:
        self.base_url = load_base_url(base_env, default_base)
        api_key = load_secret(api_key_env)
        if not api_key:
            raise SabnzbdClientError("Missing SABnzbd API key")
        self.api_key = api_key
        self.timeout = load_timeout(timeout_env, default_timeout)

    def _call(self, mode: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}/api"
        try:
            response = httpx.get(
                url,
                params={
                    "mode": mode,
                    "apikey": self.api_key,
                    "output": "json",
                    **(params or {}),
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise SabnzbdClientError("Unexpected response payload")
            return data
        except httpx.HTTPError as exc:
            raise SabnzbdClientError(f"SABnzbd request failed: {exc}") from exc

    def status(self) -> Any:
        return self._call("qstatus")

    def queue(self) -> Any:
        return self._call("queue")

    def warnings(self) -> Any:
        return self._call("warnings")
