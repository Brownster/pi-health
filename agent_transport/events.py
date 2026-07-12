"""Parse Mattermost websocket frames into mention events (pure).

A frame is the JSON text Mattermost sends over `/api/v4/websocket`. Only `posted` events
that explicitly mention the bot, are not the bot's own posts, and (when configured) fall
inside the channel allowlist become `MentionEvent`s. Everything else returns None.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True)
class MentionEvent:
    post_id: str
    root_post_id: str  # == post_id when the mention starts a new thread
    channel_id: str
    user_id: str
    username: str
    text: str  # mention-stripped


def _strip_mention(message: str, bot_username: str) -> str:
    return re.sub(rf"@{re.escape(bot_username)}\b", "", message).strip()


def parse_frame(
    frame_text: str,
    *,
    bot_username: str,
    bot_user_id: str,
    allowed_channels: Collection[str] = (),
) -> MentionEvent | None:
    try:
        frame = json.loads(frame_text)
    except ValueError:
        return None
    if not isinstance(frame, dict) or frame.get("event") != "posted":
        return None
    data = frame.get("data") or {}
    try:
        post = json.loads(data.get("post") or "{}")
    except ValueError:
        return None
    if not isinstance(post, dict) or not post.get("id"):
        return None

    message = str(post.get("message") or "")
    if post.get("user_id") == bot_user_id:
        return None  # never respond to our own posts
    if f"@{bot_username}" not in message:
        return None  # explicit mentions only
    channel_id = str(post.get("channel_id") or "")
    if allowed_channels and channel_id not in allowed_channels:
        return None

    post_id = str(post["id"])
    return MentionEvent(
        post_id=post_id,
        root_post_id=str(post.get("root_id") or "") or post_id,
        channel_id=channel_id,
        user_id=str(post.get("user_id") or ""),
        username=str(data.get("sender_name") or "").lstrip("@"),
        text=_strip_mention(message, bot_username),
    )
