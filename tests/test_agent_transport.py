"""AA-005 Mattermost transport: events, state, bot bootstrap, listener loop."""

import io
import json

import pytest

from agent_transport.bot_client import BotApiError, MattermostBotApi
from agent_transport.bot_setup import BotSetupRequest, run_bot_setup, verify_threaded_delivery
from agent_transport.events import parse_frame
from agent_transport.gateway_contract import (
    MAX_TURN_INPUT_BYTES,
    TurnBusyError,
    TurnRequest,
    TurnResult,
)
from agent_transport.listener import ListenerConfig, MentionListener, chunk_reply
from agent_transport.state import EventDedup, ThreadMap

BOT = {"bot_username": "limeos", "bot_user_id": "bot-1"}


def _frame(message, *, post_id="p1", root_id="", channel="chan-1", user="user-1", sender="@marc"):
    return json.dumps(
        {
            "event": "posted",
            "data": {
                "sender_name": sender,
                "post": json.dumps(
                    {
                        "id": post_id,
                        "root_id": root_id,
                        "channel_id": channel,
                        "user_id": user,
                        "message": message,
                    }
                ),
            },
        }
    )


# -- events -------------------------------------------------------------------
def test_parse_frame_extracts_mention_and_strips_it():
    event = parse_frame(_frame("@limeos why is jellyfin down?"), **BOT)
    assert event is not None
    assert event.text == "why is jellyfin down?"
    assert event.root_post_id == "p1"  # new thread roots at the mention post
    assert event.username == "marc"


def test_parse_frame_keeps_existing_thread_root():
    event = parse_frame(_frame("@limeos more detail", root_id="root-9"), **BOT)
    assert event.root_post_id == "root-9"


@pytest.mark.parametrize(
    "frame_text",
    [
        _frame("no mention here"),
        _frame("@limeos hi", user="bot-1"),  # own post
        json.dumps({"event": "typing", "data": {}}),
        "not json",
        json.dumps({"event": "posted", "data": {"post": "not json"}}),
    ],
)
def test_parse_frame_ignores_non_mentions(frame_text):
    assert parse_frame(frame_text, **BOT) is None


def test_parse_frame_enforces_channel_allowlist():
    assert parse_frame(_frame("@limeos hi"), allowed_channels=("other",), **BOT) is None
    assert parse_frame(_frame("@limeos hi"), allowed_channels=("chan-1",), **BOT) is not None


# -- state ---------------------------------------------------------------------
def test_dedup_and_thread_map_survive_restart(tmp_path):
    dedup, threads = EventDedup(tmp_path), ThreadMap(tmp_path)
    assert not dedup.seen("p1")
    dedup.mark("p1")
    conversation = threads.conversation_for("root-1")

    dedup2, threads2 = EventDedup(tmp_path), ThreadMap(tmp_path)
    assert dedup2.seen("p1")
    assert threads2.conversation_for("root-1") == conversation


def test_dedup_is_bounded(tmp_path):
    dedup = EventDedup(tmp_path)
    for index in range(520):
        dedup.mark(f"p{index}")
    assert not dedup.seen("p0")  # oldest evicted
    assert dedup.seen("p519")


# -- bot client / setup ----------------------------------------------------------
class FakeOpener:
    """Responds by (method, path); records every request for assertions."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, req, timeout=15):
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), req.selector, body))
        status, payload, headers = self.routes.get(
            (req.get_method(), req.selector), (200, {}, {})
        )
        if status >= 400:
            from urllib.error import HTTPError

            raise HTTPError(req.full_url, status, "error", {}, io.BytesIO(b"{}"))
        response = io.BytesIO(json.dumps(payload).encode())
        response.headers = headers
        return response


def _setup_routes(*, bot_create_status=200):
    return {
        ("POST", "/api/v4/users/login"): (200, {"id": "admin-1"}, {"Token": "admin-token"}),
        ("PUT", "/api/v4/config/patch"): (200, {}, {}),
        ("POST", "/api/v4/bots"): (bot_create_status, {"user_id": "bot-1"}, {}),
        ("GET", "/api/v4/users/username/limeos"): (200, {"id": "bot-1"}, {}),
        ("POST", "/api/v4/teams/team-1/members"): (200, {}, {}),
        ("POST", "/api/v4/channels/chan-1/members"): (200, {}, {}),
        ("POST", "/api/v4/users/bot-1/tokens"): (200, {"id": "tok-1", "token": "SECRET"}, {}),
        ("POST", "/api/v4/users/tokens/revoke"): (200, {}, {}),
    }


def _request(**overrides):
    values = {
        "admin_username": "admin",
        "admin_password": "write-only-password",
        "team_id": "team-1",
        "channel_id": "chan-1",
    }
    values.update(overrides)
    return BotSetupRequest(**values)


def test_bot_setup_full_flow_keeps_secrets_out_of_the_report():
    opener = FakeOpener(_setup_routes())
    stored = []
    report = run_bot_setup(
        MattermostBotApi("http://mm:8065", opener=opener),
        _request(),
        secret_writer=stored.append,
    )
    assert stored == ["SECRET"]  # token goes only to the secret writer
    assert report.bot_user_id == "bot-1" and report.token_id == "tok-1"
    assert "token-stored" in report.steps
    # Neither secret appears anywhere in the non-secret report.
    blob = json.dumps(report.__dict__)
    assert "SECRET" not in blob and "write-only-password" not in blob
    # Bot settings were enabled through the config API.
    assert ("PUT", "/api/v4/config/patch", {
        "ServiceSettings": {"EnableBotAccountCreation": True, "EnableUserAccessTokens": True}
    }) in opener.requests


def test_bot_setup_finds_existing_bot_and_rotates_previous_token():
    opener = FakeOpener(_setup_routes(bot_create_status=400))
    report = run_bot_setup(
        MattermostBotApi("http://mm:8065", opener=opener),
        _request(previous_token_id="tok-old"),
        secret_writer=lambda _secret: None,
    )
    assert report.bot_user_id == "bot-1"
    assert "previous-token-revoked" in report.steps
    assert ("POST", "/api/v4/users/tokens/revoke", {"token_id": "tok-old"}) in opener.requests


def test_verify_threaded_delivery_posts_root_then_reply():
    routes = {("POST", "/api/v4/posts"): (200, {"id": "post-1"}, {})}
    opener = FakeOpener(routes)
    api = MattermostBotApi("http://mm:8065", opener=opener)
    api.use_token("bot-token")
    assert verify_threaded_delivery(api, channel_id="chan-1") is True
    assert opener.requests[1][2]["root_id"] == "post-1"  # second post is threaded


def test_bot_client_raises_typed_error_with_status():
    opener = FakeOpener({("POST", "/api/v4/users/login"): (401, {}, {})})
    with pytest.raises(BotApiError) as excinfo:
        MattermostBotApi("http://mm:8065", opener=opener).login("a", "b")
    assert excinfo.value.status == 401


def test_bot_client_resolves_team_and_channel_ids():
    opener = FakeOpener(
        {
            ("GET", "/api/v4/teams/name/limeos"): (200, {"id": "team-1"}, {}),
            (
                "GET",
                "/api/v4/teams/team-1/channels/name/limeos-alerts",
            ): (200, {"id": "channel-1"}, {}),
        }
    )
    api = MattermostBotApi("http://mm:8065", opener=opener)
    api.use_token("admin-token")
    assert api.team_id("limeos") == "team-1"
    assert api.channel_id("team-1", "limeos-alerts") == "channel-1"


# -- listener --------------------------------------------------------------------
class FakeGateway:
    def __init__(self, result_text="All healthy.", raises=None):
        self.requests: list[TurnRequest] = []
        self.result_text = result_text
        self.raises = raises

    def handle_turn(self, request):
        self.requests.append(request)
        if self.raises:
            raise self.raises
        return TurnResult(text=self.result_text)


def _listener(tmp_path, gateway, posts, **config_overrides):
    def post_reply(*, channel_id, message, root_id):
        posts.append((channel_id, root_id, message))
        return f"reply-{len(posts)}"

    return MentionListener(
        config=ListenerConfig(bot_username="limeos", bot_user_id="bot-1", **config_overrides),
        gateway=gateway,
        post_reply=post_reply,
        dedup=EventDedup(tmp_path),
        threads=ThreadMap(tmp_path),
    )


def test_listener_runs_turn_and_replies_in_thread(tmp_path):
    gateway, posts = FakeGateway(), []
    listener = _listener(tmp_path, gateway, posts)
    assert listener.handle_frame(_frame("@limeos status please", root_id="root-1")) is True
    assert gateway.requests[0].text == "status please"
    assert gateway.requests[0].root_post_id == "root-1"
    assert gateway.requests[0].conversation_id.startswith("conv-")
    assert posts == [("chan-1", "root-1", "All healthy.")]


def test_listener_dedups_duplicate_frames(tmp_path):
    gateway, posts = FakeGateway(), []
    listener = _listener(tmp_path, gateway, posts)
    frame = _frame("@limeos hello")
    assert listener.handle_frame(frame) is True
    assert listener.handle_frame(frame) is False  # duplicate delivery dropped
    assert len(gateway.requests) == 1 and len(posts) == 1


def test_listener_same_thread_maps_to_same_conversation(tmp_path):
    gateway, posts = FakeGateway(), []
    listener = _listener(tmp_path, gateway, posts)
    listener.handle_frame(_frame("@limeos one", post_id="p1", root_id="root-1"))
    listener.handle_frame(_frame("@limeos two", post_id="p2", root_id="root-1"))
    assert gateway.requests[0].conversation_id == gateway.requests[1].conversation_id


def test_listener_posts_typed_public_message_on_turn_error(tmp_path):
    gateway, posts = FakeGateway(raises=TurnBusyError()), []
    _listener(tmp_path, gateway, posts).handle_frame(_frame("@limeos hi"))
    assert posts[0][2] == TurnBusyError.public_message


def test_listener_never_leaks_internal_errors(tmp_path):
    gateway, posts = FakeGateway(raises=RuntimeError("secret-connection-string")), []
    _listener(tmp_path, gateway, posts).handle_frame(_frame("@limeos hi"))
    assert "secret-connection-string" not in posts[0][2]


def test_listener_chunks_long_replies(tmp_path):
    gateway, posts = FakeGateway(result_text="x" * 8000), []
    _listener(tmp_path, gateway, posts, reply_chunk_chars=3500).handle_frame(
        _frame("@limeos long")
    )
    assert [len(message) for (_c, _r, message) in posts] == [3500, 3500, 1000]


def test_listener_truncates_oversized_input(tmp_path):
    gateway, posts = FakeGateway(), []
    _listener(tmp_path, gateway, posts).handle_frame(_frame("@limeos " + "y" * 40000))
    assert len(gateway.requests[0].text.encode()) <= MAX_TURN_INPUT_BYTES


def test_listener_reconnects_with_backoff(tmp_path):
    gateway, posts, sleeps = FakeGateway(), [], []
    listener = _listener(tmp_path, gateway, posts)
    attempts = []

    def connect():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("ws down")
        return iter([_frame("@limeos back online")])

    listener.run(connect, sleeper=sleeps.append, max_connects=3)
    assert len(attempts) == 3
    assert sleeps == [1, 5]  # capped backoff between reconnects
    assert len(gateway.requests) == 1


def test_chunk_reply_enforces_output_ceiling():
    chunks = chunk_reply("z" * (64 * 1024), chunk_chars=4000)
    assert sum(len(chunk) for chunk in chunks) == 32 * 1024
