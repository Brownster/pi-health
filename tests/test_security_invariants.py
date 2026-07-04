"""BF-004 characterization: authentication, CSRF, and credential invariants.

These tests lock in security guarantees that must survive any transport or client
change. They assert on behavior (rejection, constant work, token rotation) rather
than on HTTP payload shapes, so they fail when an invariant regresses even if the
response body still looks valid.
"""

from flask import Flask, jsonify

from app import AppDependencies, create_app
from auth_utils import (
    LoginRateLimiter,
    csrf_protect,
    get_csrf_token,
    rotate_csrf_token,
    verify_credentials,
)
from operation_manager import OperationRegistry
from werkzeug.security import generate_password_hash

VALID_TOKEN = "x" * 40


def _authenticated_client(*, csrf_header):
    """Build an authenticated test client, optionally sending the CSRF header."""
    dependencies = AppDependencies(
        users={"u": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
        login_rate_limiter=LoginRateLimiter(),
        docker_client=None,
        operation_registry=OperationRegistry(),
    )
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "INIT_PLUGINS": False,
            "START_SCHEDULERS": False,
        },
        dependencies,
    )
    client = application.test_client()
    with client.session_transaction() as session:
        session["authenticated"] = True
        session["username"] = "u"
        session["csrf_token"] = "session-token"
    if csrf_header:
        client.environ_base["HTTP_X_CSRF_TOKEN"] = "session-token"
    return client


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


# --- app-wide CSRF enforcement (before_request) ------------------------------

def test_authenticated_mutation_without_token_is_rejected():
    """An authenticated POST without X-CSRF-Token is blocked app-wide (403)."""
    response = _authenticated_client(csrf_header=False).post("/api/logout")
    assert response.status_code == 403


def test_authenticated_mutation_with_matching_token_passes():
    """An authenticated POST with the matching token is allowed through."""
    response = _authenticated_client(csrf_header=True).post("/api/logout")
    assert response.status_code == 200


def test_get_requests_do_not_require_csrf():
    response = _authenticated_client(csrf_header=False).get("/api/auth/check")
    assert response.status_code == 200


def test_login_route_is_exempt_from_csrf():
    """POST /api/login must not be blocked by CSRF (no token exists pre-login)."""
    client = _authenticated_client(csrf_header=False)
    with client.session_transaction() as session:
        session.clear()  # unauthenticated, no token
    response = client.post(
        "/api/login",
        json={"username": "u", "password": "wrong"},
    )
    assert response.status_code != 403


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
