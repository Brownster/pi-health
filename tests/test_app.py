#!/usr/bin/env python3
"""
Tests for Pi-Health application
"""
import pytest
import json
import sys
import os
import subprocess

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import LOGIN_RATE_LIMITER, app, load_users, verify_credentials
from auth_utils import CredentialConfigurationError

TEST_USERNAME = os.environ["PIHEALTH_USER"]
TEST_PASSWORD = os.environ["PIHEALTH_TEST_PASSWORD"]
TEST_PASSWORD_HASH = os.environ["PIHEALTH_PASSWORD_HASH"]


@pytest.fixture
def client():
    """Create a test client for the Flask application."""
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    LOGIN_RATE_LIMITER.reset()
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
        assert verify_credentials(TEST_USERNAME, TEST_PASSWORD) is True

    def test_verify_credentials_invalid(self):
        """Test that invalid credentials are rejected."""
        assert verify_credentials('nonexistent', 'wrongpass') is False

    def test_verify_credentials_wrong_password(self):
        """Test that wrong password is rejected."""
        assert verify_credentials(TEST_USERNAME, 'wrongpassword') is False

    def test_login_endpoint_success(self, client):
        """Test successful login."""
        response = client.post('/api/login',
            data=json.dumps({'username': TEST_USERNAME, 'password': TEST_PASSWORD}),
            content_type='application/json')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert data['username'] == TEST_USERNAME

    def test_missing_credentials_are_rejected(self):
        with pytest.raises(CredentialConfigurationError, match="not configured"):
            load_users({})

    def test_app_startup_fails_without_credentials(self):
        result = subprocess.run(
            [sys.executable, "-c", "import app"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env={},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        assert result.returncode != 0
        assert "Authentication is not configured" in result.stderr

    def test_plaintext_password_configuration_is_rejected(self):
        with pytest.raises(CredentialConfigurationError, match="plaintext"):
            load_users({"PIHEALTH_USER": "admin", "PIHEALTH_PASSWORD": "pihealth"})

        with pytest.raises(CredentialConfigurationError, match="plaintext"):
            load_users({
                "PIHEALTH_USER": "admin",
                "PIHEALTH_PASSWORD": "pihealth",
                "PIHEALTH_PASSWORD_HASH": TEST_PASSWORD_HASH,
            })

        with pytest.raises(CredentialConfigurationError, match="hashes"):
            load_users({"PIHEALTH_USERS": "admin:pihealth"})

    def test_hashed_multi_user_configuration(self):
        users = load_users({"PIHEALTH_USERS": f"admin:{TEST_PASSWORD_HASH}"})
        assert users == {"admin": TEST_PASSWORD_HASH}

    def test_malformed_password_hash_is_rejected(self):
        malformed_hash = "pbkdf2:unknown:1$salt$" + ("0" * 64)
        with pytest.raises(CredentialConfigurationError, match="PBKDF2-SHA256"):
            load_users({
                "PIHEALTH_USER": "admin",
                "PIHEALTH_PASSWORD_HASH": malformed_hash,
            })

    def test_login_rate_limit_and_recovery(self, client):
        payload = {'username': TEST_USERNAME, 'password': 'wrong'}
        for _ in range(4):
            response = client.post('/api/login', json=payload)
            assert response.status_code == 401

        response = client.post('/api/login', json=payload)
        assert response.status_code == 429
        assert int(response.headers['Retry-After']) > 0

        blocked_valid_login = client.post(
            '/api/login',
            json={'username': TEST_USERNAME, 'password': TEST_PASSWORD},
        )
        assert blocked_valid_login.status_code == 429

        LOGIN_RATE_LIMITER.reset('127.0.0.1')
        recovered = client.post(
            '/api/login',
            json={'username': TEST_USERNAME, 'password': TEST_PASSWORD},
        )
        assert recovered.status_code == 200

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

    def test_logout_clears_session(self, authenticated_client):
        """Test logout clears authenticated session state."""
        with authenticated_client.session_transaction() as sess:
            assert sess.get('authenticated') is True
            assert sess.get('username') == 'testuser'

        response = authenticated_client.post('/api/logout')
        assert response.status_code == 200

        with authenticated_client.session_transaction() as sess:
            assert sess.get('authenticated') is None
            assert sess.get('username') is None

    def test_auth_check_authenticated_without_username(self, client):
        """Test auth check falls back to unknown username."""
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess.pop('username', None)

        response = client.get('/api/auth/check')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['authenticated'] is True
        assert data['username'] == 'unknown'

    def test_auth_check_stale_session_is_unauthenticated(self, client):
        """Test stale session data without auth flag is treated as unauthenticated."""
        with client.session_transaction() as sess:
            sess['username'] = 'stale-user'
            sess.pop('authenticated', None)

        response = client.get('/api/auth/check')
        assert response.status_code == 401
        data = json.loads(response.data)
        assert data['authenticated'] is False


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

    def test_shutdown_with_auth_calls_system_action(self, authenticated_client, monkeypatch):
        """Test authenticated shutdown delegates to system_action."""
        monkeypatch.setattr('app.system_action', lambda action: {'status': f'{action}-ok'})
        response = authenticated_client.post('/api/shutdown')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'shutdown-ok'

    def test_reboot_with_auth_calls_system_action(self, authenticated_client, monkeypatch):
        """Test authenticated reboot delegates to system_action."""
        monkeypatch.setattr('app.system_action', lambda action: {'status': f'{action}-ok'})
        response = authenticated_client.post('/api/reboot')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'reboot-ok'

    def test_network_test_with_auth_calls_runner(self, authenticated_client, monkeypatch):
        """Test authenticated network test delegates to run_network_test."""
        monkeypatch.setattr(
            'app.run_network_test',
            lambda: {'ping_success': True, 'probe_method': 'socket'},
        )
        response = authenticated_client.post('/api/network-test')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['ping_success'] is True
        assert data['probe_method'] == 'socket'


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
        body = response.data.decode('utf-8')
        assert '/css/foundation.css' in body
        assert '/css/index.css' in body
        assert 'type="module" src="/js/pages/index.js"' in body
        assert 'Docker Web Services' in body

    def test_containers_page(self, client):
        """Test containers page loads."""
        response = client.get('/containers.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert '/css/foundation.css' in body
        assert '/css/containers.css' in body
        assert 'type="module" src="/js/pages/containers.js"' in body
        assert 'Docker Containers' in body

    def test_system_page(self, client):
        """Test system page loads."""
        response = client.get('/system.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert '/css/foundation.css' in body
        assert '/css/system.css' in body
        assert 'type="module" src="/js/pages/system.js"' in body
        assert 'System Metrics' in body

    def test_edit_page(self, client):
        """Test edit page loads."""
        response = client.get('/edit.html')
        assert response.status_code == 404

    def test_login_page(self, client):
        """Test login page loads."""
        response = client.get('/login.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert '/css/foundation.css' in body
        assert '/css/login.css' in body
        assert 'type="module" src="/js/pages/login.js"' in body
        assert 'onclick=' not in body
        assert 'onkeydown=' not in body

    def test_storage_page_redirects(self, client):
        """Test storage page redirects to pools.html."""
        response = client.get('/storage.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Redirecting' in body or 'pools.html' in body

    def test_pools_page(self, client):
        """Test pools page loads."""
        response = client.get('/pools.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Storage Pools' in body
        assert 'pool-plugins' in body

    def test_mounts_page(self, client):
        """Test mounts page loads."""
        response = client.get('/mounts.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Mounts' in body
        assert 'Media Paths' in body
        assert 'mount-plugins' in body

    def test_shares_page(self, client):
        """Test shares page loads."""
        response = client.get('/shares.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Shares' in body
        assert 'shares-content' in body
        assert 'share-modal' in body

    def test_plugins_page(self, client):
        """Test plugins page loads."""
        response = client.get('/plugins.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Plugins' in body
        assert 'plugins-list' in body

    def test_tools_page(self, client):
        """Test tools page loads."""
        response = client.get('/tools.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Tools' in body
        assert 'CopyParty' in body

    def test_settings_page_setup_hooks(self, client):
        """Test settings page has backup hooks (Tailscale moved to /tailscale.html)."""
        response = client.get('/settings.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'tailscale-authkey' not in body  # Moved to /tailscale.html
        assert 'vpn-config-dir' not in body
        assert 'backup-enabled' in body
        assert 'backup-dest-dir' in body
        assert 'backup-config-dir' in body
        assert 'backup-stacks-path' in body
        assert 'backup-retention' in body
        assert 'backup-include-env' in body
        assert 'backup-plugins-enabled' in body
        assert 'backup-plugin-retention' in body
        assert 'backup-run-now' in body
        assert 'backup-list' in body
        assert 'backup-plugins-list' in body
        assert 'settings-pihealth-update' in body
        assert 'pihealth-repo-path' in body
        assert 'pihealth-service-name' in body
        assert 'settings-updates-logs' in body

    def test_network_page(self, client):
        """Test host network page loads."""
        response = client.get('/network.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Host Network' in body
        assert 'network-content' in body

    def test_tailscale_page(self, client):
        """Test Tailscale page loads."""
        response = client.get('/tailscale.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'Tailscale' in body
        assert 'tailscale-authkey' in body
        assert 'setup-section' in body
        assert 'status-section' in body

    def test_apps_page_vpn_config_modal(self, client):
        """Test apps page includes VPN config modal."""
        response = client.get('/apps.html')
        assert response.status_code == 200
        body = response.data.decode('utf-8')
        assert 'vpn-config-dir' in body
        assert 'vpn-username' in body
        assert 'vpn-password' in body
        assert 'vpn-network-name' in body

class TestV2Routes:
    """Test /v2 static serving and SPA fallback behavior."""

    def test_v2_root_serves_index_when_present(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        static_dir = tmp_path / "static"
        v2_dir = static_dir / "v2"
        v2_dir.mkdir(parents=True)
        (v2_dir / "index.html").write_text(
            "<html><body>v2-shell</body></html>",
            encoding="utf-8",
        )
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2')
        assert response.status_code == 200
        assert "v2-shell" in response.data.decode("utf-8")

    def test_v2_missing_index_returns_404(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        static_dir = tmp_path / "static"
        static_dir.mkdir(parents=True)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert "missing" in data["error"]

    def test_v2_assets_served_directly(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        static_dir = tmp_path / "static"
        assets_dir = static_dir / "v2" / "assets"
        assets_dir.mkdir(parents=True)
        (assets_dir / "app.js").write_text(
            "console.log('v2-asset');",
            encoding="utf-8",
        )
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2/assets/app.js')
        assert response.status_code == 200
        assert "v2-asset" in response.data.decode("utf-8")

    def test_v2_missing_asset_returns_404_without_spa_fallback(
        self,
        client,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        static_dir = tmp_path / "static"
        v2_dir = static_dir / "v2"
        v2_dir.mkdir(parents=True)
        (v2_dir / "index.html").write_text(
            "<html><body>v2-shell</body></html>",
            encoding="utf-8",
        )
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2/assets/missing.js')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert "asset not found" in data["error"]

    def test_v2_spa_route_falls_back_to_index(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        static_dir = tmp_path / "static"
        v2_dir = static_dir / "v2"
        v2_dir.mkdir(parents=True)
        (v2_dir / "index.html").write_text(
            "<html><body>v2-fallback</body></html>",
            encoding="utf-8",
        )
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2/containers')
        assert response.status_code == 200
        assert "v2-fallback" in response.data.decode("utf-8")


class TestUiRuntimeModes:
    """Test deterministic legacy/hybrid/v2 mode behavior."""

    def _build_mode_test_static(self, tmp_path):
        static_dir = tmp_path / "static"
        v2_dir = static_dir / "v2"
        v2_dir.mkdir(parents=True)

        (static_dir / "index.html").write_text("<html><body>legacy-index</body></html>", encoding="utf-8")
        (static_dir / "containers.html").write_text(
            "<html><body>legacy-containers</body></html>",
            encoding="utf-8",
        )
        (static_dir / "system.html").write_text("<html><body>legacy-system</body></html>", encoding="utf-8")
        (static_dir / "login.html").write_text("<html><body>legacy-login</body></html>", encoding="utf-8")
        (v2_dir / "index.html").write_text("<html><body>v2-shell</body></html>", encoding="utf-8")

        return static_dir

    def test_legacy_mode_disables_v2_routes(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "legacy")
        static_dir = self._build_mode_test_static(tmp_path)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        v2_response = client.get('/v2')
        assert v2_response.status_code == 404
        v2_data = json.loads(v2_response.data)
        assert "disabled" in v2_data["error"]

        legacy_response = client.get('/containers.html')
        assert legacy_response.status_code == 200
        assert "legacy-containers" in legacy_response.data.decode("utf-8")

    def test_invalid_mode_defaults_to_legacy(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "invalid-mode")
        static_dir = self._build_mode_test_static(tmp_path)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        response = client.get('/v2')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["mode"] == "legacy"

    def test_hybrid_mode_redirects_only_selected_pages(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        monkeypatch.setenv("PIHEALTH_UI_V2_PAGES", "containers,unknown")
        static_dir = self._build_mode_test_static(tmp_path)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        redirected = client.get('/containers.html', follow_redirects=False)
        assert redirected.status_code == 302
        assert redirected.headers["Location"] == "/v2/containers"

        legacy = client.get('/system.html')
        assert legacy.status_code == 200
        assert "legacy-system" in legacy.data.decode("utf-8")

    def test_v2_mode_prefers_v2_routes_for_legacy_pages(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "v2")
        static_dir = self._build_mode_test_static(tmp_path)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        index_response = client.get('/', follow_redirects=False)
        assert index_response.status_code == 302
        assert index_response.headers["Location"] == "/v2"

        containers_response = client.get('/containers.html', follow_redirects=False)
        assert containers_response.status_code == 302
        assert containers_response.headers["Location"] == "/v2/containers"

        login_response = client.get('/login.html')
        assert login_response.status_code == 200
        assert "legacy-login" in login_response.data.decode("utf-8")

    def test_hybrid_selected_pages_support_home_alias(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("PIHEALTH_UI_MODE", "hybrid")
        monkeypatch.setenv("PIHEALTH_UI_V2_PAGES", " home , system ")
        static_dir = self._build_mode_test_static(tmp_path)
        monkeypatch.setattr(app, "static_folder", str(static_dir))

        index_response = client.get('/', follow_redirects=False)
        assert index_response.status_code == 302
        assert index_response.headers["Location"] == "/v2"

        system_response = client.get('/system.html', follow_redirects=False)
        assert system_response.status_code == 302
        assert system_response.headers["Location"] == "/v2/system"

        containers_response = client.get('/containers.html')
        assert containers_response.status_code == 200
        assert "legacy-containers" in containers_response.data.decode("utf-8")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
