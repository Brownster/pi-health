#!/usr/bin/env python3
"""Generate a Werkzeug-compatible PBKDF2 password hash without dependencies."""

import getpass
import hashlib
import secrets


PBKDF2_ITERATIONS = 600_000


def generate_password_hash(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2:sha256:{PBKDF2_ITERATIONS}${salt}${digest}"


def main() -> None:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password:
        raise SystemExit("Password must not be empty")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    print(generate_password_hash(password))


if __name__ == "__main__":
    main()
