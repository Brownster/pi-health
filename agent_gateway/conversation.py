"""Persistent, bounded, provider-neutral conversation store.

One JSON file per conversation under the agent state directory
(`/var/lib/lime-agent/state/conversations/` on the target; injected in tests).
Provider-native session files are disposable — this store is the source of truth, so
switching provider preserves understandable context (design: "Provider-native session
files are disposable implementation details").

History is bounded: only the most recent messages are retained, so prompts stay bounded
without a summarizer (conversation summaries are deferred work).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent_gateway.provider import Message

_MAX_MESSAGES = 40
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class ConversationStore:
    def __init__(self, state_dir: Path | str, *, max_messages: int = _MAX_MESSAGES) -> None:
        self._dir = Path(state_dir) / "conversations"
        self._max_messages = max_messages

    def _path(self, conversation_id: str) -> Path:
        if not _ID_RE.match(conversation_id):
            raise ValueError("invalid conversation id")
        return self._dir / f"{conversation_id}.json"

    def messages(self, conversation_id: str) -> list[Message]:
        path = self._path(conversation_id)  # id validation must not be swallowed below
        try:
            raw = json.loads(path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return []
        loaded = []
        for item in raw.get("messages", []) if isinstance(raw, dict) else []:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                loaded.append(Message(role=str(item.get("role") or "user"), text=item["text"]))
        return loaded

    def append(self, conversation_id: str, *new_messages: Message) -> list[Message]:
        messages = self.messages(conversation_id)
        messages.extend(new_messages)
        messages = messages[-self._max_messages :]
        path = self._path(conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump({"messages": [asdict(message) for message in messages]}, handle)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return messages
