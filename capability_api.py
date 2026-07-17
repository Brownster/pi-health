"""Authenticated HTTP transport for capability providers and extensions."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from auth_utils import login_required
from capability_registry_service import redact_capability_value


logger = logging.getLogger(__name__)

capability_api = Blueprint("capability_api", __name__)

PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
CAPABILITY_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_-]*)+$"
)
LIFECYCLE_ACTIONS = frozenset({"enable", "disable", "update", "repair"})
MAX_LIFECYCLE_VALUES = 64
INSTALL_FIELDS = frozenset({"type", "source", "id", "entry", "class_name"})
INSTALL_SOURCE_TYPES = frozenset({"github", "pip"})
PYTHON_ENTRY_PATTERN = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./-]+\.py$"
)
PYTHON_CLASS_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PUBLIC_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
PUBLIC_ERROR_STATUS_CODES = frozenset({400, 404, 409, 422, 429, 503})


class CapabilityLifecycleError(RuntimeError):
    """A lifecycle request failed with a bounded public API error."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "extension_lifecycle_failed",
        status_code: int = 409,
    ) -> None:
        public_message = str(message)
        if (
            not public_message
            or len(public_message) > 240
            or any(ord(character) < 32 for character in public_message)
        ):
            public_message = "Extension lifecycle operation failed."
        public_code = (
            code
            if isinstance(code, str) and PUBLIC_ERROR_CODE_PATTERN.fullmatch(code)
            else "extension_lifecycle_failed"
        )
        public_status = (
            status_code
            if isinstance(status_code, int)
            and status_code in PUBLIC_ERROR_STATUS_CODES
            else 409
        )
        super().__init__(public_message)
        self.message = public_message
        self.code = public_code
        self.status_code = public_status


class UnavailableCapabilityAuthorizer:
    """Fail closed until CP-006 installs the server-owned role policy."""

    def allows(self, _username: str, _permission: str) -> bool:
        raise RuntimeError("Capability authorization policy is unavailable")


def _error(code: str, message: str, status_code: int):
    response = jsonify({"code": code, "error": message})
    response.headers["Cache-Control"] = "no-store"
    return response, status_code


def _registry_snapshot() -> Mapping[str, Any] | None:
    service = current_app.extensions.get("capability_registry_service")
    if service is None:
        return None
    try:
        snapshot = service.snapshot()
    except Exception:
        logger.error("Capability registry API read failed")
        return None
    if not isinstance(snapshot, Mapping):
        logger.error("Capability registry returned an invalid snapshot")
        return None
    if not all(
        isinstance(snapshot.get(key), list)
        for key in ("providers", "capabilities", "errors")
    ):
        logger.error("Capability registry snapshot is missing required collections")
        return None
    if any(
        not isinstance(item, Mapping)
        for key in ("providers", "capabilities", "errors")
        for item in snapshot[key]
    ):
        logger.error("Capability registry snapshot contains an invalid entry")
        return None
    if snapshot.get("schema_version") != "1":
        logger.error("Capability registry snapshot version is unsupported")
        return None
    return snapshot


def _read_response(collection: str, *, public_name: str | None = None):
    snapshot = _registry_snapshot()
    if snapshot is None:
        return _error(
            "capability_registry_unavailable",
            "Capability registry is unavailable.",
            503,
        )
    payload = {
        "schema_version": snapshot["schema_version"],
        public_name or collection: snapshot[collection],
        "errors": snapshot["errors"],
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


def _detail_response(collection: str, identity: str, *, public_name: str):
    snapshot = _registry_snapshot()
    if snapshot is None:
        return _error(
            "capability_registry_unavailable",
            "Capability registry is unavailable.",
            503,
        )
    item = next(
        (entry for entry in snapshot[collection] if entry.get("id") == identity),
        None,
    )
    if item is None:
        return _error(
            f"{public_name}_not_found",
            f"{public_name.replace('_', ' ').title()} was not found.",
            404,
        )
    related_provider_ids = {identity}
    if collection == "capabilities":
        related_provider_ids = {
            provider.get("id")
            for provider in item.get("providers", [])
            if isinstance(provider, Mapping)
        }
    response = jsonify(
        {
            "schema_version": snapshot["schema_version"],
            public_name: item,
            "errors": [
                error
                for error in snapshot["errors"]
                if error.get("provider_id") is None
                or error.get("provider_id") in related_provider_ids
            ],
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _require_capability_view():
    authorizer = current_app.extensions.get("capability_authorizer")
    if authorizer is None:
        return _error(
            "authorization_unavailable",
            "Capability authorization policy is unavailable.",
            503,
        )
    try:
        allowed = authorizer.allows(
            session.get("username", "unknown"), "capability.view"
        )
    except Exception:
        logger.error("Capability authorization policy failed")
        return _error(
            "authorization_unavailable",
            "Capability authorization policy is unavailable.",
            503,
        )
    if not allowed:
        return _error(
            "capability_read_forbidden",
            "Capability view permission is required.",
            403,
        )
    return None


def _record_lifecycle_audit(
    *,
    action: str,
    provider_id: str | None,
    decision: str,
    outcome: str,
    code: str,
) -> None:
    audit = current_app.extensions.get("audit")
    if audit is None:
        return
    event = {
        "domain": "capability",
        "event": "extension_lifecycle",
        "actor": session.get("username", "unknown"),
        "permission": "extensions.admin",
        "action": action,
        "decision": decision,
        "outcome": outcome,
        "code": code,
    }
    if provider_id is not None:
        event["provider_id"] = provider_id
    try:
        audit.record(event)
    except Exception:
        logger.error("Extension lifecycle audit write failed")


def _require_extensions_admin(*, action: str, provider_id: str | None):
    authorizer = current_app.extensions.get("capability_authorizer")
    if authorizer is None:
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="unavailable",
            outcome="rejected",
            code="authorization_unavailable",
        )
        return _error(
            "authorization_unavailable",
            "Extension authorization policy is unavailable.",
            503,
        )
    try:
        allowed = authorizer.allows(
            session.get("username", "unknown"), "extensions.admin"
        )
    except Exception:
        logger.error("Extension authorization policy failed")
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="unavailable",
            outcome="rejected",
            code="authorization_unavailable",
        )
        return _error(
            "authorization_unavailable",
            "Extension authorization policy is unavailable.",
            503,
        )
    if not allowed:
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="denied",
            outcome="rejected",
            code="extension_lifecycle_forbidden",
        )
        return _error(
            "extension_lifecycle_forbidden",
            "Administrator permission is required.",
            403,
        )
    return None


def _valid_install_values(values: Mapping[str, Any]) -> bool:
    source_type = values.get("type")
    source = values.get("source")
    if source_type not in INSTALL_SOURCE_TYPES:
        return False
    if (
        not isinstance(source, str)
        or not source
        or len(source) > 512
        or any(ord(character) < 32 for character in source)
    ):
        return False
    provider_id = values.get("id")
    if provider_id is not None and (
        not isinstance(provider_id, str)
        or not PROVIDER_ID_PATTERN.fullmatch(provider_id)
    ):
        return False
    entry = values.get("entry")
    if entry is not None and (
        not isinstance(entry, str)
        or len(entry) > 160
        or not PYTHON_ENTRY_PATTERN.fullmatch(entry)
    ):
        return False
    class_name = values.get("class_name")
    if class_name is not None and (
        not isinstance(class_name, str)
        or len(class_name) > 80
        or not PYTHON_CLASS_PATTERN.fullmatch(class_name)
    ):
        return False
    return True


def _request_values(*, action: str):
    if not request.is_json:
        return None, _error(
            "invalid_lifecycle_parameters",
            "Lifecycle parameters are invalid.",
            400,
        )
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return None, _error(
            "invalid_lifecycle_parameters",
            "Lifecycle parameters are invalid.",
            400,
        )
    if len(values) > MAX_LIFECYCLE_VALUES:
        return None, _error(
            "invalid_lifecycle_parameters",
            "Lifecycle parameters are invalid.",
            400,
        )
    if action == "install":
        if set(values) - INSTALL_FIELDS or not _valid_install_values(values):
            return None, _error(
                "invalid_lifecycle_parameters",
                "Lifecycle parameters are invalid.",
                400,
            )
    elif values:
        return None, _error(
            "invalid_lifecycle_parameters",
            "Lifecycle parameters are invalid.",
            400,
        )
    return values, None


def _lifecycle_response(
    operation,
    *args,
    action: str,
    provider_id: str | None,
    **kwargs,
):
    service = current_app.extensions.get("capability_lifecycle_service")
    if service is None:
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="allowed",
            outcome="failed",
            code="extension_lifecycle_unavailable",
        )
        return _error(
            "extension_lifecycle_unavailable",
            "Extension lifecycle service is unavailable.",
            503,
        )
    try:
        result = operation(service, *args, **kwargs)
    except CapabilityLifecycleError as exc:
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="allowed",
            outcome="rejected",
            code=exc.code,
        )
        return _error(exc.code, exc.message, exc.status_code)
    except Exception:
        logger.error("Extension lifecycle API operation failed")
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="allowed",
            outcome="failed",
            code="extension_lifecycle_failed",
        )
        return _error(
            "extension_lifecycle_failed",
            "Extension lifecycle operation failed.",
            500,
        )

    status_code = 200
    payload = result
    if isinstance(result, tuple) and len(result) == 2:
        payload, status_code = result
    if (
        not isinstance(payload, Mapping)
        or type(status_code) is not int
        or status_code not in {200, 201, 202}
    ):
        logger.error("Extension lifecycle service returned an invalid result")
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="allowed",
            outcome="failed",
            code="extension_lifecycle_failed",
        )
        return _error(
            "extension_lifecycle_failed",
            "Extension lifecycle operation failed.",
            500,
        )
    _record_lifecycle_audit(
        action=action,
        provider_id=provider_id,
        decision="allowed",
        outcome="accepted",
        code="ok",
    )
    return jsonify(redact_capability_value(dict(payload))), status_code


@capability_api.route("/api/capabilities", methods=["GET"])
@login_required
def list_capabilities():
    denied = _require_capability_view()
    if denied is not None:
        return denied
    return _read_response("capabilities")


@capability_api.route("/api/capabilities/<capability_id>", methods=["GET"])
@login_required
def capability_details(capability_id: str):
    denied = _require_capability_view()
    if denied is not None:
        return denied
    if not CAPABILITY_ID_PATTERN.fullmatch(capability_id):
        return _error("invalid_capability_id", "Capability ID is invalid.", 400)
    return _detail_response("capabilities", capability_id, public_name="capability")


@capability_api.route("/api/extensions", methods=["GET"])
@login_required
def list_extensions():
    denied = _require_capability_view()
    if denied is not None:
        return denied
    return _read_response("providers", public_name="extensions")


@capability_api.route("/api/extensions/<provider_id>", methods=["GET"])
@login_required
def extension_details(provider_id: str):
    denied = _require_capability_view()
    if denied is not None:
        return denied
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        return _error("invalid_extension_id", "Extension ID is invalid.", 400)
    return _detail_response("providers", provider_id, public_name="extension")


@capability_api.route("/api/extensions/install", methods=["POST"])
@login_required
def install_extension():
    denied = _require_extensions_admin(action="install", provider_id=None)
    if denied is not None:
        return denied
    values, invalid = _request_values(action="install")
    if invalid is not None:
        _record_lifecycle_audit(
            action="install",
            provider_id=None,
            decision="allowed",
            outcome="rejected",
            code="invalid_lifecycle_parameters",
        )
        return invalid
    return _lifecycle_response(
        lambda service: service.install(
            values, username=session.get("username", "unknown")
        ),
        action="install",
        provider_id=None,
    )


@capability_api.route(
    "/api/extensions/<provider_id>/<action>", methods=["POST"]
)
@login_required
def transition_extension(provider_id: str, action: str):
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        return _error("invalid_extension_id", "Extension ID is invalid.", 400)
    if action not in LIFECYCLE_ACTIONS:
        return _error(
            "invalid_lifecycle_action", "Extension lifecycle action is invalid.", 404
        )
    denied = _require_extensions_admin(action=action, provider_id=provider_id)
    if denied is not None:
        return denied
    values, invalid = _request_values(action=action)
    if invalid is not None:
        _record_lifecycle_audit(
            action=action,
            provider_id=provider_id,
            decision="allowed",
            outcome="rejected",
            code="invalid_lifecycle_parameters",
        )
        return invalid
    return _lifecycle_response(
        lambda service: service.transition(
            provider_id,
            action,
            values,
            username=session.get("username", "unknown"),
        ),
        action=action,
        provider_id=provider_id,
    )


@capability_api.route("/api/extensions/<provider_id>", methods=["DELETE"])
@login_required
def remove_extension(provider_id: str):
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        return _error("invalid_extension_id", "Extension ID is invalid.", 400)
    denied = _require_extensions_admin(action="remove", provider_id=provider_id)
    if denied is not None:
        return denied
    return _lifecycle_response(
        lambda service: service.transition(
            provider_id,
            "remove",
            {},
            username=session.get("username", "unknown"),
        ),
        action="remove",
        provider_id=provider_id,
    )
