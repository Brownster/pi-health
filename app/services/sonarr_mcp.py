from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


SonarrMCPConfig = MCPClientConfig
SonarrMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[SonarrMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="SONARR_MCP_BASE_URL")


class SonarrMCPClient(MCPHTTPClient):
    def system_status(self) -> Any:
        return self.call_tool("get_system_status", {})

    def queue(self) -> Any:
        return self.call_tool("get_queue", {})

    def health(self) -> Any:
        return self.call_tool("get_health", {})

    def wanted_missing(self) -> Any:
        return self.call_tool("get_wanted_missing", {})


__all__ = [
    "SonarrMCPClient",
    "SonarrMCPConfig",
    "SonarrMCPError",
    "config_from_mapping",
]
