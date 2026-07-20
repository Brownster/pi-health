"""Mattermost stack installation, bootstrap, and alert policy management."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from alert_evaluator import Notification
from alert_notifier import MattermostWebhookNotifier
from alert_policy import AlertPolicy, AlertPolicyError, default_alert_policy, normalize_alert_policy
from compose_yaml import dump_compose_yaml


INTEGRATION_VERSION = 1
MATTERMOST_VERSION = "11.8.3"
MATTERMOST_ARM64_SHA256 = "c784ca5d34cfe3793a31a6a7d17d209e0d916bb744a50df776c78aa318d5b98f"
ALERTD_SOURCE_FILES = (
    "alert_daemon.py",
    "alert_history.py",
    "alert_evaluator.py",
    "alert_notifier.py",
    "alert_policy.py",
    "alert_signals.py",
    "helper_client.py",
    "runtime_paths.py",
)
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,64}$")

#: A single dedicated channel receives normalized *arr (Radarr/Sonarr/…) webhooks.
STACK_NOTIFICATIONS_CHANNEL = "stack-notifications"
STACK_NOTIFICATIONS_DISPLAY = "Stack Notifications"
STACK_NOTIFICATIONS_WEBHOOK_NAME = "LimeOS Stack Notifications"

#: The nightly package job posts held/critical pending updates here for review/approval.
PACKAGE_UPDATES_CHANNEL = "limeos-updates"
PACKAGE_UPDATES_DISPLAY = "LimeOS Updates"
PACKAGE_UPDATES_WEBHOOK_NAME = "LimeOS Updates"


class MattermostIntegrationError(Exception):
    """Raised when Mattermost setup or management fails."""


class MattermostApiError(MattermostIntegrationError):
    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)


class MattermostApiClient:
    """Small Mattermost v4 API client used only during bootstrap."""

    def __init__(self, site_url: str, *, opener: Callable[..., Any] = request.urlopen) -> None:
        self._site_url = site_url.rstrip("/")
        self._opener = opener
        self._token: str | None = None

    def ping(self) -> None:
        self._request("GET", "/api/v4/system/ping", authenticated=False)

    def ensure_admin(self, *, username: str, email: str, password: str) -> str:
        try:
            return self.login(username, password)
        except MattermostApiError as exc:
            if exc.status not in {400, 401}:
                raise

        try:
            created, _headers = self._request(
                "POST",
                "/api/v4/users",
                {"username": username, "email": email, "password": password},
                authenticated=False,
            )
        except MattermostApiError as exc:
            if exc.status != 400:
                raise
            # The account may exist after a partial setup. Login distinguishes
            # that case from invalid credentials without listing users publicly.
        self.login(username, password)
        if "created" in locals() and isinstance(created, dict):
            return str(created.get("id", ""))
        me, _headers = self._request("GET", "/api/v4/users/me")
        return str(me["id"])

    def login(self, username: str, password: str) -> str:
        user, headers = self._request(
            "POST",
            "/api/v4/users/login",
            {"login_id": username, "password": password},
            authenticated=False,
        )
        token = headers.get("Token") or headers.get("token")
        if not token:
            raise MattermostApiError("Mattermost login did not return a session token")
        self._token = token
        return str(user["id"])

    def ensure_team(self, *, name: str, display_name: str) -> str:
        try:
            team, _headers = self._request("GET", f"/api/v4/teams/name/{name}")
        except MattermostApiError as exc:
            if exc.status != 404:
                raise
            team, _headers = self._request(
                "POST",
                "/api/v4/teams",
                {"name": name, "display_name": display_name, "type": "O"},
            )
        return str(team["id"])

    def ensure_team_member(self, *, team_id: str, user_id: str) -> None:
        try:
            self._request(
                "POST",
                f"/api/v4/teams/{team_id}/members",
                {"team_id": team_id, "user_id": user_id},
            )
        except MattermostApiError as exc:
            if exc.status != 400:
                raise

    def ensure_channel(
        self, *, team_id: str, name: str, display_name: str
    ) -> str:
        try:
            channel, _headers = self._request(
                "GET", f"/api/v4/teams/{team_id}/channels/name/{name}"
            )
        except MattermostApiError as exc:
            if exc.status != 404:
                raise
            channel, _headers = self._request(
                "POST",
                "/api/v4/channels",
                {
                    "team_id": team_id,
                    "name": name,
                    "display_name": display_name,
                    "type": "O",
                },
            )
        return str(channel["id"])

    def ensure_incoming_webhook(
        self,
        *,
        team_id: str,
        channel_id: str,
        display_name: str = "LimeOS Alerts",
        description: str = "Health incidents from LimeOS",
    ) -> str:
        hooks, _headers = self._request(
            "GET", f"/api/v4/hooks/incoming?team_id={team_id}&page=0&per_page=100"
        )
        for hook in hooks if isinstance(hooks, list) else []:
            # Match on our display_name so distinct channels (alerts vs stack
            # notifications) keep distinct webhooks rather than colliding.
            if hook.get("display_name") == display_name and hook.get("id"):
                return f"{self._site_url}/hooks/{hook['id']}"
        hook, _headers = self._request(
            "POST",
            "/api/v4/hooks/incoming",
            {
                "channel_id": channel_id,
                "display_name": display_name,
                "description": description,
            },
        )
        return f"{self._site_url}/hooks/{hook['id']}"

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
                raise MattermostApiError("Mattermost API session is not authenticated")
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
            raise MattermostApiError(
                f"Mattermost API request failed ({exc.code})", exc.code
            ) from exc
        except (error.URLError, TimeoutError, ValueError) as exc:
            raise MattermostApiError("Mattermost API is unavailable") from exc


class MattermostIntegrationService:
    """Own the Mattermost stack and its LimeOS alert configuration."""

    def __init__(
        self,
        *,
        config_path: Path,
        secrets_path: Path,
        status_path: Path,
        stack_path_provider: Callable[[str], str],
        config_repository: Any,
        atomic_writer: Callable[..., None],
        compose_runner: Callable[..., Any] = subprocess.run,
        api_factory: Callable[[str], MattermostApiClient] = MattermostApiClient,
        notifier_factory: Callable[[str], Any] = MattermostWebhookNotifier,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        container_status_provider: Callable[[str], Mapping[str, Any] | None] | None = None,
        stack_notifications_config_path: Path | None = None,
        package_updates_config_path: Path | None = None,
        lifecycle_resolver: Any | None = None,
        agent_lifecycle_snapshot: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._stack_notifications_config_path = (
            Path(stack_notifications_config_path)
            if stack_notifications_config_path is not None
            else None
        )
        self._package_updates_config_path = (
            Path(package_updates_config_path)
            if package_updates_config_path is not None
            else None
        )
        self._secrets_path = Path(secrets_path)
        self._status_path = Path(status_path)
        self._stack_path_provider = stack_path_provider
        self._repository = config_repository
        self._atomic_writer = atomic_writer
        self._compose_runner = compose_runner
        self._api_factory = api_factory
        self._notifier_factory = notifier_factory
        self._sleep = sleep
        self._clock = clock
        self._container_status_provider = container_status_provider
        self._lifecycle_resolver = lifecycle_resolver
        self._agent_lifecycle_snapshot = agent_lifecycle_snapshot

    def status(self) -> dict[str, Any]:
        config = self._load_config()
        daemon = self._repository.read_json(self._status_path, default={}) or {}
        installed = bool(config.get("installed"))
        state = "connected" if installed else "not_installed"
        delivery = daemon.get("delivery") or {}
        services = self._service_statuses() if installed else {}
        if services and any(value.get("state") != "running" for value in services.values()):
            state = "disconnected"
        elif services and any(value.get("health") == "unhealthy" for value in services.values()):
            state = "degraded"
        if state == "connected" and delivery.get("ok") is False:
            state = "degraded"
        public = {
            "state": state,
            "installed": installed,
            "site_url": config.get("site_url"),
            "stack_name": config.get("stack_name", "mattermost"),
            "team": config.get("team_name", "limeos"),
            "channel": config.get("channel_name", "limeos-alerts"),
            "webhook_configured": self._read_secret("LIMEOS_ALERT_MATTERMOST_WEBHOOK") is not None,
            "updates_channel_configured": self._updates_channel_configured(),
            "policy": self._policy(config),
            "resources": daemon.get("resources", []),
            "incidents": daemon.get("incidents", []),
            "delivery": delivery,
            "updated_at": daemon.get("updated_at"),
            "services": services,
        }
        if self._lifecycle_resolver is not None:
            public = self._lifecycle_resolver.status(public)
            if self._agent_lifecycle_snapshot is not None:
                try:
                    snapshot = self._agent_lifecycle_snapshot()
                except Exception:
                    snapshot = {
                        "state": "cleanup_required",
                        "installed": True,
                        "enabled": True,
                    }
                public = self._lifecycle_resolver.apply_mattermost_dependencies(
                    public, snapshot
                )
        return public

    def _updates_channel_configured(self) -> bool:
        if self._package_updates_config_path is None:
            return False
        config = self._repository.read_json(self._package_updates_config_path, default={}) or {}
        return bool(config.get("webhook_url"))

    def update_policy(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        policy = normalize_alert_policy(raw)
        config = self._load_config()
        config["version"] = INTEGRATION_VERSION
        config["policy"] = policy
        self._repository.write_json(self._config_path, config, mode=0o640)
        return policy

    def send_test(self) -> dict[str, Any]:
        webhook = self._read_secret("LIMEOS_ALERT_MATTERMOST_WEBHOOK")
        if not webhook:
            raise MattermostIntegrationError("Mattermost webhook is not configured")
        notification = Notification(
            event="incident",
            key="integration:test",
            kind="generic",
            severity="warning",
            summary="LimeOS alert delivery is working.",
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock())),
        )
        self._notifier_factory(webhook).send(notification)
        return {"status": "sent", "at": notification.at}

    def _provision_stack_notifications(self, client: Any, team_id: str) -> str:
        """Create the shared #stack-notifications channel + webhook and persist config.

        Idempotent: the ``ensure_*`` calls no-op when the channel/webhook exist, and an
        existing token/mode is preserved so re-running never rotates the token *arr apps
        are already pointed at.
        """
        channel_id = client.ensure_channel(
            team_id=team_id,
            name=STACK_NOTIFICATIONS_CHANNEL,
            display_name=STACK_NOTIFICATIONS_DISPLAY,
        )
        webhook = client.ensure_incoming_webhook(
            team_id=team_id,
            channel_id=channel_id,
            display_name=STACK_NOTIFICATIONS_WEBHOOK_NAME,
            description="Normalized Radarr/Sonarr/*arr notifications",
        )
        self._write_stack_notifications_config(webhook_url=webhook)
        return webhook

    def _provision_package_updates(self, client: Any, team_id: str) -> str:
        """Create the #limeos-updates channel + webhook and persist its config. Idempotent."""
        channel_id = client.ensure_channel(
            team_id=team_id,
            name=PACKAGE_UPDATES_CHANNEL,
            display_name=PACKAGE_UPDATES_DISPLAY,
        )
        webhook = client.ensure_incoming_webhook(
            team_id=team_id,
            channel_id=channel_id,
            display_name=PACKAGE_UPDATES_WEBHOOK_NAME,
            description="Held/critical package updates awaiting review",
        )
        self._write_package_updates_config(webhook_url=webhook)
        return webhook

    def _write_package_updates_config(self, *, webhook_url: str) -> None:
        if self._package_updates_config_path is None:
            return
        config = {
            "version": INTEGRATION_VERSION,
            "enabled": True,
            "webhook_url": webhook_url,
            "channel_name": PACKAGE_UPDATES_CHANNEL,
        }
        self._repository.write_json(self._package_updates_config_path, config, mode=0o600)

    def _write_stack_notifications_config(self, *, webhook_url: str) -> None:
        if self._stack_notifications_config_path is None:
            return
        existing = (
            self._repository.read_json(self._stack_notifications_config_path, default={}) or {}
        )
        config = {
            "version": INTEGRATION_VERSION,
            "enabled": True,
            # A secret capability token gates the public *arr webhook endpoint; keep the
            # one already handed to the *arr apps on re-provision.
            "token": existing.get("token") or secrets.token_urlsafe(32),
            "webhook_url": webhook_url,
            "mode": existing.get("mode") or "quiet",
            "source_default": existing.get("source_default") or "stack",
            "channel_name": STACK_NOTIFICATIONS_CHANNEL,
        }
        self._repository.write_json(
            self._stack_notifications_config_path, config, mode=0o600
        )

    def stream_enable_stack_notifications(
        self, values: Mapping[str, Any]
    ) -> Iterator[dict[str, Any]]:
        """Provision stack notifications on an already-installed Mattermost (existing users).

        Channel + webhook creation needs a Mattermost session; the admin password is never
        stored, so it is re-supplied here (write-only) and used only for this login.
        """
        try:
            config = self._load_config()
            if not config.get("installed"):
                raise MattermostIntegrationError(
                    "Install Mattermost before enabling stack notifications"
                )
            site_url = config.get("site_url")
            team_name = config.get("team_name")
            admin_username = config.get("admin_username")
            password = values.get("admin_password") if isinstance(values, Mapping) else None
            if not (site_url and team_name and admin_username):
                raise MattermostIntegrationError("Mattermost configuration is incomplete")
            if not isinstance(password, str) or not password:
                raise MattermostIntegrationError("Administrator password is required")
            yield {"step": "auth", "line": "Authenticating with Mattermost"}
            client = self._api_factory(site_url)
            client.login(admin_username, password)
            yield {"step": "team", "line": "Locating LimeOS team"}
            team_id = client.ensure_team(name=team_name, display_name="LimeOS")
            yield {"step": "stack-notifications", "line": "Creating stack notifications channel"}
            self._provision_stack_notifications(client, team_id)
            yield {"step": "updates-channel", "line": "Creating updates channel"}
            self._provision_package_updates(client, team_id)
            yield {
                "step": "complete",
                "line": "LimeOS channels are ready",
                "done": True,
            }
        except (MattermostIntegrationError, OSError) as exc:
            yield {"step": "error", "error": str(exc)}

    def stream_install(self, values: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        try:
            setup = self._validate_setup(values)
            yield {"step": "prepare", "line": "Preparing Mattermost stack"}
            database_password = self._read_secret("POSTGRES_PASSWORD") or secrets.token_urlsafe(32)
            self._write_config(setup, installed=False)
            self._write_secrets(database_password=database_password, webhook_url="")
            stack_dir = Path(self._stack_path_provider(setup["stack_name"]))
            stack_dir.mkdir(parents=True, exist_ok=True)
            self._atomic_writer(
                stack_dir / "compose.yaml",
                dump_compose_yaml(self._compose(setup)),
                mode=0o600,
            )
            self._atomic_writer(
                stack_dir / "Dockerfile.mattermost",
                self._mattermost_dockerfile(),
                mode=0o600,
            )
            self._atomic_writer(
                stack_dir / "Dockerfile.alertd",
                self._alertd_dockerfile(),
                mode=0o600,
            )
            source_dir = Path(__file__).resolve().parent
            for filename in ALERTD_SOURCE_FILES:
                self._atomic_writer(
                    stack_dir / filename,
                    (source_dir / filename).read_text(),
                    mode=0o600,
                )

            yield {"step": "services", "line": "Starting Postgres and Mattermost"}
            self._run_compose(stack_dir, "up", "-d", "postgres", "mattermost")

            client = self._api_factory(setup["site_url"])
            yield {"step": "ready", "line": "Waiting for Mattermost"}
            self._wait_until_ready(client)

            yield {"step": "account", "line": "Creating Mattermost administrator"}
            user_id = client.ensure_admin(
                username=setup["admin_username"],
                email=setup["admin_email"],
                password=setup["admin_password"],
            )
            yield {"step": "team", "line": "Creating LimeOS team"}
            team_id = client.ensure_team(name=setup["team_name"], display_name="LimeOS")
            client.ensure_team_member(team_id=team_id, user_id=user_id)
            yield {"step": "channel", "line": "Creating alerts channel"}
            channel_id = client.ensure_channel(
                team_id=team_id,
                name=setup["channel_name"],
                display_name="LimeOS Alerts",
            )
            yield {"step": "webhook", "line": "Connecting alert delivery"}
            webhook = client.ensure_incoming_webhook(
                team_id=team_id, channel_id=channel_id
            )
            self._write_secrets(database_password=database_password, webhook_url=webhook)

            yield {"step": "stack-notifications", "line": "Creating stack notifications channel"}
            self._provision_stack_notifications(client, team_id)
            yield {"step": "updates-channel", "line": "Creating updates channel"}
            self._provision_package_updates(client, team_id)

            yield {"step": "alertd-image", "line": "Building LimeOS alert service"}
            self._run_compose(stack_dir, "build", "limeos-alertd")
            yield {"step": "alertd", "line": "Starting LimeOS alerts"}
            self._run_compose(stack_dir, "up", "-d", "--no-deps", "limeos-alertd")
            self.send_test()
            self._write_config(setup, installed=True)
            yield {"step": "test", "line": "Test alert delivered"}
            yield {
                "step": "complete",
                "line": "Mattermost and LimeOS alerts are ready",
                "done": True,
            }
        except (MattermostIntegrationError, AlertPolicyError, OSError) as exc:
            yield {"step": "error", "error": str(exc)}

    def _validate_setup(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        site_url = str(raw.get("site_url", "")).strip().rstrip("/")
        parsed = urlparse(site_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MattermostIntegrationError("Site URL must be an HTTP or HTTPS URL")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise MattermostIntegrationError("Site URL cannot contain credentials, a query, or a fragment")
        username = str(raw.get("admin_username", "")).strip().lower()
        email = str(raw.get("admin_email", "")).strip()
        password = str(raw.get("admin_password", ""))
        stack_name = str(raw.get("stack_name") or "mattermost").strip()
        team_name = str(raw.get("team_name") or "limeos").strip().lower()
        channel_name = str(raw.get("channel_name") or "limeos-alerts").strip().lower()
        if not USERNAME_PATTERN.fullmatch(username):
            raise MattermostIntegrationError("Admin username is invalid")
        if "@" not in email or len(email) > 254:
            raise MattermostIntegrationError("Admin email is invalid")
        if len(password) < 10:
            raise MattermostIntegrationError("Admin password must be at least 10 characters")
        if not SLUG_PATTERN.fullmatch(stack_name):
            raise MattermostIntegrationError("Stack name is invalid")
        if not SLUG_PATTERN.fullmatch(team_name) or not SLUG_PATTERN.fullmatch(channel_name):
            raise MattermostIntegrationError("Team and channel names must use lowercase letters, numbers, and hyphens")
        try:
            poll_seconds = max(15, int(raw.get("poll_seconds", 60)))
            fail_threshold = max(1, int(raw.get("fail_threshold", 2)))
        except (TypeError, ValueError) as exc:
            raise MattermostIntegrationError("Alert timing values must be numbers") from exc
        return {
            "site_url": site_url,
            "admin_username": username,
            "admin_email": email,
            "admin_password": password,
            "stack_name": stack_name,
            "team_name": team_name,
            "channel_name": channel_name,
            "timezone": str(raw.get("timezone") or "Europe/London"),
            "poll_seconds": poll_seconds,
            "fail_threshold": fail_threshold,
        }

    def _compose(self, setup: Mapping[str, Any]) -> dict[str, Any]:
        secrets_file = str(self._secrets_path)
        config_file = str(self._config_path)
        status_dir = str(self._status_path.parent)
        return {
            "services": {
                "postgres": {
                    "image": "docker.io/library/postgres:16-alpine",
                    "container_name": "limeos-mattermost-db",
                    "env_file": [secrets_file],
                    "volumes": ["mattermost-postgres:/var/lib/postgresql/data"],
                    "healthcheck": {
                        "test": ["CMD-SHELL", "pg_isready -U mmuser -d mattermost"],
                        "interval": "10s",
                        "timeout": "5s",
                        "retries": 12,
                    },
                    "restart": "unless-stopped",
                },
                "mattermost": {
                    "image": f"limeos/mattermost-team:{MATTERMOST_VERSION}-arm64",
                    "build": {
                        "context": ".",
                        "dockerfile": "Dockerfile.mattermost",
                    },
                    "container_name": "limeos-mattermost",
                    "env_file": [secrets_file],
                    "environment": {
                        "MM_SERVICESETTINGS_SITEURL": setup["site_url"],
                        "MM_SERVICESETTINGS_ENABLEINCOMINGWEBHOOKS": "true",
                        "TZ": setup["timezone"],
                    },
                    "ports": [f"{urlparse(setup['site_url']).port or 8065}:8065"],
                    "volumes": [
                        "mattermost-config:/mattermost/config",
                        "mattermost-data:/mattermost/data",
                        "mattermost-logs:/mattermost/logs",
                        "mattermost-plugins:/mattermost/plugins",
                    ],
                    "depends_on": {"postgres": {"condition": "service_healthy"}},
                    "restart": "unless-stopped",
                },
                "limeos-alertd": {
                    "image": "limeos/alertd:local",
                    "build": {
                        "context": ".",
                        "dockerfile": "Dockerfile.alertd",
                    },
                    "pull_policy": "never",
                    "container_name": "limeos-alertd",
                    "command": ["python", "alert_daemon.py"],
                    "env_file": [secrets_file],
                    "environment": {
                        "LIMEOS_ALERT_POLL_SECONDS": str(setup["poll_seconds"]),
                        "LIMEOS_ALERT_FAIL_THRESHOLD": str(setup["fail_threshold"]),
                        "LIMEOS_ALERT_POLICY_PATH": "/etc/limeos/mattermost.json",
                        "LIMEOS_ALERT_STATUS_PATH": "/var/lib/limeos/mattermost-status.json",
                        "LIMEOS_ALERT_HISTORY_PATH": "/var/lib/limeos/alert-events.jsonl",
                        "LIMEOS_STATE_DIR": "/var/lib/limeos",
                    },
                    "volumes": [
                        "/var/run/docker.sock:/var/run/docker.sock:ro",
                        "/run/pihealth:/run/pihealth:ro",
                        f"{config_file}:/etc/limeos/mattermost.json:ro",
                        f"{status_dir}:/var/lib/limeos",
                    ],
                    "depends_on": {"mattermost": {"condition": "service_started"}},
                    "restart": "unless-stopped",
                },
            },
            "volumes": {
                "mattermost-postgres": {},
                "mattermost-config": {},
                "mattermost-data": {},
                "mattermost-logs": {},
                "mattermost-plugins": {},
            },
        }

    def _run_compose(self, stack_dir: Path, *args: str) -> None:
        try:
            result = self._compose_runner(
                ["docker", "compose", "-f", "compose.yaml", *args],
                cwd=stack_dir,
                capture_output=True,
                text=True,
                timeout=1200,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise MattermostIntegrationError("Docker Compose could not start Mattermost") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Docker Compose failed").strip()
            raise MattermostIntegrationError(detail[:500])

    def _wait_until_ready(self, client: MattermostApiClient) -> None:
        for _attempt in range(60):
            try:
                client.ping()
                return
            except MattermostApiError:
                self._sleep(2)
        raise MattermostIntegrationError("Mattermost did not become ready within two minutes")

    def _write_config(self, setup: Mapping[str, Any], *, installed: bool) -> None:
        previous = self._load_config()
        config = {
            "version": INTEGRATION_VERSION,
            "installed": installed,
            "site_url": setup["site_url"],
            "stack_name": setup["stack_name"],
            "team_name": setup["team_name"],
            "channel_name": setup["channel_name"],
            "admin_username": setup["admin_username"],
            "policy": self._policy(previous),
        }
        self._repository.write_json(self._config_path, config, mode=0o640)

    def _write_secrets(self, *, database_password: str, webhook_url: str) -> None:
        datasource = (
            f"postgres://mmuser:{database_password}@postgres:5432/"
            "mattermost?sslmode=disable&connect_timeout=10"
        )
        lines = [
            "POSTGRES_DB=mattermost",
            "POSTGRES_USER=mmuser",
            f"POSTGRES_PASSWORD={database_password}",
            "MM_SQLSETTINGS_DRIVERNAME=postgres",
            f"MM_SQLSETTINGS_DATASOURCE={datasource}",
            f"LIMEOS_ALERT_MATTERMOST_WEBHOOK={webhook_url}",
        ]
        self._atomic_writer(self._secrets_path, "\n".join(lines) + "\n", mode=0o600)

    def _read_secret(self, key: str) -> str | None:
        try:
            lines = self._secrets_path.read_text().splitlines()
        except OSError:
            return None
        prefix = f"{key}="
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix):] or None
        return None

    def _load_config(self) -> dict[str, Any]:
        value = self._repository.read_json(self._config_path, default={})
        return value if isinstance(value, dict) else {}

    def _service_statuses(self) -> dict[str, Mapping[str, Any]]:
        if self._container_status_provider is None:
            return {}
        statuses = {}
        for name in ("limeos-mattermost-db", "limeos-mattermost", "limeos-alertd"):
            try:
                value = self._container_status_provider(name)
            except Exception:
                value = None
            statuses[name] = value or {"state": "missing", "health": None}
        return statuses

    @staticmethod
    def _mattermost_dockerfile() -> str:
        return f"""FROM ubuntu:24.04

ARG MM_VERSION={MATTERMOST_VERSION}
ARG MM_SHA256={MATTERMOST_ARM64_SHA256}

RUN apt-get update \\
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \\
        ca-certificates curl media-types mailcap poppler-utils tidy tzdata unrtf wv \\
    && rm -rf /var/lib/apt/lists/*

RUN curl --fail --location --show-error \\
        "https://releases.mattermost.com/${{MM_VERSION}}/mattermost-team-${{MM_VERSION}}-linux-arm64.tar.gz" \\
        --output /tmp/mattermost.tar.gz \\
    && echo "${{MM_SHA256}}  /tmp/mattermost.tar.gz" | sha256sum --check - \\
    && tar -xzf /tmp/mattermost.tar.gz -C / \\
    && rm /tmp/mattermost.tar.gz \\
    && groupadd --gid 2000 mattermost \\
    && useradd --uid 2000 --gid 2000 --home-dir /mattermost mattermost \\
    && mkdir -p /mattermost/data /mattermost/logs /mattermost/plugins /mattermost/client/plugins \\
    && chown -R mattermost:mattermost /mattermost

ENV PATH="/mattermost/bin:${{PATH}}" \\
    MM_SERVICESETTINGS_ENABLELOCALMODE="true" \\
    MM_INSTALL_TYPE="docker"

USER mattermost
WORKDIR /mattermost
HEALTHCHECK --interval=30s --timeout=10s \\
    CMD ["/mattermost/bin/mmctl", "system", "status", "--local"]
CMD ["/mattermost/bin/mattermost"]
EXPOSE 8065 8067 8074
"""

    @staticmethod
    def _alertd_dockerfile() -> str:
        sources = " ".join(ALERTD_SOURCE_FILES)
        return f"""FROM python:3.12-slim-bookworm

WORKDIR /app
RUN pip install --no-cache-dir "docker>=7,<8" "requests>=2.31,<3"
COPY {sources} /app/

CMD ["python", "alert_daemon.py"]
"""

    @staticmethod
    def _policy(config: Mapping[str, Any]) -> dict[str, Any]:
        raw = config.get("policy") if isinstance(config, Mapping) else None
        normalized = normalize_alert_policy(raw or default_alert_policy())
        return AlertPolicy.from_mapping(normalized).without_expired()
