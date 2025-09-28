from __future__ import annotations

import subprocess
from typing import Dict, List

try:
    import docker
    docker_client = docker.from_env()
    docker_available = True
except Exception as e:  # pragma: no cover
    print(f"Warning: Could not connect to Docker: {e}")
    print("Docker functionality will be disabled")
    docker = None
    docker_client = None
    docker_available = False

# Track update status for containers
container_updates: Dict[str, bool] = {}


def list_containers() -> List[Dict[str, str]]:
    if not docker_available:
        return [
            {
                "id": "docker-not-available",
                "name": "Docker Not Available",
                "status": "unavailable",
                "image": "N/A",
            }
        ]
    try:
        containers = docker_client.containers.list(all=True)
        return [
            {
                "id": container.id[:12],
                "name": container.name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "update_available": container_updates.get(container.id[:12], False),
            }
            for container in containers
        ]
    except Exception as e:
        print(f"Error listing containers: {e}")
        return [
            {
                "id": "error-listing",
                "name": "Error Listing Containers",
                "status": "error",
                "image": str(e)[:30] + "..." if len(str(e)) > 30 else str(e),
            }
        ]


def check_container_update(container):
    try:
        if not container.image.tags:
            return {"error": "Container image has no tag"}
        tag = container.image.tags[0]
        current_id = container.image.id
        pulled = docker_client.images.pull(tag)
        update = pulled.id != current_id
        container_updates[container.id[:12]] = update
        return {"update_available": update}
    except Exception as e:
        return {"error": str(e)}


def update_container(container):
    try:
        if not container.image.tags:
            return {"error": "Container image has no tag"}
        tag = container.image.tags[0]
        docker_client.images.pull(tag)
        subprocess.run(["docker", "compose", "up", "-d", container.name], check=False)
        container_updates[container.id[:12]] = False
        return {"status": "Container updated"}
    except Exception as e:
        return {"error": str(e)}


def control_container(container_id: str, action: str):
    if not docker_available:
        return {"error": "Docker is not available"}
    try:
        container = docker_client.containers.get(container_id)
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop()
        elif action == "restart":
            container.restart()
        elif action == "check_update":
            return check_container_update(container)
        elif action == "update":
            return update_container(container)
        else:
            return {"error": "Invalid action"}
        return {"status": f"Container {action}ed successfully"}
    except Exception as e:
        return {"error": str(e)}
