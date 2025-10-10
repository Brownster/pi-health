"""Ops-Copilot AI agent orchestration."""
from __future__ import annotations

import json
import os
import re
import textwrap
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from .messages import assistant_message, build_suggestion
from .mcp import BaseMCPTool
from .providers import AIProvider
from .structured_schema import SCHEMA as STRUCTURED_SCHEMA

try:  # pragma: no cover - optional dependency
    from markdown import markdown as markdown_to_html
except Exception:  # pragma: no cover - gracefully degrade when markdown missing
    markdown_to_html = None

try:  # pragma: no cover - optional dependency
    from openai import OpenAI
except Exception:  # pragma: no cover - we only instantiate when available
    OpenAI = None  # type: ignore[assignment]


DEFAULT_SYSTEM_PROMPT = textwrap.dedent(
    """
    You are Coraline's Ops-Copilot: an on-call site reliability assistant for a family
    media server stack. Keep explanations concise, reference live telemetry that the
    tooling provides, and suggest a single actionable next step when appropriate.
    Always prefer safe, reversible actions and call out when human assistance may
    be required. Never invent commands that were not provided in the tool catalog.

Respond ONLY with JSON matching this schema:

{
  "thought": "short internal reasoning",
  "speak": "markdown response for the user",
  "action": {
    "id": "restart_sonarr",
    "tool_id": "docker_actions",
    "action": "restart_container",
    "action_params": {"container_name": "sonarr"},
    "description": "Restart the Sonarr container to unstick the queue.",
    "command": "docker compose restart sonarr",
    "impact": "Downtime ~30s",
    "cta_label": "Approve Restart",
    "confidence": 0.85
  }
}

If no automation is appropriate set "action": null. Always return valid JSON without extra commentary or markdown fences.
    """
).strip()


class OpsCopilotApprovalError(RuntimeError):
    """Raised when an approval request cannot be satisfied."""


class OpsCopilotAgent:
    """Coordinate chat generation, MCP tool execution, and approvals."""

    def __init__(
        self,
        tools: Iterable[BaseMCPTool],
        *,
        system_prompt: Optional[str] = None,
        max_history: int = 8,
        temperature: float = 0.2,
        provider: Optional[AIProvider] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        enable_legacy_suggestions: bool = True,
    ) -> None:
        self.tools: List[BaseMCPTool] = list(tools)
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.temperature = temperature
        self.history: Deque[Dict[str, str]] = deque(maxlen=max_history)
        self.pending_actions: Dict[str, Dict[str, str]] = {}
        self.model = (model or os.getenv("OPENAI_API_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip() or "gpt-4o-mini"
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = self._build_client()
        self._provider = provider
        self._action_confidence_threshold = 0.6
        self._enable_legacy_suggestions = enable_legacy_suggestions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def chat(self, message: str) -> Dict[str, List[Dict[str, str]]]:
        """Generate an assistant reply for the provided user message."""
        cleaned = (message or "").strip()
        if not cleaned:
            return {
                "messages": [
                    assistant_message(
                        "<p class=\"text-blue-100/80\">Share a question so I can investigate.</p>"
                    )
                ]
            }

        self.history.append({"role": "user", "content": cleaned})
        context_blocks: List[str] = []
        signals: Dict[str, str] = {}
        for tool in self.tools:
            if not tool.should_run(cleaned):
                continue
            try:
                payload = tool.collect(cleaned)
            except Exception as exc:  # pragma: no cover - defensive logging
                context_blocks.append(
                    f"[{tool.tool_id}] tool failed: {exc}"
                )
                continue
            summary = tool.render_for_prompt(payload)
            if summary:
                context_blocks.append(f"[{tool.tool_id}] {summary}")
            signals.update({k: str(v) for k, v in tool.derive_signals(payload).items()})

        reply_text, model_used, structured = self._generate_reply(cleaned, context_blocks)
        html = self._render_markdown(reply_text)
        suggestion = self._suggestion_from_structured(structured)
        if suggestion is None and self._enable_legacy_suggestions:
            suggestion = self._maybe_build_suggestion(cleaned, signals)
        if suggestion:
            self.pending_actions[suggestion["id"]] = suggestion

        self.history.append({"role": "assistant", "content": reply_text})

        return {
            "messages": [assistant_message(html, suggestion=suggestion)],
            "model": model_used,
        }

    def approve(self, action_id: str) -> Dict[str, str]:
        """Handle approval of a queued automation."""
        if not action_id:
            raise OpsCopilotApprovalError("action_id is required")

        suggestion = self.pending_actions.pop(action_id, None)
        if not suggestion:
            raise OpsCopilotApprovalError("Unknown or expired automation request")

        if action_id in {"cooldown_notice", "disk_cleanup_notice"}:
            acknowledgement = textwrap.dedent(
                """
                <p class='font-semibold text-blue-100'>✅ Acknowledged</p>
                <p class='mt-2 text-blue-100/80'>Thanks for confirming. I will keep monitoring the telemetry and surface any changes.</p>
                """
            ).strip()
            return {
                "status": "acknowledged",
                "result": "Reminder recorded.",
                "followup": acknowledgement,
            }

        tool_id = suggestion.get("toolId") or suggestion.get("tool_id")
        action = suggestion.get("action")
        action_params = suggestion.get("actionParams") or suggestion.get("action_params") or {}

        if tool_id and action:
            tool = self._find_tool(tool_id)
            if tool is None:
                raise OpsCopilotApprovalError("Automation unavailable: required tool not loaded")

            action_method = getattr(tool, action, None)
            if not callable(action_method):
                raise OpsCopilotApprovalError("Automation action is not available")

            try:
                result = action_method(**action_params)
            except (TypeError, ValueError) as exc:
                raise OpsCopilotApprovalError(f"Invalid automation parameters: {exc}") from exc
            except Exception as exc:
                raise OpsCopilotApprovalError(f"Automation execution failed: {exc}") from exc

            followup = self._format_action_followup(suggestion, result)
            return {
                "status": "success",
                "result": result,
                "followup": followup,
            }

        raise OpsCopilotApprovalError("This automation is not yet implemented")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_client(self):
        api_key = self._api_key
        if not api_key:
            return None
        if OpenAI is None:
            print("Warning: openai package is not installed; running in offline mode.")
            return None
        try:
            return OpenAI(api_key=api_key)
        except Exception as exc:  # pragma: no cover - fail gracefully
            print(f"Warning: could not initialise OpenAI client: {exc}")
            return None

    def _generate_reply(self, message: str, context_blocks: List[str]) -> Tuple[str, str, Optional[Dict[str, Any]]]:
        prompt_messages = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]

        # include conversation history except the current user entry
        for entry in list(self.history)[:-1]:
            prompt_messages.append(
                {
                    "role": entry["role"],
                    "content": entry["content"],
                }
            )

        user_text = message
        if context_blocks:
            context_text = "\n\n".join(context_blocks)
            user_text = f"{message}\n\nLive telemetry:\n{context_text}"

        prompt_messages.append(
            {
                "role": "user",
                "content": user_text,
            }
        )

        # Prefer injected provider if available
        if self._provider is not None and self._provider.is_available():
            try:
                reply_text, model_used = self._provider.generate(prompt_messages, temperature=self.temperature)
                if reply_text:
                    return self._interpret_model_output(reply_text, model_used)
            except Exception as exc:  # pragma: no cover
                print(f"Warning: provider request failed: {exc}")

        if self._client is not None:
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=prompt_messages,
                    temperature=self.temperature,
                )
                reply_text = (response.choices[0].message.content or "").strip()
                if reply_text:
                    return self._interpret_model_output(reply_text, self.model)
            except Exception as exc:  # pragma: no cover - network/path errors
                print(f"Warning: OpenAI request failed: {exc}")

        return self._fallback_response(message, context_blocks), "offline-fallback", None

    def _interpret_model_output(self, raw: str, model: str) -> Tuple[str, str, Optional[Dict[str, Any]]]:
        payload = self._parse_json_response(raw)
        if payload is None:
            return raw, model, None

        speak_text = str(payload.get("speak") or raw)
        return speak_text, model, payload

    def _parse_json_response(self, raw: str) -> Optional[Dict[str, Any]]:
        text = raw.strip()
        if not text:
            return None

        candidate = self._extract_json_snippet(text)
        if candidate is None:
            return None

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None
        if not self._validate_structured_payload(parsed):
            return None
        return parsed

    def _validate_structured_payload(self, payload: Dict[str, Any]) -> bool:
        required = STRUCTURED_SCHEMA.get("required", [])
        for key in required:
            if key not in payload:
                return False
        action = payload.get("action")
        if action in (None, {}):
            return True
        if not isinstance(action, dict):
            return False
        must_have = ["action"]
        for key in must_have:
            if key not in action:
                return False
        return True

    @staticmethod
    def _extract_json_snippet(text: str) -> Optional[str]:
        fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        return None

    def _fallback_response(self, message: str, context_blocks: List[str]) -> str:
        lines = [
            "I cannot reach the cloud AI service right now, so I will summarise the telemetry locally.",
        ]
        if context_blocks:
            lines.append("Latest checks:")
            lines.extend(f"- {block}" for block in context_blocks)
        else:
            lines.append("No telemetry tools were run for this request.")
        lines.append("If you still need help, consider retrying in a few minutes or pinging a human operator.")
        return "\n\n".join(lines)

    @staticmethod
    def _render_markdown(text: str) -> str:
        if not text:
            return "<p>I did not receive a response.</p>"
        if markdown_to_html is None:  # pragma: no cover - fallback path
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            paragraphs = "".join(f"<p>{line}</p>" for line in escaped.split("\n\n"))
            return paragraphs or "<p>I did not receive a response.</p>"
        return markdown_to_html(text, extensions=["extra", "sane_lists"])  # type: ignore[no-any-return]

    def _maybe_build_suggestion(self, message: str, signals: Dict[str, str]):
        lowered = message.lower()
        trigger_words = ["sonarr", "queue", "stalled", "restart"]
        docker_tool_present = any(tool.tool_id == "docker_actions" for tool in self.tools)
        if any(word in lowered for word in trigger_words) and docker_tool_present:
            return build_suggestion(
                action_id="restart_sonarr",
                description="Restart the Sonarr container to clear the stalled download queue.",
                command="docker compose restart sonarr",
                impact="Expected downtime: ~30 seconds. Action will be logged for audit.",
                cta_label="Approve Restart",
                tool_id="docker_actions",
                action="restart_container",
                action_params={"container_name": "sonarr"},
            )
        # Provide informational nudges when telemetry looks unhealthy.
        if "hot_system" in signals:
            return build_suggestion(
                action_id="cooldown_notice",
                description="System temperature is elevated. Please inspect airflow before continuing heavy workloads.",
                command="Manual check required",
                impact="No automation available yet; manual intervention recommended.",
                cta_label="Acknowledge",
            )
        if "disk_pressure" in signals:
            return build_suggestion(
                action_id="disk_cleanup_notice",
                description="Primary disk usage is above 85%. Consider running the cleanup playbook.",
                command="Manual cleanup",
                impact="Delete unused downloads or move media to long-term storage.",
                cta_label="Got It",
            )
        return None

    def _suggestion_from_structured(self, payload: Optional[Dict[str, Any]]):
        if not isinstance(payload, dict):
            return None

        action = payload.get("action")
        if not isinstance(action, dict):
            return None

        confidence_value = action.get("confidence") or action.get("Confidence")
        try:
            confidence = float(confidence_value or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self._action_confidence_threshold:
            return None

        tool_id = action.get("tool_id") or action.get("toolId")
        action_name = action.get("action")
        if not tool_id or not action_name:
            return None

        action_params = action.get("action_params") or action.get("actionParams") or {}
        if not isinstance(action_params, dict):
            action_params = {}

        description = action.get("description") or "Automation suggested by Ops-Copilot"
        command = action.get("command") or f"{tool_id}.{action_name}"
        impact = action.get("impact") or "Execution will be logged."
        cta_label = action.get("cta_label") or action.get("ctaLabel") or "Approve"
        action_id = action.get("id") or f"{tool_id}_{action_name}"

        return build_suggestion(
            action_id=action_id,
            description=description,
            command=command,
            impact=impact,
            cta_label=cta_label,
            tool_id=tool_id,
            action=action_name,
            action_params=action_params,
        )

    def _find_tool(self, tool_id: str) -> Optional[BaseMCPTool]:
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        return None

    def _format_action_followup(self, suggestion: Dict[str, Any], result: Dict[str, Any]) -> str:
        params = suggestion.get("action_params") or suggestion.get("actionParams") or {}
        container = result.get("container") or params.get("container_name")
        action = result.get("action") or suggestion.get("action")
        if result.get("status") == "error":
            error_msg = result.get("error") or "The automation reported an error."
            return textwrap.dedent(
                f"""
                <p class='font-semibold text-rose-200'>⛔ Automation failed</p>
                <p class='mt-2 text-rose-200/90'>{error_msg}</p>
                """
            ).strip()

        action_label = action.capitalize() if isinstance(action, str) else "Automation"
        subject = container or suggestion.get("description") or "requested action"
        message = textwrap.dedent(
            f"""
            <p class='font-semibold text-blue-100'>🔧 {action_label} complete</p>
            <p class='mt-2 text-blue-100/80'>The {subject} was queued successfully via the MCP gateway.</p>
            """
        ).strip()
        return message
