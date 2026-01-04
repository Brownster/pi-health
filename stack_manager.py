"""
Stack Manager - Dockge-inspired stack management for pi-health

Manages Docker Compose stacks as directories containing compose.yaml files.
"""
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, request, Response
import yaml
from auth_utils import login_required

# Create Blueprint
stack_manager = Blueprint('stack_manager', __name__)

# Configuration
STACKS_PATH = os.getenv('STACKS_PATH', '/opt/stacks')
STACK_FILENAMES = ['compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml']
STACK_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
BACKUP_DIR = os.getenv('STACK_BACKUP_DIR', os.path.join(STACKS_PATH, '.backups'))
BACKUP_NAME_RE = re.compile(r'^compose-\d{14}\.ya?ml$')


def validate_stack_name(name):
    """Validate stack name to prevent path traversal and injection."""
    if not name:
        return False, "Stack name is required"
    if not STACK_NAME_RE.match(name):
        return False, "Stack name must start with alphanumeric and contain only letters, numbers, dots, underscores, and hyphens"
    if '..' in name or name.startswith('.'):
        return False, "Invalid stack name"
    if len(name) > 64:
        return False, "Stack name too long (max 64 characters)"
    return True, None


def get_stack_path(name):
    """Get the full path to a stack directory."""
    return os.path.join(STACKS_PATH, name)


def find_compose_file(stack_dir):
    """Find the compose file in a stack directory."""
    for filename in STACK_FILENAMES:
        path = os.path.join(stack_dir, filename)
        if os.path.exists(path):
            return path
    return None


def get_compose_filename(stack_dir):
    """Get just the filename of the compose file."""
    for filename in STACK_FILENAMES:
        path = os.path.join(stack_dir, filename)
        if os.path.exists(path):
            return filename
    return None


def ensure_stacks_directory():
    """Ensure the stacks directory exists."""
    os.makedirs(STACKS_PATH, exist_ok=True)


def ensure_backup_directory():
    """Ensure the backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def list_stacks():
    """List all stacks in the stacks directory."""
    try:
        ensure_stacks_directory()
    except Exception as e:
        return [], str(e)
    stacks = []

    try:
        for entry in os.listdir(STACKS_PATH):
            # Skip hidden directories and backup directory
            if entry.startswith('.'):
                continue

            stack_dir = os.path.join(STACKS_PATH, entry)
            if not os.path.isdir(stack_dir):
                continue

            compose_file = find_compose_file(stack_dir)
            if compose_file:
                stacks.append({
                    'name': entry,
                    'path': stack_dir,
                    'compose_file': os.path.basename(compose_file)
                })
    except Exception as e:
        return [], str(e)

    return sorted(stacks, key=lambda x: x['name']), None


def get_stack_status(stack_name):
    """Get the status of containers in a stack."""
    stack_dir = get_stack_path(stack_name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return None, "Stack not found"

    try:
        # Get container status using docker compose ps
        result = subprocess.run(
            ['docker', 'compose', '-f', compose_file, 'ps', '--format', 'json'],
            cwd=stack_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        containers = []
        if result.stdout.strip():
            import json
            stdout = result.stdout.strip()
            try:
                parsed = json.loads(stdout)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                if isinstance(parsed, list):
                    for container in parsed:
                        if not isinstance(container, dict):
                            continue
                        containers.append({
                            'name': container.get('Name', ''),
                            'service': container.get('Service', ''),
                            'status': container.get('State', 'unknown'),
                            'health': container.get('Health', ''),
                            'ports': container.get('Publishers', [])
                        })
                else:
                    parsed = None
            except json.JSONDecodeError:
                parsed = None

            if parsed is None:
                # docker compose ps --format json can output one JSON object per line
                for line in stdout.split('\n'):
                    if not line:
                        continue
                    try:
                        container = json.loads(line)
                        if not isinstance(container, dict):
                            continue
                        containers.append({
                            'name': container.get('Name', ''),
                            'service': container.get('Service', ''),
                            'status': container.get('State', 'unknown'),
                            'health': container.get('Health', ''),
                            'ports': container.get('Publishers', [])
                        })
                    except json.JSONDecodeError:
                        continue

        # Determine overall stack status
        if not containers:
            status = 'stopped'
        elif all(c['status'] == 'running' for c in containers):
            status = 'running'
        elif any(c['status'] == 'running' for c in containers):
            status = 'partial'
        else:
            status = 'stopped'

        return {
            'status': status,
            'containers': containers,
            'container_count': len(containers),
            'running_count': sum(1 for c in containers if c['status'] == 'running')
        }, None

    except subprocess.TimeoutExpired:
        return None, "Timeout getting stack status"
    except Exception as e:
        return {'status': 'unknown', 'containers': [], 'error': str(e)}, None


def backup_stack(stack_name):
    """Create a backup of a stack's compose file."""
    ensure_backup_directory()
    stack_dir = get_stack_path(stack_name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return None

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup_subdir = os.path.join(BACKUP_DIR, stack_name)
    os.makedirs(backup_subdir, exist_ok=True)

    backup_file = os.path.join(backup_subdir, f"compose-{timestamp}.yaml")
    shutil.copy(compose_file, backup_file)

    # Keep only the 10 most recent backups per stack
    backups = sorted([f for f in os.listdir(backup_subdir) if f.startswith('compose-')])
    if len(backups) > 10:
        for old_backup in backups[:-10]:
            os.remove(os.path.join(backup_subdir, old_backup))

    return backup_file


def list_backups(stack_name):
    """List backups for a stack, newest first."""
    ensure_backup_directory()
    backup_subdir = os.path.join(BACKUP_DIR, stack_name)
    if not os.path.isdir(backup_subdir):
        return []

    backups = [
        name for name in os.listdir(backup_subdir)
        if BACKUP_NAME_RE.match(name)
    ]
    backups.sort(reverse=True)
    return backups


def validate_compose_yaml(content):
    """Validate compose YAML and return an error message or None."""
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return str(exc)
    return None


def run_compose_command(stack_name, command, detach=True):
    """Run a docker compose command for a stack."""
    stack_dir = get_stack_path(stack_name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return None, "Stack not found"

    cmd = ['docker', 'compose', '-f', os.path.basename(compose_file)]

    if command == 'up':
        cmd.extend(['up', '-d'] if detach else ['up'])
    elif command == 'down':
        cmd.append('down')
    elif command == 'restart':
        cmd.append('restart')
    elif command == 'pull':
        cmd.append('pull')
    elif command == 'stop':
        cmd.append('stop')
    elif command == 'start':
        cmd.append('start')
    else:
        return None, f"Unknown command: {command}"

    try:
        result = subprocess.run(
            cmd,
            cwd=stack_dir,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout for pull operations
        )

        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }, None

    except subprocess.TimeoutExpired:
        return None, "Command timed out"
    except Exception as e:
        return None, str(e)


# ============================================================================
# API Endpoints
# ============================================================================

@stack_manager.route('/api/stacks', methods=['GET'])
@login_required
def api_list_stacks():
    """List all stacks."""
    stacks, error = list_stacks()
    if error:
        return jsonify({'stacks': [], 'error': error}), 200

    # Optionally include status for each stack
    include_status = request.args.get('status', 'false').lower() == 'true'

    if include_status:
        for stack in stacks:
            status_info, _ = get_stack_status(stack['name'])
            if status_info:
                stack['status'] = status_info['status']
                stack['running_count'] = status_info.get('running_count', 0)
                stack['container_count'] = status_info.get('container_count', 0)
            else:
                stack['status'] = 'unknown'

    return jsonify({'stacks': stacks})


@stack_manager.route('/api/stacks/scan', methods=['POST'])
@login_required
def api_scan_stacks():
    """Re-scan the stacks directory."""
    stacks, error = list_stacks()
    if error:
        return jsonify({'error': error}), 500
    return jsonify({'stacks': stacks, 'count': len(stacks)})


@stack_manager.route('/api/stacks/<name>', methods=['GET'])
@login_required
def api_get_stack(name):
    """Get details for a specific stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return jsonify({'error': 'Stack not found'}), 404

    # Get compose content
    try:
        with open(compose_file, 'r') as f:
            content = f.read()
    except Exception as e:
        return jsonify({'error': f'Error reading compose file: {e}'}), 500

    # Get status
    status_info, _ = get_stack_status(name)

    # Check for .env file
    env_file = os.path.join(stack_dir, '.env')
    has_env = os.path.exists(env_file)
    env_content = None
    if has_env:
        try:
            with open(env_file, 'r') as f:
                env_content = f.read()
        except:
            pass

    return jsonify({
        'name': name,
        'path': stack_dir,
        'compose_file': os.path.basename(compose_file),
        'compose_content': content,
        'has_env': has_env,
        'env_content': env_content,
        'status': status_info
    })


@stack_manager.route('/api/stacks/<name>', methods=['POST'])
@login_required
def api_create_stack(name):
    """Create a new stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)

    if os.path.exists(stack_dir):
        return jsonify({'error': 'Stack already exists'}), 409

    data = request.get_json() or {}
    compose_content = data.get('compose_content', '')
    env_content = data.get('env_content', '')

    if not compose_content:
        # Provide a minimal template
        compose_content = f"""# {name} stack
services:
  # Add your services here
  # example:
  #   image: nginx:latest
  #   ports:
  #     - "8080:80"
"""
    else:
        error = validate_compose_yaml(compose_content)
        if error:
            return jsonify({'error': f'Compose YAML invalid: {error}'}), 400

    try:
        os.makedirs(stack_dir, exist_ok=True)

        # Write compose file
        compose_file = os.path.join(stack_dir, 'compose.yaml')
        with open(compose_file, 'w') as f:
            f.write(compose_content)

        # Write .env file if provided
        if env_content:
            env_file = os.path.join(stack_dir, '.env')
            with open(env_file, 'w') as f:
                f.write(env_content)

        return jsonify({'status': 'created', 'name': name, 'path': stack_dir})

    except Exception as e:
        # Cleanup on failure
        if os.path.exists(stack_dir):
            shutil.rmtree(stack_dir, ignore_errors=True)
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>', methods=['DELETE'])
@login_required
def api_delete_stack(name):
    """Delete a stack (stops containers first)."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)

    if not os.path.exists(stack_dir):
        return jsonify({'error': 'Stack not found'}), 404

    # Stop containers first
    run_compose_command(name, 'down')

    # Backup before deletion
    backup_stack(name)

    try:
        shutil.rmtree(stack_dir)
        return jsonify({'status': 'deleted', 'name': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/compose', methods=['GET'])
@login_required
def api_get_compose(name):
    """Get the compose file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return jsonify({'error': 'Stack not found'}), 404

    try:
        with open(compose_file, 'r') as f:
            content = f.read()
        return jsonify({'content': content, 'filename': os.path.basename(compose_file)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/compose', methods=['POST'])
@login_required
def api_save_compose(name):
    """Save the compose file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return jsonify({'error': 'Stack not found'}), 404

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400

    error = validate_compose_yaml(data['content'])
    if error:
        return jsonify({'error': f'Compose YAML invalid: {error}'}), 400

    # Backup before saving
    backup_stack(name)

    try:
        with open(compose_file, 'w') as f:
            f.write(data['content'])
        return jsonify({'status': 'saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/env', methods=['GET'])
@login_required
def api_get_env(name):
    """Get the .env file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)
    env_file = os.path.join(stack_dir, '.env')

    if not os.path.exists(env_file):
        return jsonify({'content': '', 'exists': False})

    try:
        with open(env_file, 'r') as f:
            content = f.read()
        return jsonify({'content': content, 'exists': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/env', methods=['POST'])
@login_required
def api_save_env(name):
    """Save the .env file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)

    if not os.path.exists(stack_dir):
        return jsonify({'error': 'Stack not found'}), 404

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400

    env_file = os.path.join(stack_dir, '.env')

    try:
        with open(env_file, 'w') as f:
            f.write(data['content'])
        return jsonify({'status': 'saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/backups', methods=['GET'])
@login_required
def api_list_backups(name):
    """List backups for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    backups = list_backups(name)
    return jsonify({'backups': backups})


@stack_manager.route('/api/stacks/<name>/backups/<backup_name>', methods=['GET'])
@login_required
def api_get_backup(name, backup_name):
    """Get a specific backup content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    if not BACKUP_NAME_RE.match(backup_name):
        return jsonify({'error': 'Invalid backup name'}), 400

    backup_path = os.path.join(BACKUP_DIR, name, backup_name)
    if not os.path.exists(backup_path):
        return jsonify({'error': 'Backup not found'}), 404

    try:
        with open(backup_path, 'r') as f:
            content = f.read()
        return jsonify({'content': content, 'filename': backup_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/restore', methods=['POST'])
@login_required
def api_restore_backup(name):
    """Restore a stack compose file from a backup."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    data = request.get_json()
    if not data or 'backup' not in data:
        return jsonify({'error': 'No backup specified'}), 400

    backup_name = data['backup']
    if not BACKUP_NAME_RE.match(backup_name):
        return jsonify({'error': 'Invalid backup name'}), 400

    backup_path = os.path.join(BACKUP_DIR, name, backup_name)
    if not os.path.exists(backup_path):
        return jsonify({'error': 'Backup not found'}), 404

    stack_dir = get_stack_path(name)
    compose_file = find_compose_file(stack_dir)
    if not compose_file:
        return jsonify({'error': 'Stack not found'}), 404

    try:
        with open(backup_path, 'r') as f:
            content = f.read()

        error = validate_compose_yaml(content)
        if error:
            return jsonify({'error': f'Compose YAML invalid: {error}'}), 400

        backup_stack(name)
        with open(compose_file, 'w') as f:
            f.write(content)

        return jsonify({'status': 'restored', 'backup': backup_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/status', methods=['GET'])
@login_required
def api_get_stack_status(name):
    """Get the status of a stack's containers."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    status_info, error = get_stack_status(name)
    if error:
        return jsonify({'error': error}), 404

    return jsonify(status_info)


@stack_manager.route('/api/stacks/<name>/up', methods=['POST'])
@login_required
def api_stack_up(name):
    """Start a stack (docker compose up -d)."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    result, error = run_compose_command(name, 'up')
    if error:
        return jsonify({'error': error}), 500

    return jsonify(result)


@stack_manager.route('/api/stacks/<name>/down', methods=['POST'])
@login_required
def api_stack_down(name):
    """Stop a stack (docker compose down)."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    result, error = run_compose_command(name, 'down')
    if error:
        return jsonify({'error': error}), 500

    return jsonify(result)


@stack_manager.route('/api/stacks/<name>/restart', methods=['POST'])
@login_required
def api_stack_restart(name):
    """Restart a stack (docker compose restart)."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    result, error = run_compose_command(name, 'restart')
    if error:
        return jsonify({'error': error}), 500

    return jsonify(result)


@stack_manager.route('/api/stacks/<name>/pull', methods=['POST'])
@login_required
def api_stack_pull(name):
    """Pull latest images for a stack (docker compose pull)."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    result, error = run_compose_command(name, 'pull')
    if error:
        return jsonify({'error': error}), 500

    return jsonify(result)


@stack_manager.route('/api/stacks/<name>/logs', methods=['GET'])
@login_required
def api_stack_logs(name):
    """Get logs for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    stack_dir = get_stack_path(name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        return jsonify({'error': 'Stack not found'}), 404

    tail = request.args.get('tail', '100')
    service = request.args.get('service', '')

    cmd = ['docker', 'compose', '-f', os.path.basename(compose_file), 'logs', '--tail', tail]
    if service:
        cmd.append(service)

    try:
        result = subprocess.run(
            cmd,
            cwd=stack_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        return jsonify({
            'logs': result.stdout + result.stderr,
            'returncode': result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timeout getting logs'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# SSE Streaming Endpoints (Phase 2)
# ============================================================================

def stream_compose_command(stack_name, command):
    """Generator that streams compose command output via SSE."""
    stack_dir = get_stack_path(stack_name)
    compose_file = find_compose_file(stack_dir)

    if not compose_file:
        yield f"data: {json.dumps({'error': 'Stack not found'})}\n\n"
        return

    cmd = ['docker', 'compose', '-f', os.path.basename(compose_file)]

    if command == 'up':
        cmd.extend(['up', '-d'])
    elif command == 'down':
        cmd.append('down')
    elif command == 'pull':
        cmd.append('pull')
    elif command == 'restart':
        cmd.append('restart')
    else:
        yield f"data: {json.dumps({'error': 'Unknown command'})}\n\n"
        return

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=stack_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in iter(proc.stdout.readline, ''):
            if line:
                yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"

        proc.wait()
        yield f"data: {json.dumps({'done': True, 'returncode': proc.returncode})}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


@stack_manager.route('/api/stacks/<name>/up/stream', methods=['GET'])
@login_required
def api_stack_up_stream(name):
    """Start a stack with streaming output."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    return Response(
        stream_compose_command(name, 'up'),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@stack_manager.route('/api/stacks/<name>/down/stream', methods=['GET'])
@login_required
def api_stack_down_stream(name):
    """Stop a stack with streaming output."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    return Response(
        stream_compose_command(name, 'down'),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@stack_manager.route('/api/stacks/<name>/pull/stream', methods=['GET'])
@login_required
def api_stack_pull_stream(name):
    """Pull images for a stack with streaming output."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    return Response(
        stream_compose_command(name, 'pull'),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@stack_manager.route('/api/stacks/<name>/restart/stream', methods=['GET'])
@login_required
def api_stack_restart_stream(name):
    """Restart a stack with streaming output."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    return Response(
        stream_compose_command(name, 'restart'),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )
