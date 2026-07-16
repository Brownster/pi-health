import socket

from flask import Blueprint, jsonify, request
from auth_utils import login_required
from helper_client import helper_call, helper_available, HelperError
from disk_manager import load_media_paths

setup_manager = Blueprint('setup_manager', __name__)


def _lan_subnet_from_ip(ip):
    """Best-effort LAN /24 for a host IP (e.g. 192.168.0.45 -> 192.168.0.0/24).

    Returns None for missing/loopback/malformed addresses so the caller can skip it.
    """
    if not ip or ip.startswith('127.'):
        return None
    octets = ip.split('.')
    if len(octets) != 4 or not all(o.isdigit() and 0 <= int(o) <= 255 for o in octets):
        return None
    return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"


def _default_lan_subnet():
    """The host's LAN /24, derived from the interface that reaches the default gateway.

    Used to seed gluetun's FIREWALL_OUTBOUND_SUBNETS so containers sharing the VPN
    namespace (network_mode: service:vpn) can still reach LAN services such as the
    LimeOS stack-notifications webhook, which the VPN firewall blocks by default.
    """
    ip = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(('8.8.8.8', 80))  # no packet sent; just selects the egress iface
            ip = probe.getsockname()[0]
        finally:
            probe.close()
    except OSError:
        ip = None
    return _lan_subnet_from_ip(ip)


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
        # Allow the LAN out of the VPN so containers behind gluetun can reach LAN
        # services (e.g. the stack-notifications webhook). Caller may override.
        outbound_subnets = (data.get('outbound_subnets') or '').strip() or _default_lan_subnet()
        env_lines = [
            "VPN_SERVICE_PROVIDER=private internet access",
            f"OPENVPN_USER={pia_username}",
            f"OPENVPN_PASSWORD={pia_password}",
            "SERVER_REGIONS=Netherlands",
        ]
        if outbound_subnets:
            env_lines.append(f"FIREWALL_OUTBOUND_SUBNETS={outbound_subnets}")
        env_lines.append("")
        env_content = "\n".join(env_lines)
        env_result = helper_call('write_vpn_env', {
            'path': env_path,
            'content': env_content
        })
        if not env_result.get('success'):
            return jsonify({'error': env_result.get('error', 'Failed to write VPN env')}), 500

        return jsonify({'status': 'ok', 'env_path': env_path})
    except HelperError as exc:
        return jsonify({'error': str(exc)}), 503
