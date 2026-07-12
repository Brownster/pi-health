"""
Helper service client utilities.
"""
import json
import os
import socket
import struct


HELPER_SOCKET = os.getenv('PIHEALTH_HELPER_SOCKET', '/run/pihealth/helper.sock')
MAX_MESSAGE_SIZE = 65536
FRAME_HEADER_SIZE = 4


class HelperError(Exception):
    """Error communicating with helper service."""
    pass


def _recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise HelperError('Incomplete response from helper')
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)


def _recv_frame(sock):
    header = _recv_exact(sock, FRAME_HEADER_SIZE)
    (message_size,) = struct.unpack('!I', header)
    if not 0 < message_size <= MAX_MESSAGE_SIZE:
        raise HelperError('Invalid response size from helper')
    return _recv_exact(sock, message_size)


def helper_call(command, params=None, *, timeout=30):
    """
    Call the privileged helper service.

    Args:
        command: Command name (must be whitelisted in helper)
        params: Optional dict of parameters
        timeout: Socket deadline in seconds (1..1800 for bounded setup operations)

    Returns:
        Response dict from helper

    Raises:
        HelperError: If communication fails
    """
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 1 <= timeout <= 1800
    ):
        raise HelperError('Invalid helper timeout')
    if not os.path.exists(HELPER_SOCKET):
        raise HelperError('Helper service not running (socket not found)')

    request_data = {
        'command': command,
        'params': params or {}
    }

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(HELPER_SOCKET)
        payload = json.dumps(request_data, separators=(',', ':')).encode('utf-8')
        if len(payload) > MAX_MESSAGE_SIZE:
            raise HelperError('Helper request exceeds maximum size')
        sock.sendall(struct.pack('!I', len(payload)) + payload)

        response = json.loads(_recv_frame(sock).decode('utf-8'))
        return response
    except socket.timeout:
        raise HelperError('Helper request timed out')
    except socket.error as exc:
        raise HelperError(f'Socket error: {exc}')
    except json.JSONDecodeError:
        raise HelperError('Invalid response from helper')
    finally:
        if 'sock' in locals():
            sock.close()


def helper_available():
    """Check if the helper service is available."""
    try:
        result = helper_call('ping')
        return result.get('success', False)
    except HelperError:
        return False
