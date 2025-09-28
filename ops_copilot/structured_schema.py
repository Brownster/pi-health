from __future__ import annotations

SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "speak": {"type": "string"},
        "action": {
            "type": ["object", "null"],
            "properties": {
                "id": {"type": "string"},
                "tool_id": {"type": "string"},
                "toolId": {"type": "string"},  # tolerance for camelCase
                "action": {"type": "string"},
                "action_params": {"type": "object"},
                "actionParams": {"type": "object"},
                "description": {"type": "string"},
                "command": {"type": "string"},
                "impact": {"type": "string"},
                "cta_label": {"type": "string"},
                "ctaLabel": {"type": "string"},
                "confidence": {"type": ["number", "string"]},
            },
            "required": ["tool_id", "action", "action_params"],
            "additionalProperties": True,
        },
    },
    "required": ["speak"],
    "additionalProperties": True,
}
