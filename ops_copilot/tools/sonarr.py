from __future__ import annotations

from typing import Any, Dict, List

from app.services.sonarr_mcp import SonarrMCPClient, SonarrMCPError

from ..mcp import BaseMCPTool


class SonarrStatusTool(BaseMCPTool):
    """Summarise Sonarr health, queue, and missing items."""

    tool_id = "sonarr_status"

    def __init__(self, client: SonarrMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = ["sonarr", "series", "episode", "tv", "arr"]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        errors: List[str] = []
        queue = health = missing = status = None

        try:
            status = self._client.system_status()
        except SonarrMCPError as exc:
            errors.append(str(exc))

        try:
            queue = self._client.queue()
        except SonarrMCPError as exc:
            errors.append(str(exc))

        try:
            health = self._client.health()
        except SonarrMCPError as exc:
            errors.append(str(exc))

        try:
            missing = self._client.wanted_missing()
        except SonarrMCPError as exc:
            errors.append(str(exc))

        return {
            "tool": self.tool_id,
            "status": status,
            "queue": queue,
            "health": health,
            "missing": missing,
            "errors": errors,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        errors: List[str] = payload.get("errors", []) or []
        if errors:
            return "; ".join(errors)

        status_summary = _summarise_status(payload.get("status"))
        queue_summary = _summarise_queue(payload.get("queue"))
        health_summary = _summarise_health(payload.get("health"))
        missing_summary = _summarise_missing(payload.get("missing"))

        parts = [piece for piece in [status_summary, queue_summary, health_summary, missing_summary] if piece]
        return " | ".join(parts) if parts else "Sonarr MCP returned no data"

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        signals: Dict[str, Any] = {}
        health = payload.get("health")
        issues = _health_issues(health)
        if issues:
            signals["sonarr_health"] = ", ".join(issues)

        queue = payload.get("queue")
        if queue:
            count = _queue_length(queue)
            if count and count >= 5:
                signals["sonarr_queue_backlog"] = count
        return signals


def _summarise_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    version = data.get("version") or data.get("Version")
    app_name = data.get("appName") or data.get("AppName") or "Sonarr"
    return f"{app_name} {version}" if version else app_name


def _queue_length(data: Any) -> int:
    if isinstance(data, dict):
        records = data.get("records") or data.get("queue") or data.get("items")
        if isinstance(records, list):
            return len(records)
    if isinstance(data, list):
        return len(data)
    return 0


def _summarise_queue(data: Any) -> str:
    length = _queue_length(data)
    if not length:
        return "Queue: empty"
    return f"Queue: {length} download{'s' if length != 1 else ''}"


def _health_issues(data: Any) -> List[str]:
    issues: List[str] = []
    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            message = entry.get("message") or entry.get("Message")
            if message:
                issues.append(str(message))
    elif isinstance(data, dict):
        warnings = data.get("issues")
        if isinstance(warnings, list):
            for item in warnings:
                if isinstance(item, dict) and item.get("message"):
                    issues.append(str(item["message"]))
    return issues


def _summarise_health(data: Any) -> str:
    issues = _health_issues(data)
    if not issues:
        return "Health: OK"
    return f"Health issues: {', '.join(issues[:3])}" + (" …" if len(issues) > 3 else "")


def _summarise_missing(data: Any) -> str:
    if isinstance(data, dict):
        total = data.get("totalRecords") or data.get("total")
        if isinstance(total, int) and total > 0:
            return f"Missing episodes: {total}"
        entries = data.get("records") or data.get("items")
        if isinstance(entries, list):
            count = len(entries)
            if count:
                return f"Missing episodes: {count}"
    if isinstance(data, list) and data:
        return f"Missing episodes: {len(data)}"
    return ""


__all__ = ["SonarrStatusTool"]
