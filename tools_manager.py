"""Tools manager transport for auxiliary services (e.g., CopyParty).

Domain behavior lives in :mod:`tools_service`; this module wires the Flask
blueprint, supplies the config path and helper call, and preserves the historical
module-level names used by tests.
"""
from flask import Blueprint, current_app, has_app_context, jsonify, request

from auth_utils import login_required
from helper_client import HelperError, helper_call  # noqa: F401  (helper_call patched in tests)
from ports import JsonFileRepository
from runtime_paths import CONFIG_DIR as RUNTIME_CONFIG_DIR
from tools_service import (  # noqa: F401  (re-exported for compatibility)
    DEFAULT_CONFIG,
    ToolsConfigError,
    ToolsHelperError,
    ToolsOperationError,
    ToolsService,
)


tools_manager = Blueprint("tools_manager", __name__)

CONFIG_PATH = RUNTIME_CONFIG_DIR / "copyparty.json"


def default_tools_service(repository=None):
    """Build a ToolsService bound to this module's config path and helper call."""
    return ToolsService(
        repository=repository if repository is not None else JsonFileRepository(),
        helper_call=lambda command, params: helper_call(command, params),
        config_path_provider=lambda: CONFIG_PATH,
        defaults=DEFAULT_CONFIG,
    )


def _tools_service():
    if has_app_context():
        service = current_app.extensions.get("tools_service")
        if service is not None:
            return service
    return default_tools_service()


@tools_manager.route("/api/tools/copyparty/status", methods=["GET"])
@login_required
def copyparty_status():
    try:
        result = _tools_service().status()
    except ToolsHelperError as exc:
        return jsonify({"error": str(exc), "config": exc.config}), 503

    host = request.host.split(":", 1)[0]
    result["url"] = f"http://{host}:{result['config'].get('port', 3923)}"
    return jsonify(result)


@tools_manager.route("/api/tools/copyparty/install", methods=["POST"])
@login_required
def copyparty_install():
    try:
        return jsonify(_tools_service().install())
    except ToolsOperationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ToolsHelperError as exc:
        return jsonify({"error": str(exc)}), 503


@tools_manager.route("/api/tools/copyparty/config", methods=["POST"])
@login_required
def copyparty_config():
    data = request.get_json() or {}
    try:
        return jsonify(_tools_service().configure(data))
    except ToolsConfigError as exc:
        return jsonify({"error": str(exc)}), 400
    except ToolsOperationError as exc:
        return jsonify({"error": str(exc)}), 400
    except ToolsHelperError as exc:
        return jsonify({"error": str(exc)}), 503
