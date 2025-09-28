from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


JellyfinMCPConfig = MCPClientConfig
JellyfinMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[JellyfinMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="JELLYFIN_MCP_BASE_URL")


class JellyfinMCPClient(MCPHTTPClient):
    def system_info(self) -> Any:
        return self.call_tool("get_system_info", {})

    def libraries(self) -> Any:
        return self.call_tool("get_libraries", {})

    def sessions(self) -> Any:
        return self.call_tool("get_sessions", {})

    def scheduled_tasks(self) -> Any:
        return self.call_tool("get_scheduled_tasks", {})


__all__ = [
    "JellyfinMCPClient",
    "JellyfinMCPConfig",
    "JellyfinMCPError",
    "config_from_mapping",
]
