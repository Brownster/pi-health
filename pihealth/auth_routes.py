"""Simple authentication routes for the dashboard."""

import json
import os
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth_bp", __name__)

_user_db = {}


def _users_file() -> str:
    """Return the path to the users file."""
    return os.getenv("PIHEALTH_USERS_FILE", "users.json")


def load_users() -> None:
    """Load users from the configured JSON file."""
    global _user_db
    path = _users_file()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            _user_db = data.get("users", {})
        except Exception:
            _user_db = {}
    else:
        _user_db = {}



# Load users when the module is imported
load_users()


@auth_bp.route("/api/login", methods=["POST"])
def login() -> tuple:
    """Handle login requests."""
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if username in _user_db and check_password_hash(_user_db[username], password):
        session["username"] = username
        return jsonify({"status": "success"})

    return (
        jsonify({"status": "error", "message": "Invalid credentials"}),
        401,
    )


@auth_bp.route("/api/logout", methods=["POST"])
def logout() -> dict:
    """Clear the current session."""
    session.pop("username", None)
    return {"status": "success"}


@auth_bp.route("/api/users", methods=["POST"])
def add_user() -> tuple:
    """Add a new user. Intended for small deployments."""

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return (
            jsonify({"status": "error", "message": "Username and password required"}),
            400,
        )

    if username in _user_db:
        return (
            jsonify({"status": "error", "message": "User already exists"}),
            400,
        )

    _user_db[username] = generate_password_hash(password)
    os.makedirs(os.path.dirname(_users_file()) or ".", exist_ok=True)
    with open(_users_file(), "w") as f:
        json.dump({"users": _user_db}, f, indent=2)

    return jsonify({"status": "success", "username": username})


@auth_bp.route("/api/current_user", methods=["GET"])
def current_user() -> dict:
    """Return the currently logged in user, if any."""
    user = session.get("username")
    return {"logged_in": bool(user), "username": user}

