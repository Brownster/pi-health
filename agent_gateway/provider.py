"""Frozen gateway->provider contract (AA-004 boundary).

One provider invocation is a single bounded model turn: it receives the canonical
context plus the conversation so far, and returns either a final answer or exactly one
typed `limeops` tool request (baseline: "The structured result is either a final answer
or one typed limeops request"). The gateway owns the tool loop; providers never execute
tools themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Union


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant" | "tool"
    text: str


@dataclass(frozen=True)
class ProviderContext:
    system_context: str  # canonical, non-secret LimeOS context
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class ToolCall:
    operation: str  # limeops operation name, e.g. "container.logs"
    params: dict


ProviderReply = Union[FinalAnswer, ToolCall]


class ProviderError(Exception):
    """Base for typed provider failures. Never contains credential material."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    """Authentication expired or invalid; surfaced as assistant-unavailable."""


class ProviderMalformedError(ProviderError):
    """The provider returned output that does not match the turn schema."""


class ProviderUnavailableError(ProviderError):
    pass


class Provider(Protocol):
    def invoke(self, context: ProviderContext, *, timeout_seconds: float) -> ProviderReply: ...
