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
    """Create a structured suggestion payload for the Ops-Copilot UI."""
    suggestion: Dict[str, Any] = {
        "id": action_id,
        "description": description,
        "command": command,
        "impact": impact,
        "ctaLabel": cta_label,
    }
    if tool_id and action:
        suggestion["toolId"] = tool_id
        suggestion["action"] = action
        if action_params:
            suggestion["actionParams"] = action_params
    return suggestion


def assistant_message(content: str, suggestion: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return a chat message formatted for the Ops-Copilot frontend."""
    message = {
        "id": f"assistant-{uuid4().hex}",
        "role": "assistant",
        "content": content,
    }
    if suggestion:
        message["suggestion"] = suggestion
    return message
