"""BF-004 characterization: authentication, CSRF, and credential invariants.

These tests lock in security guarantees that must survive any transport or client
change. They assert on behavior (rejection, constant work, token rotation) rather
than on HTTP payload shapes, so they fail when an invariant regresses even if the
response body still looks valid.
"""

from flask import Flask, jsonify

from auth_utils import (
    csrf_protect,
    get_csrf_token,
    rotate_csrf_token,
    verify_credentials,
)
from werkzeug.security import generate_password_hash

VALID_TOKEN = "x" * 40


def _make_app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key"

    @app.route("/mutate", methods=["POST"])
    @csrf_protect
    def mutate():
        return jsonify({"ok": True})

    @app.route("/rotate", methods=["POST"])
    def rotate():
        return jsonify({"token": rotate_csrf_token()})

    @app.route("/token")
    def token():
        return jsonify({"token": get_csrf_token()})

    return app


# --- csrf_protect decorator --------------------------------------------------

def test_csrf_protect_rejects_missing_header():
    """A mutation without the CSRF header is rejected even with a session token."""
    client = _make_app().test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = VALID_TOKEN
    response = client.post("/mutate")
    assert response.status_code == 403


def test_csrf_protect_rejects_when_no_session_token():
    """A mutation is rejected when the session has no CSRF token at all."""
    client = _make_app().test_client()
    response = client.post("/mutate", headers={"X-CSRF-Token": VALID_TOKEN})
    assert response.status_code == 403


def test_csrf_protect_rejects_mismatched_token():
    """A mutation with the wrong token value is rejected."""
    client = _make_app().test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = VALID_TOKEN
    response = client.post("/mutate", headers={"X-CSRF-Token": "y" * 40})
    assert response.status_code == 403


def test_csrf_protect_allows_matching_token():
    """A mutation with the exact session token is allowed through."""
    client = _make_app().test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = VALID_TOKEN
    response = client.post("/mutate", headers={"X-CSRF-Token": VALID_TOKEN})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


# --- CSRF token lifecycle ----------------------------------------------------

def test_rotate_issues_strong_token_and_persists_it():
    """rotate_csrf_token stores a fresh high-entropy token in the session."""
    client = _make_app().test_client()
    token = client.post("/rotate").get_json()["token"]
    assert isinstance(token, str)
    assert len(token) >= 32
    with client.session_transaction() as sess:
        assert sess["csrf_token"] == token


def test_get_token_returns_existing_valid_token_without_rotation():
    """get_csrf_token returns the current token when it is already valid."""
    client = _make_app().test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = VALID_TOKEN
    assert client.get("/token").get_json()["token"] == VALID_TOKEN


def test_get_token_rotates_when_missing():
    """get_csrf_token mints a strong token when the session has none."""
    client = _make_app().test_client()
    token = client.get("/token").get_json()["token"]
    assert len(token) >= 32
    with client.session_transaction() as sess:
        assert sess["csrf_token"] == token


def test_get_token_rotates_when_existing_token_is_too_short():
    """A short (weak/legacy) token is replaced with a strong one."""
    client = _make_app().test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = "short"
    token = client.get("/token").get_json()["token"]
    assert token != "short"
    assert len(token) >= 32


# --- verify_credentials ------------------------------------------------------

def test_verify_credentials_accepts_correct_password():
    users = {"admin": generate_password_hash("secret", method="pbkdf2:sha256:600000")}
    assert verify_credentials(users, "admin", "secret") is True


def test_verify_credentials_rejects_wrong_password():
    users = {"admin": generate_password_hash("secret", method="pbkdf2:sha256:600000")}
    assert verify_credentials(users, "admin", "nope") is False


def test_verify_credentials_unknown_user_still_performs_comparison(monkeypatch):
    """An unknown username must return False *and* still run a hash comparison.

    Short-circuiting for missing users would leak account existence through
    response timing; this invariant keeps the work constant.
    """
    calls = []

    def spy(comparison_hash, password):
        calls.append((comparison_hash, password))
        return True  # Even a "matching" comparison must not authenticate a ghost.

    monkeypatch.setattr("auth_utils.check_password_hash", spy)
    users = {"admin": "a-stored-hash"}

    assert verify_credentials(users, "ghost", "secret") is False
    assert calls, "expected a hash comparison for the unknown user"
