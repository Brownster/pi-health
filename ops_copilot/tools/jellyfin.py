from __future__ import annotations

from typing import Any, Dict, List

from app.services.jellyfin_mcp import JellyfinMCPClient, JellyfinMCPError

from ..mcp import BaseMCPTool


class JellyfinStatusTool(BaseMCPTool):
    """Summarise Jellyfin server health, sessions, and scheduled tasks."""

    tool_id = "jellyfin_status"

    def __init__(self, client: JellyfinMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = ["jellyfin", "stream", "transcode", "media"]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        errors: List[str] = []
        system = libraries = sessions = tasks = None

        try:
            system = self._client.system_info()
        except JellyfinMCPError as exc:
            errors.append(str(exc))

        try:
            libraries = self._client.libraries()
        except JellyfinMCPError as exc:
            errors.append(str(exc))

        try:
            sessions = self._client.sessions()
        except JellyfinMCPError as exc:
            errors.append(str(exc))

        try:
            tasks = self._client.scheduled_tasks()
        except JellyfinMCPError as exc:
            errors.append(str(exc))

        return {
            "tool": self.tool_id,
            "system": system,
            "libraries": libraries,
            "sessions": sessions,
            "tasks": tasks,
            "errors": errors,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        errors: List[str] = payload.get("errors", []) or []
        if errors:
            return "; ".join(errors)

        system_summary = _summarise_system(payload.get("system"))
        session_summary = _summarise_sessions(payload.get("sessions"))
        task_summary = _summarise_tasks(payload.get("tasks"))

        parts = [piece for piece in [system_summary, session_summary, task_summary] if piece]
        return " | ".join(parts) if parts else "Jellyfin MCP returned no data"

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        signals: Dict[str, Any] = {}
        sessions = payload.get("sessions")
        active_count = _session_count(sessions)
        if active_count and active_count >= 1:
            signals["jellyfin_active_sessions"] = active_count

        tasks = payload.get("tasks")
        failing = _failing_tasks(tasks)
        if failing:
            signals["jellyfin_task_alert"] = ", ".join(failing)
        return signals


def _summarise_system(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    version = data.get("version") or data.get("Version")
    name = data.get("server_name") or data.get("serverName") or "Jellyfin"
    return f"{name} {version}" if version else name


def _session_count(data: Any) -> int:
    if isinstance(data, dict):
        sessions = data.get("active_sessions") or data.get("Sessions")
        if isinstance(sessions, list):
            return len(sessions)
    if isinstance(data, list):
        return len(data)
    return 0


def _summarise_sessions(data: Any) -> str:
    count = _session_count(data)
    if not count:
        return "Sessions: idle"
    now_playing = []
    sessions = data.get("active_sessions") if isinstance(data, dict) else data
    if isinstance(sessions, list):
        for entry in sessions[:3]:
            if isinstance(entry, dict):
                title = entry.get("now_playing") or entry.get("NowPlayingItem", {}).get("Name")
                user = entry.get("user_name") or entry.get("UserName")
                if title and user:
                    now_playing.append(f"{user}: {title}")
    summary = f"Sessions: {count} active"
    if now_playing:
        summary += f" ({'; '.join(now_playing)})"
    return summary


def _failing_tasks(data: Any) -> List[str]:
    failing: List[str] = []
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if isinstance(tasks, list):
        for task in tasks:
            if not isinstance(task, dict):
                continue
            state = str(task.get("state") or task.get("Status") or "").lower()
            if state in {"failed", "error"}:
                failing.append(str(task.get("name") or task.get("TaskName") or "task"))
    return failing


def _summarise_tasks(data: Any) -> str:
    failing = _failing_tasks(data)
    if failing:
        return f"Tasks failing: {', '.join(failing)}"
    return "Tasks: healthy"


__all__ = ["JellyfinStatusTool"]
