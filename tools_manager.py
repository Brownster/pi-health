"""
Tools manager for auxiliary services (e.g., CopyParty).
"""
import json
import os

from flask import Blueprint, jsonify, request

from auth_utils import login_required
from helper_client import helper_call, HelperError


tools_manager = Blueprint("tools_manager", __name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "copyparty.json")
DEFAULT_CONFIG = {
    "share_path": "/srv/copyparty",
    "port": 3923,
    "extra_args": ""
}


def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as handle:
                data = json.load(handle)
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def _save_config(config: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as handle:
        json.dump(config, handle, indent=2)


@tools_manager.route("/api/tools/copyparty/status", methods=["GET"])
@login_required
def copyparty_status():
    config = _load_config()
    try:
        status = helper_call("copyparty_status", {})
    except HelperError as exc:
        return jsonify({"error": str(exc), "config": config}), 503

    host = request.host.split(":", 1)[0]
    url = f"http://{host}:{config.get('port', 3923)}"

    return jsonify({
        "config": config,
        "installed": status.get("installed", False),
        "service_active": status.get("service_active", False),
        "service_status": status.get("service_status", "unknown"),
        "url": url
    })


@tools_manager.route("/api/tools/copyparty/install", methods=["POST"])
@login_required
def copyparty_install():
    config = _load_config()
    try:
        result = helper_call("copyparty_install", config)
    except HelperError as exc:
        return jsonify({"error": str(exc)}), 503

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Install failed")}), 400

    return jsonify({"status": "installed"})


@tools_manager.route("/api/tools/copyparty/config", methods=["POST"])
@login_required
def copyparty_config():
    data = request.get_json() or {}
    share_path = str(data.get("share_path", "")).strip()
    port = data.get("port", DEFAULT_CONFIG["port"])
    extra_args = str(data.get("extra_args", "")).strip()

    if not share_path.startswith("/"):
        return jsonify({"error": "share_path must be absolute"}), 400

    try:
        port = int(port)
    except (TypeError, ValueError):
        return jsonify({"error": "port must be an integer"}), 400

    config = {
        "share_path": share_path,
        "port": port,
        "extra_args": extra_args
    }
    _save_config(config)

    try:
        result = helper_call("copyparty_configure", config)
    except HelperError as exc:
        return jsonify({"error": str(exc)}), 503

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Configure failed")}), 400

    return jsonify({"status": "configured"})
