"""Authenticated HTTP transport for capability providers and extensions."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session

from auth_utils import login_required


logger = logging.getLogger(__name__)

capability_api = Blueprint("capability_api", __name__)

PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
CAPABILITY_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_-]*)+$"
)
LIFECYCLE_ACTIONS = frozenset({"enable", "disable", "update", "repair"})
MAX_LIFECYCLE_VALUES = 64
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


def _require_extensions_admin():
    authorizer = current_app.extensions.get("capability_authorizer")
    if authorizer is None:
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
        return _error(
            "authorization_unavailable",
            "Extension authorization policy is unavailable.",
            503,
        )
    if not allowed:
        return _error(
            "extension_lifecycle_forbidden",
            "Administrator permission is required.",
            403,
        )
    return None


def _request_values():
    if not request.is_json:
        return None, _error(
            "invalid_request", "Request body must be a JSON object.", 400
        )
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return None, _error(
            "invalid_request", "Request body must be a JSON object.", 400
        )
    if len(values) > MAX_LIFECYCLE_VALUES:
        return None, _error(
            "invalid_request", "Request body contains too many values.", 400
        )
    return values, None


def _lifecycle_response(operation, *args, **kwargs):
    service = current_app.extensions.get("capability_lifecycle_service")
    if service is None:
        return _error(
            "extension_lifecycle_unavailable",
            "Extension lifecycle service is unavailable.",
            503,
        )
    try:
        result = operation(service, *args, **kwargs)
    except CapabilityLifecycleError as exc:
        return _error(exc.code, exc.message, exc.status_code)
    except Exception:
        logger.error("Extension lifecycle API operation failed")
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
        or not isinstance(status_code, int)
        or status_code not in {200, 201, 202}
    ):
        logger.error("Extension lifecycle service returned an invalid result")
        return _error(
            "extension_lifecycle_failed",
            "Extension lifecycle operation failed.",
            500,
        )
    return jsonify(dict(payload)), status_code


@capability_api.route("/api/capabilities", methods=["GET"])
@login_required
def list_capabilities():
    return _read_response("capabilities")


@capability_api.route("/api/capabilities/<capability_id>", methods=["GET"])
@login_required
def capability_details(capability_id: str):
    if not CAPABILITY_ID_PATTERN.fullmatch(capability_id):
        return _error("invalid_capability_id", "Capability ID is invalid.", 400)
    return _detail_response("capabilities", capability_id, public_name="capability")


@capability_api.route("/api/extensions", methods=["GET"])
@login_required
def list_extensions():
    return _read_response("providers", public_name="extensions")


@capability_api.route("/api/extensions/<provider_id>", methods=["GET"])
@login_required
def extension_details(provider_id: str):
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        return _error("invalid_extension_id", "Extension ID is invalid.", 400)
    return _detail_response("providers", provider_id, public_name="extension")


@capability_api.route("/api/extensions/install", methods=["POST"])
@login_required
def install_extension():
    denied = _require_extensions_admin()
    if denied is not None:
        return denied
    values, invalid = _request_values()
    if invalid is not None:
        return invalid
    return _lifecycle_response(
        lambda service: service.install(
            values, username=session.get("username", "unknown")
        )
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
    denied = _require_extensions_admin()
    if denied is not None:
        return denied
    values, invalid = _request_values()
    if invalid is not None:
        return invalid
    return _lifecycle_response(
        lambda service: service.transition(
            provider_id,
            action,
            values,
            username=session.get("username", "unknown"),
        )
    )


@capability_api.route("/api/extensions/<provider_id>", methods=["DELETE"])
@login_required
def remove_extension(provider_id: str):
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        return _error("invalid_extension_id", "Extension ID is invalid.", 400)
    denied = _require_extensions_admin()
    if denied is not None:
        return denied
    return _lifecycle_response(
        lambda service: service.transition(
            provider_id,
            "remove",
            {},
            username=session.get("username", "unknown"),
        )
    )
