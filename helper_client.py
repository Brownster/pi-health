"""
Helper service client utilities.
"""
import json
import os
import socket


HELPER_SOCKET = os.getenv('PIHEALTH_HELPER_SOCKET', '/run/pihealth/helper.sock')


class HelperError(Exception):
    """Error communicating with helper service."""
    pass


def helper_call(command, params=None):
    """
    Call the privileged helper service.

    Args:
        command: Command name (must be whitelisted in helper)
        params: Optional dict of parameters

    Returns:
        Response dict from helper

    Raises:
        HelperError: If communication fails
    """
    if not os.path.exists(HELPER_SOCKET):
        raise HelperError('Helper service not running (socket not found)')

    request_data = {
        'command': command,
        'params': params or {}
    }

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(HELPER_SOCKET)
        sock.sendall(json.dumps(request_data).encode('utf-8'))

        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()

        response = json.loads(b''.join(chunks).decode('utf-8'))
        return response
    except socket.timeout:
        raise HelperError('Helper request timed out')
    except socket.error as exc:
        raise HelperError(f'Socket error: {exc}')
    except json.JSONDecodeError:
        raise HelperError('Invalid response from helper')


def helper_available():
    """Check if the helper service is available."""
    try:
        result = helper_call('ping')
        return result.get('success', False)
    except HelperError:
        return False
