from flask import Blueprint, jsonify, request
from auth_utils import login_required
from helper_client import helper_call, helper_available, HelperError
from disk_manager import load_media_paths

setup_manager = Blueprint('setup_manager', __name__)


@setup_manager.route('/api/setup/defaults', methods=['GET'])
@login_required
def api_setup_defaults():
    paths = load_media_paths()
    return jsonify({
        'config_dir': paths.get('config', '/home/pi/docker'),
        'network_name': 'vpn_network'
    })


@setup_manager.route('/api/setup/tailscale', methods=['POST'])
@login_required
def api_setup_tailscale():
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    data = request.get_json() or {}
    auth_key = data.get('auth_key', '').strip()

    try:
        install_result = helper_call('tailscale_install', {})
        if not install_result.get('success'):
            return jsonify({'error': install_result.get('stderr', 'Tailscale install failed')}), 500

        up_params = {}
        if auth_key:
            up_params['auth_key'] = auth_key
        up_result = helper_call('tailscale_up', up_params)
        if not up_result.get('success'):
            return jsonify({'error': up_result.get('stderr', 'Tailscale up failed')}), 500

        return jsonify({'status': 'ok'})
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503


@setup_manager.route('/api/tailscale/status', methods=['GET'])
@login_required
def api_tailscale_status():
    """Get Tailscale status and network info."""
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    try:
        result = helper_call('tailscale_status', {})
        return jsonify(result)
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503


@setup_manager.route('/api/tailscale/logout', methods=['POST'])
@login_required
def api_tailscale_logout():
    """Logout from Tailscale for re-authentication."""
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    try:
        result = helper_call('tailscale_logout', {})
        if not result.get('success'):
            return jsonify({'error': result.get('stderr', 'Logout failed')}), 500
        return jsonify({'status': 'ok'})
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503


@setup_manager.route('/api/network/info', methods=['GET'])
@login_required
def api_network_info():
    """Get detailed host network information."""
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    try:
        result = helper_call('network_info', {})
        return jsonify(result)
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503


@setup_manager.route('/api/setup/vpn', methods=['POST'])
@login_required
def api_setup_vpn():
    if not helper_available():
        return jsonify({'error': 'Helper service unavailable'}), 503

    data = request.get_json() or {}
    config_dir = data.get('config_dir', '/home/pi/docker').strip()
    network_name = data.get('network_name', 'vpn_network').strip()
    pia_username = data.get('pia_username', '').strip()
    pia_password = data.get('pia_password', '').strip()

    if not config_dir.startswith('/'):
        return jsonify({'error': 'Invalid config_dir'}), 400
    if not network_name:
        return jsonify({'error': 'Invalid network_name'}), 400
    if not pia_username or not pia_password:
        return jsonify({'error': 'PIA credentials required'}), 400

    try:
        net_result = helper_call('docker_network_create', {'name': network_name})
        if not net_result.get('success'):
            return jsonify({'error': net_result.get('stderr', 'Network create failed')}), 500

        env_path = f"{config_dir}/vpn/.env"
        env_content = "\n".join([
            "VPN_SERVICE_PROVIDER=private internet access",
            f"OPENVPN_USER={pia_username}",
            f"OPENVPN_PASSWORD={pia_password}",
            "SERVER_REGIONS=Netherlands",
            ""
        ])
        env_result = helper_call('write_vpn_env', {
            'path': env_path,
            'content': env_content
        })
        if not env_result.get('success'):
            return jsonify({'error': env_result.get('error', 'Failed to write VPN env')}), 500

        return jsonify({'status': 'ok', 'env_path': env_path})
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503
