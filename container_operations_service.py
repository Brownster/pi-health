"""Framework-neutral container lifecycle, update, and log operations."""

from __future__ import annotations

from collections.abc import Callable

from ports import DockerPort


class ContainerOperationsService:
    """Run container operations through injected Docker and process adapters."""

    def __init__(
        self,
        *,
        docker: DockerPort,
        compose_runner: Callable,
        update_writer: Callable[[str, bool], None],
    ):
        self._docker = docker
        self._compose_runner = compose_runner
        self._update_writer = update_writer

    def control(self, container_id: str, action: str) -> dict:
        if not self._docker.available:
            return {"error": "Docker is not available"}

        try:
            container = self._docker.get_container(container_id)
            if action == "check_update":
                return self.check_update(container)
            if action == "update":
                return self.update(container)
            if action not in {"start", "stop", "restart"}:
                return {"error": "Invalid action"}
            getattr(container, action)()
            return {"status": f"Container {action}ed successfully"}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _image_ref(container) -> str | None:
        """The image reference to pull.

        Prefer the container's configured image (``Config.Image``, e.g.
        ``linuxserver/jellyfin:latest``) over ``container.image.tags``: after a
        ``check_update`` pull the tag moves to the newly fetched image, leaving the
        running container's image dangling with no tags — so ``image.tags`` would be
        empty at ``update`` time even though the container has a perfectly valid ref.
        """
        try:
            config = (container.attrs or {}).get("Config") or {}
        except Exception:
            config = {}
        ref = config.get("Image")
        if ref:
            return ref
        tags = list(getattr(container.image, "tags", None) or [])
        return tags[0] if tags else None

    def check_update(self, container) -> dict:
        try:
            ref = self._image_ref(container)
            if not ref:
                return {"error": "Container image has no tag"}
            pulled = self._docker.pull_image(ref)
            update_available = pulled.id != container.image.id
            self._update_writer(container.id[:12], update_available)
            return {"update_available": update_available}
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def _compose_recreate_command(container) -> tuple[list[str], str | None]:
        """Build the compose recreation command from the container's own compose
        labels, so it runs in the right project directory against the right config
        file and service — not the app's cwd with the container name as a service.
        Falls back to the container name when the labels are absent (non-compose)."""
        try:
            labels = ((container.attrs or {}).get("Config") or {}).get("Labels") or {}
        except Exception:
            labels = {}
        service = labels.get("com.docker.compose.service")
        working_dir = labels.get("com.docker.compose.project.working_dir") or None
        config_files = [
            path
            for path in (labels.get("com.docker.compose.project.config_files") or "").split(",")
            if path
        ]
        command = ["docker", "compose"]
        for config_file in config_files:
            command += ["-f", config_file]
        command += ["up", "-d", service or container.name]
        return command, working_dir

    def update(self, container) -> dict:
        try:
            ref = self._image_ref(container)
            if not ref:
                return {"error": "Container image has no tag"}
            self._docker.pull_image(ref)
            command, cwd = self._compose_recreate_command(container)
            result = self._compose_runner(
                command, check=False, cwd=cwd, capture_output=True, text=True
            )
            # Don't report success if the recreate actually failed (e.g. compose file
            # not found) — that was the "says updated but nothing changed" bug.
            returncode = getattr(result, "returncode", 0)
            if returncode:
                stderr = (getattr(result, "stderr", "") or "").strip()
                return {"error": f"Recreate failed: {stderr or f'compose exited {returncode}'}"}
            self._update_writer(container.id[:12], False)
            return {"status": "Container updated"}
        except Exception as exc:
            return {"error": str(exc)}

    def logs(self, container_id: str, *, tail: int = 200) -> dict:
        if not self._docker.available:
            return {"error": "Docker is not available"}
        try:
            container = self._docker.get_container(container_id)
            logs = container.logs(tail=tail)
            if isinstance(logs, bytes):
                logs = logs.decode("utf-8", errors="replace")
            return {"logs": logs, "container": container.name}
        except Exception as exc:
            return {"error": str(exc)}
