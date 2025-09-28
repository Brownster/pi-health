from __future__ import annotations

from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


SabnzbdMCPConfig = MCPClientConfig
SabnzbdMCPError = MCPClientError


def config_from_mapping(config: Mapping[str, Any]) -> Optional[SabnzbdMCPConfig]:
    return MCPClientConfig.from_mapping(config, base_key="SABNZBD_MCP_BASE_URL")


class SabnzbdMCPClient(MCPHTTPClient):
    def status(self) -> Any:
        return self.call_tool("get_status", {})

    def queue(self) -> Any:
        return self.call_tool("get_queue", {})

    def warnings(self) -> Any:
        return self.call_tool("get_warnings", {})


__all__ = [
    "SabnzbdMCPClient",
    "SabnzbdMCPConfig",
    "SabnzbdMCPError",
    "config_from_mapping",
]
