"""Authenticated API for external service integrations."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, session

from alert_policy import AlertPolicyError
from auth_utils import csrf_protect, login_required
from mattermost_integration_service import MattermostIntegrationError
from operation_manager import OperationCapacityError


integrations_manager = Blueprint("integrations_manager", __name__)


def _service():
    return current_app.extensions["mattermost_integration_service"]


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
