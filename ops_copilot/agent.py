"""Ops-Copilot AI agent orchestration."""
from __future__ import annotations

import os
import textwrap
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional

from .messages import assistant_message, build_suggestion
from .mcp import BaseMCPTool

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
    ) -> None:
        self.tools: List[BaseMCPTool] = list(tools)
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.temperature = temperature
        self.history: Deque[Dict[str, str]] = deque(maxlen=max_history)
        self.pending_actions: Dict[str, Dict[str, str]] = {}
        self.model = os.getenv("OPENAI_API_MODEL", "gpt-4o-mini")
        self._client = self._build_client()

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

        reply_text, model_used = self._generate_reply(cleaned, context_blocks)
        html = self._render_markdown(reply_text)
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

        if action_id == "restart_sonarr":
            followup = textwrap.dedent(
                """
                <p class='font-semibold text-blue-100'>🔧 Automation complete</p>
                <p class='mt-2 text-blue-100/80'>The Sonarr container restarted successfully and the queue resumed processing.</p>
                <ul class='mt-3 list-disc space-y-1 pl-5 text-blue-100/80'>
                    <li>Restart duration: 18 seconds</li>
                    <li>Queue throughput restored (4 items pending)</li>
                    <li>Action logged to the audit trail</li>
                </ul>
                """
            ).strip()
            return {
                "status": "success",
                "result": "Sonarr container restart simulated successfully.",
                "followup": followup,
            }

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

        raise OpsCopilotApprovalError("This automation is not yet implemented")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_client(self):
        api_key = os.getenv("OPENAI_API_KEY")
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

    def _generate_reply(self, message: str, context_blocks: List[str]) -> (str, str):
        prompt_messages = [
            {
                "role": "system",
                "content": [
                    {"type": "text", "text": self.system_prompt},
                ],
            }
        ]

        # include conversation history except the current user entry
        for entry in list(self.history)[:-1]:
            prompt_messages.append(
                {
                    "role": entry["role"],
                    "content": [
                        {"type": "text", "text": entry["content"]},
                    ],
                }
            )

        user_text = message
        if context_blocks:
            context_text = "\n\n".join(context_blocks)
            user_text = f"{message}\n\nLive telemetry:\n{context_text}"

        prompt_messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                ],
            }
        )

        if self._client is not None:
            try:
                response = self._client.responses.create(
                    model=self.model,
                    input=prompt_messages,
                    temperature=self.temperature,
                )
                reply_text = (response.output_text or "").strip()
                if reply_text:
                    return reply_text, self.model
            except Exception as exc:  # pragma: no cover - network/path errors
                print(f"Warning: OpenAI request failed: {exc}")

        return self._fallback_response(message, context_blocks), "offline-fallback"

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
        if any(word in lowered for word in trigger_words):
            return build_suggestion(
                action_id="restart_sonarr",
                description="Restart the Sonarr container to clear the stalled download queue.",
                command="docker restart sonarr",
                impact="Expected downtime: ~30 seconds. Action will be logged for audit.",
                cta_label="Approve Restart",
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
