"""Frozen listener->gateway contract (AA-003 boundary).

AA-005 builds against this interface with a mocked implementation; AA-003's real gateway
implements it without the listener changing. The listener never sees provider details —
only bounded text in, bounded text out, and typed failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

#: Baseline limit: Mattermost input retained per turn (32 KiB).
MAX_TURN_INPUT_BYTES = 32 * 1024
#: Baseline limit: final response size before transport chunking (32 KiB).
MAX_TURN_OUTPUT_BYTES = 32 * 1024


@dataclass(frozen=True)
class TurnRequest:
    """One user turn. `conversation_id` is stable per Mattermost root post."""

    conversation_id: str
    channel_id: str
    root_post_id: str
    post_id: str
    actor_id: str
    actor_username: str
    text: str  # mention-stripped, truncated to MAX_TURN_INPUT_BYTES


@dataclass(frozen=True)
class ActionProposal:
    id: str
    operation: str
    target: str
    risk: str
    reason: str
    impact: str
    state: str
    expires_at: str


@dataclass(frozen=True)
class TurnResult:
    text: str  # bounded by MAX_TURN_OUTPUT_BYTES
    action_proposals: tuple[ActionProposal, ...] = ()


class TurnError(Exception):
    """Typed, non-secret turn failure. `public_message` is safe to post in-thread."""

    public_message = "I could not complete that request. Please try again."


class TurnBusyError(TurnError):
    public_message = "I am already handling a request. Please try again shortly."


class TurnLimitError(TurnError):
    public_message = "The daily assistant usage limit has been reached."


class TurnUnavailableError(TurnError):
    public_message = "The assistant is not available right now."


class TurnHandler(Protocol):
    def handle_turn(self, request: TurnRequest) -> TurnResult: ...
