from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urljoin

import requests


class MCPClientError(RuntimeError):
    """Raised when an MCP gateway responds with an error."""


@dataclass(frozen=True)
class MCPClientConfig:
    base_url: str
    read_timeout: float
    write_timeout: float

    @classmethod
    def from_mapping(
        cls,
        config: Mapping[str, Any],
        *,
        base_key: str,
        read_key: str = "MCP_READ_TIMEOUT",
        write_key: str = "MCP_WRITE_TIMEOUT",
        default_read: float = 5.0,
        default_write: float = 30.0,
    ) -> Optional["MCPClientConfig"]:
        base_url = (config.get(base_key) or "").strip()
        if not base_url:
            return None
        read_timeout = float(config.get(read_key, default_read) or default_read)
        write_timeout = float(config.get(write_key, default_write) or default_write)
        return cls(base_url=base_url, read_timeout=read_timeout, write_timeout=write_timeout)


class MCPHTTPClient:
    """Shared HTTP helper for calling MCP tools."""

    def __init__(self, config: MCPClientConfig) -> None:
        self._config = config

    @property
    def config(self) -> MCPClientConfig:
        return self._config

    def call_tool(
        self,
        tool_name: str,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        mutating: bool = False,
    ) -> Any:
        timeout = self._config.write_timeout if mutating else self._config.read_timeout
        url = urljoin(self._config.base_url.rstrip('/') + '/', f"tools/{tool_name}")
        request_payload = payload or {}
        if mutating:
            request_payload = dict(request_payload)
            request_payload.setdefault("approved", True)

        try:
            response = requests.post(url, json=request_payload, timeout=timeout)
        except requests.RequestException as exc:
            raise MCPClientError(f"Failed to reach MCP tool '{tool_name}': {exc}") from exc

        if response.status_code >= 400:
            snippet = response.text[:200]
            raise MCPClientError(
                f"MCP tool '{tool_name}' responded with {response.status_code}: {snippet}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise MCPClientError(f"MCP tool '{tool_name}' returned invalid JSON") from exc


__all__ = [
    "MCPClientError",
    "MCPClientConfig",
    "MCPHTTPClient",
]
