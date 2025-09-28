from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


RadarrMCPConfig = MCPClientConfig
RadarrMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[RadarrMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="RADARR_MCP_BASE_URL")


class RadarrMCPClient(MCPHTTPClient):
    def system_status(self) -> Any:
        return self.call_tool("get_system_status", {})

    def queue(self) -> Any:
        return self.call_tool("get_queue", {})

    def health(self) -> Any:
        return self.call_tool("get_health", {})

    def wanted_missing(self) -> Any:
        return self.call_tool("get_wanted_missing", {})

    def search_movie(self, movie_id: int) -> Any:
        payload = {"movie_id": movie_id}
        return self.call_tool("search_movie", payload, mutating=True)


__all__ = [
    "RadarrMCPClient",
    "RadarrMCPConfig",
    "RadarrMCPError",
    "config_from_mapping",
]
