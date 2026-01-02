#!/usr/bin/env python3
"""
Tests for shared auth utilities.
"""
import os
import sys

import pytest
from flask import Flask, jsonify

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth_utils import login_required


@pytest.fixture
def client():
    """Create a test client for a minimal Flask app."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'

    @app.route('/protected')
    @login_required
    def protected():
        return jsonify({'ok': True})

    with app.test_client() as client:
        yield client


def test_login_required_rejects_unauthenticated(client):
    """Unauthenticated requests should be rejected."""
    response = client.get('/protected')
    assert response.status_code == 401


def test_login_required_allows_authenticated(client):
    """Authenticated requests should pass through."""
    with client.session_transaction() as sess:
        sess['authenticated'] = True

    response = client.get('/protected')
    assert response.status_code == 200
