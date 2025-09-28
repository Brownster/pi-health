from __future__ import annotations

from typing import Any, Mapping, List

from .mcp import SystemStatsTool, BaseMCPTool
from app.services.system_stats import get_system_stats
from app.services.docker_mcp import DockerMCPClient, DockerMCPConfig
from app.services.sonarr_mcp import SonarrMCPClient, config_from_mapping as sonarr_config
from app.services.sabnzbd_mcp import SabnzbdMCPClient, config_from_mapping as sab_config
from .tools.docker import DockerStatusTool, DockerActionTool
from .tools.sonarr import SonarrStatusTool
from .tools.sabnzbd import SabnzbdStatusTool


def build_tools(config: Mapping[str, Any] | None = None) -> List[BaseMCPTool]:
    tools: List[BaseMCPTool] = [SystemStatsTool(get_system_stats)]

    if not config:
        return tools

    docker_config = DockerMCPConfig.from_mapping(config)
    if docker_config:
        docker_client = DockerMCPClient(docker_config)
        tools.append(DockerStatusTool(docker_client))
        tools.append(DockerActionTool(docker_client))

    sonarr_cfg = sonarr_config(config)
    if sonarr_cfg:
        tools.append(SonarrStatusTool(SonarrMCPClient(sonarr_cfg)))

    sab_cfg = sab_config(config)
    if sab_cfg:
        tools.append(SabnzbdStatusTool(SabnzbdMCPClient(sab_cfg)))

    return tools
