"""AA-006 framework-neutral AI Agents integration orchestration."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from agent_transport.bot_client import MattermostBotApi
from agent_transport.bot_setup import BotSetupRequest, run_bot_setup
from runtime_paths import STATIC_CONFIG_DIR

SETUP_TIMEOUT_SECONDS = 1200
_USERNAME = re.compile(r"^[a-z0-9._-]{3,64}$")
_RESOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SETUP_FIELDS = frozenset({"admin_username", "admin_password", "limits"})
_SAFE_HELPER_ERRORS = frozenset(
    {
        "Failed to install Claude Code",
        "Installed Claude Code version is unsupported",
        "Failed to activate agent runtime units",
        "Failed to prepare the isolated agent runtime",
        "Required LimeOps groups are unavailable",
        "Claude authentication is already running or unavailable",
    }
)
_DENIED_CAPABILITIES = (
    "container.restart",
    "container.stop",
    "stack.up",
    "stack.down",
    "file.read",
    "file.write",
    "shell.execute",
    "system.update",
)
_AUTH_URL_HOSTS = frozenset({"claude.ai", "claude.com", "console.anthropic.com"})


class AgentIntegrationError(Exception):
    """A bounded public integration failure."""


class AgentIntegrationService:
    def __init__(
        self,
        *,
        helper_call: Callable[..., dict],
        mattermost_status: Callable[[], dict],
        bot_api_factory: Callable[[str], MattermostBotApi] = MattermostBotApi,
        resource_provider: Callable[[], dict] = lambda: {"containers": [], "stacks": []},
        sleep: Callable[[float], None] = time.sleep,
        policy_path: Path | str = STATIC_CONFIG_DIR / "agent-policy.default.json",
        lifecycle_resolver=None,
    ) -> None:
        self._helper_call = helper_call
        self._mattermost_status = mattermost_status
        self._bot_api_factory = bot_api_factory
        self._resource_provider = resource_provider
        self._sleep = sleep
        self._policy_path = Path(policy_path)
        self._lifecycle_resolver = lifecycle_resolver

    def status(self) -> dict:
        mattermost = self._mattermost()
        if self._lifecycle_resolver is not None:
            authoritative = self._lifecycle_resolver.authoritative_status(
                self._public_status("not_installed", mattermost, {})
            )
            if authoritative is not None:
                return authoritative
        if not mattermost.get("installed"):
            return self._lifecycle_status(
                self._public_status("setup_required", mattermost, {})
            )
        runtime = self._call("agent_runtime_status", public_error="Agent runtime is unavailable")
        if not runtime.get("runtime_installed"):
            state = "not_installed"
        elif runtime.get("auth_state") == "running":
            state = "authenticating"
        elif (
            not runtime.get("configured")
            or not runtime.get("claude_installed")
            or not runtime.get("claude_compatible")
        ):
            state = "setup_required"
        elif not runtime.get("enabled"):
            state = "disabled"
        elif not runtime.get("claude_authenticated"):
            state = "setup_required"
        elif mattermost.get("state") == "disconnected":
            state = "disconnected"
        elif runtime.get("agent_active") == "active" and runtime.get("broker_active") == "active":
            state = "degraded" if mattermost.get("state") == "degraded" else "connected"
        elif runtime.get("agent_active") in {"failed", "activating"}:
            state = "degraded"
        else:
            state = "disconnected"
        public = self._public_status(state, mattermost, runtime)
        try:
            usage = self._call(
                "agent_usage_read", {"limit": 20}, public_error="Agent usage is unavailable"
            )
            successful = [
                record
                for record in usage.get("records", [])
                if isinstance(record, dict) and record.get("outcome") == "ok"
            ]
            public["last_successful_turn"] = successful[-1] if successful else None
        except AgentIntegrationError:
            public["last_successful_turn"] = None
        return self._lifecycle_status(public)

    def _lifecycle_status(self, status: dict) -> dict:
        if self._lifecycle_resolver is None:
            return status
        return self._lifecycle_resolver.status(status)

    def providers(self) -> dict:
        status = self.status()
        provider = status.get("provider") or {}
        return {
            "providers": [
                {
                    "id": "claude",
                    "name": "Claude Code",
                    "installed": bool(provider.get("installed")),
                    "version": provider.get("version"),
                    "authenticated": bool(provider.get("authenticated")),
                    "compatible": bool(provider.get("compatible")),
                    "state": status["state"],
                }
            ]
        }

    def stream_install(self, values: Mapping) -> Iterator[dict]:
        setup = self._validate_setup(values)
        return self._install(setup)

    def _install(self, setup: dict) -> Iterator[dict]:
        try:
            mattermost = self._require_mattermost()
            yield {"step": "provider", "line": "Installing Claude Code"}
            self._call(
                "agent_provider_install",
                timeout=SETUP_TIMEOUT_SECONDS,
                public_error="Claude Code installation failed",
            )
            yield {"step": "runtime", "line": "Preparing isolated agent runtime"}
            self._call(
                "agent_runtime_install",
                timeout=SETUP_TIMEOUT_SECONDS,
                public_error="Agent runtime installation failed",
            )
            yield {"step": "bot", "line": "Creating Mattermost assistant bot"}
            report, team_id, channel_id = self._setup_bot(mattermost, setup)
            yield {"step": "policy", "line": "Applying read-only permissions"}
            settings = self._settings(
                mattermost, report, team_id, channel_id, setup["limits"]
            )
            policy = self._policy()
            self._call(
                "agent_configure",
                {"settings": settings, "policy": policy},
                public_error="Agent configuration failed",
            )
            runtime = self._call(
                "agent_runtime_status", public_error="Agent runtime status is unavailable"
            )
            if runtime.get("claude_authenticated"):
                yield {"step": "service", "line": "Starting LimeOS assistant"}
                self._call("agent_runtime_start", public_error="Agent service failed to start")
                line = "AI Agents setup is ready"
                requires_auth = False
            else:
                line = "AI Agents is installed and requires Claude authentication"
                requires_auth = True
            yield {
                "step": "complete",
                "line": line,
                "requires_auth": requires_auth,
                "done": True,
            }
        except AgentIntegrationError as exc:
            yield {"step": "error", "error": str(exc)}
        except Exception:
            yield {"step": "error", "error": "AI Agents setup failed"}

    def stream_repair(self, values: Mapping) -> Iterator[dict]:
        if not isinstance(values, Mapping) or set(values) - _SETUP_FIELDS:
            raise AgentIntegrationError("Repair values are invalid")
        if values.get("admin_username") or values.get("admin_password"):
            return self.stream_install(values)

        def repair():
            try:
                self._require_mattermost()
                yield {"step": "provider", "line": "Repairing Claude Code installation"}
                self._call(
                    "agent_provider_install",
                    timeout=SETUP_TIMEOUT_SECONDS,
                    public_error="Claude Code repair failed",
                )
                yield {"step": "runtime", "line": "Repairing isolated agent runtime"}
                self._call(
                    "agent_runtime_install",
                    timeout=SETUP_TIMEOUT_SECONDS,
                    public_error="Agent runtime repair failed",
                )
                runtime = self._call(
                    "agent_runtime_status", public_error="Agent runtime is unavailable"
                )
                if not runtime.get("configured") or not runtime.get("claude_authenticated"):
                    raise AgentIntegrationError("Agent setup or Claude authentication is required")
                self._call("agent_runtime_start", public_error="Agent service failed to start")
                yield {"step": "complete", "line": "AI Agents repair completed", "done": True}
            except AgentIntegrationError as exc:
                yield {"step": "error", "error": str(exc)}

        return repair()

    def stream_auth(self) -> Iterator[dict]:
        try:
            yield from self._auth_events()
        except AgentIntegrationError as exc:
            yield {"step": "error", "error": str(exc)}
        except Exception:
            yield {"step": "error", "error": "Claude authentication failed"}

    def _auth_events(self) -> Iterator[dict]:
        started = self._call(
            "agent_provider_auth_start", public_error="Claude authentication could not start"
        )
        operation_id = started.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise AgentIntegrationError("Claude authentication could not start")
        cursor = 0
        yield {
            "step": "auth",
            "line": "Starting Claude authentication",
            "operation_id": operation_id,
        }
        while True:
            status = self._call(
                "agent_provider_auth_status",
                {"operation_id": operation_id, "cursor": cursor},
                public_error="Claude authentication status is unavailable",
            )
            cursor = status.get("cursor", cursor)
            for event in status.get("events", []):
                if event.get("type") == "authorization_url" and isinstance(event.get("url"), str):
                    if self._valid_auth_url(event["url"]):
                        yield {
                            "step": "authorization",
                            "authorization_url": event["url"],
                            "operation_id": operation_id,
                            "_ephemeral": True,
                        }
                elif event.get("type") == "input_required":
                    yield {
                        "step": "input_required",
                        "line": "Paste the authorization code to continue.",
                        "operation_id": operation_id,
                    }
                elif event.get("type") == "status":
                    yield {"step": "status", "line": str(event.get("message", ""))[:160]}
            state = status.get("state")
            if state == "complete":
                runtime = self._call(
                    "agent_runtime_status",
                    public_error="Agent runtime status is unavailable",
                )
                if runtime.get("configured"):
                    self._call("agent_runtime_start", public_error="Agent service failed to start")
                    yield {
                        "step": "complete",
                        "line": "Claude authentication completed",
                        "done": True,
                    }
                else:
                    yield {
                        "step": "complete",
                        "line": "Claude authentication completed. Finish assistant setup.",
                        "requires_setup": True,
                        "done": True,
                    }
                return
            if state in {"failed", "cancelled", "timeout"}:
                yield {"step": "error", "error": "Claude authentication failed"}
                return
            self._sleep(0.5)

    def submit_auth(self, operation_id: str, code: str) -> dict:
        self._call(
            "agent_provider_auth_submit",
            {"operation_id": operation_id, "code": code},
            public_error="Claude authentication response was rejected",
        )
        return {"accepted": True}

    def cancel_auth(self, operation_id: str) -> dict:
        self._call(
            "agent_provider_auth_cancel",
            {"operation_id": operation_id},
            public_error="Claude authentication cancellation failed",
        )
        return {"cancelled": True}

    def disable(self) -> dict:
        self._call("agent_runtime_disable", public_error="Agent disable failed")
        return {"state": "disabled"}

    def test_delivery(self) -> dict:
        self._call("agent_delivery_test", public_error="Assistant delivery test failed")
        return {"status": "sent"}

    def usage(self, *, limit: int = 50) -> dict:
        limit = self._limit(limit)
        result = self._call(
            "agent_usage_read", {"limit": limit}, public_error="Agent usage is unavailable"
        )
        return {"totals": result.get("totals") or {}, "records": result.get("records") or []}

    def audit(self, *, limit: int = 50) -> dict:
        limit = self._limit(limit)
        result = self._call(
            "agent_audit_read", {"limit": limit}, public_error="Agent audit is unavailable"
        )
        return {"records": result.get("records") or []}

    def permissions(self) -> dict:
        policy = self._policy()
        return {
            "profile": "read_only",
            "allowed_operations": sorted(
                name for name, config in policy["operations"].items() if config.get("enabled")
            ),
            "resources": {
                name: config.get("resources", [])
                for name, config in policy["operations"].items()
                if "resources" in config
            },
            "denied_capabilities": list(_DENIED_CAPABILITIES),
        }

    def _setup_bot(self, mattermost: dict, setup: dict):
        api = self._bot_api_factory(mattermost["site_url"])
        api.login(setup["admin_username"], setup["admin_password"])
        team_id = api.team_id(mattermost.get("team") or "limeos")
        channel_id = api.channel_id(team_id, mattermost.get("channel") or "limeos-alerts")
        previous_token_id = self._call(
            "agent_runtime_status", public_error="Agent runtime status is unavailable"
        ).get("bot_token_id")

        def store_secret(token):
            self._call(
                "agent_bot_secret_write",
                {"token": token},
                public_error="Mattermost bot credential could not be stored",
            )

        report = run_bot_setup(
            api,
            BotSetupRequest(
                admin_username=setup["admin_username"],
                admin_password=setup["admin_password"],
                team_id=team_id,
                channel_id=channel_id,
                previous_token_id=previous_token_id,
            ),
            secret_writer=store_secret,
        )
        return report, team_id, channel_id

    def _settings(
        self, mattermost: dict, report, team_id: str, channel_id: str, limits: dict
    ) -> dict:
        return {
            "schema_version": "1",
            "enabled": True,
            "mattermost": {
                "site_url": mattermost["site_url"],
                "bot_username": "limeos",
                "bot_user_id": report.bot_user_id,
                "allowed_channels": [channel_id],
                "team_id": team_id,
                "channel_id": channel_id,
                "bot_token_id": report.token_id,
            },
            "limits": limits,
        }

    def _policy(self) -> dict:
        try:
            policy = json.loads(self._policy_path.read_text())
        except (OSError, ValueError) as exc:
            raise AgentIntegrationError("Default agent policy is unavailable") from exc
        try:
            resources = self._resource_provider() or {}
        except Exception as exc:
            raise AgentIntegrationError("Agent resources are unavailable") from exc
        containers = self._resource_names(resources.get("containers"))
        stacks = self._resource_names(resources.get("stacks"))
        for name in ("container.status", "container.logs"):
            policy["operations"][name]["resources"] = containers
        for name in ("stack.status", "stack.inspect"):
            policy["operations"][name]["resources"] = stacks
        return policy

    @staticmethod
    def _resource_names(values) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        return sorted({value for value in values if isinstance(value, str) and _RESOURCE.fullmatch(value)})

    def _require_mattermost(self) -> dict:
        status = self._mattermost()
        if not status.get("installed") or status.get("state") not in {"connected", "degraded"}:
            raise AgentIntegrationError("Mattermost must be connected before AI Agents setup")
        if not isinstance(status.get("site_url"), str) or not status["site_url"]:
            raise AgentIntegrationError("Mattermost connection details are unavailable")
        return status

    def _mattermost(self) -> dict:
        try:
            status = self._mattermost_status()
        except Exception as exc:
            raise AgentIntegrationError("Mattermost status is unavailable") from exc
        return status if isinstance(status, dict) else {}

    @staticmethod
    def _valid_auth_url(value: str) -> bool:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname in _AUTH_URL_HOSTS
            and not parsed.username
            and not parsed.password
        )

    @staticmethod
    def _validate_setup(values: Mapping) -> dict:
        if not isinstance(values, Mapping) or set(values) - _SETUP_FIELDS:
            raise AgentIntegrationError("Setup values are invalid")
        username = values.get("admin_username")
        password = values.get("admin_password")
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            raise AgentIntegrationError("Mattermost administrator username is invalid")
        if (
            not isinstance(password, str)
            or not 10 <= len(password) <= 256
            or any(character in password for character in ("\x00", "\r", "\n"))
        ):
            raise AgentIntegrationError("Mattermost administrator password is invalid")
        limits = values.get("limits") or {}
        if not isinstance(limits, Mapping) or set(limits) - {
            "turn_timeout_seconds", "tool_rounds_per_turn", "invocations_per_day"
        }:
            raise AgentIntegrationError("Agent limits are invalid")
        normalized = {
            "turn_timeout_seconds": limits.get("turn_timeout_seconds", 300),
            "tool_rounds_per_turn": limits.get("tool_rounds_per_turn", 6),
            "invocations_per_day": limits.get("invocations_per_day", 20),
        }
        timeout, rounds, daily = normalized.values()
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 10 <= timeout <= 600:
            raise AgentIntegrationError("Agent limits are invalid")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or not 1 <= rounds <= 10:
            raise AgentIntegrationError("Agent limits are invalid")
        if not isinstance(daily, int) or isinstance(daily, bool) or not 1 <= daily <= 1000:
            raise AgentIntegrationError("Agent limits are invalid")
        return {"admin_username": username, "admin_password": password, "limits": normalized}

    def _call(self, command, params=None, *, timeout=30, public_error="Agent operation failed") -> dict:
        try:
            result = self._helper_call(command, params or {}, timeout=timeout)
        except Exception as exc:
            raise AgentIntegrationError(public_error) from exc
        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error") if isinstance(result, dict) else None
            message = error if error in _SAFE_HELPER_ERRORS else public_error
            raise AgentIntegrationError(message)
        return result

    @staticmethod
    def _limit(value) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 200:
            raise AgentIntegrationError("Limit must be between 1 and 200")
        return value

    @staticmethod
    def _public_status(state: str, mattermost: dict, runtime: dict) -> dict:
        return {
            "state": state,
            "installed": bool(runtime.get("runtime_installed")),
            "enabled": bool(runtime.get("enabled")),
            "configured": bool(runtime.get("configured")),
            "mattermost": {
                "state": mattermost.get("state", "not_installed"),
                "site_url": mattermost.get("site_url"),
                "team": mattermost.get("team"),
                "channel": mattermost.get("channel"),
            },
            "gateway": {
                "state": runtime.get("agent_active", "inactive"),
                "broker_state": runtime.get("broker_active", "inactive"),
            },
            "provider": {
                "id": "claude",
                "installed": bool(runtime.get("claude_installed")),
                "version": runtime.get("claude_version"),
                "compatible": bool(runtime.get("claude_compatible")),
                "authenticated": bool(runtime.get("claude_authenticated")),
            },
        }
