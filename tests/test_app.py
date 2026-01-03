#!/usr/bin/env python3
"""
Tests for Pi-Health application
"""
import pytest
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, verify_credentials, load_users, AUTH_USERS


@pytest.fixture
def client():
    """Create a test client for the Flask application."""
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    """Create an authenticated test client."""
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = 'testuser'
    return client


class TestAuthentication:
    """Test authentication functionality."""

    def test_verify_credentials_valid(self):
        """Test that valid credentials are accepted."""
        # Get first user from AUTH_USERS
        if AUTH_USERS:
            username = list(AUTH_USERS.keys())[0]
            password = AUTH_USERS[username]
            assert verify_credentials(username, password) is True

    def test_verify_credentials_invalid(self):
        """Test that invalid credentials are rejected."""
        assert verify_credentials('nonexistent', 'wrongpass') is False

    def test_verify_credentials_wrong_password(self):
        """Test that wrong password is rejected."""
        if AUTH_USERS:
            username = list(AUTH_USERS.keys())[0]
            assert verify_credentials(username, 'wrongpassword') is False

    def test_login_endpoint_success(self, client):
        """Test successful login."""
        if AUTH_USERS:
            username = list(AUTH_USERS.keys())[0]
            password = AUTH_USERS[username]
            response = client.post('/api/login',
                data=json.dumps({'username': username, 'password': password}),
                content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'success'
            assert data['username'] == username

    def test_login_endpoint_failure(self, client):
        """Test failed login."""
        response = client.post('/api/login',
            data=json.dumps({'username': 'wrong', 'password': 'wrong'}),
            content_type='application/json')
        assert response.status_code == 401
        data = json.loads(response.data)
        assert 'error' in data

    def test_login_endpoint_no_data(self, client):
        """Test login with no data."""
        response = client.post('/api/login',
            content_type='application/json')
        assert response.status_code == 400

    def test_logout_endpoint(self, authenticated_client):
        """Test logout endpoint."""
        response = authenticated_client.post('/api/logout')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'logged out'

    def test_auth_check_authenticated(self, authenticated_client):
        """Test auth check when authenticated."""
        response = authenticated_client.get('/api/auth/check')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['authenticated'] is True

    def test_auth_check_unauthenticated(self, client):
        """Test auth check when not authenticated."""
        response = client.get('/api/auth/check')
        assert response.status_code == 401


class TestProtectedEndpoints:
    """Test that protected endpoints require authentication."""

    def test_stats_requires_auth(self, client):
        """Test that /api/stats requires authentication."""
        response = client.get('/api/stats')
        assert response.status_code == 401

    @pytest.mark.skipif(not os.path.exists('/host_proc/stat'),
                        reason="/host_proc/stat not mounted - test requires Docker environment")
    def test_stats_with_auth(self, authenticated_client):
        """Test that /api/stats works when authenticated."""
        response = authenticated_client.get('/api/stats')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should have expected keys
        assert 'memory_usage' in data

    def test_containers_requires_auth(self, client):
        """Test that /api/containers requires authentication."""
        response = client.get('/api/containers')
        assert response.status_code == 401

    def test_containers_with_auth(self, authenticated_client):
        """Test that /api/containers works when authenticated."""
        response = authenticated_client.get('/api/containers')
        assert response.status_code == 200

    def test_shutdown_requires_auth(self, client):
        """Test that /api/shutdown requires authentication."""
        response = client.post('/api/shutdown')
        assert response.status_code == 401

    def test_reboot_requires_auth(self, client):
        """Test that /api/reboot requires authentication."""
        response = client.post('/api/reboot')
        assert response.status_code == 401

    def test_network_test_requires_auth(self, client):
        """Test that /api/network-test requires authentication."""
        response = client.post('/api/network-test')
        assert response.status_code == 401


class TestPublicEndpoints:
    """Test that public endpoints don't require authentication."""

    def test_theme_endpoint(self, client):
        """Test that /api/theme is publicly accessible."""
        response = client.get('/api/theme')
        assert response.status_code == 200

    def test_login_page(self, client):
        """Test that login page is accessible."""
        response = client.get('/login.html')
        assert response.status_code == 200

    def test_home_page(self, client):
        """Test that home page is accessible."""
        response = client.get('/')
        assert response.status_code == 200


class TestStaticPages:
    """Test static page serving."""

    def test_index_page(self, client):
        """Test index page loads."""
        response = client.get('/')
        assert response.status_code == 200

    def test_containers_page(self, client):
        """Test containers page loads."""
        response = client.get('/containers.html')
        assert response.status_code == 200

    def test_system_page(self, client):
        """Test system page loads."""
        response = client.get('/system.html')
        assert response.status_code == 200

    def test_edit_page(self, client):
        """Test edit page loads."""
        response = client.get('/edit.html')
        assert response.status_code == 200

    def test_login_page(self, client):
        """Test login page loads."""
        response = client.get('/login.html')
        assert response.status_code == 200

    def test_storage_page(self, client):
        """Test storage page loads and contains key sections."""
        response = client.get('/storage.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Storage' in body
        assert 'tab-snapraid' in body
        assert 'tab-mergerfs' in body
        assert 'tab-schedules' in body
        assert 'tab-tools' in body
        assert 'tab-recovery' in body
        assert 'snapraid-drives' in body
        assert 'snapraid-excludes' in body
        assert 'mergerfs-pools' in body
        assert 'schedule-sync-cron' in body
        assert 'snapraid-output' in body
        assert 'snapraid-modal' in body
        assert 'mergerfs-modal' in body
        assert 'snapraid-modal-name' in body
        assert 'mergerfs-modal-name' in body

    def test_settings_page_setup_hooks(self, client):
        """Test settings page has setup hooks."""
        response = client.get('/settings.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'tailscale-authkey' in body
        assert 'vpn-config-dir' in body
        assert 'vpn-username' in body
        assert 'vpn-password' in body
        assert 'vpn-network-name' in body


class TestComposeEditorProtection:
    """Test compose editor endpoints require authentication."""

    def test_compose_get_requires_auth(self, client):
        """Test that GET /api/compose requires authentication."""
        response = client.get('/api/compose')
        assert response.status_code == 401

    def test_compose_post_requires_auth(self, client):
        """Test that POST /api/compose requires authentication."""
        response = client.post('/api/compose',
            data=json.dumps({'content': 'test'}),
            content_type='application/json')
        assert response.status_code == 401

    def test_env_get_requires_auth(self, client):
        """Test that GET /api/env requires authentication."""
        response = client.get('/api/env')
        assert response.status_code == 401

    def test_env_post_requires_auth(self, client):
        """Test that POST /api/env requires authentication."""
        response = client.post('/api/env',
            data=json.dumps({'content': 'test'}),
            content_type='application/json')
        assert response.status_code == 401


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
