"""Authenticated API for external service integrations."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from flask import Blueprint, current_app, jsonify, request, session

from alert_policy import AlertPolicyError
from agent_actions.service import AgentActionError
from agent_findings.service import FindingError
from agent_automation.service import AutomationError
from agent_integration_service import AgentIntegrationError
from auth_utils import csrf_protect, login_required
from helper_client import helper_call
from mattermost_integration_service import MattermostIntegrationError
from operation_manager import OperationCapacityError, OperationConflictError


integrations_manager = Blueprint("integrations_manager", __name__)
logger = logging.getLogger(__name__)

_LIFECYCLE_STEP = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_ADMIN_USERNAME = re.compile(r"^[a-z0-9._-]{3,64}$")
_AGENT_UNINSTALL_FIELDS = frozenset(
    {"confirmation", "admin_username", "admin_password", "remove_claude_code"}
)
_MATTERMOST_PURGE_FIELDS = frozenset(
    {"confirmation", "acknowledge_data_loss"}
)
_BOT_WARNING = {
    "code": "agent_bot_cleanup_failed",
    "message": "AI Agents was removed locally, but the Mattermost bot could not be removed.",
}


def _service():
    return current_app.extensions["mattermost_integration_service"]


def _agent_service():
    return current_app.extensions["agent_integration_service"]


def _agent_action_service():
    return current_app.extensions["agent_action_service"]


def _agent_findings_service():
    return current_app.extensions["agent_findings_service"]


def _agent_automation_service():
    return current_app.extensions["agent_automation_service"]


def _stack_notifications_service():
    return current_app.extensions["stack_notifications_service"]


def _require_action_permission(permission):
    authorizer = current_app.extensions.get("capability_authorizer")
    try:
        allowed = bool(
            authorizer
            and authorizer.allows(session.get("username", "unknown"), permission)
        )
    except Exception:
        logger.error("Agent action authorization failed")
        return _lifecycle_error(
            "action_authorization_unavailable",
            "Agent action authorization is unavailable.",
            503,
        )
    if not allowed:
        return _lifecycle_error(
            "action_forbidden",
            "Required agent action permission is missing.",
            403,
        )
    return None


def _action_error(exc):
    status = {
        "not_found": 404,
        "denied_approver": 403,
        "denied_operation": 403,
        "denied_target": 403,
        "kill_switch": 409,
        "expired": 409,
        "precondition_changed": 409,
        "policy_changed": 409,
        "contract_changed": 409,
        "invalid_state": 409,
        "conflict": 409,
        "idempotency_conflict": 409,
    }.get(exc.code, 400)
    return _lifecycle_error(exc.code, str(exc), status)


def _finding_error(exc):
    status = {
        "not_found": 404,
        "invalid_state": 409,
        "conflict": 409,
        "store_unavailable": 503,
        "store_failure": 503,
    }.get(exc.code, 400)
    return _lifecycle_error(exc.code, str(exc), status)


def _automation_error(exc):
    status = {
        "not_found": 404,
        "conflict": 409,
        "unsafe_store": 503,
        "store_unavailable": 503,
        "store_failure": 503,
    }.get(exc.code, 400)
    return _lifecycle_error(exc.code, str(exc), status)


#: *arr webhook bodies are small; reject anything implausibly large before parsing.
_STACK_NOTIFICATION_MAX_BYTES = 256 * 1024


def _start_agent_operation(*, kind, target, producer):
    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session["csrf_token"],
            username=session.get("username", "unknown"),
            kind=kind,
            target=target,
            producer=producer,
        )
    except OperationCapacityError as exc:
        return jsonify({"error": str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({"error": f"Unable to start AI Agents operation: {exc}"}), 500
    return jsonify(
        {
            "operation_id": operation.operation_id,
            "stream_url": f"/api/integrations/agents/operations/{operation.operation_id}/stream",
        }
    ), 202


def _lifecycle_error(code, message, status_code):
    response = jsonify({"code": code, "error": message})
    response.headers["Cache-Control"] = "no-store"
    return response, status_code


def _record_lifecycle_audit(
    *,
    integration,
    action,
    decision,
    outcome,
    code,
    operation_id=None,
):
    audit = current_app.extensions.get("audit")
    _write_lifecycle_audit(
        audit=audit,
        actor=session.get("username", "unknown"),
        integration=integration,
        action=action,
        decision=decision,
        outcome=outcome,
        code=code,
        operation_id=operation_id,
    )


def _write_lifecycle_audit(
    *,
    audit,
    actor,
    integration,
    action,
    decision,
    outcome,
    code,
    operation_id=None,
):
    if audit is None:
        return
    event = {
        "domain": "integration",
        "event": "integration_lifecycle",
        "actor": actor,
        "permission": "extensions.admin",
        "integration": integration,
        "action": action,
        "decision": decision,
        "outcome": outcome,
        "code": code,
    }
    if operation_id is not None:
        event["operation_id"] = operation_id
    try:
        audit.record(event)
    except Exception:
        logger.error("Integration lifecycle audit write failed")


def _require_lifecycle_admin(*, integration, action):
    authorizer = current_app.extensions.get("capability_authorizer")
    if authorizer is None:
        allowed = None
    else:
        try:
            allowed = authorizer.allows(
                session.get("username", "unknown"), "extensions.admin"
            )
        except Exception:
            allowed = None
    if allowed is True:
        return None
    if allowed is None:
        code = "integration_authorization_unavailable"
        decision = "unavailable"
        status_code = 503
        message = "Integration authorization policy is unavailable."
    else:
        code = "integration_lifecycle_forbidden"
        decision = "denied"
        status_code = 403
        message = "Administrator permission is required."
    _record_lifecycle_audit(
        integration=integration,
        action=action,
        decision=decision,
        outcome="rejected",
        code=code,
    )
    return _lifecycle_error(code, message, status_code)


def _reject_lifecycle(*, integration, action, code, message, status_code=400):
    _record_lifecycle_audit(
        integration=integration,
        action=action,
        decision="allowed",
        outcome="rejected",
        code=code,
    )
    return _lifecycle_error(code, message, status_code)


def _strict_lifecycle_values(*, integration, action, fields):
    values = request.get_json(silent=True)
    if not isinstance(values, dict) or set(values) != fields:
        return None, _reject_lifecycle(
            integration=integration,
            action=action,
            code="invalid_lifecycle_parameters",
            message="Lifecycle request values are invalid.",
        )
    return values, None


def _valid_admin_credentials(values):
    username = values.get("admin_username")
    password = values.get("admin_password")
    return bool(
        isinstance(username, str)
        and _ADMIN_USERNAME.fullmatch(username)
        and isinstance(password, str)
        and 10 <= len(password) <= 256
        and not any(character in password for character in ("\x00", "\r", "\n"))
    )


def _lifecycle_dispatch_mode(*, integration, action, service):
    try:
        status = service.status()
    except Exception:
        return None, _reject_lifecycle(
            integration=integration,
            action=action,
            code="integration_status_unavailable",
            message="Integration status is unavailable.",
            status_code=503,
        )
    if not isinstance(status, Mapping) or not isinstance(
        status.get("allowed_actions"), list
    ):
        return None, _reject_lifecycle(
            integration=integration,
            action=action,
            code="integration_status_unavailable",
            message="Integration status is unavailable.",
            status_code=503,
        )
    allowed_actions = status["allowed_actions"]
    blocked_actions = status.get("blocked_actions", [])
    if not all(isinstance(item, str) for item in allowed_actions) or not isinstance(
        blocked_actions, list
    ):
        return None, _reject_lifecycle(
            integration=integration,
            action=action,
            code="integration_status_unavailable",
            message="Integration status is unavailable.",
            status_code=503,
        )
    if action in allowed_actions:
        return "action", None
    cleanup = status.get("cleanup_operation")
    if (
        "retry_cleanup" in allowed_actions
        and isinstance(cleanup, Mapping)
        and cleanup.get("action") == action
    ):
        return "retry", None
    blocked = next(
        (
            item
            for item in blocked_actions
            if isinstance(item, Mapping) and item.get("action") == action
        ),
        None,
    )
    message = (
        blocked.get("message")
        if blocked is not None
        and isinstance(blocked.get("message"), str)
        and 1 <= len(blocked["message"]) <= 240
        and not any(ord(character) < 32 for character in blocked["message"])
        and not _sensitive_lifecycle_text(blocked["message"])
        else "Integration action is not available in the current state."
    )
    return None, _reject_lifecycle(
        integration=integration,
        action=action,
        code="integration_action_unavailable",
        message=message,
        status_code=409,
    )


def _public_lifecycle_event(event):
    if not isinstance(event, Mapping):
        return None
    public = {}
    step = event.get("step")
    if isinstance(step, str) and len(step) <= 64 and _LIFECYCLE_STEP.fullmatch(step):
        public["step"] = step
    for key in ("line", "error"):
        value = event.get(key)
        if (
            isinstance(value, str)
            and 1 <= len(value) <= 240
            and not any(ord(character) < 32 for character in value)
            and not _sensitive_lifecycle_text(value)
        ):
            public[key] = value
        elif isinstance(value, str):
            public[key] = (
                "Integration lifecycle operation failed"
                if key == "error"
                else "Integration lifecycle step is running"
            )
    if event.get("done") is True:
        public["done"] = True
    warnings = event.get("warnings")
    if isinstance(warnings, list) and any(
        isinstance(item, Mapping) and item.get("code") == _BOT_WARNING["code"]
        for item in warnings
    ):
        public["warnings"] = [dict(_BOT_WARNING)]
    return public or None


def _sensitive_lifecycle_text(value):
    lowered = value.lower()
    return bool(
        "://" in value
        or "/" in value
        or "\\" in value
        or re.search(
            r"\b(?:password|passwd|token|secret|webhook|dsn|api[_ -]?key)\b",
            lowered,
        )
        or re.search(r"\b[A-Z][A-Z0-9_]{2,}=", value)
    )


def _audited_lifecycle_events(
    *, integration, action, operation_id, producer, audit, actor
):
    terminal = False
    try:
        for event in producer:
            public = _public_lifecycle_event(event)
            if public is None:
                continue
            if public.get("error"):
                terminal = True
                _write_lifecycle_audit(
                    audit=audit,
                    actor=actor,
                    integration=integration,
                    action=action,
                    decision="allowed",
                    outcome="failed",
                    code=f"{integration}_{action}_failed",
                    operation_id=operation_id,
                )
            elif public.get("done"):
                terminal = True
                warning = bool(public.get("warnings"))
                _write_lifecycle_audit(
                    audit=audit,
                    actor=actor,
                    integration=integration,
                    action=action,
                    decision="allowed",
                    outcome="warning" if warning else "succeeded",
                    code=_BOT_WARNING["code"] if warning else "ok",
                    operation_id=operation_id,
                )
            yield public
    except Exception:
        if not terminal:
            _write_lifecycle_audit(
                audit=audit,
                actor=actor,
                integration=integration,
                action=action,
                decision="allowed",
                outcome="failed",
                code=f"{integration}_{action}_failed",
                operation_id=operation_id,
            )
        raise
    if not terminal:
        _write_lifecycle_audit(
            audit=audit,
            actor=actor,
            integration=integration,
            action=action,
            decision="allowed",
            outcome="failed",
            code="operation_ended_without_result",
            operation_id=operation_id,
        )


def _start_lifecycle_operation(*, integration, action, producer_factory):
    registry = current_app.extensions["operation_registry"]
    kind = f"integration-lifecycle-{integration}"
    audit = current_app.extensions.get("audit")
    actor = session.get("username", "unknown")
    try:
        operation = registry.create(
            owner=session["csrf_token"],
            username=session.get("username", "unknown"),
            kind=kind,
            target=integration,
            conflict_key=f"integration:{integration}",
            before_start=lambda item: _record_lifecycle_audit(
                integration=integration,
                action=action,
                decision="allowed",
                outcome="accepted",
                code="ok",
                operation_id=item.operation_id,
            ),
            producer_factory=lambda operation_id: _audited_lifecycle_events(
                integration=integration,
                action=action,
                operation_id=operation_id,
                producer=producer_factory(operation_id),
                audit=audit,
                actor=actor,
            ),
        )
    except OperationConflictError:
        return _reject_lifecycle(
            integration=integration,
            action=action,
            code="integration_operation_conflict",
            message="An integration operation is already running.",
            status_code=409,
        )
    except OperationCapacityError:
        return _reject_lifecycle(
            integration=integration,
            action=action,
            code="operation_capacity_reached",
            message="No integration operation slot is available.",
            status_code=429,
        )
    except Exception:
        return _reject_lifecycle(
            integration=integration,
            action=action,
            code="integration_operation_start_failed",
            message="Integration lifecycle operation could not start.",
            status_code=503,
        )
    return jsonify(
        {
            "operation_id": operation.operation_id,
            "stream_url": (
                f"/api/integrations/{integration}/operations/"
                f"{operation.operation_id}/stream"
            ),
        }
    ), 202


@integrations_manager.route("/api/integrations/mattermost", methods=["GET"])
@login_required
def mattermost_status():
    return jsonify(_service().status())


def _mattermost_lifecycle_request(action, fields, validate):
    denied = _require_lifecycle_admin(integration="mattermost", action=action)
    if denied is not None:
        return denied
    values, rejected = _strict_lifecycle_values(
        integration="mattermost", action=action, fields=fields
    )
    if rejected is not None:
        return rejected
    if not validate(values):
        return _reject_lifecycle(
            integration="mattermost",
            action=action,
            code="invalid_lifecycle_confirmation",
            message="Lifecycle confirmation is invalid.",
        )
    service = _service()
    mode, rejected = _lifecycle_dispatch_mode(
        integration="mattermost", action=action, service=service
    )
    if rejected is not None:
        return rejected
    method = (
        service.stream_retry_cleanup
        if mode == "retry"
        else getattr(service, f"stream_{action}")
    )
    return _start_lifecycle_operation(
        integration="mattermost",
        action=action,
        producer_factory=lambda operation_id: method(operation_id),
    )


@integrations_manager.route("/api/integrations/mattermost/disable", methods=["POST"])
@login_required
@csrf_protect
def disable_mattermost():
    return _mattermost_lifecycle_request("disable", frozenset(), lambda _values: True)


@integrations_manager.route("/api/integrations/mattermost/enable", methods=["POST"])
@login_required
@csrf_protect
def enable_mattermost():
    return _mattermost_lifecycle_request("enable", frozenset(), lambda _values: True)


@integrations_manager.route("/api/integrations/mattermost/uninstall", methods=["POST"])
@login_required
@csrf_protect
def uninstall_mattermost():
    return _mattermost_lifecycle_request(
        "uninstall",
        frozenset({"confirmation"}),
        lambda values: values.get("confirmation") == "Mattermost",
    )


@integrations_manager.route("/api/integrations/mattermost/purge", methods=["POST"])
@login_required
@csrf_protect
def purge_mattermost():
    return _mattermost_lifecycle_request(
        "purge",
        _MATTERMOST_PURGE_FIELDS,
        lambda values: (
            values.get("confirmation") == "Mattermost"
            and values.get("acknowledge_data_loss") is True
        ),
    )


@integrations_manager.route("/api/integrations/mattermost/install", methods=["POST"])
@login_required
@csrf_protect
def install_mattermost():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Setup values must be an object"}), 400
    service = _service()

    def produce_events():
        yield from service.stream_install(values)

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session["csrf_token"],
            username=session.get("username", "unknown"),
            kind="mattermost-install",
            target=str(values.get("stack_name") or "mattermost"),
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({"error": str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({"error": f"Unable to start Mattermost setup: {exc}"}), 500
    return jsonify(
        {
            "operation_id": operation.operation_id,
            "stream_url": (
                f"/api/integrations/mattermost/operations/"
                f"{operation.operation_id}/stream"
            ),
        }
    ), 202


@integrations_manager.route(
    "/api/integrations/mattermost/operations/<operation_id>/stream",
    methods=["GET"],
)
@login_required
def stream_mattermost_install(operation_id):
    from operation_sse import stream_operation_response

    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind=("mattermost-install", "integration-lifecycle-mattermost"),
    )


@integrations_manager.route("/api/integrations/mattermost/policy", methods=["PUT"])
@login_required
@csrf_protect
def update_mattermost_policy():
    policy = request.get_json(silent=True)
    if not isinstance(policy, dict):
        return jsonify({"error": "Alert policy must be an object"}), 400
    try:
        return jsonify({"policy": _service().update_policy(policy)})
    except AlertPolicyError as exc:
        return jsonify({"error": str(exc)}), 400


@integrations_manager.route("/api/integrations/mattermost/test", methods=["POST"])
@login_required
@csrf_protect
def test_mattermost_delivery():
    try:
        return jsonify(_service().send_test())
    except MattermostIntegrationError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception:
        current_app.logger.exception("Mattermost test delivery failed")
        return jsonify({"error": "Mattermost test delivery failed"}), 502


@integrations_manager.route("/api/integrations/agents", methods=["GET"])
@login_required
def agent_status():
    try:
        return jsonify(_agent_service().status())
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc), "state": "disconnected"}), 503


@integrations_manager.route("/api/integrations/agents/install", methods=["POST"])
@login_required
@csrf_protect
def install_agents():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Setup values must be an object"}), 400
    try:
        producer = _agent_service().stream_install(values)
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 400
    return _start_agent_operation(
        kind="agent-install", target="claude", producer=lambda: producer
    )


@integrations_manager.route("/api/integrations/agents/repair", methods=["POST"])
@login_required
@csrf_protect
def repair_agents():
    values = request.get_json(silent=True)
    if values is None:
        values = {}
    if not isinstance(values, dict):
        return jsonify({"error": "Repair values must be an object"}), 400
    try:
        producer = _agent_service().stream_repair(values)
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 400
    return _start_agent_operation(
        kind="agent-repair", target="claude", producer=lambda: producer
    )


@integrations_manager.route(
    "/api/integrations/agents/operations/<operation_id>/stream", methods=["GET"]
)
@login_required
def stream_agent_operation(operation_id):
    from operation_sse import stream_operation_response

    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind=(
            "agent-install",
            "agent-repair",
            "agent-auth",
            "integration-lifecycle-agents",
        ),
    )


@integrations_manager.route("/api/integrations/agents/disable", methods=["POST"])
@login_required
@csrf_protect
def disable_agents():
    denied = _require_lifecycle_admin(integration="agents", action="disable")
    if denied is not None:
        return denied
    _values, rejected = _strict_lifecycle_values(
        integration="agents", action="disable", fields=frozenset()
    )
    if rejected is not None:
        return rejected
    service = _agent_service()
    mode, rejected = _lifecycle_dispatch_mode(
        integration="agents", action="disable", service=service
    )
    if rejected is not None:
        return rejected
    method = (
        (lambda operation_id: service.stream_retry_cleanup(operation_id, {}))
        if mode == "retry"
        else service.stream_disable
    )
    return _start_lifecycle_operation(
        integration="agents",
        action="disable",
        producer_factory=method,
    )


@integrations_manager.route("/api/integrations/agents/uninstall", methods=["POST"])
@login_required
@csrf_protect
def uninstall_agents():
    denied = _require_lifecycle_admin(integration="agents", action="uninstall")
    if denied is not None:
        return denied
    values, rejected = _strict_lifecycle_values(
        integration="agents", action="uninstall", fields=_AGENT_UNINSTALL_FIELDS
    )
    if rejected is not None:
        return rejected
    if (
        values.get("confirmation") != "AI Agents"
        or not _valid_admin_credentials(values)
        or not isinstance(values.get("remove_claude_code"), bool)
    ):
        return _reject_lifecycle(
            integration="agents",
            action="uninstall",
            code="invalid_lifecycle_confirmation",
            message="Lifecycle confirmation is invalid.",
        )
    service = _agent_service()
    mode, rejected = _lifecycle_dispatch_mode(
        integration="agents", action="uninstall", service=service
    )
    if rejected is not None:
        return rejected
    credentials = {
        "admin_username": values["admin_username"],
        "admin_password": values["admin_password"],
    }
    if mode == "retry":
        def producer_factory(operation_id):
            return service.stream_retry_cleanup(operation_id, credentials)
    else:
        cleanup = {
            **credentials,
            "remove_claude_code": values["remove_claude_code"],
        }

        def producer_factory(operation_id):
            return service.stream_uninstall(operation_id, cleanup)
    return _start_lifecycle_operation(
        integration="agents",
        action="uninstall",
        producer_factory=producer_factory,
    )


@integrations_manager.route("/api/integrations/agents/providers", methods=["GET"])
@login_required
def agent_providers():
    try:
        return jsonify(_agent_service().providers())
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 503


@integrations_manager.route(
    "/api/integrations/agents/providers/claude/auth", methods=["POST"]
)
@login_required
@csrf_protect
def authenticate_claude():
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Authentication values must be an object"}), 400
    action = values.get("action")
    try:
        if action == "start" and set(values) <= {"action"}:
            producer = _agent_service().stream_auth()
            return _start_agent_operation(
                kind="agent-auth", target="claude", producer=lambda: producer
            )
        if action == "submit" and set(values) == {"action", "operation_id", "code"}:
            return jsonify(
                _agent_service().submit_auth(values["operation_id"], values["code"])
            )
        if action == "cancel" and set(values) == {"action", "operation_id"}:
            return jsonify(_agent_service().cancel_auth(values["operation_id"]))
        return jsonify({"error": "Authentication action is invalid"}), 400
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 409


@integrations_manager.route("/api/integrations/agents/test", methods=["POST"])
@login_required
@csrf_protect
def test_agent_delivery():
    try:
        return jsonify(_agent_service().test_delivery())
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 409


def _query_limit():
    try:
        return int(request.args.get("limit", "50"))
    except ValueError as exc:
        raise AgentIntegrationError("Limit must be between 1 and 200") from exc


@integrations_manager.route("/api/integrations/agents/usage", methods=["GET"])
@login_required
def agent_usage():
    try:
        return jsonify(_agent_service().usage(limit=_query_limit()))
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 400


@integrations_manager.route("/api/integrations/agents/audit", methods=["GET"])
@login_required
def agent_audit():
    try:
        return jsonify(_agent_service().audit(limit=_query_limit()))
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 400


@integrations_manager.route("/api/integrations/agents/permissions", methods=["GET"])
@login_required
def agent_permissions():
    try:
        return jsonify(_agent_service().permissions())
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 503


@integrations_manager.route("/api/integrations/agents/actions", methods=["GET"])
@login_required
def agent_actions():
    denied = _require_action_permission("capability.view")
    if denied is not None:
        return denied
    try:
        result = _agent_action_service().list(limit=_query_limit())
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/actions/capabilities", methods=["GET"]
)
@login_required
def agent_action_capabilities():
    denied = _require_action_permission("capability.view")
    if denied is not None:
        return denied
    try:
        result = _agent_action_service().capabilities()
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/actions/<action_id>", methods=["GET"]
)
@login_required
def agent_action_details(action_id):
    denied = _require_action_permission("capability.view")
    if denied is not None:
        return denied
    try:
        result = _agent_action_service().get(action_id)
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify({"action": result})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/actions/<action_id>/approve", methods=["POST"]
)
@login_required
@csrf_protect
def approve_agent_action(action_id):
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    values = request.get_json(silent=True)
    if values not in ({}, None):
        return _lifecycle_error(
            "invalid_action_approval",
            "Action approval accepts no parameters.",
            400,
        )
    username = session.get("username", "unknown")
    try:
        action = _agent_action_service().approve(
            action_id,
            approver={"type": "local", "id": username, "username": username},
        )
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify({"action": action})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/actions/<action_id>/reject", methods=["POST"]
)
@login_required
@csrf_protect
def reject_agent_action(action_id):
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    values = request.get_json(silent=True)
    if values not in ({}, None):
        return _lifecycle_error(
            "invalid_action_rejection",
            "Action rejection accepts no parameters.",
            400,
        )
    try:
        action = _agent_action_service().reject(action_id)
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify({"action": action})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/actions/<action_id>/cancel", methods=["POST"]
)
@login_required
@csrf_protect
def cancel_agent_action(action_id):
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    if request.get_json(silent=True) not in ({}, None):
        return _lifecycle_error(
            "invalid_action_cancellation",
            "Action cancellation accepts no parameters.",
            400,
        )
    try:
        action = _agent_action_service().cancel(action_id)
    except AgentActionError as exc:
        return _action_error(exc)
    response = jsonify({"action": action})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/automation/policy", methods=["GET", "PUT"]
)
@login_required
def agent_automation_policy():
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            policy = _agent_action_service().policy()
        else:
            values = request.get_json(silent=True)
            if not isinstance(values, dict):
                return _lifecycle_error(
                    "invalid_policy", "Action policy must be an object.", 400
                )
            policy = _agent_action_service().validate_policy(values)
            helper = current_app.extensions.get("helper")
            result = helper.call("agent_action_policy_write", {"policy": policy})
            if not isinstance(result, dict) or not result.get("success"):
                return _lifecycle_error(
                    "policy_write_failed",
                    "Action policy could not be saved.",
                    503,
                )
    except AgentActionError as exc:
        return _action_error(exc)
    except Exception:
        logger.error("Agent action policy update failed")
        return _lifecycle_error(
            "policy_write_failed", "Action policy could not be saved.", 503
        )
    response = jsonify({"policy": policy})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/automation/schedules", methods=["GET", "POST"]
)
@login_required
def agent_automation_schedules():
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            result = _agent_automation_service().list()
            response = jsonify(result)
        else:
            values = request.get_json(silent=True)
            if not isinstance(values, dict):
                return _lifecycle_error(
                    "invalid_schedule", "Schedule must be an object.", 400
                )
            username = session.get("username", "unknown")
            schedule = _agent_automation_service().create(
                values,
                owner={"type": "local", "id": username, "username": username},
            )
            response = jsonify({"schedule": schedule})
            response.status_code = 201
    except AutomationError as exc:
        return _automation_error(exc)
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/automation/schedules/<schedule_id>",
    methods=["GET", "PUT"],
)
@login_required
def agent_automation_schedule_details(schedule_id):
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            schedule = _agent_automation_service().get(schedule_id)
        else:
            values = request.get_json(silent=True)
            if not isinstance(values, dict):
                return _lifecycle_error(
                    "invalid_schedule", "Schedule must be an object.", 400
                )
            schedule = _agent_automation_service().update(schedule_id, values)
    except AutomationError as exc:
        return _automation_error(exc)
    response = jsonify({"schedule": schedule})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route("/api/integrations/agents/findings", methods=["GET"])
@login_required
def agent_findings():
    denied = _require_action_permission("capability.view")
    if denied is not None:
        return denied
    try:
        result = _agent_findings_service().list(limit=_query_limit())
    except FindingError as exc:
        return _finding_error(exc)
    response = jsonify(result)
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/findings/<finding_id>", methods=["GET", "PUT"]
)
@login_required
def agent_finding_details(finding_id):
    permission = "capability.view" if request.method == "GET" else "extensions.admin"
    denied = _require_action_permission(permission)
    if denied is not None:
        return denied
    try:
        if request.method == "GET":
            finding = _agent_findings_service().get(finding_id)
        else:
            values = request.get_json(silent=True)
            if not isinstance(values, dict):
                return _lifecycle_error(
                    "invalid_finding", "Finding must be an object.", 400
                )
            finding = _agent_findings_service().update(finding_id, values)
    except FindingError as exc:
        return _finding_error(exc)
    response = jsonify({"finding": finding})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route(
    "/api/integrations/agents/findings/<finding_id>/reject", methods=["POST"]
)
@login_required
@csrf_protect
def reject_agent_finding(finding_id):
    denied = _require_action_permission("extensions.admin")
    if denied is not None:
        return denied
    if request.get_json(silent=True) not in ({}, None):
        return _lifecycle_error(
            "invalid_finding_rejection",
            "Finding rejection accepts no parameters.",
            400,
        )
    try:
        finding = _agent_findings_service().reject(finding_id)
    except FindingError as exc:
        return _finding_error(exc)
    response = jsonify({"finding": finding})
    response.headers["Cache-Control"] = "no-store"
    return response


@integrations_manager.route("/api/integrations/stack-notifications", methods=["GET"])
@login_required
def stack_notifications_status():
    return jsonify(_stack_notifications_service().status())


def pending_setup_actions(*, mattermost_status, stack_notifications_status):
    """Outstanding one-time actions the user must complete (e.g. after an update).

    Condition-based rather than "did an update just run": the unmet state itself is the
    trigger, so an action disappears once the user completes it. Pure + testable.
    """
    actions = []
    if not mattermost_status.get("installed"):
        return actions
    missing_stack = not stack_notifications_status.get("configured")
    missing_updates = not mattermost_status.get("updates_channel_configured")
    if missing_stack or missing_updates:
        actions.append(
            {
                "id": "limeos-channels-setup",
                "title": "Finish setting up LimeOS Mattermost channels",
                "body": (
                    "LimeOS can post Radarr / Sonarr / *arr events and held package updates to "
                    "dedicated Mattermost channels. Creating channels needs your Mattermost "
                    "admin password once, so it could not be done automatically during the update."
                ),
                "action_label": "Set up on Integrations",
                "href": "/integrations",
            }
        )
    return actions


@integrations_manager.route("/api/integrations/packages/pending", methods=["GET"])
@login_required
def packages_pending():
    """Held/critical package updates awaiting review, plus recorded approvals."""
    result = helper_call("packages_pending", {}) or {}
    if not result.get("success"):
        return jsonify({"error": result.get("error", "Unable to read pending updates")}), 502
    return jsonify({"pending": result.get("pending", []), "approvals": result.get("approvals", [])})


@integrations_manager.route("/api/integrations/packages/approve", methods=["POST"])
@login_required
@csrf_protect
def packages_approve():
    """Approve a specific held update. Payload-bound (name+version must match a pending
    update, enforced in the helper) and actor-bound (the authenticated admin is recorded)."""
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Request body must be an object"}), 400
    name, version = values.get("name"), values.get("version")
    if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
        return jsonify({"error": "name and version are required"}), 400
    result = helper_call(
        "packages_approve",
        {"name": name, "version": version, "approved_by": session.get("username", "unknown")},
    ) or {}
    if not result.get("success"):
        return jsonify({"error": result.get("error", "Approval failed")}), 400
    return jsonify({"approval": result.get("approval")}), 201


@integrations_manager.route("/api/setup/pending", methods=["GET"])
@login_required
def setup_pending():
    return jsonify(
        {
            "actions": pending_setup_actions(
                mattermost_status=_service().status(),
                stack_notifications_status=_stack_notifications_service().status(),
            )
        }
    )


@integrations_manager.route("/api/integrations/stack-notifications/mode", methods=["PUT"])
@login_required
@csrf_protect
def stack_notifications_mode():
    values = request.get_json(silent=True)
    mode = values.get("mode") if isinstance(values, dict) else None
    body, status = _stack_notifications_service().set_mode(str(mode or ""))
    return jsonify(body), status


@integrations_manager.route("/api/integrations/stack-notifications/enable", methods=["POST"])
@login_required
@csrf_protect
def enable_stack_notifications():
    """Provision the channel/webhook for an already-installed Mattermost (existing users).

    Delegates to the Mattermost service, which owns the admin session; the admin password
    supplied here is used only to authenticate and is never stored.
    """
    values = request.get_json(silent=True)
    if not isinstance(values, dict):
        return jsonify({"error": "Request body must be an object"}), 400
    service = _service()

    def produce_events():
        yield from service.stream_enable_stack_notifications(values)

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session["csrf_token"],
            username=session.get("username", "unknown"),
            kind="stack-notifications-enable",
            target="stack-notifications",
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({"error": str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({"error": f"Unable to enable stack notifications: {exc}"}), 500
    return jsonify(
        {
            "operation_id": operation.operation_id,
            "stream_url": (
                f"/api/integrations/stack-notifications/operations/"
                f"{operation.operation_id}/stream"
            ),
        }
    ), 202


@integrations_manager.route(
    "/api/integrations/stack-notifications/operations/<operation_id>/stream",
    methods=["GET"],
)
@login_required
def stream_stack_notifications_enable(operation_id):
    from operation_sse import stream_operation_response

    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind="stack-notifications-enable",
    )


@integrations_manager.route(
    "/api/integrations/stack-notifications/hook/<token>", methods=["POST"]
)
def stack_notifications_ingest(token):
    """Token-gated *arr webhook sink.

    Deliberately without ``login_required``/``csrf_protect``: *arr apps post here directly
    with only the per-install token in the path (constant-time compared inside the service).
    The body is size-capped before parsing and always answered 200 for a valid token so an
    *arr connection Test succeeds.
    """
    length = request.content_length
    if length is not None and length > _STACK_NOTIFICATION_MAX_BYTES:
        return jsonify({"error": "Payload too large"}), 413
    payload = request.get_json(silent=True)
    body, status = _stack_notifications_service().ingest(token, payload)
    return jsonify(body), status
