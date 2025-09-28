from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.docker_mcp import DockerMCPClient, DockerMCPError

from ..mcp import BaseMCPTool


class DockerStatusTool(BaseMCPTool):
    """Surface Docker/Compose status from the Docker MCP gateway."""

    tool_id = "docker_status"

    def __init__(self, client: DockerMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = ["docker", "container", "compose", "stack", "service"]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        errors: List[str] = []
        compose_data: Optional[Any]
        container_data: Optional[Any]

        try:
            compose_data = self._client.compose_ps()
        except DockerMCPError as exc:
            errors.append(str(exc))
            compose_data = None

        try:
            container_data = self._client.docker_ps()
        except DockerMCPError as exc:
            errors.append(str(exc))
            container_data = None

        return {
            "tool": self.tool_id,
            "compose": compose_data,
            "containers": container_data,
            "errors": errors,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        errors: List[str] = payload.get("errors", []) or []
        if errors:
            return "; ".join(errors)

        compose_summary = self._summarise_compose(payload.get("compose"))
        container_summary = self._summarise_containers(payload.get("containers"))

        parts = [piece for piece in [compose_summary, container_summary] if piece]
        return " | ".join(parts) if parts else "Docker MCP returned no data"

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        containers = self._extract_containers(payload.get("containers"))
        unhealthy = [c for c in containers if _is_unhealthy(c)]
        if not unhealthy:
            return {}
        names = ", ".join(_container_name(c) for c in unhealthy)
        return {"container_alert": names}

    @staticmethod
    def _summarise_compose(data: Any) -> str:
        services = DockerStatusTool._extract_services(data)
        if not services:
            return ""
        running = [svc for svc in services if _is_running(svc)]
        unhealthy = [svc for svc in services if not _is_running(svc)]
        summary = f"Compose services: {len(running)}/{len(services)} running"
        if unhealthy:
            names = ", ".join(_service_name(service) for service in unhealthy)
            summary += f" (attention: {names})"
        return summary

    @staticmethod
    def _summarise_containers(data: Any) -> str:
        containers = DockerStatusTool._extract_containers(data)
        if not containers:
            return ""
        labels = [f"{_container_name(c)} ({_container_status(c)})" for c in containers[:8]]
        summary = f"Containers: {', '.join(labels)}"
        if len(containers) > len(labels):
            summary += f" … +{len(containers) - len(labels)} more"
        return summary

    @staticmethod
    def _extract_services(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            if isinstance(data.get("services"), list):
                return [svc for svc in data["services"] if isinstance(svc, dict)]
            if isinstance(data.get("containers"), list):  # some implementations reuse key
                return [svc for svc in data["containers"] if isinstance(svc, dict)]
        if isinstance(data, list):
            return [svc for svc in data if isinstance(svc, dict)]
        return []

    @staticmethod
    def _extract_containers(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            if isinstance(data.get("containers"), list):
                return [c for c in data["containers"] if isinstance(c, dict)]
            if isinstance(data.get("data"), list):
                return [c for c in data["data"] if isinstance(c, dict)]
        if isinstance(data, list):
            return [c for c in data if isinstance(c, dict)]
        return []


def _is_running(record: Dict[str, Any]) -> bool:
    state = str(record.get("state") or record.get("status") or "").lower()
    if not state:
        return False
    return state.startswith("running") or state.startswith("up")


def _is_unhealthy(record: Dict[str, Any]) -> bool:
    return not _is_running(record)


def _container_name(container: Dict[str, Any]) -> str:
    return str(
        container.get("name")
        or container.get("Names")
        or container.get("container")
        or container.get("id")
        or "unknown"
    )


def _container_status(container: Dict[str, Any]) -> str:
    return str(container.get("status") or container.get("State") or "unknown")


def _service_name(service: Dict[str, Any]) -> str:
    return str(service.get("name") or service.get("service") or service.get("id") or "unknown")


class DockerActionTool(BaseMCPTool):
    """Expose mutating Docker actions via the MCP gateway."""

    tool_id = "docker_actions"

    def __init__(self, client: DockerMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        return False

    def collect(self, message: str) -> Dict[str, Any]:  # pragma: no cover - not used for prompt context
        return {}

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:  # pragma: no cover - not used for prompt context
        return ""

    def restart_container(self, container_name: str) -> Dict[str, Any]:
        if not container_name:
            raise ValueError("container_name is required")
        try:
            result = self._client.compose_restart(container_name)
        except DockerMCPError as exc:
            return {"action": "restart", "container": container_name, "error": str(exc)}
        return {"action": "restart", "container": container_name, "result": result}

    def start_container(self, container_name: str) -> Dict[str, Any]:
        if not container_name:
            raise ValueError("container_name is required")
        try:
            result = self._client.compose_start(container_name)
        except DockerMCPError as exc:
            return {"action": "start", "container": container_name, "error": str(exc)}
        return {"action": "start", "container": container_name, "result": result}

    def stop_container(self, container_name: str) -> Dict[str, Any]:
        if not container_name:
            raise ValueError("container_name is required")
        try:
            result = self._client.compose_stop(container_name)
        except DockerMCPError as exc:
            return {"action": "stop", "container": container_name, "error": str(exc)}
        return {"action": "stop", "container": container_name, "result": result}


__all__ = ["DockerStatusTool"]
