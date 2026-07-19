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

from agent_transport.events import MentionEvent, extract_post_text, parse_frame
from agent_transport.gateway_contract import (
    MAX_TURN_INPUT_BYTES,
    MAX_TURN_OUTPUT_BYTES,
    TurnError,
    TurnHandler,
    TurnRequest,
)
from agent_transport.state import EventDedup, ThreadMap

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
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._post_reply = post_reply
        self._dedup = dedup
        self._threads = threads
        # Fetches a post by id so a mention that starts a thread on an alert incident
        # can carry that incident's content into the turn. Best-effort; optional.
        self._fetch_post = fetch_post

    # -- per-frame handling (pure of I/O except posting) -----------------------
    def handle_frame(self, frame_text: str) -> bool:
        """Process one frame. Returns True when a turn was executed."""
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
            actor_username=event.username,
            text=truncate_input(text),
        )
        try:
            result = self._gateway.handle_turn(request)
            chunks = chunk_reply(result.text, chunk_chars=self._config.reply_chunk_chars)
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
