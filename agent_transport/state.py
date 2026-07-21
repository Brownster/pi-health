"""Restart-safe listener state: event deduplication + thread->conversation mapping.

Duplicate websocket delivery and gateway restarts must not duplicate replies (baseline:
"Restarting the gateway preserves thread mappings and event deduplication"). Both stores
persist as atomically-replaced JSON under the agent state directory
(`/var/lib/lime-agent/state/` on the target; injected in tests).
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

_DEDUP_KEEP = 500  # bounded: enough to cover reconnect replay windows
_APPROVAL_KEEP = 200


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text())
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


class EventDedup:
    """Have we already handled this post? Insertion-ordered, bounded, persisted."""

    def __init__(self, state_dir: Path | str) -> None:
        self._path = Path(state_dir) / "seen-events.json"
        loaded = _load(self._path).get("seen")
        self._seen: dict[str, None] = dict.fromkeys(loaded if isinstance(loaded, list) else [])

    def seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark(self, event_id: str) -> None:
        self._seen[event_id] = None
        while len(self._seen) > _DEDUP_KEEP:
            self._seen.pop(next(iter(self._seen)))
        _atomic_write(self._path, {"seen": list(self._seen)})


class ThreadMap:
    """One Mattermost root post <-> one gateway conversation id. Persisted."""

    def __init__(self, state_dir: Path | str) -> None:
        self._path = Path(state_dir) / "thread-map.json"
        loaded = _load(self._path).get("threads")
        self._threads: dict[str, str] = dict(loaded) if isinstance(loaded, dict) else {}

    def known(self, root_post_id: str) -> bool:
        return root_post_id in self._threads

    def conversation_for(self, root_post_id: str) -> str:
        existing = self._threads.get(root_post_id)
        if existing:
            return existing
        conversation_id = f"conv-{uuid.uuid4().hex}"
        self._threads[root_post_id] = conversation_id
        _atomic_write(self._path, {"threads": self._threads})
        return conversation_id


class ApprovalPostMap:
    """Restart-safe Mattermost proposal post -> action binding."""

    def __init__(self, state_dir: Path | str) -> None:
        self._path = Path(state_dir) / "approval-posts.json"
        loaded = _load(self._path).get("posts")
        self._posts = dict(loaded) if isinstance(loaded, dict) else {}

    def bind(self, post_id: str, *, action_id: str, channel_id: str, root_id: str) -> None:
        self._posts[post_id] = {
            "action_id": action_id,
            "channel_id": channel_id,
            "root_id": root_id,
            "resolved": False,
        }
        while len(self._posts) > _APPROVAL_KEEP:
            self._posts.pop(next(iter(self._posts)))
        self._save()

    def pending(self, post_id: str) -> dict[str, str] | None:
        value = self._posts.get(post_id)
        if not isinstance(value, dict) or value.get("resolved") is not False:
            return None
        required = ("action_id", "channel_id", "root_id")
        if any(not isinstance(value.get(field), str) or not value[field] for field in required):
            return None
        return {field: value[field] for field in required}

    def resolve(self, post_id: str) -> None:
        if isinstance(self._posts.get(post_id), dict):
            self._posts[post_id]["resolved"] = True
            self._save()

    def _save(self) -> None:
        _atomic_write(self._path, {"posts": self._posts})
