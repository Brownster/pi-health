from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


LidarrMCPConfig = MCPClientConfig
LidarrMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[LidarrMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="LIDARR_MCP_BASE_URL")


class LidarrMCPClient(MCPHTTPClient):
    def system_status(self) -> Any:
        return self.call_tool("get_system_status", {})

    def queue(self) -> Any:
        return self.call_tool("get_queue", {})

    def health(self) -> Any:
        return self.call_tool("get_health", {})

    def wanted_missing(self) -> Any:
        return self.call_tool("get_wanted_missing", {})


__all__ = [
    "LidarrMCPClient",
    "LidarrMCPConfig",
    "LidarrMCPError",
    "config_from_mapping",
]
