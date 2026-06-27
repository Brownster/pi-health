import math
import os
import string
import threading
import time
from collections import deque
from functools import wraps

from flask import jsonify, session
from werkzeug.security import check_password_hash


class CredentialConfigurationError(RuntimeError):
    """Raised when no safe login credential configuration is available."""


def _validate_password_hash(password_hash):
    parts = password_hash.split("$")
    method = parts[0] if parts else ""
    method_parts = method.split(":")
    valid_method = False
    expected_digest_length = 0

    try:
        if method_parts[:2] == ["pbkdf2", "sha256"] and len(method_parts) == 3:
            valid_method = int(method_parts[2]) > 0
            expected_digest_length = 64
        elif method_parts[:1] == ["scrypt"] and len(method_parts) == 4:
            valid_method = all(int(value) > 0 for value in method_parts[1:])
            expected_digest_length = 128
    except ValueError:
        valid_method = False

    digest = parts[2] if len(parts) == 3 else ""
    if (
        len(parts) != 3
        or not all(parts)
        or not valid_method
        or len(digest) != expected_digest_length
        or any(character not in string.hexdigits for character in digest)
    ):
        raise CredentialConfigurationError(
            "Password values must be Werkzeug scrypt or PBKDF2-SHA256 hashes"
        )


def load_users(environ=None):
    """Load explicitly configured users with password hashes only."""
    env = os.environ if environ is None else environ
    if env.get("PIHEALTH_PASSWORD", "").strip():
        raise CredentialConfigurationError(
            "PIHEALTH_PASSWORD plaintext configuration is not supported; remove it "
            "after setting PIHEALTH_PASSWORD_HASH"
        )
    users_value = env.get("PIHEALTH_USERS", "").strip()
    users = {}

    if users_value:
        for entry in users_value.split(","):
            if ":" not in entry:
                raise CredentialConfigurationError(
                    "PIHEALTH_USERS entries must use username:password_hash"
                )
            username, password_hash = entry.split(":", 1)
            username = username.strip()
            password_hash = password_hash.strip()
            if not username or username in users:
                raise CredentialConfigurationError(
                    "PIHEALTH_USERS contains an empty or duplicate username"
                )
            _validate_password_hash(password_hash)
            users[username] = password_hash
    else:
        username = env.get("PIHEALTH_USER", "").strip()
        password_hash = env.get("PIHEALTH_PASSWORD_HASH", "").strip()
        if not username or not password_hash:
            raise CredentialConfigurationError(
                "Authentication is not configured. Set PIHEALTH_USER and "
                "PIHEALTH_PASSWORD_HASH, or set PIHEALTH_USERS with hashed passwords."
            )
        _validate_password_hash(password_hash)
        users[username] = password_hash

    return users


def verify_credentials(users, username, password):
    """Verify a password while performing equivalent hash work for unknown users."""
    password_hash = users.get(username)
    comparison_hash = password_hash or next(iter(users.values()))
    password_matches = check_password_hash(comparison_hash, password)
    return password_hash is not None and password_matches


class LoginRateLimiter:
    """Bound failed login attempts per client in the current app process."""

    def __init__(self, max_attempts=5, window_seconds=60, lockout_seconds=60, clock=None):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._clock = clock or time.monotonic
        self._failures = {}
        self._blocked_until = {}
        self._lock = threading.Lock()

    def retry_after(self, client_key):
        now = self._clock()
        with self._lock:
            blocked_until = self._blocked_until.get(client_key, 0)
            if blocked_until <= now:
                self._blocked_until.pop(client_key, None)
                return 0
            return max(1, math.ceil(blocked_until - now))

    def record_failure(self, client_key):
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            failures = self._failures.setdefault(client_key, deque())
            while failures and failures[0] <= cutoff:
                failures.popleft()
            failures.append(now)
            if len(failures) < self.max_attempts:
                return 0
            blocked_until = now + self.lockout_seconds
            self._blocked_until[client_key] = blocked_until
            failures.clear()
            return self.lockout_seconds

    def reset(self, client_key=None):
        with self._lock:
            if client_key is None:
                self._failures.clear()
                self._blocked_until.clear()
                return
            self._failures.pop(client_key, None)
            self._blocked_until.pop(client_key, None)


def login_required(f):
    """Decorator to require authentication for API endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function
