"""Mattermost mention listener (AA-005): frames -> gateway turns -> threaded replies.

The websocket transport is injected as a `connect()` factory yielding frame texts, so the
loop is fully testable without a network and the real adapter stays a thin deployment
detail. Turns run strictly sequentially — that satisfies the baseline limits of one
concurrent turn globally and one per thread.

Failure contract: a turn failure posts a typed, non-secret message in the originating
thread; a transport failure reconnects with capped backoff; duplicate frames (websocket
replay after reconnect) are dropped by the persisted dedup store.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from agent_transport.events import (
    MentionEvent,
    ReactionEvent,
    extract_post_text,
    parse_frame,
    parse_reaction_frame,
)
from agent_transport.gateway_contract import (
    ActionProposal,
    MAX_TURN_INPUT_BYTES,
    MAX_TURN_OUTPUT_BYTES,
    TurnError,
    TurnHandler,
    TurnRequest,
)
from agent_transport.state import ApprovalPostMap, EventDedup, ThreadMap

logger = logging.getLogger("limeos.agent.listener")

#: Safe under Mattermost's smallest common per-post limit (4000 chars).
REPLY_CHUNK_CHARS = 3500

#: Posted when the bot is explicitly @mentioned in a channel outside its allowlist.
#: An explicit mention is always acknowledged rather than silently dropped, so the
#: user is never left hanging waiting for a reply that will not come.
OUT_OF_SCOPE_REPLY = (
    "I'm not enabled to respond in this channel. An admin can enable it under "
    "LimeOS → Integrations → Agents."
)

ReplyPoster = Callable[..., str]  # post_message(channel_id=, message=, root_id=) -> post id
ReactionAdder = Callable[..., None]
ActionDecider = Callable[[str, str, dict], dict]

APPROVE_EMOJI = "white_check_mark"
REJECT_EMOJI = "x"


def chunk_reply(text: str, *, chunk_chars: int = REPLY_CHUNK_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Enforce the gateway output ceiling before chunking (defence in depth; the
    # gateway is contract-bound to the same limit).
    encoded = text.encode("utf-8")[:MAX_TURN_OUTPUT_BYTES]
    text = encoded.decode("utf-8", errors="ignore")
    return [text[i : i + chunk_chars] for i in range(0, len(text), chunk_chars)]


def truncate_input(text: str) -> str:
    encoded = text.encode("utf-8")[:MAX_TURN_INPUT_BYTES]
    return encoded.decode("utf-8", errors="ignore")


@dataclass
class ListenerConfig:
    bot_username: str
    bot_user_id: str
    allowed_channels: tuple[str, ...] = ()
    reply_chunk_chars: int = REPLY_CHUNK_CHARS
    reconnect_backoff_seconds: tuple[float, ...] = (1, 5, 15, 30, 60)


class MentionListener:
    def __init__(
        self,
        *,
        config: ListenerConfig,
        gateway: TurnHandler,
        post_reply: ReplyPoster,
        dedup: EventDedup,
        threads: ThreadMap,
        fetch_post: Callable[[str], dict] | None = None,
        approvals: ApprovalPostMap | None = None,
        action_decider: ActionDecider | None = None,
        add_reaction: ReactionAdder | None = None,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._post_reply = post_reply
        self._dedup = dedup
        self._threads = threads
        # Fetches a post by id so a mention that starts a thread on an alert incident
        # can carry that incident's content into the turn. Best-effort; optional.
        self._fetch_post = fetch_post
        self._approvals = approvals
        self._action_decider = action_decider
        self._add_reaction = add_reaction

    # -- per-frame handling (pure of I/O except posting) -----------------------
    def handle_frame(self, frame_text: str) -> bool:
        """Process one frame. Returns True when a turn was executed."""
        reaction = parse_reaction_frame(
            frame_text, bot_user_id=self._config.bot_user_id
        )
        if reaction is not None:
            return self._handle_reaction(reaction)
        # The channel allowlist is enforced here rather than inside parse_frame so
        # that an explicit mention in a non-allowed channel is acknowledged (see
        # _post_out_of_scope) instead of silently dropped.
        event = parse_frame(
            frame_text,
            bot_username=self._config.bot_username,
            bot_user_id=self._config.bot_user_id,
        )
        if event is None:
            return False
        if self._dedup.seen(event.post_id):
            return False
        # Mark before executing so a crash mid-turn cannot double-run the same
        # mention after restart (losing one reply is safer than acting twice).
        self._dedup.mark(event.post_id)
        if (
            self._config.allowed_channels
            and event.channel_id not in self._config.allowed_channels
        ):
            self._post_out_of_scope(event)
            return False
        self._run_turn(event)
        return True

    def _handle_reaction(self, event: ReactionEvent) -> bool:
        if (
            event.emoji_name not in {APPROVE_EMOJI, REJECT_EMOJI}
            or self._approvals is None
            or self._action_decider is None
        ):
            return False
        binding = self._approvals.pending(event.post_id)
        if binding is None or binding["channel_id"] != event.channel_id:
            return False
        event_id = f"reaction:{event.post_id}:{event.user_id}:{event.emoji_name}"
        if self._dedup.seen(event_id):
            return False
        self._dedup.mark(event_id)
        decision = "approve" if event.emoji_name == APPROVE_EMOJI else "reject"
        actor = {"type": "mattermost", "id": event.user_id}
        if event.username:
            actor["username"] = event.username
        try:
            envelope = self._action_decider(binding["action_id"], decision, actor)
        except Exception:  # noqa: BLE001 - never expose broker or state internals
            envelope = {"ok": False, "error": {"code": "unavailable_dependency"}}
        if not isinstance(envelope, dict):
            envelope = {"ok": False, "error": {"code": "unavailable_dependency"}}
        message = self._decision_message(decision, envelope)
        if self._decision_applied(envelope):
            self._approvals.resolve(event.post_id)
        try:
            self._post_reply(
                channel_id=event.channel_id,
                message=message,
                root_id=binding["root_id"],
            )
        except Exception:  # noqa: BLE001 - decision is already durable
            logger.error("failed to post action decision in %s", binding["root_id"])
        return True

    def _post_out_of_scope(self, event: MentionEvent) -> None:
        """Acknowledge a mention in a non-allowed channel so the user isn't left hanging."""
        try:
            self._post_reply(
                channel_id=event.channel_id,
                message=OUT_OF_SCOPE_REPLY,
                root_id=event.root_post_id,
            )
        except Exception:  # noqa: BLE001 - delivery failure must not kill the loop
            logger.error("failed to post out-of-scope reply in %s", event.root_post_id)

    def _run_turn(self, event: MentionEvent) -> None:
        # On the first mention in a thread rooted elsewhere (e.g. an alert incident),
        # prepend the root post's content so the assistant can see what it is being
        # asked to investigate. Only for a new conversation, so follow-ups don't
        # re-inject it; entirely best-effort.
        text = event.text
        if (
            self._fetch_post is not None
            and event.root_post_id != event.post_id
            and not self._threads.known(event.root_post_id)
        ):
            root_text = self._root_context(event.root_post_id)
            if root_text:
                text = f"Alert being discussed:\n{root_text}\n\nUser: {event.text}"

        request = TurnRequest(
            conversation_id=self._threads.conversation_for(event.root_post_id),
            channel_id=event.channel_id,
            root_post_id=event.root_post_id,
            post_id=event.post_id,
            actor_id=event.user_id,
            actor_username=event.username,
            text=truncate_input(text),
        )
        proposals: tuple[ActionProposal, ...] = ()
        try:
            result = self._gateway.handle_turn(request)
            chunks = chunk_reply(result.text, chunk_chars=self._config.reply_chunk_chars)
            proposals = result.action_proposals
        except TurnError as exc:
            chunks = [exc.public_message]
        except Exception:  # noqa: BLE001 - never leak internals into the thread
            logger.error("gateway turn failed for %s", request.conversation_id)
            chunks = [TurnError.public_message]
        for chunk in chunks:
            try:
                self._post_reply(
                    channel_id=event.channel_id, message=chunk, root_id=event.root_post_id
                )
            except Exception:  # noqa: BLE001 - delivery failure must not kill the loop
                logger.error("failed to post reply in %s", event.root_post_id)
                break
        for proposal in proposals:
            self._post_proposal(event, proposal)

    def _post_proposal(self, event: MentionEvent, proposal: ActionProposal) -> None:
        awaiting = proposal.state == "awaiting_approval"
        instructions = (
            "React with :white_check_mark: to approve this action once, or :x: to reject it."
            if awaiting and self._approvals is not None and self._action_decider is not None
            else "This proposal is recorded but is not awaiting Mattermost approval."
        )
        message = "\n".join(
            (
                "#### Agent action proposal",
                f"**Operation:** `{_safe_markdown(proposal.operation)}`",
                f"**Target:** `{_safe_markdown(proposal.target)}`",
                f"**Risk:** `{_safe_markdown(proposal.risk)}`",
                f"**Reason:** {_safe_markdown(proposal.reason)}",
                f"**Expected impact:** {_safe_markdown(proposal.impact)}",
                f"**Expires:** `{_safe_markdown(proposal.expires_at)}`",
                instructions,
                f"Action ID: `{_safe_markdown(proposal.id)}`",
            )
        )
        try:
            post_id = self._post_reply(
                channel_id=event.channel_id,
                message=message,
                root_id=event.root_post_id,
            )
            if awaiting and self._approvals is not None and self._action_decider is not None:
                self._approvals.bind(
                    post_id,
                    action_id=proposal.id,
                    channel_id=event.channel_id,
                    root_id=event.root_post_id,
                )
                if self._add_reaction is not None:
                    for emoji_name in (APPROVE_EMOJI, REJECT_EMOJI):
                        self._add_reaction(post_id=post_id, emoji_name=emoji_name)
        except Exception:  # noqa: BLE001 - delivery failure must not kill the listener
            logger.error("failed to post action proposal in %s", event.root_post_id)

    @staticmethod
    def _decision_message(decision: str, envelope: dict) -> str:
        data = envelope.get("data")
        data = data if isinstance(data, dict) else {}
        if envelope.get("ok") is True and data.get("decision_applied") is True:
            action = data.get("action") or {}
            state = str(action.get("state") or ("authorised" if decision == "approve" else "rejected"))
            verb = "approved" if decision == "approve" else "rejected"
            return f"Action **{verb}**. Current state: `{_safe_markdown(state)}`."
        code = str(
            data.get("error_code")
            or (envelope.get("error") or {}).get("code")
            or "action_failure"
        )
        messages = {
            "denied_approver": "You are not allowed to approve this action.",
            "kill_switch": "Agent actions are disabled by the emergency stop.",
            "expired": "This action proposal has expired.",
            "precondition_changed": "The target changed after the proposal. Request a fresh action.",
            "policy_changed": "The authority policy changed. Request a fresh action.",
            "invalid_state": "This action has already been decided or started.",
            "not_found": "This action proposal is no longer available.",
        }
        return messages.get(code, "The action decision could not be applied. Review it in LimeOS.")

    @staticmethod
    def _decision_applied(envelope: dict) -> bool:
        return bool(
            envelope.get("ok") is True
            and isinstance(envelope.get("data"), dict)
            and envelope["data"].get("decision_applied") is True
        )

    def _root_context(self, root_post_id: str) -> str:
        try:
            return extract_post_text(self._fetch_post(root_post_id) or {})
        except Exception:  # noqa: BLE001 - context enrichment is best-effort
            logger.error("failed to fetch root post %s", root_post_id)
            return ""

    # -- run loop ---------------------------------------------------------------
    def run(
        self,
        connect: Callable[[], Iterable[str]],
        *,
        sleeper: Callable[[float], None] = time.sleep,
        max_connects: int | None = None,
    ) -> None:
        """Consume frames, reconnecting with capped backoff on transport failure.

        `max_connects` bounds the loop for tests; production passes None (run forever).
        """
        failures = 0
        connects = 0
        while max_connects is None or connects < max_connects:
            connects += 1
            try:
                for frame_text in connect():
                    failures = 0
                    self.handle_frame(frame_text)
            except Exception:  # noqa: BLE001 - reconnect on any transport failure
                logger.error("listener transport failed; reconnecting")
            backoff = self._config.reconnect_backoff_seconds
            delay = backoff[min(failures, len(backoff) - 1)]
            failures += 1
            if max_connects is None or connects < max_connects:
                sleeper(delay)


def websocket_frames(site_url: str, token: str) -> Iterator[str]:  # pragma: no cover
    """Real transport: authenticated Mattermost websocket frames.

    Deployment detail (AA-004/AA-006 install the `websocket-client` package into the
    agent environment); imported lazily so this module needs no extra dependency.
    """
    import websocket  # type: ignore

    url = site_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    connection = websocket.create_connection(f"{url}/api/v4/websocket", timeout=90)
    try:
        connection.send(
            json.dumps(
                {
                    "seq": 1,
                    "action": "authentication_challenge",
                    "data": {"token": token},
                },
                separators=(",", ":"),
            )
        )
        while True:
            yield connection.recv()
    finally:
        connection.close()


def _safe_markdown(value: str) -> str:
    return value.replace("`", "'").replace("@", "@\u200b")[:1000]
