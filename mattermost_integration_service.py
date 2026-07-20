"""Mattermost stack installation, bootstrap, and alert policy management."""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from alert_evaluator import Notification
from alert_notifier import MattermostWebhookNotifier
from alert_policy import (
    AlertPolicy,
    AlertPolicyError,
    default_alert_policy,
    normalize_alert_policy,
)
from compose_yaml import ComposeYamlError, dump_compose_yaml, load_compose_yaml
from integration_lifecycle_service import (
    LifecycleStateError,
    RecoveryCredentialError,
)


INTEGRATION_VERSION = 1
MATTERMOST_VERSION = "11.8.3"
MATTERMOST_ARM64_SHA256 = (
    "c784ca5d34cfe3793a31a6a7d17d209e0d916bb744a50df776c78aa318d5b98f"
)
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
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

LIFECYCLE_FAILURE_MESSAGE = (
    "Mattermost cleanup did not complete. Retry cleanup from Integrations."
)
UNKNOWN_STORAGE_MESSAGE = (
    "Mattermost storage ownership could not be verified. Preserve the data and "
    "review the generated stack manually."
)

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

    def __init__(
        self, site_url: str, *, opener: Callable[..., Any] = request.urlopen
    ) -> None:
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

    def ensure_channel(self, *, team_id: str, name: str, display_name: str) -> str:
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
        container_status_provider: Callable[[str], Mapping[str, Any] | None]
        | None = None,
        stack_notifications_config_path: Path | None = None,
        package_updates_config_path: Path | None = None,
        lifecycle_resolver: Any | None = None,
        lifecycle_repository: Any | None = None,
        lifecycle_policy: Mapping[str, Any] | None = None,
        recovery_custody: Any | None = None,
        agent_lifecycle_snapshot: Callable[[], Mapping[str, Any]] | None = None,
        docker_runner: Callable[..., Any] = subprocess.run,
        directory_remover: Callable[..., None] = shutil.rmtree,
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
        self._lifecycle_repository = lifecycle_repository
        self._lifecycle_policy = dict(lifecycle_policy or {})
        self._recovery_custody = recovery_custody
        self._agent_lifecycle_snapshot = agent_lifecycle_snapshot
        self._docker_runner = docker_runner
        self._directory_remover = directory_remover

    def status(self) -> dict[str, Any]:
        config = self._load_config()
        daemon = self._repository.read_json(self._status_path, default={}) or {}
        installed = bool(config.get("installed"))
        state = "connected" if installed else "not_installed"
        delivery = daemon.get("delivery") or {}
        services = self._service_statuses() if installed else {}
        if services and any(
            value.get("state") != "running" for value in services.values()
        ):
            state = "disconnected"
        elif services and any(
            value.get("health") == "unhealthy" for value in services.values()
        ):
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
            "webhook_configured": self._read_secret("LIMEOS_ALERT_MATTERMOST_WEBHOOK")
            is not None,
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
        config = (
            self._repository.read_json(self._package_updates_config_path, default={})
            or {}
        )
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
        self._repository.write_json(
            self._package_updates_config_path, config, mode=0o600
        )

    def _write_stack_notifications_config(self, *, webhook_url: str) -> None:
        if self._stack_notifications_config_path is None:
            return
        existing = (
            self._repository.read_json(
                self._stack_notifications_config_path, default={}
            )
            or {}
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
            password = (
                values.get("admin_password") if isinstance(values, Mapping) else None
            )
            if not (site_url and team_name and admin_username):
                raise MattermostIntegrationError(
                    "Mattermost configuration is incomplete"
                )
            if not isinstance(password, str) or not password:
                raise MattermostIntegrationError("Administrator password is required")
            yield {"step": "auth", "line": "Authenticating with Mattermost"}
            client = self._api_factory(site_url)
            client.login(admin_username, password)
            yield {"step": "team", "line": "Locating LimeOS team"}
            team_id = client.ensure_team(name=team_name, display_name="LimeOS")
            yield {
                "step": "stack-notifications",
                "line": "Creating stack notifications channel",
            }
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

    def stream_disable(self, operation_id: str) -> Iterator[dict[str, Any]]:
        """Stop the complete stack while retaining all configuration and data."""
        try:
            self._require_agents_disabled()
            current = self._lifecycle_record()
            if self._is_completed_target(current, "disabled"):
                yield self._completion_event("Mattermost is already disabled")
                return
            self._require_no_pending_lifecycle(current)
            config = self._installed_config()
            record = self._new_lifecycle_record(
                operation_id=operation_id,
                action="disable",
                target_state="disabled",
                retained_data=False,
            )
            steps = [
                (
                    "stop_services",
                    "Stopping Mattermost, Postgres, and alerts",
                    lambda: self._run_compose(
                        self._stack_dir(config), "down", "--remove-orphans"
                    ),
                )
            ]
            yield from self._execute_lifecycle(
                record,
                steps,
                completion="Mattermost is disabled; configuration and data were retained",
            )
        except Exception as exc:
            yield self._public_lifecycle_error(exc)

    def stream_enable(self, operation_id: str) -> Iterator[dict[str, Any]]:
        """Start a disabled stack and remove its lifecycle tombstone once verified."""
        try:
            current = self._lifecycle_record()
            if not self._is_completed_target(current, "disabled"):
                raise MattermostIntegrationError("Mattermost is not disabled")
            config = self._installed_config()
            record = self._new_lifecycle_record(
                operation_id=operation_id,
                action="enable",
                target_state="connected",
                retained_data=False,
            )
            client = self._api_factory(str(config["site_url"]))
            steps = [
                (
                    "start_services",
                    "Starting Mattermost, Postgres, and alerts",
                    lambda: self._run_compose(self._stack_dir(config), "up", "-d"),
                ),
                (
                    "verify_services",
                    "Waiting for Mattermost",
                    lambda: self._wait_until_ready(client),
                ),
            ]
            yield from self._execute_lifecycle(
                record,
                steps,
                completion="Mattermost is enabled",
                delete_tombstone=True,
            )
        except Exception as exc:
            yield self._public_lifecycle_error(exc)

    def stream_uninstall(self, operation_id: str) -> Iterator[dict[str, Any]]:
        """Remove LimeOS runtime ownership while preserving Mattermost volumes."""
        try:
            self._require_agents_uninstalled()
            current = self._lifecycle_record()
            if self._is_completed_target(current, "retained_data"):
                yield self._completion_event(
                    "Mattermost is already uninstalled; data is retained"
                )
                return
            if current is not None and not self._is_completed_target(
                current, "disabled"
            ):
                self._require_no_pending_lifecycle(current)
            config = self._installed_config()
            self._require_fixed_compose_project(config)
            record = self._new_lifecycle_record(
                operation_id=operation_id,
                action="uninstall",
                target_state="retained_data",
                retained_data=True,
            )
            yield from self._execute_lifecycle(
                record,
                self._uninstall_steps(config),
                completion="Mattermost was uninstalled; chat data is retained",
            )
        except Exception as exc:
            yield self._public_lifecycle_error(exc)

    def stream_purge(self, operation_id: str) -> Iterator[dict[str, Any]]:
        """Delete retained volumes only when the server release policy permits it."""
        try:
            if not self._lifecycle_policy.get("release_policy", {}).get(
                "mattermost_purge_enabled"
            ):
                raise MattermostIntegrationError(
                    "Mattermost data deletion is not enabled in this release"
                )
            current = self._lifecycle_record()
            if not self._is_completed_target(current, "retained_data"):
                raise MattermostIntegrationError(
                    "Mattermost has no retained data to delete"
                )
            record = self._new_lifecycle_record(
                operation_id=operation_id,
                action="purge",
                target_state="not_installed",
                retained_data=False,
            )
            yield from self._execute_lifecycle(
                record,
                self._purge_steps(),
                completion="Retained Mattermost data was deleted",
                delete_tombstone=True,
            )
        except Exception as exc:
            yield self._public_lifecycle_error(exc)

    def stream_retry_cleanup(self, operation_id: str) -> Iterator[dict[str, Any]]:
        """Resume the fixed remaining steps recorded by an interrupted operation."""
        try:
            record = self._lifecycle_record()
            if record is None or record.get("phase") not in {
                "running",
                "cleanup_required",
            }:
                raise MattermostIntegrationError(
                    "There is no Mattermost cleanup to retry"
                )
            action = str(record["action"])
            if action == "disable":
                self._require_agents_disabled()
                config = self._installed_config()
                steps = [
                    (
                        "stop_services",
                        "Stopping Mattermost, Postgres, and alerts",
                        lambda: self._run_compose(
                            self._stack_dir(config), "down", "--remove-orphans"
                        ),
                    )
                ]
                completion = (
                    "Mattermost is disabled; configuration and data were retained"
                )
                delete_tombstone = False
            elif action == "enable":
                config = self._installed_config()
                client = self._api_factory(str(config["site_url"]))
                steps = [
                    (
                        "start_services",
                        "Starting Mattermost, Postgres, and alerts",
                        lambda: self._run_compose(self._stack_dir(config), "up", "-d"),
                    ),
                    (
                        "verify_services",
                        "Waiting for Mattermost",
                        lambda: self._wait_until_ready(client),
                    ),
                ]
                completion = "Mattermost is enabled"
                delete_tombstone = True
            elif action == "uninstall":
                self._require_agents_uninstalled()
                config = self._load_config()
                steps = self._uninstall_steps(config)
                completion = "Mattermost was uninstalled; chat data is retained"
                delete_tombstone = False
            elif action == "purge":
                if not self._lifecycle_policy.get("release_policy", {}).get(
                    "mattermost_purge_enabled"
                ):
                    raise MattermostIntegrationError(
                        "Mattermost data deletion is not enabled in this release"
                    )
                steps = self._purge_steps()
                completion = "Retained Mattermost data was deleted"
                delete_tombstone = True
            else:
                raise MattermostIntegrationError("Mattermost cleanup state is invalid")
            now = self._lifecycle_timestamp()
            record.update(
                operation_id=self._validate_operation_id(operation_id),
                phase="running",
                started_at=now,
                updated_at=now,
                failure=None,
            )
            self._lifecycle_repository.write(record)
            yield from self._execute_lifecycle(
                record,
                steps,
                completion=completion,
                delete_tombstone=delete_tombstone,
            )
        except Exception as exc:
            yield self._public_lifecycle_error(exc)

    def stream_install(self, values: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
        try:
            setup = self._validate_setup(values)
            retained_reinstall = False
            current = self._lifecycle_record(optional=True)
            if current is not None:
                if current.get("phase") != "complete":
                    raise MattermostIntegrationError(
                        "Retry Mattermost cleanup before running setup"
                    )
                if current.get("target_state") == "retained_data":
                    self._require_recovery_custody()
                    yield {
                        "step": "credential",
                        "line": "Restoring the retained database credential",
                    }
                    restored = self._recovery_custody.restore()
                    if not restored.get("credential_restored"):
                        raise MattermostIntegrationError(
                            "The retained Mattermost database credential is unavailable"
                        )
                    retained_reinstall = True
                elif current.get("target_state") != "connected":
                    raise MattermostIntegrationError(
                        "Mattermost setup is unavailable in its current lifecycle state"
                    )
            yield {"step": "prepare", "line": "Preparing Mattermost stack"}
            database_password = self._read_secret(
                "POSTGRES_PASSWORD"
            ) or secrets.token_urlsafe(32)
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
            self._write_secrets(
                database_password=database_password, webhook_url=webhook
            )

            yield {
                "step": "stack-notifications",
                "line": "Creating stack notifications channel",
            }
            self._provision_stack_notifications(client, team_id)
            yield {"step": "updates-channel", "line": "Creating updates channel"}
            self._provision_package_updates(client, team_id)

            yield {"step": "alertd-image", "line": "Building LimeOS alert service"}
            self._run_compose(stack_dir, "build", "limeos-alertd")
            yield {"step": "alertd", "line": "Starting LimeOS alerts"}
            self._run_compose(stack_dir, "up", "-d", "--no-deps", "limeos-alertd")
            self.send_test()
            self._write_config(setup, installed=True)
            if retained_reinstall:
                self._lifecycle_repository.delete()
            yield {"step": "test", "line": "Test alert delivered"}
            yield {
                "step": "complete",
                "line": "Mattermost and LimeOS alerts are ready",
                "done": True,
            }
        except (MattermostIntegrationError, AlertPolicyError, OSError) as exc:
            yield {"step": "error", "error": str(exc)}

    def _uninstall_steps(
        self, config: Mapping[str, Any]
    ) -> list[tuple[str, str, Callable[[], None]]]:
        stack_dir = self._fixed_stack_dir()
        images = self._mattermost_policy()["local_images"]
        return [
            (
                "verify_storage_layout",
                "Verifying LimeOS storage ownership",
                lambda: self._validate_owned_stack_layout(stack_dir),
            ),
            (
                "stop_services",
                "Removing Mattermost, Postgres, and alert containers",
                lambda: self._run_compose(stack_dir, "down", "--remove-orphans"),
            ),
            (
                "retain_database_credential",
                "Protecting the retained database credential",
                self._retain_database_credential,
            ),
            (
                "remove_stack_notification_hook",
                "Disconnecting stack notifications",
                lambda: self._remove_owned_file(self._stack_notifications_config_path),
            ),
            (
                "remove_package_update_hook",
                "Disconnecting package update notifications",
                lambda: self._remove_owned_file(self._package_updates_config_path),
            ),
            (
                "remove_runtime_status",
                "Removing Mattermost runtime status",
                lambda: self._remove_owned_file(self._status_path),
            ),
            (
                "remove_alert_history",
                "Removing local alert history",
                lambda: self._remove_owned_file(
                    self._status_path.parent / "alert-events.jsonl"
                ),
            ),
            (
                "remove_integration_config",
                "Removing Mattermost integration configuration",
                lambda: self._remove_owned_file(self._config_path),
            ),
            (
                "remove_generated_stack",
                "Removing generated Mattermost stack files",
                lambda: self._remove_owned_directory(stack_dir),
            ),
            *[
                (
                    f"remove_image_{index}",
                    "Removing a LimeOS-owned local image",
                    lambda image=image: self._remove_local_image(str(image)),
                )
                for index, image in enumerate(images, start=1)
            ],
        ]

    def _purge_steps(self) -> list[tuple[str, str, Callable[[], None]]]:
        policy = self._mattermost_policy()
        project = str(policy["compose_project"])
        logical_volumes = [str(value) for value in policy["logical_volumes"]]
        return [
            (
                "verify_volume_ownership",
                "Verifying retained volume ownership",
                lambda: self._verify_volume_ownership(project, logical_volumes),
            ),
            *[
                (
                    f"remove_volume_{index}",
                    "Deleting a verified Mattermost data volume",
                    lambda logical=logical: self._remove_volume(project, logical),
                )
                for index, logical in enumerate(logical_volumes, start=1)
            ],
            (
                "discard_database_credential",
                "Deleting the retained database credential",
                self._discard_database_credential,
            ),
        ]

    def _execute_lifecycle(
        self,
        record: dict[str, Any],
        steps: list[tuple[str, str, Callable[[], None]]],
        *,
        completion: str,
        delete_tombstone: bool = False,
    ) -> Iterator[dict[str, Any]]:
        completed = set(record.get("completed_steps") or [])
        try:
            for step, line, action in steps:
                if step in completed:
                    continue
                yield {"step": step, "line": line}
                action()
                record["completed_steps"].append(step)
                record["updated_at"] = self._lifecycle_timestamp()
                self._lifecycle_repository.write(record)
                completed.add(step)
            if delete_tombstone:
                self._lifecycle_repository.delete()
            else:
                record.update(
                    phase="complete",
                    updated_at=self._lifecycle_timestamp(),
                    failure=None,
                )
                self._lifecycle_repository.write(record)
        except Exception:
            record.update(
                phase="cleanup_required",
                updated_at=self._lifecycle_timestamp(),
                failure={
                    "code": f"mattermost_{record['action']}_failed",
                    "message": LIFECYCLE_FAILURE_MESSAGE,
                },
            )
            self._lifecycle_repository.write(record)
            yield {"step": "error", "error": LIFECYCLE_FAILURE_MESSAGE}
            return
        yield self._completion_event(completion)

    def _new_lifecycle_record(
        self,
        *,
        operation_id: str,
        action: str,
        target_state: str,
        retained_data: bool,
    ) -> dict[str, Any]:
        self._require_lifecycle_repository()
        timestamp = self._lifecycle_timestamp()
        record = {
            "schema_version": "1",
            "integration": "mattermost",
            "operation_id": self._validate_operation_id(operation_id),
            "action": action,
            "phase": "running",
            "target_state": target_state,
            "started_at": timestamp,
            "updated_at": timestamp,
            "completed_steps": [],
            "retained_data": retained_data,
            "remove_claude_code": None,
            "failure": None,
            "warning_codes": [],
        }
        self._lifecycle_repository.write(record)
        return record

    def _lifecycle_record(self, *, optional: bool = False) -> dict[str, Any] | None:
        if self._lifecycle_repository is None:
            if optional:
                return None
            raise MattermostIntegrationError(
                "Mattermost lifecycle support is unavailable"
            )
        try:
            return self._lifecycle_repository.read()
        except LifecycleStateError as exc:
            raise MattermostIntegrationError(
                "Mattermost cleanup state is unavailable; review it manually"
            ) from exc

    def _require_lifecycle_repository(self) -> None:
        if self._lifecycle_repository is None:
            raise MattermostIntegrationError(
                "Mattermost lifecycle support is unavailable"
            )

    def _require_recovery_custody(self) -> None:
        if self._recovery_custody is None:
            raise MattermostIntegrationError(
                "Mattermost recovery credential support is unavailable"
            )

    @staticmethod
    def _is_completed_target(
        record: Mapping[str, Any] | None, target_state: str
    ) -> bool:
        return bool(
            record
            and record.get("phase") == "complete"
            and record.get("target_state") == target_state
        )

    @staticmethod
    def _require_no_pending_lifecycle(record: Mapping[str, Any] | None) -> None:
        if record is not None:
            raise MattermostIntegrationError(
                "Mattermost has an unfinished lifecycle action; retry cleanup first"
            )

    def _require_agents_disabled(self) -> None:
        snapshot = self._agent_snapshot()
        if snapshot.get("installed") and snapshot.get("enabled"):
            raise MattermostIntegrationError(
                "Disable AI Agents before stopping Mattermost"
            )

    def _require_agents_uninstalled(self) -> None:
        snapshot = self._agent_snapshot()
        if snapshot.get("installed"):
            raise MattermostIntegrationError(
                "Uninstall AI Agents before removing Mattermost"
            )

    def _agent_snapshot(self) -> Mapping[str, Any]:
        if self._agent_lifecycle_snapshot is None:
            raise MattermostIntegrationError("AI Agents status is unavailable")
        try:
            snapshot = self._agent_lifecycle_snapshot()
        except Exception as exc:
            raise MattermostIntegrationError("AI Agents status is unavailable") from exc
        if not isinstance(snapshot, Mapping) or not {
            "installed",
            "enabled",
        }.issubset(snapshot):
            raise MattermostIntegrationError("AI Agents status is unavailable")
        return snapshot

    def _installed_config(self) -> dict[str, Any]:
        config = self._load_config()
        if not config.get("installed"):
            raise MattermostIntegrationError("Mattermost is not installed")
        if not config.get("site_url") or not config.get("stack_name"):
            raise MattermostIntegrationError("Mattermost configuration is incomplete")
        return config

    def _stack_dir(self, config: Mapping[str, Any]) -> Path:
        stack_name = str(config.get("stack_name") or "")
        if not SLUG_PATTERN.fullmatch(stack_name):
            raise MattermostIntegrationError("Mattermost stack ownership is invalid")
        return Path(self._stack_path_provider(stack_name))

    def _fixed_stack_dir(self) -> Path:
        project = str(self._mattermost_policy()["compose_project"])
        return Path(self._stack_path_provider(project))

    def _require_fixed_compose_project(self, config: Mapping[str, Any]) -> None:
        if config.get("stack_name") != self._mattermost_policy()["compose_project"]:
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)

    def _mattermost_policy(self) -> Mapping[str, Any]:
        try:
            policy = self._lifecycle_policy["integrations"]["mattermost"]
            if not isinstance(policy, Mapping):
                raise KeyError
            return policy
        except (KeyError, TypeError) as exc:
            raise MattermostIntegrationError(
                "Mattermost lifecycle policy is unavailable"
            ) from exc

    def _validate_owned_stack_layout(self, stack_dir: Path) -> None:
        compose_path = stack_dir / "compose.yaml"
        if compose_path.is_symlink() or not compose_path.is_file():
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)
        try:
            compose = load_compose_yaml(compose_path.read_text(encoding="utf-8"))
        except (OSError, ComposeYamlError) as exc:
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE) from exc
        policy = self._mattermost_policy()
        logical = {str(value) for value in policy["logical_volumes"]}
        volumes = compose.get("volumes")
        services = compose.get("services")
        if (
            compose.get("name") is not None
            or not isinstance(volumes, Mapping)
            or set(volumes) != logical
            or any(value not in ({}, None) for value in volumes.values())
            or not isinstance(services, Mapping)
            or set(services) != {"postgres", "mattermost", "limeos-alertd"}
        ):
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)
        expected_mounts = {
            "postgres": {"mattermost-postgres:/var/lib/postgresql/data"},
            "mattermost": {
                "mattermost-config:/mattermost/config",
                "mattermost-data:/mattermost/data",
                "mattermost-logs:/mattermost/logs",
                "mattermost-plugins:/mattermost/plugins",
            },
        }
        for service, expected in expected_mounts.items():
            definition = services.get(service)
            mounts = (
                definition.get("volumes") if isinstance(definition, Mapping) else None
            )
            if not isinstance(mounts, list) or set(mounts) != expected:
                raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)

    def _retain_database_credential(self) -> None:
        self._require_recovery_custody()
        result = self._recovery_custody.retain()
        if not result.get("credential_retained"):
            raise RecoveryCredentialError(
                "Mattermost recovery credential operation failed"
            )

    def _discard_database_credential(self) -> None:
        self._require_recovery_custody()
        result = self._recovery_custody.discard()
        if not result.get("credential_discarded"):
            raise RecoveryCredentialError(
                "Mattermost recovery credential operation failed"
            )

    @staticmethod
    def _remove_owned_file(path: Path | None) -> None:
        if path is None:
            return
        try:
            if path.is_symlink():
                raise MattermostIntegrationError(
                    "Mattermost owned-file cleanup requires manual review"
                )
            path.unlink(missing_ok=True)
        except MattermostIntegrationError:
            raise
        except OSError as exc:
            raise MattermostIntegrationError(
                "Mattermost owned-file cleanup failed"
            ) from exc

    def _remove_owned_directory(self, path: Path) -> None:
        try:
            if path.is_symlink():
                raise MattermostIntegrationError(
                    "Mattermost stack cleanup requires manual review"
                )
            if path.exists():
                self._directory_remover(path)
        except MattermostIntegrationError:
            raise
        except OSError as exc:
            raise MattermostIntegrationError("Mattermost stack cleanup failed") from exc

    def _remove_local_image(self, image: str) -> None:
        if image not in self._mattermost_policy()["local_images"]:
            raise MattermostIntegrationError("Mattermost image ownership is invalid")
        images = set(
            self._docker_names("image", "ls", "--format", "{{.Repository}}:{{.Tag}}")
        )
        if image in images:
            self._run_docker("image", "rm", image)

    def _verify_volume_ownership(
        self, project: str, logical_volumes: list[str]
    ) -> None:
        expected = {f"{project}_{logical}" for logical in logical_volumes}
        all_names = set(self._docker_names("volume", "ls", "--format", "{{.Name}}"))
        owned_names = set(
            self._docker_names(
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Name}}",
            )
        )
        if expected - all_names or owned_names != expected:
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)
        for logical in logical_volumes:
            name = f"{project}_{logical}"
            labels = self._volume_labels(name)
            if (
                labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.volume") != logical
            ):
                raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)

    def _remove_volume(self, project: str, logical: str) -> None:
        policy = self._mattermost_policy()
        if (
            project != policy["compose_project"]
            or logical not in policy["logical_volumes"]
        ):
            raise MattermostIntegrationError("Mattermost volume ownership is invalid")
        name = f"{project}_{logical}"
        names = set(self._docker_names("volume", "ls", "--format", "{{.Name}}"))
        if name in names:
            labels = self._volume_labels(name)
            if (
                labels.get("com.docker.compose.project") != project
                or labels.get("com.docker.compose.volume") != logical
            ):
                raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)
            self._run_docker("volume", "rm", name)

    def _volume_labels(self, name: str) -> Mapping[str, Any]:
        result = self._run_docker("volume", "inspect", name)
        try:
            payload = json.loads(result.stdout)
            labels = payload[0]["Labels"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE) from exc
        if not isinstance(labels, Mapping):
            raise MattermostIntegrationError(UNKNOWN_STORAGE_MESSAGE)
        return labels

    def _docker_names(self, *args: str) -> list[str]:
        result = self._run_docker(*args)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _run_docker(self, *args: str) -> Any:
        try:
            result = self._docker_runner(
                ["docker", *args],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise MattermostIntegrationError("Docker cleanup is unavailable") from exc
        if result.returncode != 0:
            raise MattermostIntegrationError("Docker cleanup did not complete")
        return result

    def _lifecycle_timestamp(self) -> str:
        return datetime.fromtimestamp(self._clock(), timezone.utc).isoformat()

    @staticmethod
    def _validate_operation_id(operation_id: str) -> str:
        if not isinstance(operation_id, str) or not OPERATION_ID_PATTERN.fullmatch(
            operation_id
        ):
            raise MattermostIntegrationError(
                "Lifecycle operation identifier is invalid"
            )
        return operation_id

    @staticmethod
    def _completion_event(line: str) -> dict[str, Any]:
        return {"step": "complete", "line": line, "done": True}

    @staticmethod
    def _public_lifecycle_error(exc: Exception) -> dict[str, str]:
        if isinstance(
            exc,
            (MattermostIntegrationError, LifecycleStateError, RecoveryCredentialError),
        ):
            message = str(exc)
        else:
            message = "Mattermost lifecycle operation failed"
        return {"step": "error", "error": message}

    def _validate_setup(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        site_url = str(raw.get("site_url", "")).strip().rstrip("/")
        parsed = urlparse(site_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MattermostIntegrationError("Site URL must be an HTTP or HTTPS URL")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise MattermostIntegrationError(
                "Site URL cannot contain credentials, a query, or a fragment"
            )
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
            raise MattermostIntegrationError(
                "Admin password must be at least 10 characters"
            )
        if not SLUG_PATTERN.fullmatch(stack_name):
            raise MattermostIntegrationError("Stack name is invalid")
        if not SLUG_PATTERN.fullmatch(team_name) or not SLUG_PATTERN.fullmatch(
            channel_name
        ):
            raise MattermostIntegrationError(
                "Team and channel names must use lowercase letters, numbers, and hyphens"
            )
        try:
            poll_seconds = max(15, int(raw.get("poll_seconds", 60)))
            fail_threshold = max(1, int(raw.get("fail_threshold", 2)))
        except (TypeError, ValueError) as exc:
            raise MattermostIntegrationError(
                "Alert timing values must be numbers"
            ) from exc
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
            raise MattermostIntegrationError(
                "Docker Compose could not start Mattermost"
            ) from exc
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
        raise MattermostIntegrationError(
            "Mattermost did not become ready within two minutes"
        )

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
                return line[len(prefix) :] or None
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
