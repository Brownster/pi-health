"""AA-005 bot bootstrap: enable settings, ensure the bot, rotate its token.

Contract (AA-000 "Mattermost Transport Prerequisites"):
  1. The administrator password is write-only — used for one login, never stored, never
     included in the returned report.
  2. Bot-account creation and user access tokens are enabled through the config API.
  3. The `limeos` bot is created (or found) and added only to the configured team/channel.
  4. Its token is created (rotating any previously recorded token) and handed to the
     injected `secret_writer`; it never appears in the report or logs.
  5. The report is non-secret and safe to stream to the browser (AA-006).

The incoming alert webhook stays owned by the Mattermost integration; it is not reused
as the bot credential.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent_transport.bot_client import MattermostBotApi


@dataclass(frozen=True)
class BotSetupRequest:
    admin_username: str
    admin_password: str  # write-only; consumed for one login
    team_id: str
    channel_id: str
    bot_username: str = "limeos"
    bot_display_name: str = "LimeOS Assistant"
    previous_token_id: str | None = None  # rotate: revoke after the new token is stored


@dataclass
class BotSetupReport:
    """Non-secret outcome, safe for operation streams and audit."""

    bot_user_id: str = ""
    token_id: str = ""
    steps: list[str] = field(default_factory=list)


def run_bot_setup(
    api: MattermostBotApi,
    request: BotSetupRequest,
    *,
    secret_writer: Callable[[str], None],
) -> BotSetupReport:
    """Bootstrap the bot. The token secret goes only to `secret_writer`."""
    report = BotSetupReport()

    api.login(request.admin_username, request.admin_password)
    report.steps.append("admin-login")

    api.enable_bot_settings()
    report.steps.append("bot-settings-enabled")

    bot_user_id = api.ensure_bot(
        username=request.bot_username, display_name=request.bot_display_name
    )
    report.bot_user_id = bot_user_id
    report.steps.append("bot-ensured")

    api.ensure_team_member(team_id=request.team_id, user_id=bot_user_id)
    api.ensure_channel_member(channel_id=request.channel_id, user_id=bot_user_id)
    report.steps.append("memberships-ensured")

    token_id, token_secret = api.create_token(
        user_id=bot_user_id, description="limeos-agent-listener"
    )
    secret_writer(token_secret)
    report.token_id = token_id
    report.steps.append("token-stored")

    if request.previous_token_id and request.previous_token_id != token_id:
        api.revoke_token(token_id=request.previous_token_id)
        report.steps.append("previous-token-revoked")

    return report


def verify_threaded_delivery(api: MattermostBotApi, *, channel_id: str) -> bool:
    """Post a root message + threaded reply with the bot token (setup verification)."""
    root_id = api.post_message(
        channel_id=channel_id, message="LimeOS assistant connectivity check"
    )
    reply_id = api.post_message(
        channel_id=channel_id, message="Threaded reply OK", root_id=root_id
    )
    return bool(root_id and reply_id)
