"""Settings management API endpoints."""
from __future__ import annotations

import os
import secrets
import hashlib
import time
from typing import Dict, Any
from functools import wraps

from flask import Blueprint, jsonify, request, current_app, session
from app.services.mcp_manager import MCPServiceManager

settings_api = Blueprint('settings_api', __name__)

# Global MCP manager instance
_mcp_manager: MCPServiceManager = None

# Default admin credentials (should be changed on first use)
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD_HASH = hashlib.sha256("password".encode()).hexdigest()

def _get_stored_password_hash():
    """Get stored password hash from environment or use default."""
    return os.getenv('PI_HEALTH_PASSWORD_HASH', DEFAULT_PASSWORD_HASH)

def _hash_password(password: str) -> str:
    """Hash a password with SHA-256."""
    return hashlib.sha256(password.encode()).hexdigest()

def require_auth(f):
    """Decorator to require authentication for sensitive endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for valid session
        if not session.get('authenticated'):
            return jsonify({
                'success': False,
                'error': 'Authentication required. Please login first.'
            }), 401

        # Check session expiry (24 hours)
        login_time = session.get('login_time', 0)
        if time.time() - login_time > 86400:  # 24 hours
            session.clear()
            return jsonify({
                'success': False,
                'error': 'Session expired. Please login again.'
            }), 401

        return f(*args, **kwargs)
    return decorated_function


def get_mcp_manager() -> MCPServiceManager:
    """Get or create MCP manager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPServiceManager(current_app.config)
    return _mcp_manager


def _update_env_file(key: str, value: str) -> bool:
    """Update a value in the .env file."""
    env_path = '.env'

    # Create .env file if it doesn't exist
    if not os.path.exists(env_path):
        try:
            with open(env_path, 'w') as f:
                f.write(f'{key}={value}\n')
            return True
        except Exception as e:
            print(f"Error creating .env file: {e}")
            return False

    try:
        # Read current .env file
        with open(env_path, 'r') as f:
            lines = f.readlines()

        # Update the specified key
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith(f'{key}='):
                new_lines.append(f'{key}={value}\n')
                updated = True
            else:
                new_lines.append(line)

        # If key wasn't found, add it
        if not updated:
            new_lines.append(f'{key}={value}\n')

        # Write back to .env file
        with open(env_path, 'w') as f:
            f.writelines(new_lines)

        return True

    except Exception as e:
        print(f"Error updating .env file: {e}")
        return False


@settings_api.route('/api/auth/login', methods=['POST'])
def login():
    """Login endpoint with username/password authentication."""
    try:
        data = request.get_json() or {}
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()

        if not username or not password:
            return jsonify({
                'success': False,
                'error': 'Username and password are required'
            }), 400

        # Check credentials
        if username == DEFAULT_USERNAME and _hash_password(password) == _get_stored_password_hash():
            # Create session
            session['authenticated'] = True
            session['username'] = username
            session['login_time'] = time.time()
            session.permanent = True

            return jsonify({
                'success': True,
                'message': 'Login successful',
                'username': username
            })
        else:
            # Add delay to prevent brute force
            time.sleep(1)
            return jsonify({
                'success': False,
                'error': 'Invalid username or password'
            }), 401

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Login failed: {str(e)}'
        }), 500


@settings_api.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout endpoint."""
    session.clear()
    return jsonify({
        'success': True,
        'message': 'Logout successful'
    })


@settings_api.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """Get authentication status."""
    authenticated = session.get('authenticated', False)
    login_time = session.get('login_time', 0)

    # Check session expiry
    if authenticated and time.time() - login_time > 86400:  # 24 hours
        session.clear()
        authenticated = False

    return jsonify({
        'authenticated': authenticated,
        'username': session.get('username') if authenticated else None,
        'login_time': login_time if authenticated else None,
        'default_credentials': _get_stored_password_hash() == DEFAULT_PASSWORD_HASH
    })


@settings_api.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    """Change admin password."""
    try:
        data = request.get_json() or {}
        current_password = data.get('current_password', '').strip()
        new_password = data.get('new_password', '').strip()

        if not current_password or not new_password:
            return jsonify({
                'success': False,
                'error': 'Current password and new password are required'
            }), 400

        if len(new_password) < 8:
            return jsonify({
                'success': False,
                'error': 'New password must be at least 8 characters long'
            }), 400

        # Verify current password
        if _hash_password(current_password) != _get_stored_password_hash():
            return jsonify({
                'success': False,
                'error': 'Current password is incorrect'
            }), 401

        # Update password hash in .env
        new_hash = _hash_password(new_password)
        if _update_env_file('PI_HEALTH_PASSWORD_HASH', new_hash):
            # CRITICAL: Update runtime environment immediately so new hash takes effect
            os.environ['PI_HEALTH_PASSWORD_HASH'] = new_hash

            return jsonify({
                'success': True,
                'message': 'Password changed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save new password'
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Password change failed: {str(e)}'
        }), 500


@settings_api.route('/api/settings/status', methods=['GET'])
def get_settings_status():
    """Get current settings status."""
    config = current_app.config

    return jsonify({
        'ai_agent_enabled': config.get('ENABLE_AI_AGENT', False),
        'api_key_configured': bool(config.get('OPENAI_API_KEY', '').strip()),
        'openai_model': config.get('OPENAI_API_MODEL', 'gpt-4o-mini'),
        'disk_path': config.get('DISK_PATH', '/'),
        'disk_path_2': config.get('DISK_PATH_2', '/mnt/backup'),
        'system_actions_enabled': config.get('ENABLE_SYSTEM_ACTIONS', False),
        'legacy_suggestions_enabled': config.get('ENABLE_LEGACY_SUGGESTIONS', True),
        'authenticated': session.get('authenticated', False)
    })


@settings_api.route('/api/settings/ai-agent/toggle', methods=['POST'])
@require_auth
def toggle_ai_agent():
    """Toggle AI agent enable/disable state."""
    try:
        data = request.get_json() or {}
        enabled = data.get('enabled', False)

        # Update runtime config
        current_app.config['ENABLE_AI_AGENT'] = enabled

        # Update .env file
        if _update_env_file('ENABLE_AI_AGENT', 'true' if enabled else 'false'):
            # Clear/rebuild agent based on new state
            if enabled:
                # Import here to avoid circular imports
                from app.routes.ops_copilot import build_agent
                agent = build_agent(current_app.config)
                current_app.extensions['ops_copilot_agent'] = agent
            else:
                current_app.extensions['ops_copilot_agent'] = None

            return jsonify({
                'success': True,
                'enabled': enabled,
                'message': f'AI agent {"enabled" if enabled else "disabled"} successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to update configuration file'
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to toggle AI agent: {str(e)}'
        }), 500


@settings_api.route('/api/settings/api-key/update', methods=['POST'])
@require_auth
def update_api_key():
    """Update OpenAI API key."""
    try:
        data = request.get_json() or {}
        api_key = data.get('api_key', '').strip()

        if not api_key:
            return jsonify({
                'success': False,
                'error': 'API key is required'
            }), 400

        # More flexible API key validation for newer OpenAI formats
        if not api_key.startswith('sk-') or len(api_key) < 20:
            return jsonify({
                'success': False,
                'error': 'Invalid API key format - must start with sk- and be at least 20 characters'
            }), 400

        # Update runtime config
        current_app.config['OPENAI_API_KEY'] = api_key

        # Update .env file
        if _update_env_file('OPENAI_API_KEY', api_key):
            # If AI agent is currently enabled, rebuild it with new API key
            if current_app.config.get('ENABLE_AI_AGENT', False):
                from app.routes.ops_copilot import build_agent
                agent = build_agent(current_app.config)
                current_app.extensions['ops_copilot_agent'] = agent

            return jsonify({
                'success': True,
                'message': 'API key updated successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to update configuration file'
            }), 500

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to update API key: {str(e)}'
        }), 500


@settings_api.route('/api/settings/restart-agent', methods=['POST'])
@require_auth
def restart_ai_agent():
    """Restart the AI agent with current configuration."""
    try:
        if not current_app.config.get('ENABLE_AI_AGENT', False):
            return jsonify({
                'success': False,
                'error': 'AI agent is disabled'
            }), 400

        # Rebuild agent
        from app.routes.ops_copilot import build_agent
        agent = build_agent(current_app.config)
        current_app.extensions['ops_copilot_agent'] = agent

        return jsonify({
            'success': True,
            'message': 'AI agent restarted successfully'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to restart AI agent: {str(e)}'
        }), 500


@settings_api.route('/api/settings/system/update', methods=['POST'])
def update_system_settings():
    """Update system settings (paths, actions, etc.)."""
    try:
        data = request.get_json() or {}

        # This endpoint could be extended to allow updating system paths
        # For now, we return a message indicating these require restart
        return jsonify({
            'success': False,
            'error': 'System settings require application restart to update'
        }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to update system settings: {str(e)}'
        }), 500


# MCP Service Management Endpoints

@settings_api.route('/api/mcp/services', methods=['GET'])
def get_mcp_services():
    """Get list of all MCP services."""
    try:
        manager = get_mcp_manager()
        services = manager.get_all_services()

        return jsonify({
            'success': True,
            'services': [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description,
                    'status': s.status.value,
                    'port': s.port,
                    'url': s.url,
                    'pid': s.pid,
                    'auto_start': s.auto_start,
                    'config_required': s.config_required,
                    'last_started': s.last_started,
                    'last_used': s.last_used,
                }
                for s in services
            ]
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get MCP services: {str(e)}'
        }), 500


@settings_api.route('/api/mcp/services/<service_id>/start', methods=['POST'])
@require_auth
def start_mcp_service(service_id: str):
    """Start an MCP service."""
    try:
        manager = get_mcp_manager()
        result = manager.start_service(service_id)
        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to start service: {str(e)}'
        }), 500


@settings_api.route('/api/mcp/services/<service_id>/stop', methods=['POST'])
@require_auth
def stop_mcp_service(service_id: str):
    """Stop an MCP service."""
    try:
        manager = get_mcp_manager()
        result = manager.stop_service(service_id)
        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to stop service: {str(e)}'
        }), 500


@settings_api.route('/api/mcp/services/<service_id>/restart', methods=['POST'])
@require_auth
def restart_mcp_service(service_id: str):
    """Restart an MCP service."""
    try:
        manager = get_mcp_manager()
        result = manager.restart_service(service_id)
        status_code = 200 if result['success'] else 400
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to restart service: {str(e)}'
        }), 500


@settings_api.route('/api/mcp/services/bulk', methods=['POST'])
@require_auth
def bulk_mcp_action():
    """Perform bulk actions on MCP services."""
    try:
        data = request.get_json() or {}
        action = data.get('action')
        service_ids = data.get('service_ids', [])

        if not action or not service_ids:
            return jsonify({
                'success': False,
                'error': 'Action and service_ids are required'
            }), 400

        manager = get_mcp_manager()
        results = {}

        for service_id in service_ids:
            if action == 'start':
                results[service_id] = manager.start_service(service_id)
            elif action == 'stop':
                results[service_id] = manager.stop_service(service_id)
            elif action == 'restart':
                results[service_id] = manager.restart_service(service_id)
            else:
                results[service_id] = {'success': False, 'error': f'Unknown action: {action}'}

        return jsonify({
            'success': True,
            'action': action,
            'results': results
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to perform bulk action: {str(e)}'
        }), 500


@settings_api.route('/api/mcp/resource-usage', methods=['GET'])
def get_mcp_resource_usage():
    """Get resource usage statistics for MCP services."""
    try:
        manager = get_mcp_manager()
        usage = manager.get_resource_usage()
        return jsonify({
            'success': True,
            **usage
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Failed to get resource usage: {str(e)}'
        }), 500