"""
Storage plugins Flask blueprint.
Provides REST API for plugin management.
"""
import json
from flask import Blueprint, jsonify, request, Response
from auth_utils import login_required
from storage_plugins.registry import get_registry

storage_bp = Blueprint("storage", __name__)


@storage_bp.route("/api/storage/plugins", methods=["GET"])
@login_required
def list_plugins():
    registry = get_registry()
    return jsonify({"plugins": registry.list_plugins()})


@storage_bp.route("/api/storage/plugins/<plugin_id>", methods=["GET"])
@login_required
def get_plugin(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    return jsonify({
        "id": plugin.PLUGIN_ID,
        "name": plugin.PLUGIN_NAME,
        "description": plugin.PLUGIN_DESCRIPTION,
        "version": plugin.PLUGIN_VERSION,
        "installed": plugin.is_installed(),
        "install_instructions": plugin.get_install_instructions(),
        "schema": plugin.get_schema(),
        "config": plugin.get_config(),
        "status": plugin.get_status(),
        "commands": plugin.get_commands()
    })


@storage_bp.route("/api/storage/plugins/<plugin_id>/config", methods=["POST"])
@login_required
def set_plugin_config(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    config = request.get_json() or {}

    errors = plugin.validate_config(config)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    result = plugin.set_config(config)
    if not result.success:
        return jsonify({"error": result.error}), 400

    return jsonify({"status": "saved", "config": plugin.get_config()})


@storage_bp.route("/api/storage/plugins/<plugin_id>/validate", methods=["POST"])
@login_required
def validate_plugin_config(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    config = request.get_json() or {}
    errors = plugin.validate_config(config)

    return jsonify({
        "valid": len(errors) == 0,
        "errors": errors
    })


@storage_bp.route("/api/storage/plugins/<plugin_id>/apply", methods=["POST"])
@login_required
def apply_plugin_config(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    result = plugin.apply_config()

    if result.success:
        return jsonify({"status": "applied", "message": result.message})
    return jsonify({"error": result.error}), 400


@storage_bp.route("/api/storage/plugins/<plugin_id>/status", methods=["GET"])
@login_required
def get_plugin_status(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    return jsonify(plugin.get_status())


@storage_bp.route("/api/storage/plugins/<plugin_id>/recovery", methods=["GET"])
@login_required
def get_plugin_recovery(plugin_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    if not hasattr(plugin, "get_recovery_status"):
        return jsonify({"error": "Recovery not supported"}), 404

    return jsonify(plugin.get_recovery_status())


@storage_bp.route("/api/storage/plugins/<plugin_id>/commands/<command_id>", methods=["POST"])
@login_required
def run_plugin_command(plugin_id: str, command_id: str):
    registry = get_registry()
    plugin = registry.get(plugin_id)

    if not plugin:
        return jsonify({"error": f"Plugin not found: {plugin_id}"}), 404

    commands = {c["id"]: c for c in plugin.get_commands()}
    if command_id not in commands:
        return jsonify({"error": f"Unknown command: {command_id}"}), 404

    params = request.get_json() or {}

    def generate():
        try:
            result = None
            gen = plugin.run_command(command_id, params)
            while True:
                try:
                    line = next(gen)
                except StopIteration as exc:
                    result = exc.value or result
                    break
                if isinstance(line, str):
                    yield f"data: {json.dumps({'type': 'output', 'line': line})}\n\n"
                else:
                    result = line

            if result:
                payload = {
                    "type": "complete",
                    "success": result.success,
                    "message": result.message
                }
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )
