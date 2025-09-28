from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .mcp_client import MCPClientConfig, MCPClientError, MCPHTTPClient


class DockerMCPError(MCPClientError):
    """Namespace-specific error for Docker MCP interactions."""


@dataclass(frozen=True)
class DockerMCPConfig(MCPClientConfig):
    compose_file: Optional[str] = None

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> Optional["DockerMCPConfig"]:
        base_config = MCPClientConfig.from_mapping(config, base_key="DOCKER_MCP_BASE_URL")
        if not base_config:
            return None
        compose_file = (config.get("DOCKER_MCP_COMPOSE_FILE") or "").strip() or None
        return cls(
            base_url=base_config.base_url,
            read_timeout=base_config.read_timeout,
            write_timeout=base_config.write_timeout,
            compose_file=compose_file,
        )


class DockerMCPClient(MCPHTTPClient):
    """Lightweight helper for Docker MCP read-only tooling."""

    def __init__(self, config: DockerMCPConfig) -> None:
        super().__init__(config)
        self._compose_file = config.compose_file

    def docker_ps(self) -> Any:
        try:
            return self.call_tool("docker_ps", {})
        except MCPClientError as exc:
            raise DockerMCPError(str(exc)) from exc

    def compose_ps(self) -> Any:
        payload: dict[str, Any] = {}
        if self._compose_file:
            payload["file"] = self._compose_file
        try:
            return self.call_tool("compose_ps", payload)
        except MCPClientError as exc:
            raise DockerMCPError(str(exc)) from exc

    def compose_restart(self, service: str) -> Any:
        payload: dict[str, Any] = {"service": service}
        if self._compose_file:
            payload["file"] = self._compose_file
        try:
            return self.call_tool("compose_restart", payload, mutating=True)
        except MCPClientError as exc:
            raise DockerMCPError(str(exc)) from exc

    def compose_start(self, service: str) -> Any:
        payload: dict[str, Any] = {"service": service}
        if self._compose_file:
            payload["file"] = self._compose_file
        try:
            return self.call_tool("compose_start", payload, mutating=True)
        except MCPClientError as exc:
            raise DockerMCPError(str(exc)) from exc

    def compose_stop(self, service: str) -> Any:
        payload: dict[str, Any] = {"service": service}
        if self._compose_file:
            payload["file"] = self._compose_file
        try:
            return self.call_tool("compose_stop", payload, mutating=True)
        except MCPClientError as exc:
            raise DockerMCPError(str(exc)) from exc


__all__ = [
    "DockerMCPClient",
    "DockerMCPConfig",
    "DockerMCPError",
]
