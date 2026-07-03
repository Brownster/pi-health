#!/usr/bin/env python3
"""
Tests for Auto-Update Scheduler module
"""
import pytest
import json
import sys
import os
import tempfile
import shutil
from unittest.mock import patch, Mock, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))




@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestAutoUpdateConfig:
    """Test auto-update configuration management."""

    def test_load_config_default(self, temp_config_dir):
        """Test default config when file doesn't exist."""
        import update_scheduler
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'nonexistent.json')

        try:
            config = update_scheduler.load_config()
            assert config is not None
            assert 'enabled' in config
            assert config['enabled'] is False
            assert config['schedule_preset'] == 'disabled'
            assert config['excluded_stacks'] == []
        finally:
            update_scheduler.CONFIG_FILE = original_config_file

    def test_save_config_creates_file(self, temp_config_dir):
        """Test config file creation."""
        import update_scheduler
        original_config_dir = update_scheduler.CONFIG_DIR
        original_config_file = update_scheduler.CONFIG_FILE

        update_scheduler.CONFIG_DIR = temp_config_dir
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            config = {
                'version': 1,
                'enabled': True,
                'schedule_preset': 'daily_4am',
                'excluded_stacks': ['test-stack'],
                'notify_on_update': True,
                'last_run': None,
                'last_run_result': None
            }
            update_scheduler.save_config(config)

            assert os.path.exists(update_scheduler.CONFIG_FILE)

            with open(update_scheduler.CONFIG_FILE, 'r') as f:
                saved_config = json.load(f)

            assert saved_config['enabled'] is True
            assert saved_config['schedule_preset'] == 'daily_4am'
            assert saved_config['excluded_stacks'] == ['test-stack']
        finally:
            update_scheduler.CONFIG_DIR = original_config_dir
            update_scheduler.CONFIG_FILE = original_config_file

    def test_config_round_trip(self, temp_config_dir):
        """Test saving and loading config preserves values."""
        import update_scheduler
        original_config_dir = update_scheduler.CONFIG_DIR
        original_config_file = update_scheduler.CONFIG_FILE

        update_scheduler.CONFIG_DIR = temp_config_dir
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            original_config = {
                'version': 1,
                'enabled': True,
                'schedule_preset': 'weekly_sunday_4am',
                'excluded_stacks': ['stack1', 'stack2'],
                'notify_on_update': False,
                'last_run': '2024-01-01T00:00:00',
                'last_run_result': {'updated': ['stack1'], 'failed': [], 'skipped': []}
            }
            update_scheduler.save_config(original_config)
            loaded_config = update_scheduler.load_config()

            assert loaded_config['enabled'] == original_config['enabled']
            assert loaded_config['schedule_preset'] == original_config['schedule_preset']
            assert loaded_config['excluded_stacks'] == original_config['excluded_stacks']
        finally:
            update_scheduler.CONFIG_DIR = original_config_dir
            update_scheduler.CONFIG_FILE = original_config_file


class TestSchedulePresets:
    """Test schedule preset to cron conversion."""

    def test_schedule_preset_daily(self):
        """Test daily_4am preset converts to correct cron."""
        from update_scheduler import get_schedule_cron
        cron = get_schedule_cron('daily_4am')
        assert cron == '0 4 * * *'

    def test_schedule_preset_weekly(self):
        """Test weekly_sunday_4am preset converts to correct cron."""
        from update_scheduler import get_schedule_cron
        cron = get_schedule_cron('weekly_sunday_4am')
        assert cron == '0 4 * * 0'

    def test_schedule_preset_disabled(self):
        """Test disabled preset returns None."""
        from update_scheduler import get_schedule_cron
        cron = get_schedule_cron('disabled')
        assert cron is None

    def test_schedule_preset_invalid(self):
        """Test invalid preset returns None."""
        from update_scheduler import get_schedule_cron
        cron = get_schedule_cron('invalid_preset')
        assert cron is None


class TestHasNewImages:
    """Test new image detection from pull output."""

    def test_has_new_images_downloaded(self):
        """Test detection of downloaded images."""
        from update_scheduler import has_new_images

        output = """
        [+] Pulling nginx (nginx:latest)...
        nginx Pulling from library/nginx
        Download complete
        Status: Downloaded newer image for nginx:latest
        """
        assert has_new_images(output) is True

    def test_has_new_images_extracting(self):
        """Test detection when extracting layers."""
        from update_scheduler import has_new_images
        output = "Extracting [==>                    ] 1.2MB/24.5MB"
        assert has_new_images(output) is True

    def test_has_new_images_up_to_date(self):
        """Test no new images detected."""
        from update_scheduler import has_new_images
        output = "nginx: digest: sha256:abc123 - Status: Image is up to date for nginx:latest"
        # This contains "Image is up to date" but our function looks for positive indicators
        assert has_new_images(output) is False

    def test_has_new_images_empty(self):
        """Test empty output."""
        from update_scheduler import has_new_images
        assert has_new_images('') is False
        assert has_new_images(None) is False


class TestAutoUpdateEndpoints:
    """Test auto-update API endpoints."""

    def test_get_config_requires_auth(self, client):
        """Test that /api/auto-update/config requires authentication."""
        response = client.get('/api/auto-update/config')
        assert response.status_code == 401

    def test_get_config_with_auth(self, authenticated_client, temp_config_dir):
        """Test GET /api/auto-update/config returns config."""
        import update_scheduler
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            response = authenticated_client.get('/api/auto-update/config')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'enabled' in data
            assert 'schedule_preset' in data
            assert 'excluded_stacks' in data
        finally:
            update_scheduler.CONFIG_FILE = original_config_file

    def test_set_config_requires_auth(self, client):
        """Test that POST /api/auto-update/config requires authentication."""
        response = client.post('/api/auto-update/config',
                               data=json.dumps({'enabled': True}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_set_config_updates_enabled(self, authenticated_client, temp_config_dir):
        """Test POST /api/auto-update/config updates enabled state."""
        import update_scheduler
        original_config_dir = update_scheduler.CONFIG_DIR
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_DIR = temp_config_dir
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            response = authenticated_client.post('/api/auto-update/config',
                                                  data=json.dumps({'enabled': True, 'schedule_preset': 'daily_4am'}),
                                                  content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'updated'
            assert data['config']['enabled'] is True
        finally:
            update_scheduler.CONFIG_DIR = original_config_dir
            update_scheduler.CONFIG_FILE = original_config_file

    def test_set_config_invalid_preset(self, authenticated_client, temp_config_dir):
        """Test POST with invalid preset returns error."""
        import update_scheduler
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            response = authenticated_client.post('/api/auto-update/config',
                                                  data=json.dumps({'schedule_preset': 'invalid_preset'}),
                                                  content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            update_scheduler.CONFIG_FILE = original_config_file

    def test_get_status_requires_auth(self, client):
        """Test that /api/auto-update/status requires authentication."""
        response = client.get('/api/auto-update/status')
        assert response.status_code == 401

    def test_get_status_with_auth(self, authenticated_client, temp_config_dir):
        """Test GET /api/auto-update/status returns status."""
        import update_scheduler
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            response = authenticated_client.get('/api/auto-update/status')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'enabled' in data
            assert 'schedule_preset' in data
            assert 'next_run' in data
            assert 'update_running' in data
        finally:
            update_scheduler.CONFIG_FILE = original_config_file

    def test_run_now_requires_auth(self, client):
        """Test that /api/auto-update/run-now requires authentication."""
        response = client.post('/api/auto-update/run-now')
        assert response.status_code == 401

    def test_get_logs_requires_auth(self, client):
        """Test that /api/auto-update/logs requires authentication."""
        response = client.get('/api/auto-update/logs')
        assert response.status_code == 401

    def test_get_logs_with_auth(self, authenticated_client, temp_config_dir):
        """Test GET /api/auto-update/logs returns logs."""
        import update_scheduler
        original_config_file = update_scheduler.CONFIG_FILE
        update_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'auto_update.json')

        try:
            response = authenticated_client.get('/api/auto-update/logs')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'last_run' in data
            assert 'last_run_result' in data
        finally:
            update_scheduler.CONFIG_FILE = original_config_file


class TestSettingsPage:
    """Test settings page accessibility."""

    def test_settings_page_loads(self, authenticated_client):
        """Test the legacy settings URL redirects to v2."""
        response = authenticated_client.get('/settings.html', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['Location'] == '/v2/settings'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
