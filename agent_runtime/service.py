"""Wire the provider, gateway, LimeOps client, and Mattermost listener on target."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent_gateway.gateway import AgentGateway, GatewayConfig, limeops_client_executor
from agent_provider.claude import ClaudeCodeProvider
from agent_transport.bot_client import MattermostBotApi
from agent_transport.listener import ListenerConfig, MentionListener, websocket_frames
from agent_transport.state import EventDedup, ThreadMap
from limeops.client import LimeOpsClient

DEFAULT_CONFIG_PATH = "/etc/limeos/integrations/agents.json"
DEFAULT_STATE_DIR = "/var/lib/limeos/integrations/agents"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ROOT_FIELDS = frozenset({"schema_version", "enabled", "mattermost", "limits"})
_MATTERMOST_REQUIRED_FIELDS = frozenset(
    {"site_url", "bot_username", "bot_user_id", "allowed_channels"}
)
_MATTERMOST_FIELDS = _MATTERMOST_REQUIRED_FIELDS | frozenset(
    {"team_id", "channel_id", "bot_token_id"}
)
_LIMIT_FIELDS = frozenset(
    {"turn_timeout_seconds", "tool_rounds_per_turn", "invocations_per_day"}
)

logger = logging.getLogger("limeos.agent.runtime")


class RuntimeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentRuntimeConfig:
    enabled: bool
    site_url: str
    bot_username: str
    bot_user_id: str
    allowed_channels: tuple[str, ...]
    team_id: str | None = None
    channel_id: str | None = None
    bot_token_id: str | None = None
    turn_timeout_seconds: float = 300
    tool_rounds_per_turn: int = 6
    invocations_per_day: int = 20


def _safe_id(value, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise RuntimeConfigError(f"Invalid {field}")
    return value


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AgentRuntimeConfig:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeConfigError("Agent settings are unavailable") from exc
    return parse_config(raw)


def parse_config(raw) -> AgentRuntimeConfig:
    if not isinstance(raw, dict) or set(raw) - _ROOT_FIELDS:
        raise RuntimeConfigError("Invalid agent settings")
    if raw.get("schema_version") != "1" or not isinstance(raw.get("enabled"), bool):
        raise RuntimeConfigError("Unsupported agent settings")
    mattermost = raw.get("mattermost")
    if (
        not isinstance(mattermost, dict)
        or set(mattermost) - _MATTERMOST_FIELDS
        or not _MATTERMOST_REQUIRED_FIELDS <= set(mattermost)
    ):
        raise RuntimeConfigError("Invalid Mattermost settings")
    site_url = mattermost.get("site_url")
    if not isinstance(site_url, str):
        raise RuntimeConfigError("Invalid Mattermost URL")
    parsed_url = urlsplit(site_url)
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.hostname
        or parsed_url.username
        or parsed_url.password
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise RuntimeConfigError("Invalid Mattermost URL")
    allowed_channels = mattermost.get("allowed_channels")
    if not isinstance(allowed_channels, list) or len(allowed_channels) > 32:
        raise RuntimeConfigError("Invalid Mattermost channel allowlist")
    channel_ids = tuple(_safe_id(item, "channel id") for item in allowed_channels)
    metadata = {}
    for field in ("team_id", "channel_id", "bot_token_id"):
        value = mattermost.get(field)
        metadata[field] = _safe_id(value, field) if value is not None else None

    limits = raw.get("limits", {})
    if not isinstance(limits, dict) or set(limits) - _LIMIT_FIELDS:
        raise RuntimeConfigError("Invalid agent limits")
    timeout = limits.get("turn_timeout_seconds", 300)
    rounds = limits.get("tool_rounds_per_turn", 6)
    daily = limits.get("invocations_per_day", 20)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 10 <= timeout <= 600:
        raise RuntimeConfigError("Invalid turn timeout")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10:
        raise RuntimeConfigError("Invalid tool round limit")
    if not isinstance(daily, int) or isinstance(daily, bool) or not 1 <= daily <= 1000:
        raise RuntimeConfigError("Invalid daily invocation limit")
    return AgentRuntimeConfig(
        enabled=raw["enabled"],
        site_url=site_url.rstrip("/"),
        bot_username=_safe_id(mattermost.get("bot_username"), "bot username"),
        bot_user_id=_safe_id(mattermost.get("bot_user_id"), "bot user id"),
        allowed_channels=channel_ids,
        **metadata,
        turn_timeout_seconds=float(timeout),
        tool_rounds_per_turn=rounds,
        invocations_per_day=daily,
    )


def build_listener(
    config: AgentRuntimeConfig,
    *,
    bot_token: str,
    state_dir: Path | str = DEFAULT_STATE_DIR,
    provider=None,
    limeops_client=None,
) -> MentionListener:
    if not bot_token or any(character in bot_token for character in ("\x00", "\n", "\r")):
        raise RuntimeConfigError("Mattermost bot credential is unavailable")
    provider = provider or ClaudeCodeProvider()
    limeops_client = limeops_client or LimeOpsClient()

    def canonical_context() -> str:
        envelope = limeops_client.request(
            "context", {}, {"type": "system", "id": "lime-agent"}
        )
        if not envelope.get("ok"):
            return "LimeOS context is temporarily unavailable."
        return json.dumps(envelope.get("data"), separators=(",", ":"))

    gateway = AgentGateway(
        state_dir=state_dir,
        provider=provider,
        limeops_executor=limeops_client_executor(limeops_client),
        config=GatewayConfig(
            turn_timeout_seconds=config.turn_timeout_seconds,
            tool_rounds_per_turn=config.tool_rounds_per_turn,
            invocations_per_day=config.invocations_per_day,
        ),
        context_provider=canonical_context,
    )
    api = MattermostBotApi(config.site_url)
    api.use_token(bot_token)
    return MentionListener(
        config=ListenerConfig(
            bot_username=config.bot_username,
            bot_user_id=config.bot_user_id,
            allowed_channels=config.allowed_channels,
        ),
        gateway=gateway,
        post_reply=api.post_message,
        dedup=EventDedup(state_dir),
        threads=ThreadMap(state_dir),
    )


def main() -> int:  # pragma: no cover - target service integration
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config(os.getenv("LIMEOS_AGENT_CONFIG", DEFAULT_CONFIG_PATH))
        if not config.enabled:
            logger.info("LimeOS assistant is disabled")
            return 0
        token = os.getenv("MATTERMOST_BOT_TOKEN", "")
        provider = ClaudeCodeProvider()
        health = provider.health()
        if not health.installed or not health.meets_minimum or not health.authenticated:
            logger.error("Claude Code is not installed, compatible, and authenticated")
            return 2
        listener = build_listener(config, bot_token=token, provider=provider)
        listener.run(lambda: websocket_frames(config.site_url, token))
        return 0
    except RuntimeConfigError as exc:
        logger.error("Agent runtime configuration error: %s", exc)
        return 2
    except Exception:
        logger.exception("Agent runtime stopped unexpectedly")
        return 1


if __name__ == "__main__":
    sys.exit(main())
