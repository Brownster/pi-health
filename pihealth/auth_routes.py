"""Simple authentication routes for the dashboard."""

import json
import os
from flask import Blueprint, request, session, jsonify
from werkzeug.security import check_password_hash


auth_bp = Blueprint("auth_bp", __name__)

# Path to the JSON file storing user credentials. Can be overridden with the
# USERS_FILE_PATH environment variable.
USERS_FILE = os.getenv(
    "USERS_FILE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "users.json")
)


def _load_users():
    """Load the user database from disk."""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@auth_bp.route("/api/login", methods=["POST"])
def login():
    """Validate credentials and create a session."""
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"status": "error", "message": "Missing credentials"}), 400

    users = _load_users()
    password_hash = users.get(username)
    if password_hash and check_password_hash(password_hash, password):
        session["username"] = username
        return jsonify({"status": "success"})

    return jsonify({"status": "error", "message": "Invalid credentials"}), 401


@auth_bp.route("/api/logout", methods=["POST"])
def logout():
    """Clear the user's session."""
    session.pop("username", None)
    return jsonify({"status": "success"})


@auth_bp.route("/api/me", methods=["GET"])
def whoami():
    """Return the currently logged in user, if any."""
    username = session.get("username")
    return jsonify({"logged_in": bool(username), "username": username})

