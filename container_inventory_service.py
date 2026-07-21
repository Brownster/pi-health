"""Framework-neutral Docker container inventory service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

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


class ContainerInspectUnavailableError(Exception):
    """Raised when Docker is unavailable for an inspect request."""


class ContainerInspectNotFoundError(Exception):
    """Raised when the requested container does not exist."""


class ContainerInspectError(Exception):
    """Raised when Docker cannot inspect a container."""


class ContainerInventoryService:
    """Build the container read model from an injected Docker adapter."""

    def __init__(
        self,
        *,
        docker: DockerPort,
        stats_reader: Callable[[str], dict | None],
        update_reader: Callable[[str], bool],
        now_provider: Callable[[], datetime] | None = None,
    ):
        self._docker = docker
        self._stats_reader = stats_reader
        self._update_reader = update_reader
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

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

        # Prefer the configured image reference so a container running a superseded
        # (now dangling, tag-less) image still shows its real name rather than "unknown".
        config = (container.attrs or {}).get("Config") or {}
        image_tags = list(getattr(container.image, "tags", None) or [])
        data = {
            "id": container.id[:12],
            "name": container.name,
            "status": container.status,
            "image": config.get("Image") or (image_tags[0] if image_tags else "unknown"),
            "stack": self._stack(container),
            "update_available": self._update_reader(container.id[:12]),
            "ports": ports,
            "health": self._health(container),
            "restart_policy": self._restart_policy(container),
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

    def inspect(self, container_id: str, *, include_env_values: bool = False) -> dict:
        """Return operational container details, hiding environment values by default."""
        if not self._docker.available:
            raise ContainerInspectUnavailableError("Docker is not available")
        try:
            container = self._docker.get_container(container_id)
        except (KeyError, LookupError) as exc:
            raise ContainerInspectNotFoundError(f"Container not found: {container_id}") from exc
        except Exception as exc:
            if exc.__class__.__name__ == "NotFound":
                raise ContainerInspectNotFoundError(
                    f"Container not found: {container_id}"
                ) from exc
            raise ContainerInspectError(str(exc)) from exc

        attrs = container.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        host_config = attrs.get("HostConfig") or {}
        # container.image is a lazy property that resolves the image via the Docker API; it
        # raises if the image was removed (e.g. `docker rmi` while the container is stopped).
        # Degrade gracefully to the image reference held in the container's own attrs.
        try:
            image = container.image
        except Exception:
            image = None
        image_tags = list(getattr(image, "tags", []) or [])
        image_attrs = getattr(image, "attrs", {}) or {}
        started_at = state.get("StartedAt") or None
        return {
            "id": container.id,
            "name": container.name,
            "status": container.status,
            "health": ((state.get("Health") or {}).get("Status")) or None,
            "stack": self._stack(container),
            "image": config.get("Image")
            or (image_tags[0] if image_tags else "unknown"),
            "image_id": getattr(image, "id", None),
            "image_tags": image_tags,
            "image_digests": list(image_attrs.get("RepoDigests") or []),
            "created": attrs.get("Created") or None,
            "started_at": started_at,
            "uptime_seconds": self._uptime_seconds(started_at, state.get("Running")),
            "restart_policy": dict(host_config.get("RestartPolicy") or {}),
            "mounts": [self._mount(item) for item in attrs.get("Mounts") or []],
            "networks": self._networks(attrs),
            "command": list(config.get("Cmd") or []),
            "environment": self._environment(
                config.get("Env") or [], include_values=include_env_values
            ),
        }

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
    def _restart_policy(container) -> str:
        try:
            return str(
                ((container.attrs.get("HostConfig") or {}).get("RestartPolicy") or {}).get(
                    "Name"
                )
                or "no"
            )
        except Exception:
            return "no"

    @staticmethod
    def _stack(container) -> str | None:
        labels = (container.attrs.get("Config") or {}).get("Labels") or {}
        return labels.get("com.docker.compose.project") or None

    @staticmethod
    def _mount(item: dict) -> dict:
        return {
            "type": item.get("Type"),
            "source": item.get("Source"),
            "destination": item.get("Destination"),
            "mode": item.get("Mode") or ("rw" if item.get("RW") else "ro"),
            "rw": bool(item.get("RW")),
        }

    @staticmethod
    def _networks(attrs: dict) -> list[dict]:
        networks = ((attrs.get("NetworkSettings") or {}).get("Networks") or {})
        return [
            {
                "name": name,
                "ip_address": details.get("IPAddress") or None,
                "gateway": details.get("Gateway") or None,
                "mac_address": details.get("MacAddress") or None,
                "aliases": list(details.get("Aliases") or []),
            }
            for name, details in networks.items()
        ]

    @staticmethod
    def _environment(entries: list[str], *, include_values: bool) -> list[dict]:
        result = []
        for entry in entries:
            key, separator, value = entry.partition("=")
            item = {"key": key}
            if include_values:
                item["value"] = value if separator else ""
            result.append(item)
        return result

    def _uptime_seconds(self, started_at: str | None, running: bool | None) -> int | None:
        if not started_at or running is not True:
            return None
        try:
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            return max(0, int((self._now_provider() - started).total_seconds()))
        except (TypeError, ValueError):
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
