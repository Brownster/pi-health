"""Utility helpers for formatting chat messages and suggestions."""
from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import uuid4


def build_suggestion(
    action_id: str,
    description: str,
    command: str,
    impact: str,
    cta_label: str = "Apply Fix",
    *,
    tool_id: str | None = None,
    action: str | None = None,
    action_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an internal suggestion payload in snake_case."""
    suggestion: Dict[str, Any] = {
        "id": action_id,
        "description": description,
        "command": command,
        "impact": impact,
        "cta_label": cta_label,
    }
    if tool_id and action:
        suggestion["tool_id"] = tool_id
        suggestion["action"] = action
        if action_params:
            suggestion["action_params"] = action_params
    return suggestion


def assistant_message(content: str, suggestion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a chat message formatted for the Ops-Copilot frontend."""
    message: Dict[str, Any] = {
        "id": f"assistant-{uuid4().hex}",
        "role": "assistant",
        "content": content,
    }
    if suggestion:
        message["suggestion"] = _format_suggestion_for_ui(suggestion)
    return message


def _format_suggestion_for_ui(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Convert snake_case suggestion to UI-friendly camelCase."""
    view = {
        "id": payload.get("id"),
        "description": payload.get("description"),
        "command": payload.get("command"),
        "impact": payload.get("impact"),
        "ctaLabel": payload.get("cta_label"),
    }

    tool_id = payload.get("tool_id")
    action = payload.get("action")
    if tool_id and action:
        view["toolId"] = tool_id
        view["action"] = action
        params = payload.get("action_params")
        if isinstance(params, dict):
            view["actionParams"] = params

    return view
