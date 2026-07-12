"""AA-004 production wiring across provider, gateway, LimeOps, and transport."""

from __future__ import annotations

import json

import pytest

from agent_gateway.provider import FinalAnswer
from agent_runtime.service import RuntimeConfigError, build_listener, load_config


def _settings(**overrides):
    raw = {
        "schema_version": "1",
        "enabled": True,
        "mattermost": {
            "site_url": "http://mattermost.local:8065",
            "bot_username": "limeos",
            "bot_user_id": "bot-1",
            "allowed_channels": ["channel-1"],
        },
        "limits": {
            "turn_timeout_seconds": 300,
            "tool_rounds_per_turn": 6,
            "invocations_per_day": 20,
        },
    }
    raw.update(overrides)
    return raw


def test_runtime_config_is_strict_and_non_secret(tmp_path):
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(_settings()))
    config = load_config(path)
    assert config.site_url == "http://mattermost.local:8065"
    assert config.allowed_channels == ("channel-1",)

    raw = _settings(secret="must-not-be-accepted")
    path.write_text(json.dumps(raw))
    with pytest.raises(RuntimeConfigError):
        load_config(path)


def test_runtime_config_accepts_non_secret_bot_metadata(tmp_path):
    raw = _settings()
    raw["mattermost"].update(
        team_id="team-1", channel_id="channel-1", bot_token_id="token-1"
    )
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(raw))
    config = load_config(path)
    assert (config.team_id, config.channel_id, config.bot_token_id) == (
        "team-1",
        "channel-1",
        "token-1",
    )


@pytest.mark.parametrize(
    "mattermost",
    [
        {
            "site_url": "http://user:password@mattermost.local",
            "bot_username": "limeos",
            "bot_user_id": "bot-1",
            "allowed_channels": [],
        },
        {
            "site_url": "file:///etc/passwd",
            "bot_username": "limeos",
            "bot_user_id": "bot-1",
            "allowed_channels": [],
        },
        {
            "site_url": "http://mattermost.local",
            "bot_username": "../bad",
            "bot_user_id": "bot-1",
            "allowed_channels": [],
        },
    ],
)
def test_runtime_config_rejects_credential_urls_and_unsafe_ids(tmp_path, mattermost):
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(_settings(mattermost=mattermost)))
    with pytest.raises(RuntimeConfigError):
        load_config(path)


class FinalProvider:
    def invoke(self, _context, *, timeout_seconds):
        return FinalAnswer(f"healthy within {timeout_seconds}")


class FakeLimeOps:
    def __init__(self):
        self.calls = []

    def request(self, operation, params, actor):
        self.calls.append((operation, params, actor))
        return {
            "ok": True,
            "data": {"summary": "canonical"},
            "warnings": [],
            "error": None,
            "audit_id": "audit-1",
        }


def test_runtime_listener_uses_system_actor_for_context_and_mattermost_actor_for_tools(
    tmp_path,
):
    config_path = tmp_path / "agents.json"
    config_path.write_text(json.dumps(_settings()))
    client = FakeLimeOps()
    listener = build_listener(
        load_config(config_path),
        bot_token="bot-token",
        state_dir=tmp_path / "state",
        provider=FinalProvider(),
        limeops_client=client,
    )
    # Exercise the provider context path without a live Mattermost API by replacing posting.
    listener._post_reply = lambda **_kwargs: "reply-1"
    frame = json.dumps(
        {
            "event": "posted",
            "data": {
                "sender_name": "@marc",
                "post": json.dumps(
                    {
                        "id": "post-1",
                        "root_id": "",
                        "channel_id": "channel-1",
                        "user_id": "user-1",
                        "message": "@limeos status",
                    }
                ),
            },
        }
    )
    assert listener.handle_frame(frame) is True
    assert client.calls[0] == ("context", {}, {"type": "system", "id": "lime-agent"})


def test_runtime_rejects_missing_or_multiline_bot_token(tmp_path):
    path = tmp_path / "agents.json"
    path.write_text(json.dumps(_settings()))
    config = load_config(path)
    for token in ("", "token\nINJECT=yes"):
        with pytest.raises(RuntimeConfigError):
            build_listener(
                config,
                bot_token=token,
                state_dir=tmp_path / "state",
                provider=FinalProvider(),
                limeops_client=FakeLimeOps(),
            )
