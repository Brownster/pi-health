"""Framework-neutral VPN network-group discovery and recreation."""

from __future__ import annotations

from container_helpers import _compose_label, analyze_network_topology
from network_diagnostics_service import DockerUnavailableError, get_container_health
from ports import DockerPort


class NetworkGroupService:
    def __init__(
        self,
        *,
        docker: DockerPort,
        command_runner,
        host_ip_reader,
        container_ip_reader,
    ):
        self._docker = docker
        self._command_runner = command_runner
        self._host_ip_reader = host_ip_reader
        self._container_ip_reader = container_ip_reader

    def list_groups(self, *, probe: bool = False) -> dict:
        if not self._docker.available:
            return {"docker_available": False, "groups": [], "orphans": []}
        try:
            containers = self._docker.list_containers(all=True)
        except Exception as exc:
            return {
                "docker_available": True,
                "error": str(exc),
                "groups": [],
                "orphans": [],
            }

        info, groups = analyze_network_topology(containers)
        by_id = {container.id: container for container in containers}
        by_name = {container.name: container for container in containers}
        host_ip = self._host_ip_reader() if probe else None

        group_list = []
        for provider_name, group_info in groups.items():
            provider = by_name.get(provider_name)
            orphaned = sorted(group_info["orphaned"])
            group = {
                "provider": provider_name,
                "provider_id": provider.id[:12] if provider else None,
                "provider_status": provider.status if provider else "missing",
                "provider_health": get_container_health(provider) if provider else None,
                "members": sorted(group_info["members"]),
                "member_count": len(group_info["members"]),
                "orphaned_members": orphaned,
                "status": "ok",
            }
            if orphaned or provider is None or provider.status != "running":
                group["status"] = "degraded"
            elif group["provider_health"] == "unhealthy":
                group["status"] = "provider_unhealthy"

            if probe and provider is not None and provider.status == "running":
                provider_ip = self._container_ip_reader(provider)
                group["provider_public_ip"] = provider_ip
                group["host_public_ip"] = host_ip
                group["vpn_leak"] = bool(
                    provider_ip and host_ip and provider_ip == host_ip
                )
            group_list.append(group)

        orphans = [
            {
                "name": by_id[container_id].name,
                "id": by_id[container_id].id[:12],
                "status": by_id[container_id].status,
                "provider": entry.get("provider"),
            }
            for container_id, entry in info.items()
            if entry.get("status") == "orphaned" and container_id in by_id
        ]
        group_list.sort(key=lambda group: group["provider"] or "")
        orphans.sort(key=lambda orphan: orphan["name"])
        return {"docker_available": True, "groups": group_list, "orphans": orphans}

    def recreate(self, provider_name: str) -> dict:
        if not self._docker.available:
            raise DockerUnavailableError("Docker is not available")
        try:
            provider = self._docker.get_container(provider_name)
        except Exception as exc:
            return {
                "error": f"Provider container '{provider_name}' not found: {exc}"
            }

        config_files = _compose_label(
            provider, "com.docker.compose.project.config_files"
        )
        working_dir = _compose_label(
            provider, "com.docker.compose.project.working_dir"
        )
        if not config_files or not working_dir:
            return {
                "error": (
                    "Provider is not managed by docker compose; "
                    "cannot safely recreate the group."
                )
            }

        try:
            containers = self._docker.list_containers(all=True)
        except Exception as exc:
            return {"error": str(exc)}
        by_name = {container.name: container for container in containers}
        _, groups = analyze_network_topology(containers)
        member_names = sorted(groups.get(provider_name, {}).get("members", set()))

        ordered_services = []
        seen = set()
        for name in [provider_name, *member_names]:
            container = by_name.get(name)
            service = (
                _compose_label(container, "com.docker.compose.service")
                if container
                else None
            )
            service = service or name
            if service not in seen:
                seen.add(service)
                ordered_services.append(service)

        command = ["docker", "compose"]
        for path in config_files.split(","):
            path = path.strip()
            if path:
                command += ["-f", path]
        command += [
            "--project-directory",
            working_dir,
            "up",
            "-d",
            *ordered_services,
        ]
        try:
            result = self._command_runner(
                command, capture_output=True, text=True, timeout=180
            )
        except Exception as exc:
            return {"error": str(exc)}

        return {
            "status": "recreated" if result.returncode == 0 else "error",
            "provider": provider_name,
            "services": ordered_services,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-2000:],
            "stderr": (result.stderr or "")[-2000:],
        }
