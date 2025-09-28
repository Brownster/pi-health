from __future__ import annotations

from typing import Any, Mapping, List

from .mcp import SystemStatsTool, BaseMCPTool
from app.services.system_stats import get_system_stats
from app.services.docker_mcp import DockerMCPClient, DockerMCPConfig
from app.services.sonarr_mcp import SonarrMCPClient, config_from_mapping as sonarr_config
from app.services.radarr_mcp import RadarrMCPClient, config_from_mapping as radarr_config
from app.services.lidarr_mcp import LidarrMCPClient, config_from_mapping as lidarr_config
from app.services.sabnzbd_mcp import SabnzbdMCPClient, config_from_mapping as sab_config
from app.services.jellyfin_mcp import JellyfinMCPClient, config_from_mapping as jellyfin_config
from app.services.jellyseerr_mcp import JellyseerrMCPClient, config_from_mapping as jellyseerr_config
from .tools.docker import DockerStatusTool, DockerActionTool
from .tools.sonarr import SonarrStatusTool
from .tools.radarr import RadarrStatusTool
from .tools.lidarr import LidarrStatusTool
from .tools.sabnzbd import SabnzbdStatusTool
from .tools.jellyfin import JellyfinStatusTool
from .tools.jellyseerr import JellyseerrStatusTool


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

    radarr_cfg = radarr_config(config)
    if radarr_cfg:
        tools.append(RadarrStatusTool(RadarrMCPClient(radarr_cfg)))

    lidarr_cfg = lidarr_config(config)
    if lidarr_cfg:
        tools.append(LidarrStatusTool(LidarrMCPClient(lidarr_cfg)))

    sab_cfg = sab_config(config)
    if sab_cfg:
        tools.append(SabnzbdStatusTool(SabnzbdMCPClient(sab_cfg)))

    jellyfin_cfg = jellyfin_config(config)
    if jellyfin_cfg:
        tools.append(JellyfinStatusTool(JellyfinMCPClient(jellyfin_cfg)))

    jellyseerr_cfg = jellyseerr_config(config)
    if jellyseerr_cfg:
        tools.append(JellyseerrStatusTool(JellyseerrMCPClient(jellyseerr_cfg)))

    return tools
