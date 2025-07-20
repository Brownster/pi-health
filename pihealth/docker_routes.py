from flask import Blueprint, jsonify

from .system_routes import list_containers, control_container

docker_bp = Blueprint('docker_bp', __name__)


docker_bp.add_url_rule('/api/containers', 'list_containers', lambda: jsonify(list_containers()), methods=['GET'])

def control_container_endpoint(container_id, action):
    return jsonify(control_container(container_id, action))

docker_bp.add_url_rule('/api/containers/<container_id>/<action>', 'control_container_endpoint', control_container_endpoint, methods=['POST'])
