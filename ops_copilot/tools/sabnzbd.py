from __future__ import annotations

from typing import Any, Dict, List

from app.services.sabnzbd_mcp import SabnzbdMCPClient, SabnzbdMCPError

from ..mcp import BaseMCPTool


class SabnzbdStatusTool(BaseMCPTool):
    """Summarise SABnzbd queue, speeds, and warnings."""

    tool_id = "sabnzbd_status"

    def __init__(self, client: SabnzbdMCPClient) -> None:
        self._client = client

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = ["sabnzbd", "download", "nzb", "usenet", "queue"]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        errors: List[str] = []
        status = queue = warnings = None

        try:
            status = self._client.status()
        except SabnzbdMCPError as exc:
            errors.append(str(exc))

        try:
            queue = self._client.queue()
        except SabnzbdMCPError as exc:
            errors.append(str(exc))

        try:
            warnings = self._client.warnings()
        except SabnzbdMCPError as exc:
            errors.append(str(exc))

        return {
            "tool": self.tool_id,
            "status": status,
            "queue": queue,
            "warnings": warnings,
            "errors": errors,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        errors: List[str] = payload.get("errors", []) or []
        if errors:
            return "; ".join(errors)

        status_summary = _summarise_status(payload.get("status"))
        queue_summary = _summarise_queue(payload.get("queue"))
        warnings_summary = _summarise_warnings(payload.get("warnings"))

        parts = [piece for piece in [status_summary, queue_summary, warnings_summary] if piece]
        return " | ".join(parts) if parts else "SABnzbd MCP returned no data"

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        signals: Dict[str, Any] = {}
        warnings = payload.get("warnings")
        messages = _extract_warnings(warnings)
        if messages:
            signals["sabnzbd_warnings"] = ", ".join(messages[:3])
        queue = payload.get("queue")
        length = _queue_length(queue)
        if length and length >= 10:
            signals["sabnzbd_queue_size"] = length
        return signals


def _summarise_status(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    speed = data.get("kbpersec") or data.get("kbpersec_total")
    status = data.get("state") or data.get("Status")
    if speed is not None:
        try:
            speed_float = float(speed)
        except (TypeError, ValueError):
            speed_float = None
        if speed_float is not None:
            mb_s = speed_float / 1024
            speed_text = f"{mb_s:.1f} MB/s"
        else:
            speed_text = str(speed)
    else:
        speed_text = "0 MB/s"
    return f"SABnzbd: {status or 'unknown'} @ {speed_text}"


def _queue_length(data: Any) -> int:
    if isinstance(data, dict):
        slots = data.get("slots") or data.get("jobs") or data.get("queue")
        if isinstance(slots, list):
            return len(slots)
    if isinstance(data, list):
        return len(data)
    return 0


def _summarise_queue(data: Any) -> str:
    length = _queue_length(data)
    if not length:
        return "Queue: empty"
    eta = None
    if isinstance(data, dict):
        eta = data.get("eta") or data.get("timeleft")
    return f"Queue: {length} item{'s' if length != 1 else ''}{f' (ETA {eta})' if eta else ''}"


def _extract_warnings(data: Any) -> List[str]:
    warnings: List[str] = []
    if isinstance(data, dict):
        entries = data.get("warnings") or data.get("items") or data.get("error")
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, str):
                    warnings.append(entry)
                elif isinstance(entry, dict) and entry.get("message"):
                    warnings.append(str(entry["message"]))
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, str):
                warnings.append(entry)
            elif isinstance(entry, dict) and entry.get("message"):
                warnings.append(str(entry["message"]))
    return warnings


def _summarise_warnings(data: Any) -> str:
    warnings = _extract_warnings(data)
    if not warnings:
        return "Warnings: none"
    preview = ", ".join(warnings[:2])
    if len(warnings) > 2:
        preview += " …"
    return f"Warnings: {preview}"


__all__ = ["SabnzbdStatusTool"]
