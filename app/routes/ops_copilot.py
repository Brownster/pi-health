from __future__ import annotations

from typing import Mapping, Any

from flask import Blueprint, jsonify, request, current_app

from ops_copilot import OpsCopilotAgent, OpsCopilotApprovalError, assistant_message
from ops_copilot.providers import OpenAIProvider, OfflineProvider
from ops_copilot.registry import build_tools
from app.services.audit import record_approval_event

ops_copilot_api = Blueprint('ops_copilot_api', __name__)


def build_agent(config: Mapping[str, Any]) -> OpsCopilotAgent:
    api_key = (config.get('OPENAI_API_KEY') or '').strip()
    model = (config.get('OPENAI_API_MODEL') or 'gpt-4o-mini').strip() or 'gpt-4o-mini'

    provider = None
    if api_key:
        candidate = OpenAIProvider(api_key, model)
        if candidate.is_available():
            provider = candidate

    if provider is None:
        provider = OfflineProvider()

    tools = build_tools(config)
    api_key_for_agent = api_key if api_key else None
    return OpsCopilotAgent(
        tools,
        provider=provider,
        model=model,
        api_key=api_key_for_agent,
        enable_legacy_suggestions=bool(config.get('ENABLE_LEGACY_SUGGESTIONS', True)),
    )


def _get_agent() -> OpsCopilotAgent:
    agent = current_app.extensions.get('ops_copilot_agent')
    if agent is None:
        agent = build_agent(current_app.config)
        current_app.extensions['ops_copilot_agent'] = agent
    return agent


@ops_copilot_api.route('/api/ops-copilot/chat', methods=['POST'])
def api_ops_copilot_chat():
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', '')
    agent = _get_agent()

    try:
        result = agent.chat(message)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Ops-Copilot chat error: {exc}")
        return jsonify({
            "messages": [
                assistant_message(
                    "<p class='text-rose-200'>I ran into an error while processing that. Please try again.</p>"
                )
            ]
        }), 500

    return jsonify(result)


@ops_copilot_api.route('/api/ops-copilot/approve', methods=['POST'])
def api_ops_copilot_approve():
    payload = request.get_json(silent=True) or {}
    action_id = (payload.get('action_id') or '').strip()

    if not action_id:
        return jsonify({"status": "error", "error": "action_id is required"}), 400

    agent = _get_agent()

    try:
        result = agent.approve(action_id)
    except OpsCopilotApprovalError as exc:
        record_approval_event(action_id, "rejected", {"error": str(exc)})
        return jsonify({"status": "error", "error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"Ops-Copilot approval error: {exc}")
        record_approval_event(action_id, "error", {"error": str(exc)})
        return jsonify({
            "status": "error",
            "error": "Failed to execute the requested automation.",
        }), 500

    record_approval_event(action_id, "success", result)
    return jsonify(result)
