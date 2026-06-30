"""Framework-neutral Docker container inventory service."""

from __future__ import annotations

from collections.abc import Callable

from container_helpers import (
    analyze_network_topology,
    get_container_ports_cached,
    get_container_web_metadata,
    inherit_ports_from_network_service,
)
from ports import DockerPort


_DEFAULT_NETWORK = {
    "mode": "",
    "role": "standalone",
    "provider": None,
    "status": "ok",
}


class ContainerInventoryService:
    """Build the container read model from an injected Docker adapter."""

    def __init__(
        self,
        *,
        docker: DockerPort,
        stats_reader: Callable[[str], dict | None],
        update_reader: Callable[[str], bool],
    ):
        self._docker = docker
        self._stats_reader = stats_reader
        self._update_reader = update_reader

    def list_containers(self, *, include_stats: bool = True) -> list[dict]:
        if not self._docker.available:
            return [self._unavailable_result()]

        try:
            containers = self._docker.list_containers(all=True)
            containers_by_name = {container.name: container for container in containers}
            network_topology, _network_groups = analyze_network_topology(containers)
            port_cache: dict[str, list[dict]] = {}
            return [
                self._container_data(
                    container,
                    containers_by_name=containers_by_name,
                    network_topology=network_topology,
                    port_cache=port_cache,
                    include_stats=include_stats,
                )
                for container in containers
            ]
        except Exception as exc:
            print(f"Error listing containers: {exc}")
            message = str(exc)
            return [
                {
                    "id": "error-listing",
                    "name": "Error Listing Containers",
                    "status": "error",
                    "image": message[:30] + "..." if len(message) > 30 else message,
                    "ports": [],
                }
            ]

    def _container_data(
        self,
        container,
        *,
        containers_by_name: dict,
        network_topology: dict,
        port_cache: dict,
        include_stats: bool,
    ) -> dict:
        ports = self._ports(container, containers_by_name, port_cache)
        stats = None
        if include_stats and container.status == "running":
            stats = self._stats_reader(container.id)

        data = {
            "id": container.id[:12],
            "name": container.name,
            "status": container.status,
            "image": container.image.tags[0] if container.image.tags else "unknown",
            "update_available": self._update_reader(container.id[:12]),
            "ports": ports,
            "health": self._health(container),
            "exit_code": (container.attrs.get("State") or {}).get("ExitCode")
            if container.status in ("exited", "dead")
            else None,
            "network": network_topology.get(container.id, _DEFAULT_NETWORK.copy()),
            "cpu_percent": None,
            "memory_percent": None,
            "memory_used": None,
            "memory_limit": None,
            "net_rx": None,
            "net_tx": None,
            **get_container_web_metadata(container),
        }
        if stats:
            data["cpu_percent"] = stats.get("cpu_percent")
            memory = stats.get("memory", {})
            data["memory_percent"] = memory.get("percent")
            data["memory_used"] = memory.get("used")
            data["memory_limit"] = memory.get("limit")
            network = stats.get("network", {})
            data["net_rx"] = network.get("rx")
            data["net_tx"] = network.get("tx")
        return data

    def _ports(self, container, containers_by_name: dict, port_cache: dict) -> list[dict]:
        try:
            ports = [dict(port) for port in get_container_ports_cached(container, port_cache)]
            if ports:
                return ports
            return inherit_ports_from_network_service(
                container,
                containers_by_name,
                port_cache,
                container_lookup=self._docker.get_container,
            )
        except Exception:
            return []

    @staticmethod
    def _health(container) -> str | None:
        try:
            return ((container.attrs.get("State") or {}).get("Health") or {}).get("Status")
        except Exception:
            return None

    @staticmethod
    def _unavailable_result() -> dict:
        return {
            "id": "docker-not-available",
            "name": "Docker Not Available",
            "status": "unavailable",
            "image": "N/A",
            "ports": [],
        }
