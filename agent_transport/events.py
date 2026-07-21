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


@dataclass(frozen=True)
class ReactionEvent:
    post_id: str
    channel_id: str
    user_id: str
    username: str
    emoji_name: str


#: Bound for thread-root context included in a turn (alert posts are small; hostile
#: or pathological roots must not eat the 32 KiB turn budget).
MAX_ROOT_TEXT_CHARS = 4096


def _strip_mention(message: str, bot_username: str) -> str:
    return re.sub(rf"@{re.escape(bot_username)}\b", "", message).strip()


def extract_post_text(post: dict) -> str:
    """Readable text of a Mattermost post, including webhook attachments.

    Alert incidents are incoming-webhook posts whose content lives in
    ``props.attachments`` (title/text/fields), not ``message`` — without this the
    assistant investigates an alert thread blind.
    """
    parts: list[str] = []
    message = str(post.get("message") or "").strip()
    if message:
        parts.append(message)
    attachments = ((post.get("props") or {}).get("attachments")) or []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        for key in ("title", "text"):
            value = str(attachment.get(key) or "").strip()
            if value:
                parts.append(value)
        for field in attachment.get("fields") or []:
            if isinstance(field, dict):
                title = str(field.get("title") or "").strip()
                value = str(field.get("value") or "").strip()
                if title or value:
                    parts.append(f"{title}: {value}".strip(": "))
    return "\n".join(parts)[:MAX_ROOT_TEXT_CHARS]


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


def parse_reaction_frame(frame_text: str, *, bot_user_id: str) -> ReactionEvent | None:
    try:
        frame = json.loads(frame_text)
    except ValueError:
        return None
    if not isinstance(frame, dict) or frame.get("event") != "reaction_added":
        return None
    data = frame.get("data") or {}
    try:
        reaction = json.loads(data.get("reaction") or "{}")
    except ValueError:
        return None
    if not isinstance(reaction, dict) or reaction.get("user_id") == bot_user_id:
        return None
    post_id = reaction.get("post_id")
    user_id = reaction.get("user_id")
    emoji_name = reaction.get("emoji_name")
    channel_id = data.get("channel_id") or (frame.get("broadcast") or {}).get("channel_id")
    if not all(isinstance(value, str) and value for value in (post_id, user_id, emoji_name, channel_id)):
        return None
    return ReactionEvent(
        post_id=post_id,
        channel_id=channel_id,
        user_id=user_id,
        username=str(data.get("sender_name") or "").lstrip("@"),
        emoji_name=emoji_name,
    )
