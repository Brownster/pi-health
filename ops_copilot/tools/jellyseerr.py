from __future__ import annotations

from typing import Any, Dict, List

from app.services.jellyseerr_mcp import JellyseerrMCPClient, JellyseerrMCPError

from ..mcp import BaseMCPTool


class JellyseerrStatusTool(BaseMCPTool):
    """Summarise Jellyseerr status and recent requests."""

    tool_id = "jellyseerr_status"

    def __init__(self, client: JellyseerrMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = ["jellyseerr", "request", "tmdb", "movie night"]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        errors: List[str] = []
        status = requests = None

        try:
            status = self._client.status()
        except JellyseerrMCPError as exc:
            errors.append(str(exc))

        try:
            requests = self._client.requests()
        except JellyseerrMCPError as exc:
            errors.append(str(exc))

        return {
            "tool": self.tool_id,
            "status": status,
            "requests": requests,
            "errors": errors,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        errors: List[str] = payload.get("errors", []) or []
        if errors:
            return "; ".join(errors)

        status_summary = _summarise_status(payload.get("status"))
        request_summary = _summarise_requests(payload.get("requests"))
        parts = [piece for piece in [status_summary, request_summary] if piece]
        return " | ".join(parts) if parts else "Jellyseerr MCP returned no data"

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        signals: Dict[str, Any] = {}
        pending = _pending_requests(payload.get("requests"))
        if pending:
            signals["jellyseerr_pending"] = pending
        return signals


def _summarise_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    version = data.get("version") or data.get("Version")
    return f"Jellyseerr {version}" if version else "Jellyseerr"


def _summarise_requests(data: Any) -> str:
    if isinstance(data, dict):
        results = data.get("results") or data.get("requests")
        if isinstance(results, list):
            total = len(results)
            pending = sum(1 for item in results if _is_pending(item))
            approved = sum(1 for item in results if _is_approved(item))
            return f"Requests: {pending} pending / {approved} approved / {total} recent"
    return "Requests: n/a"


def _is_pending(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status") or item.get("Status")
    return str(status).lower() in {"pending", "processing"}


def _is_approved(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    status = item.get("status") or item.get("Status")
    return str(status).lower() in {"approved", "available", "completed"}


def _pending_requests(data: Any) -> str | None:
    if isinstance(data, dict):
        results = data.get("results") or data.get("requests")
        if isinstance(results, list):
            pending_titles: List[str] = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                if _is_pending(item):
                    title = item.get("title") or item.get("Title") or item.get("media", {}).get("title")
                    if title:
                        pending_titles.append(str(title))
            if pending_titles:
                return ", ".join(pending_titles[:3]) + (" …" if len(pending_titles) > 3 else "")
    return None


__all__ = ["JellyseerrStatusTool"]
