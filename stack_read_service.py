"""Framework-neutral stack discovery and status queries."""

from __future__ import annotations

import json
import os
import re
import subprocess


STACK_FILENAMES = [
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
]
BACKUP_NAME_RE = re.compile(r"^compose-\d{14}\.ya?ml$")
DOCKER_PS_STACK_FORMAT = "\t".join(
    [
        "{{.ID}}",
        "{{.Names}}",
        "{{.State}}",
        "{{.Status}}",
        "{{.Ports}}",
        '{{.Label "com.docker.compose.project.working_dir"}}',
        '{{.Label "com.docker.compose.project.config_files"}}',
        '{{.Label "com.docker.compose.service"}}',
    ]
)


class ComposeFileConflictError(RuntimeError):
    code = "compose_file_conflict"

    def __init__(self, filenames):
        self.filenames = list(filenames)
        super().__init__(f'Multiple Compose files found: {", ".join(self.filenames)}')

    def as_dict(self):
        return {
            "code": self.code,
            "error": str(self),
            "files": self.filenames,
        }


class StackNotFoundError(RuntimeError):
    pass


class StackArtifactReadError(RuntimeError):
    pass


def find_compose_file(stack_dir):
    matches = [
        filename
        for filename in STACK_FILENAMES
        if os.path.exists(os.path.join(stack_dir, filename))
    ]
    if len(matches) > 1:
        raise ComposeFileConflictError(matches)
    return os.path.join(stack_dir, matches[0]) if matches else None


class StackReadService:
    def __init__(self, *, stacks_path_provider, backup_path_provider, command_runner):
        self._stacks_path_provider = stacks_path_provider
        self._backup_path_provider = backup_path_provider
        self._command_runner = command_runner

    def list_stacks(self) -> tuple[list[dict], str | None]:
        stacks_path = self._stacks_path_provider()
        try:
            os.makedirs(stacks_path, exist_ok=True)
        except Exception as exc:
            return [], str(exc)

        stacks = []
        try:
            for entry in os.listdir(stacks_path):
                if entry.startswith("."):
                    continue
                stack_dir = os.path.join(stacks_path, entry)
                if not os.path.isdir(stack_dir):
                    continue
                try:
                    compose_file = find_compose_file(stack_dir)
                except ComposeFileConflictError as exc:
                    stacks.append(
                        {
                            "name": entry,
                            "path": stack_dir,
                            "compose_file": None,
                            "compose_files": exc.filenames,
                            "status": "conflict",
                            "error": str(exc),
                            "code": exc.code,
                        }
                    )
                    continue
                if compose_file:
                    stacks.append(
                        {
                            "name": entry,
                            "path": stack_dir,
                            "compose_file": os.path.basename(compose_file),
                        }
                    )
        except Exception as exc:
            return [], str(exc)
        return sorted(stacks, key=lambda stack: stack["name"]), None

    def list_with_status(self, *, include_status: bool = False) -> tuple[list[dict], str | None]:
        stacks, error = self.list_stacks()
        if error or not include_status:
            return stacks, error

        snapshot, status_error = self.status_snapshot(stacks)
        for stack in stacks:
            if stack.get("code") == ComposeFileConflictError.code:
                continue
            if status_error:
                stack.update(
                    {
                        "status": "unknown",
                        "running_count": 0,
                        "container_count": 0,
                        "status_error": status_error,
                    }
                )
            else:
                stack.update(
                    snapshot.get(
                        stack["name"],
                        {
                            "status": "stopped",
                            "running_count": 0,
                            "container_count": 0,
                        },
                    )
                )
        return stacks, None

    def status(self, stack_name: str) -> tuple[dict | None, str | None]:
        stack_dir = os.path.join(self._stacks_path_provider(), stack_name)
        compose_file = find_compose_file(stack_dir)
        if not compose_file:
            return None, "Stack not found"
        try:
            result = self._command_runner(
                ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
                cwd=stack_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            containers = self._parse_compose_ps(result.stdout.strip())
            if not containers:
                status = "stopped"
            elif all(container["status"] == "running" for container in containers):
                status = "running"
            elif any(container["status"] == "running" for container in containers):
                status = "partial"
            else:
                status = "stopped"
            return {
                "status": status,
                "containers": containers,
                "container_count": len(containers),
                "running_count": sum(
                    1 for container in containers if container["status"] == "running"
                ),
            }, None
        except subprocess.TimeoutExpired:
            return None, "Timeout getting stack status"
        except Exception as exc:
            return {"status": "unknown", "containers": [], "error": str(exc)}, None

    @staticmethod
    def _parse_compose_ps(stdout: str) -> list[dict]:
        if not stdout:
            return []
        try:
            parsed = json.loads(stdout)
            records = [parsed] if isinstance(parsed, dict) else parsed
            if not isinstance(records, list):
                records = None
        except json.JSONDecodeError:
            records = None
        if records is None:
            records = []
            for line in stdout.splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                records.append(record)
        return [
            {
                "name": record.get("Name", ""),
                "service": record.get("Service", ""),
                "status": record.get("State", "unknown"),
                "health": record.get("Health", ""),
                "ports": record.get("Publishers", []),
            }
            for record in records
            if isinstance(record, dict)
        ]

    def status_snapshot(self, stacks: list[dict]) -> tuple[dict, str | None]:
        stack_by_file = {}
        stack_by_dir = {}
        counts = {}
        for stack in stacks:
            compose_file = stack.get("compose_file")
            stack_path = stack.get("path")
            if not compose_file or not stack_path:
                continue
            name = stack["name"]
            stack_by_file[os.path.realpath(os.path.join(stack_path, compose_file))] = name
            stack_by_dir[os.path.realpath(stack_path)] = name
            counts[name] = {"container_count": 0, "running_count": 0}
        if not counts:
            return {}, None

        try:
            result = self._command_runner(
                ["docker", "ps", "-a", "--format", DOCKER_PS_STACK_FORMAT],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {}, "Timeout getting Docker container snapshot"
        except Exception as exc:
            return {}, str(exc)
        if result.returncode != 0:
            return {}, result.stderr.strip() or "Unable to get Docker container snapshot"

        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 8:
                continue
            _, _, state, _, _, working_dir, config_files, _ = fields
            normalized_dir = os.path.realpath(working_dir) if working_dir else None
            stack_name = None
            for config_file in config_files.split(","):
                config_file = config_file.strip()
                if not config_file:
                    continue
                if not os.path.isabs(config_file) and normalized_dir:
                    config_file = os.path.join(normalized_dir, config_file)
                stack_name = stack_by_file.get(os.path.realpath(config_file))
                if stack_name:
                    break
            if not stack_name and normalized_dir:
                stack_name = stack_by_dir.get(normalized_dir)
            if not stack_name:
                continue
            counts[stack_name]["container_count"] += 1
            if state.lower() == "running":
                counts[stack_name]["running_count"] += 1

        snapshot = {}
        for name, stack_counts in counts.items():
            total = stack_counts["container_count"]
            running = stack_counts["running_count"]
            status = "stopped" if total == 0 or running == 0 else (
                "running" if running == total else "partial"
            )
            snapshot[name] = {"status": status, **stack_counts}
        return snapshot, None

    def stack_details(self, name: str) -> dict:
        stack_dir = os.path.join(self._stacks_path_provider(), name)
        compose_file = find_compose_file(stack_dir)
        if not compose_file:
            raise StackNotFoundError("Stack not found")
        try:
            with open(compose_file) as handle:
                compose_content = handle.read()
        except Exception as exc:
            raise StackArtifactReadError(
                f"Error reading compose file: {exc}"
            ) from exc

        status, _ = self.status(name)
        env_file = os.path.join(stack_dir, ".env")
        has_env = os.path.exists(env_file)
        env_content = None
        if has_env:
            try:
                with open(env_file) as handle:
                    env_content = handle.read()
            except Exception:
                pass
        return {
            "name": name,
            "path": stack_dir,
            "compose_file": os.path.basename(compose_file),
            "compose_content": compose_content,
            "has_env": has_env,
            "env_content": env_content,
            "status": status,
        }

    def compose(self, name: str) -> dict:
        stack_dir = os.path.join(self._stacks_path_provider(), name)
        compose_file = find_compose_file(stack_dir)
        if not compose_file:
            raise StackNotFoundError("Stack not found")
        try:
            with open(compose_file) as handle:
                return {
                    "content": handle.read(),
                    "filename": os.path.basename(compose_file),
                }
        except Exception as exc:
            raise StackArtifactReadError(str(exc)) from exc

    def env(self, name: str) -> dict:
        env_file = os.path.join(self._stacks_path_provider(), name, ".env")
        if not os.path.exists(env_file):
            return {"content": "", "exists": False}
        try:
            with open(env_file) as handle:
                return {"content": handle.read(), "exists": True}
        except Exception as exc:
            raise StackArtifactReadError(str(exc)) from exc

    def list_backups(self, name: str) -> list[str]:
        backup_root = self._backup_path_provider()
        os.makedirs(backup_root, exist_ok=True)
        backup_dir = os.path.join(backup_root, name)
        if not os.path.isdir(backup_dir):
            return []
        backups = [
            filename
            for filename in os.listdir(backup_dir)
            if BACKUP_NAME_RE.match(filename)
        ]
        backups.sort(reverse=True)
        return backups

    def backup(self, name: str, backup_name: str) -> dict:
        backup_path = os.path.join(self._backup_path_provider(), name, backup_name)
        if not os.path.exists(backup_path):
            raise StackNotFoundError("Backup not found")
        try:
            with open(backup_path) as handle:
                return {"content": handle.read(), "filename": backup_name}
        except Exception as exc:
            raise StackArtifactReadError(str(exc)) from exc
