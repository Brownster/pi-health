import os
from flask import Blueprint, jsonify, request

# Create a Blueprint for the compose editor
compose_editor = Blueprint('compose_editor', __name__)

# Paths to docker-compose.yml and .env files
DOCKER_COMPOSE_PATH = os.getenv('DOCKER_COMPOSE_PATH', './docker-compose.yml')
ENV_FILE_PATH = os.getenv('ENV_FILE_PATH', './.env')
BACKUP_DIR = os.getenv('BACKUP_DIR', './backups')

def ensure_backup_directory():
    """Ensure the backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)

def backup_compose_file():
    """Backup the current docker-compose.yml file."""
    ensure_backup_directory()
    if os.path.exists(DOCKER_COMPOSE_PATH):
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        backup_file = os.path.join(BACKUP_DIR, f"docker-compose-{timestamp}.yml")
        shutil.copy(DOCKER_COMPOSE_PATH, backup_file)
        # Keep only the 5 most recent backups
        backups = sorted(os.listdir(BACKUP_DIR))
        if len(backups) > 5:
            for old_backup in backups[:-5]:
                os.remove(os.path.join(BACKUP_DIR, old_backup))

def read_file(file_path):
    """Read the content of a file."""
    try:
        with open(file_path, 'r') as file:
            return file.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def save_file(file_path, content):
    """Save content to a file."""
    try:
        with open(file_path, 'w') as file:
            file.write(content)
        return True
    except Exception as e:
        return f"Error saving file: {str(e)}"


@compose_editor.route('/api/compose', methods=['GET'])
def get_docker_compose():
    """API endpoint to fetch the docker-compose.yml content."""
    content = read_file(DOCKER_COMPOSE_PATH)
    if content.startswith("Error"):
        return jsonify({"error": content}), 500
    return jsonify({"content": content})

@compose_editor.route('/api/compose/up', methods=['POST'])
def compose_up():
    """Run 'docker compose up' to apply changes."""
    try:
        # Backup the docker-compose.yml file
        backup_compose_file()

        # Run 'docker compose up -d'
        os.system('docker compose up -d')
        return jsonify({"status": "Compose updated successfully!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@compose_editor.route('/api/compose', methods=['POST'])
def save_docker_compose():
    """API endpoint to save updates to docker-compose.yml."""
    content = request.json.get('content', '')
    result = save_file(DOCKER_COMPOSE_PATH, content)
    if result is True:
        return jsonify({"status": "success"})
    return jsonify({"error": result}), 500


@compose_editor.route('/api/env', methods=['GET'])
def get_env_file():
    """API endpoint to fetch the .env content."""
    content = read_file(ENV_FILE_PATH)
    if content.startswith("Error"):
        return jsonify({"error": content}), 500
    return jsonify({"content": content})


@compose_editor.route('/api/env', methods=['POST'])
def save_env_file():
    """API endpoint to save updates to .env."""
    content = request.json.get('content', '')
    result = save_file(ENV_FILE_PATH, content)
    if result is True:
        return jsonify({"status": "success"})
    return jsonify({"error": result}), 500
