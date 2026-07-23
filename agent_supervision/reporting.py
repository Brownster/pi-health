"""Bounded threaded Mattermost delivery for supervised repair incidents."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_transport.bot_client import MattermostBotApi
from limeops.operations import redact_text


DEFAULT_DELIVERY_CONFIG_PATH = (
    "/etc/limeos/integrations/agent-supervisor/delivery.json"
)
DEFAULT_DELIVERY_SECRET_PATH = (
    "/etc/limeos/integrations/agent-supervisor/mattermost.env"
)
MAX_MESSAGE_CHARS = 4000
_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CONFIG_FIELDS = frozenset({"schema_version", "site_url", "channel_id"})
_TRANSITION_SUMMARIES = {
    "fault_confirmed": "Two consecutive health checks confirmed a service fault.",
    "fault_reconfirmed": "The service fault was confirmed again.",
    "infrastructure_blocked": "Health evidence is currently unavailable.",
    "window_deferred": "Repair is deferred until a maintenance window opens.",
    "active_action_deferred": "Repair is deferred while another action owns this target.",
    "budget_blocked": "The disruption budget currently blocks another repair.",
    "supervision_blocked": "A safety gate blocked supervised repair.",
    "action_authorized": "A bounded supervised repair was authorised.",
    "action_started": "The repair action started.",
    "verification_started": "Repair execution finished and verification started.",
    "escalated": "Automatic repair did not complete safely; administrator review is required.",
    "demoted": "Supervised authority was demoted to approval for this target.",
    "recovered": "The service recovered without an action.",
    "recovered_after_action": "The service recovered after the repair action.",
}


class IncidentDeliveryError(RuntimeError):
    pass


def load_delivery_config(path: str | Path) -> dict[str, str]:
    config_path = Path(path)
    try:
        metadata = config_path.stat()
        if (
            config_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_size > 8192
        ):
            raise IncidentDeliveryError(
                "Supervisor delivery configuration is unavailable"
            )
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IncidentDeliveryError(
            "Supervisor delivery configuration is unavailable"
        ) from exc
    if (
        not isinstance(raw, Mapping)
        or set(raw) != _CONFIG_FIELDS
        or raw.get("schema_version") != "1"
    ):
        raise IncidentDeliveryError(
            "Supervisor delivery configuration is invalid"
        )
    site_url = raw.get("site_url")
    channel_id = raw.get("channel_id")
    parsed = urlsplit(site_url) if isinstance(site_url, str) else None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not isinstance(channel_id, str)
        or _ID.fullmatch(channel_id) is None
    ):
        raise IncidentDeliveryError(
            "Supervisor delivery configuration is invalid"
        )
    return {"site_url": site_url.rstrip("/"), "channel_id": channel_id}


def load_delivery_token(path: str | Path) -> str:
    secret_path = Path(path)
    try:
        metadata = secret_path.stat()
        if (
            secret_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o027
            or metadata.st_size > 8192
        ):
            raise IncidentDeliveryError(
                "Supervisor delivery credential is unavailable"
            )
        lines = secret_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IncidentDeliveryError(
            "Supervisor delivery credential is unavailable"
        ) from exc
    prefix = "MATTERMOST_BOT_TOKEN="
    values = [line[len(prefix) :] for line in lines if line.startswith(prefix)]
    if (
        len(values) != 1
        or not values[0]
        or len(values[0]) > 4096
        or any(character in values[0] for character in "\x00\r\n")
    ):
        raise IncidentDeliveryError(
            "Supervisor delivery credential is unavailable"
        )
    return values[0]


def render_incident_message(context: Mapping[str, Any]) -> str:
    incident = context.get("incident")
    transition = context.get("transition")
    schedule = context.get("schedule")
    delivery = context.get("delivery")
    if not all(
        isinstance(value, Mapping)
        for value in (incident, transition, schedule, delivery)
    ):
        raise IncidentDeliveryError("Incident delivery context is invalid")
    transition_type = str(transition.get("type") or "")
    summary = _TRANSITION_SUMMARIES.get(transition_type)
    if summary is None:
        raise IncidentDeliveryError("Incident transition is unavailable")
    target = redact_text(str(incident.get("target") or "unknown"))[:128]
    operation = redact_text(str(incident.get("operation") or "unknown"))[:128]
    name = redact_text(str(schedule.get("name") or "Supervised repair"))[:120]
    priority = redact_text(str(schedule.get("service_priority") or "normal"))[:16]
    incident_id = redact_text(str(incident.get("id") or "unknown"))[:128]
    details = transition.get("details")
    code = ""
    if isinstance(details, Mapping):
        candidate = details.get("code") or details.get("terminal_code")
        if isinstance(candidate, str):
            code = f"\nReason: `{redact_text(candidate)[:128]}`"
    if delivery.get("message_kind") == "root":
        heading = f"### ⚠️ Supervised repair incident: {name}"
        identity = (
            f"\nTarget: `{operation}:{target}` · Priority: **{priority}**"
            f"\nIncident: `{incident_id}`"
        )
    else:
        heading = f"**{transition_type.replace('_', ' ').title()}**"
        identity = ""
    return f"{heading}\n{summary}{identity}{code}"[:MAX_MESSAGE_CHARS]


class MattermostIncidentDelivery:
    """Post one root and subsequent replies through a narrow bot projection."""

    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_DELIVERY_CONFIG_PATH,
        secrets_path: str | Path = DEFAULT_DELIVERY_SECRET_PATH,
        api_factory: Callable[[str], MattermostBotApi] = MattermostBotApi,
    ) -> None:
        config = load_delivery_config(config_path)
        api = api_factory(config["site_url"])
        api.use_token(load_delivery_token(secrets_path))
        self._api = api
        self._channel_id = config["channel_id"]

    def __call__(self, context: Mapping[str, Any]) -> str:
        delivery = context.get("delivery")
        if not isinstance(delivery, Mapping):
            raise IncidentDeliveryError("Incident delivery context is invalid")
        root_id = ""
        if delivery.get("message_kind") == "reply":
            root_id = str(delivery.get("incident_thread_id") or "")
            if _ID.fullmatch(root_id) is None:
                raise IncidentDeliveryError("Incident thread is unavailable")
        post_id = self._api.post_message(
            channel_id=self._channel_id,
            message=render_incident_message(context),
            root_id=root_id,
        )
        if _ID.fullmatch(post_id) is None:
            raise IncidentDeliveryError("Mattermost post identity is invalid")
        return post_id
