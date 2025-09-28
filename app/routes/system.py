from __future__ import annotations

from flask import Blueprint, jsonify

from app.services.system_stats import get_system_stats
from app.services.system_actions import system_action

system_api = Blueprint('system_api', __name__)


@system_api.route('/api/system-stats', methods=['GET'])
def api_system_stats():
    return jsonify(get_system_stats())


@system_api.route('/api/stats', methods=['GET'])
def api_stats():
    return jsonify(get_system_stats())


@system_api.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    return jsonify(system_action("shutdown"))


@system_api.route('/api/reboot', methods=['POST'])
def api_reboot():
    return jsonify(system_action("reboot"))
