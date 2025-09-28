from __future__ import annotations

from flask import Blueprint, jsonify

from app.services.docker_service import list_containers, control_container

containers_api = Blueprint('containers_api', __name__)


@containers_api.route('/api/containers', methods=['GET'])
def api_list_containers():
    return jsonify(list_containers())


@containers_api.route('/api/containers/<container_id>/<action>', methods=['POST'])
def api_control_container(container_id: str, action: str):
    return jsonify(control_container(container_id, action))
