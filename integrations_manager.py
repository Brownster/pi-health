"""Authenticated API for external service integrations."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session

from alert_policy import AlertPolicyError
from agent_integration_service import AgentIntegrationError
from auth_utils import csrf_protect, login_required
from mattermost_integration_service import MattermostIntegrationError
from operation_manager import OperationCapacityError


integrations_manager = Blueprint("integrations_manager", __name__)


def _service():
    return current_app.extensions["mattermost_integration_service"]


def _agent_service():
    return current_app.extensions["agent_integration_service"]


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


@integrations_manager.route("/api/integrations/mattermost", methods=["GET"])
@login_required
def mattermost_status():
    return jsonify(_service().status())


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
        expected_kind="mattermost-install",
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
        expected_kind=("agent-install", "agent-repair", "agent-auth"),
    )


@integrations_manager.route("/api/integrations/agents/disable", methods=["POST"])
@login_required
@csrf_protect
def disable_agents():
    try:
        return jsonify(_agent_service().disable())
    except AgentIntegrationError as exc:
        return jsonify({"error": str(exc)}), 409


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
