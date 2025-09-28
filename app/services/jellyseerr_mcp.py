from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


JellyseerrMCPConfig = MCPClientConfig
JellyseerrMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[JellyseerrMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="JELLYSEERR_MCP_BASE_URL")


class JellyseerrMCPClient(MCPHTTPClient):
    def status(self) -> Any:
        return self.call_tool("get_status", {})

    def requests(self) -> Any:
        return self.call_tool("get_requests", {})


__all__ = [
    "JellyseerrMCPClient",
    "JellyseerrMCPConfig",
    "JellyseerrMCPError",
    "config_from_mapping",
]
