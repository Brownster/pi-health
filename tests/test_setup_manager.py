#!/usr/bin/env python3
"""
Tests for setup manager endpoints.
"""
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = 'testuser'
    return client


class TestSetupEndpoints:
    def test_defaults_requires_auth(self, client):
        response = client.get('/api/setup/defaults')
        assert response.status_code == 401

    def test_tailscale_requires_auth(self, client):
        response = client.post('/api/setup/tailscale', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_vpn_requires_auth(self, client):
        response = client.post('/api/setup/vpn', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_defaults_with_auth(self, authenticated_client):
        response = authenticated_client.get('/api/setup/defaults')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'config_dir' in data
        assert 'network_name' in data

    def test_tailscale_helper_unavailable(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=False):
            response = authenticated_client.post('/api/setup/tailscale',
                                                 data=json.dumps({}),
                                                 content_type='application/json')
            assert response.status_code == 503

    def test_vpn_invalid_payload(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            response = authenticated_client.post('/api/setup/vpn',
                                                 data=json.dumps({'config_dir': 'relative'}),
                                                 content_type='application/json')
            assert response.status_code == 400
