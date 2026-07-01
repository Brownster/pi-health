"""
Stack Manager - Dockge-inspired stack management for pi-health

Manages Docker Compose stacks as directories containing compose.yaml files.
"""
import json
import fcntl
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from flask import Blueprint, current_app, has_app_context, jsonify, request, session
import yaml
from auth_utils import csrf_protect, login_required
from operation_manager import (
    OperationCapacityError,
    parse_sse_payload,
)
from operation_sse import stream_operation_response
from stack_read_service import (
    BACKUP_NAME_RE,
    DOCKER_PS_STACK_FORMAT,
    STACK_FILENAMES,
    ComposeFileConflictError,
    StackArtifactReadError,
    StackNotFoundError,
    StackReadService,
    find_compose_file,
)
from stack_mutation_service import (
    StackComposeValidationError,
    StackMutationError,
    StackMutationNotFoundError,
    StackMutationService,
)
from stack_operations_service import (
    StackOperationError,
    StackOperationNotFoundError,
    StackOperationsService,
    compose_up_args,
)

# Create Blueprint
stack_manager = Blueprint('stack_manager', __name__)

# Configuration
STACKS_PATH = os.getenv('STACKS_PATH', '/opt/stacks')
STACK_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]*$')
BACKUP_DIR = os.getenv('STACK_BACKUP_DIR', os.path.join(STACKS_PATH, '.backups'))
_stack_lock_state = threading.local()


@stack_manager.errorhandler(ComposeFileConflictError)
def handle_compose_file_conflict(error):
    return jsonify(error.as_dict()), 409


def _stack_lock_path(name):
    lock_dir = os.path.join(STACKS_PATH, '.locks')
    os.makedirs(lock_dir, mode=0o700, exist_ok=True)
    return os.path.join(lock_dir, f'{name}.lock')


@contextmanager
def stack_lock(name):
    """Hold a reentrant, inter-process lock for one stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        raise ValueError(error)

    lock_path = os.path.abspath(_stack_lock_path(name))
    current_pid = os.getpid()
    if getattr(_stack_lock_state, 'pid', None) != current_pid:
        _stack_lock_state.pid = current_pid
        _stack_lock_state.held_locks = {}
    held_locks = getattr(_stack_lock_state, 'held_locks', None)
    if held_locks is None:
        held_locks = {}
        _stack_lock_state.held_locks = held_locks

    held = held_locks.get(lock_path)
    if held:
        held['depth'] += 1
        try:
            yield
        finally:
            held['depth'] -= 1
        return

    lock_file = open(lock_path, 'a+')
    try:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        held_locks[lock_path] = {'file': lock_file, 'depth': 1}
        try:
            yield
        finally:
            held_locks.pop(lock_path, None)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def atomic_write_text(path, content, mode=0o644):
    """Durably replace a text file without exposing partial content."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    if os.path.exists(path):
        mode = stat.S_IMODE(os.stat(path).st_mode)

    fd, temp_path = tempfile.mkstemp(
        dir=directory,
        prefix=f'.{os.path.basename(path)}.',
        suffix='.tmp',
    )
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


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


def get_compose_filename(stack_dir):
    """Get just the filename of the compose file."""
    compose_file = find_compose_file(stack_dir)
    return os.path.basename(compose_file) if compose_file else None


def ensure_stacks_directory():
    """Ensure the stacks directory exists."""
    os.makedirs(STACKS_PATH, exist_ok=True)


def ensure_backup_directory():
    """Ensure the backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def default_stack_read_service():
    return StackReadService(
        stacks_path_provider=lambda: STACKS_PATH,
        backup_path_provider=lambda: BACKUP_DIR,
        command_runner=lambda command, **kwargs: subprocess.run(command, **kwargs),
    )


def _stack_reads():
    if has_app_context():
        service = current_app.extensions.get("stack_read_service")
        if service is not None:
            return service
    return default_stack_read_service()


def default_stack_mutation_service():
    return StackMutationService(
        stacks_path_provider=lambda: STACKS_PATH,
        backup_path_provider=lambda: BACKUP_DIR,
        now_provider=lambda: datetime.now(),
        lock_provider=lambda name: stack_lock(name),
        atomic_writer=lambda path, content, **kwargs: atomic_write_text(
            path, content, **kwargs
        ),
        backup_writer=lambda name: backup_stack(name),
        compose_validator=lambda content: validate_compose_yaml(content),
    )


def _stack_mutations():
    if has_app_context():
        service = current_app.extensions.get("stack_mutation_service")
        if service is not None:
            return service
    return default_stack_mutation_service()


def default_stack_operations_service():
    return StackOperationsService(
        stacks_path_provider=lambda: STACKS_PATH,
        lock_provider=lambda name: stack_lock(name),
        command_runner=lambda command, **kwargs: subprocess.run(command, **kwargs),
        service_name_validator=lambda name: validate_stack_name(name),
    )


def _stack_operations():
    if has_app_context():
        service = current_app.extensions.get("stack_operations_service")
        if service is not None:
            return service
    return default_stack_operations_service()


def list_stacks():
    """List all stacks in the stacks directory."""
    return _stack_reads().list_stacks()


def get_stack_status(stack_name):
    """Get the status of containers in a stack."""
    return _stack_reads().status(stack_name)


def get_stack_status_snapshot(stacks):
    """Resolve all stack summaries from one labeled Docker container snapshot."""
    return _stack_reads().status_snapshot(stacks)


def backup_stack(stack_name):
    """Create a backup of a stack's compose file."""
    return _stack_mutations().create_backup(stack_name)


def list_backups(stack_name):
    """List backups for a stack, newest first."""
    return _stack_reads().list_backups(stack_name)


def validate_compose_yaml(content):
    """Validate compose YAML and return an error message or None."""
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return str(exc)
    return None


def _compose_up_args(detach=True):
    """Build project reconciliation args for the canonical stack file."""
    return compose_up_args(detach)


def run_compose_command(stack_name, command, detach=True, service=None):
    """Run a docker compose command for a stack."""
    return _stack_operations().run(
        stack_name, command, detach=detach, service=service
    )


# ============================================================================
# API Endpoints
# ============================================================================

@stack_manager.route('/api/stacks', methods=['GET'])
@login_required
def api_list_stacks():
    """List all stacks."""
    include_status = request.args.get('status', 'false').lower() == 'true'
    service = current_app.extensions["stack_read_service"]
    stacks, error = service.list_with_status(include_status=include_status)
    if error:
        return jsonify({'stacks': [], 'error': error}), 200
    return jsonify({'stacks': stacks})


@stack_manager.route('/api/stacks/scan', methods=['POST'])
@login_required
def api_scan_stacks():
    """Re-scan the stacks directory."""
    service = current_app.extensions["stack_read_service"]
    stacks, error = service.list_stacks()
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

    service = current_app.extensions["stack_read_service"]
    try:
        return jsonify(service.stack_details(name))
    except StackNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackArtifactReadError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>', methods=['POST'])
@login_required
def api_create_stack(name):
    """Create a new stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

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

    stack_dir = get_stack_path(name)
    with stack_lock(name):
        if os.path.exists(stack_dir):
            return jsonify({'error': 'Stack already exists'}), 409

        try:
            os.makedirs(stack_dir)
            atomic_write_text(
                os.path.join(stack_dir, 'compose.yaml'),
                compose_content,
            )
            if env_content:
                atomic_write_text(
                    os.path.join(stack_dir, '.env'),
                    env_content,
                    mode=0o600,
                )

            return jsonify({'status': 'created', 'name': name, 'path': stack_dir})

        except Exception as e:
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

    data = request.get_json(silent=True) or {}
    force_requested = data.get('force') is True
    if force_requested and data.get('confirm_name') != name:
        return jsonify({'error': 'Force delete requires exact stack name confirmation'}), 400

    stack_dir = get_stack_path(name)
    with stack_lock(name):
        if not os.path.exists(stack_dir):
            return jsonify({'error': 'Stack not found'}), 404

        down_result, down_error = run_compose_command(name, 'down')
        down_succeeded = bool(
            not down_error
            and down_result
            and down_result.get('success')
        )
        if not down_succeeded and not force_requested:
            detail = down_error or (down_result or {}).get('stderr') or 'Compose down failed'
            return jsonify({
                'error': f'Cannot delete stack: {detail}',
                'down_result': down_result,
                'force_delete_available': True,
            }), 409

        backup_stack(name)

        try:
            shutil.rmtree(stack_dir)
            return jsonify({
                'status': 'deleted',
                'name': name,
                'forced': force_requested and not down_succeeded,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@stack_manager.route('/api/stacks/<name>/compose', methods=['GET'])
@login_required
def api_get_compose(name):
    """Get the compose file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    service = current_app.extensions["stack_read_service"]
    try:
        return jsonify(service.compose(name))
    except StackNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackArtifactReadError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>/compose', methods=['POST'])
@login_required
def api_save_compose(name):
    """Save the compose file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400

    service = current_app.extensions["stack_mutation_service"]
    try:
        return jsonify(service.save_compose(name, data['content']))
    except StackComposeValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except StackMutationNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackMutationError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>/env', methods=['GET'])
@login_required
def api_get_env(name):
    """Get the .env file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    service = current_app.extensions["stack_read_service"]
    try:
        return jsonify(service.env(name))
    except StackArtifactReadError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>/env', methods=['POST'])
@login_required
def api_save_env(name):
    """Save the .env file content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'error': 'No content provided'}), 400

    service = current_app.extensions["stack_mutation_service"]
    try:
        return jsonify(service.save_env(name, data['content']))
    except StackMutationNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackMutationError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>/backups', methods=['GET'])
@login_required
def api_list_backups(name):
    """List backups for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    service = current_app.extensions["stack_read_service"]
    return jsonify({'backups': service.list_backups(name)})


@stack_manager.route('/api/stacks/<name>/backups/<backup_name>', methods=['GET'])
@login_required
def api_get_backup(name, backup_name):
    """Get a specific backup content for a stack."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    if not BACKUP_NAME_RE.match(backup_name):
        return jsonify({'error': 'Invalid backup name'}), 400

    service = current_app.extensions["stack_read_service"]
    try:
        return jsonify(service.backup(name, backup_name))
    except StackNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackArtifactReadError as exc:
        return jsonify({'error': str(exc)}), 500


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

    service = current_app.extensions["stack_mutation_service"]
    try:
        return jsonify(service.restore(name, backup_name))
    except StackComposeValidationError as exc:
        return jsonify({'error': str(exc)}), 400
    except StackMutationNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackMutationError as exc:
        return jsonify({'error': str(exc)}), 500


@stack_manager.route('/api/stacks/<name>/status', methods=['GET'])
@login_required
def api_get_stack_status(name):
    """Get the status of a stack's containers."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    service = current_app.extensions["stack_read_service"]
    status_info, error = service.status(name)
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

    result, error = current_app.extensions["stack_operations_service"].run(name, 'up')
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

    result, error = current_app.extensions["stack_operations_service"].run(name, 'down')
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

    result, error = current_app.extensions["stack_operations_service"].run(
        name, 'restart'
    )
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

    result, error = current_app.extensions["stack_operations_service"].run(name, 'pull')
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

    tail = request.args.get('tail', '100')
    service = request.args.get('service', '')
    operations = current_app.extensions["stack_operations_service"]
    try:
        return jsonify(operations.logs(name, tail=tail, service=service))
    except StackOperationNotFoundError as exc:
        return jsonify({'error': str(exc)}), 404
    except StackOperationError as exc:
        return jsonify({'error': str(exc)}), 500


# ============================================================================
# SSE Streaming Endpoints (Phase 2)
# ============================================================================

def stream_compose_command(stack_name, command):
    """Generator that streams compose command output via SSE."""
    with stack_lock(stack_name):
        stack_dir = get_stack_path(stack_name)
        compose_file = find_compose_file(stack_dir)

        if not compose_file:
            yield f"data: {json.dumps({'error': 'Stack not found'})}\n\n"
            return

        cmd = ['docker', 'compose', '-f', os.path.basename(compose_file)]

        if command == 'up':
            cmd.extend(_compose_up_args())
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


@stack_manager.route('/api/stacks/<name>/operations', methods=['POST'])
@login_required
@csrf_protect
def api_create_stack_operation(name):
    """Create one stack command operation and return its read-only stream."""
    valid, error = validate_stack_name(name)
    if not valid:
        return jsonify({'error': error}), 400

    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in {'up', 'down', 'pull', 'restart'}:
        return jsonify({'error': 'Unknown stack action'}), 400

    if not find_compose_file(get_stack_path(name)):
        return jsonify({'error': 'Stack not found'}), 404

    def produce_events():
        for frame in stream_compose_command(name, action):
            payload = parse_sse_payload(frame)
            if payload is not None:
                yield payload

    try:
        operation = current_app.extensions["operation_registry"].create(
            owner=session['csrf_token'],
            username=session.get('username', 'unknown'),
            kind='stack',
            target=name,
            producer=produce_events,
        )
    except OperationCapacityError as exc:
        return jsonify({'error': str(exc)}), 429
    except RuntimeError as exc:
        return jsonify({'error': f'Unable to start stack operation: {exc}'}), 500

    return jsonify({
        'operation_id': operation.operation_id,
        'stream_url': f'/api/stacks/operations/{operation.operation_id}/stream',
    }), 202


@stack_manager.route('/api/stacks/operations/<operation_id>/stream', methods=['GET'])
@login_required
def api_stream_stack_operation(operation_id):
    """Replay and follow one previously created stack operation."""
    return stream_operation_response(
        current_app.extensions["operation_registry"],
        operation_id,
        expected_kind='stack',
    )
