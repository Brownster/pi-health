"""Mattermost v4 API surface for AA-005: admin bootstrap calls + bot posting.

Same idiom as `mattermost_integration_service.MattermostApiClient` (stdlib urllib with an
injected opener) but scoped to what the bot bootstrap and listener need. Tokens are held
in memory only; nothing here persists credentials.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib import error, request


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class BotApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MattermostBotApi:
    def __init__(self, site_url: str, *, opener: Callable[..., Any] = request.urlopen) -> None:
        self._site_url = site_url.rstrip("/")
        self._opener = opener
        self._token: str | None = None

    # -- sessions -------------------------------------------------------------
    def login(self, username: str, password: str) -> str:
        user, headers = self._request(
            "POST",
            "/api/v4/users/login",
            {"login_id": username, "password": password},
            authenticated=False,
        )
        token = headers.get("Token") or headers.get("token")
        if not token:
            raise BotApiError("Mattermost login did not return a session token")
        self._token = token
        return str(user["id"])

    def use_token(self, token: str) -> None:
        self._token = token

    def me(self) -> dict:
        user, _headers = self._request("GET", "/api/v4/users/me")
        return user

    def team_id(self, name: str) -> str:
        team, _headers = self._request("GET", f"/api/v4/teams/name/{name}")
        return str(team["id"])

    def channel_id(self, team_id: str, name: str) -> str:
        channel, _headers = self._request(
            "GET", f"/api/v4/teams/{team_id}/channels/name/{name}"
        )
        return str(channel["id"])

    # -- admin bootstrap -------------------------------------------------------
    def enable_bot_settings(self) -> None:
        """Enable bot-account creation and user access tokens (admin session)."""
        self._request(
            "PUT",
            "/api/v4/config/patch",
            {
                "ServiceSettings": {
                    "EnableBotAccountCreation": True,
                    "EnableUserAccessTokens": True,
                }
            },
        )

    def ensure_bot(self, *, username: str, display_name: str) -> str:
        """Create the bot or find the existing account. Returns the bot user id."""
        try:
            bot, _headers = self._request(
                "POST",
                "/api/v4/bots",
                {"username": username, "display_name": display_name},
            )
            return str(bot["user_id"])
        except BotApiError as exc:
            if exc.status not in {400, 409}:
                raise
        user, _headers = self._request("GET", f"/api/v4/users/username/{username}")
        return str(user["id"])

    def ensure_team_member(self, *, team_id: str, user_id: str) -> None:
        try:
            self._request(
                "POST",
                f"/api/v4/teams/{team_id}/members",
                {"team_id": team_id, "user_id": user_id},
            )
        except BotApiError as exc:
            if exc.status != 400:
                raise

    def ensure_channel_member(self, *, channel_id: str, user_id: str) -> None:
        try:
            self._request(
                "POST",
                f"/api/v4/channels/{channel_id}/members",
                {"user_id": user_id},
            )
        except BotApiError as exc:
            if exc.status != 400:
                raise

    def create_token(self, *, user_id: str, description: str) -> tuple[str, str]:
        """Create a user access token. Returns (token_id, token_secret)."""
        token, _headers = self._request(
            "POST",
            f"/api/v4/users/{user_id}/tokens",
            {"description": description},
        )
        return str(token["id"]), str(token["token"])

    def revoke_token(self, *, token_id: str) -> None:
        try:
            self._request("POST", "/api/v4/users/tokens/revoke", {"token_id": token_id})
        except BotApiError as exc:
            if exc.status != 404:
                raise

    def delete_bot(self, *, user_id: str) -> None:
        """Delete one known bot account; an already-absent bot is successful."""
        if not isinstance(user_id, str) or not _IDENTIFIER.fullmatch(user_id):
            raise BotApiError("Mattermost bot identifier is invalid")
        try:
            self._request("DELETE", f"/api/v4/bots/{user_id}")
        except BotApiError as exc:
            if exc.status != 404:
                raise

    # -- reading -----------------------------------------------------------------
    def get_post(self, post_id: str) -> dict:
        post, _headers = self._request("GET", f"/api/v4/posts/{post_id}")
        return post if isinstance(post, dict) else {}

    # -- posting ---------------------------------------------------------------
    def post_message(self, *, channel_id: str, message: str, root_id: str = "") -> str:
        payload: dict[str, Any] = {"channel_id": channel_id, "message": message}
        if root_id:
            payload["root_id"] = root_id
        post, _headers = self._request("POST", "/api/v4/posts", payload)
        return str(post["id"])

    # -- plumbing ----------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        authenticated: bool = True,
    ) -> tuple[Any, Mapping[str, str]]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if authenticated:
            if not self._token:
                raise BotApiError("Mattermost API session is not authenticated")
            headers["Authorization"] = f"Bearer {self._token}"
        body = json.dumps(payload).encode() if payload is not None else None
        req = request.Request(
            f"{self._site_url}{path}", data=body, headers=headers, method=method
        )
        try:
            response = self._opener(req, timeout=15)
            raw = response.read()
            parsed = json.loads(raw) if raw else {}
            return parsed, response.headers
        except error.HTTPError as exc:
            raise BotApiError(f"Mattermost API request failed ({exc.code})", exc.code) from exc
        except (error.URLError, TimeoutError, ValueError) as exc:
            raise BotApiError("Mattermost API is unavailable") from exc
