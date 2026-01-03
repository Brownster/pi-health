#!/usr/bin/env python3
"""
Tests for Disk Manager module
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

from app import app


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


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestDiskManagerEndpoints:
    """Test disk manager API endpoints."""

    def test_disk_list_requires_auth(self, client):
        """Test that /api/disks requires authentication."""
        response = client.get('/api/disks')
        assert response.status_code == 401

    def test_disk_list_with_auth_no_helper(self, authenticated_client):
        """Test GET /api/disks when helper is not available."""
        import disk_manager
        original_socket = disk_manager.HELPER_SOCKET

        # Point to non-existent socket
        disk_manager.HELPER_SOCKET = '/tmp/nonexistent.sock'

        try:
            response = authenticated_client.get('/api/disks')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'helper_available' in data
            assert data['helper_available'] is False
        finally:
            disk_manager.HELPER_SOCKET = original_socket

    def test_helper_status_requires_auth(self, client):
        """Test that /api/disks/helper-status requires authentication."""
        response = client.get('/api/disks/helper-status')
        assert response.status_code == 401

    def test_helper_status_with_auth(self, authenticated_client):
        """Test GET /api/disks/helper-status returns status."""
        response = authenticated_client.get('/api/disks/helper-status')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'available' in data
        assert 'socket_path' in data

    def test_mount_requires_auth(self, client):
        """Test that /api/disks/mount requires authentication."""
        response = client.post('/api/disks/mount',
                              data=json.dumps({'uuid': 'test', 'mountpoint': '/mnt/test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_mount_missing_uuid(self, authenticated_client):
        """Test mount without UUID returns error."""
        response = authenticated_client.post('/api/disks/mount',
                                             data=json.dumps({'mountpoint': '/mnt/test'}),
                                             content_type='application/json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_mount_missing_mountpoint(self, authenticated_client):
        """Test mount without mountpoint returns error."""
        response = authenticated_client.post('/api/disks/mount',
                                             data=json.dumps({'uuid': 'abc-123'}),
                                             content_type='application/json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_mount_invalid_mountpoint(self, authenticated_client):
        """Test mount with invalid mountpoint returns error."""
        response = authenticated_client.post('/api/disks/mount',
                                             data=json.dumps({
                                                 'uuid': 'abc-123',
                                                 'mountpoint': '/home/test'
                                             }),
                                             content_type='application/json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'mnt' in data['error'].lower()

    def test_unmount_requires_auth(self, client):
        """Test that /api/disks/unmount requires authentication."""
        response = client.post('/api/disks/unmount',
                              data=json.dumps({'mountpoint': '/mnt/test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_unmount_missing_mountpoint(self, authenticated_client):
        """Test unmount without mountpoint returns error."""
        response = authenticated_client.post('/api/disks/unmount',
                                             data=json.dumps({}),
                                             content_type='application/json')
        assert response.status_code == 400

    def test_unmount_invalid_mountpoint(self, authenticated_client):
        """Test unmount with invalid mountpoint returns error."""
        response = authenticated_client.post('/api/disks/unmount',
                                             data=json.dumps({'mountpoint': '/tmp/test'}),
                                             content_type='application/json')
        assert response.status_code == 400


class TestMediaPaths:
    """Test media paths configuration."""

    def test_get_media_paths_requires_auth(self, client):
        """Test that /api/disks/media-paths GET requires authentication."""
        response = client.get('/api/disks/media-paths')
        assert response.status_code == 401

    def test_get_media_paths_with_auth(self, authenticated_client, temp_config_dir):
        """Test GET /api/disks/media-paths returns paths."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        disk_manager.MEDIA_PATHS_CONFIG = os.path.join(temp_config_dir, 'media_paths.json')

        try:
            response = authenticated_client.get('/api/disks/media-paths')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'paths' in data
            # Should have default paths
            assert 'downloads' in data['paths']
            assert 'storage' in data['paths']
            assert 'backup' in data['paths']
            assert 'config' in data['paths']
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_set_media_paths_requires_auth(self, client):
        """Test that /api/disks/media-paths POST requires authentication."""
        response = client.post('/api/disks/media-paths',
                              data=json.dumps({'downloads': '/mnt/dl'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_set_media_paths_with_auth(self, authenticated_client, temp_config_dir):
        """Test POST /api/disks/media-paths updates paths."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        disk_manager.MEDIA_PATHS_CONFIG = os.path.join(temp_config_dir, 'media_paths.json')

        try:
            response = authenticated_client.post('/api/disks/media-paths',
                                                 data=json.dumps({
                                                     'downloads': '/mnt/downloads-new',
                                                     'storage': '/mnt/media'
                                                 }),
                                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'updated'
            assert data['paths']['downloads'] == '/mnt/downloads-new'
            assert data['paths']['storage'] == '/mnt/media'

            # Verify saved to file
            with open(disk_manager.MEDIA_PATHS_CONFIG, 'r') as f:
                saved = json.load(f)
            assert saved['downloads'] == '/mnt/downloads-new'
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_set_media_paths_invalid_path(self, authenticated_client, temp_config_dir):
        """Test POST with invalid path returns error."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        disk_manager.MEDIA_PATHS_CONFIG = os.path.join(temp_config_dir, 'media_paths.json')

        try:
            response = authenticated_client.post('/api/disks/media-paths',
                                                 data=json.dumps({
                                                     'downloads': 'relative/path'
                                                 }),
                                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config


class TestSuggestedMounts:
    """Test mount suggestions endpoint."""

    def test_suggested_mounts_requires_auth(self, client):
        """Test that /api/disks/suggested-mounts requires authentication."""
        response = client.get('/api/disks/suggested-mounts')
        assert response.status_code == 401

    def test_suggested_mounts_no_helper(self, authenticated_client):
        """Test suggested mounts when helper not available returns empty suggestions."""
        import disk_manager
        original_socket = disk_manager.HELPER_SOCKET
        disk_manager.HELPER_SOCKET = '/tmp/nonexistent.sock'

        try:
            response = authenticated_client.get('/api/disks/suggested-mounts')
            # Returns 200 with empty suggestions when helper not available
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'suggestions' in data
            assert data['suggestions'] == []
        finally:
            disk_manager.HELPER_SOCKET = original_socket


class TestHelperFunctions:
    """Test helper utility functions."""

    def test_load_media_paths_default(self, temp_config_dir):
        """Test loading default media paths when no config exists."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        disk_manager.MEDIA_PATHS_CONFIG = os.path.join(temp_config_dir, 'nonexistent.json')

        try:
            paths = disk_manager.load_media_paths()
            assert paths['downloads'] == '/mnt/downloads'
            assert paths['storage'] == '/mnt/storage'
            assert paths['backup'] == '/mnt/backup'
            assert paths['config'] == '/home/pi/docker'
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_load_media_paths_from_file(self, temp_config_dir):
        """Test loading media paths from config file."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        config_file = os.path.join(temp_config_dir, 'media_paths.json')
        disk_manager.MEDIA_PATHS_CONFIG = config_file

        # Write custom config
        with open(config_file, 'w') as f:
            json.dump({
                'downloads': '/custom/downloads',
                'storage': '/custom/storage'
            }, f)

        try:
            paths = disk_manager.load_media_paths()
            assert paths['downloads'] == '/custom/downloads'
            assert paths['storage'] == '/custom/storage'
            # Should still have defaults for unspecified paths
            assert paths['backup'] == '/mnt/backup'
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_save_media_paths(self, temp_config_dir):
        """Test saving media paths to config file."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        config_file = os.path.join(temp_config_dir, 'subdir', 'media_paths.json')
        disk_manager.MEDIA_PATHS_CONFIG = config_file

        try:
            paths = {
                'downloads': '/new/downloads',
                'storage': '/new/storage',
                'backup': '/new/backup',
                'config': '/new/config'
            }
            disk_manager.save_media_paths(paths)

            # Verify file was created
            assert os.path.exists(config_file)

            with open(config_file, 'r') as f:
                saved = json.load(f)
            assert saved == paths
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_helper_available_false(self):
        """Test helper_available returns False when socket doesn't exist."""
        import disk_manager
        import helper_client
        original_socket = helper_client.HELPER_SOCKET
        helper_client.HELPER_SOCKET = '/tmp/nonexistent.sock'

        try:
            result = disk_manager.helper_available()
            assert result is False
        finally:
            helper_client.HELPER_SOCKET = original_socket

    def test_parse_size_to_gb(self):
        """Test size string parsing."""
        from disk_manager import _parse_size_to_gb

        assert _parse_size_to_gb('500G') == 500.0
        assert _parse_size_to_gb('1T') == 1024.0
        assert _parse_size_to_gb('512M') == 0.5
        assert _parse_size_to_gb('') is None
        assert _parse_size_to_gb(None) is None


class TestDisksPage:
    """Test disks page accessibility."""

    def test_disks_page_loads(self, authenticated_client):
        """Test disks page loads successfully."""
        response = authenticated_client.get('/disks.html')
        assert response.status_code == 200


class TestCatalogMediaPathsIntegration:
    """Test catalog manager integration with media paths."""

    def test_catalog_item_with_media_paths(self, authenticated_client, temp_config_dir):
        """Test catalog item applies media paths to defaults."""
        import catalog_manager
        import disk_manager

        # Set up temp config
        original_config = catalog_manager.MEDIA_PATHS_CONFIG
        original_catalog = catalog_manager.CATALOG_DIR
        temp_catalog = tempfile.mkdtemp()

        config_file = os.path.join(temp_config_dir, 'media_paths.json')
        catalog_manager.MEDIA_PATHS_CONFIG = config_file
        disk_manager.MEDIA_PATHS_CONFIG = config_file
        catalog_manager.CATALOG_DIR = temp_catalog

        # Write media paths config
        with open(config_file, 'w') as f:
            json.dump({
                'config': '/custom/docker',
                'downloads': '/custom/downloads'
            }, f)

        # Create a catalog item
        import yaml
        with open(os.path.join(temp_catalog, 'test.yaml'), 'w') as f:
            yaml.dump({
                'id': 'test-app',
                'name': 'Test App',
                'fields': [
                    {'key': 'CONFIG_DIR', 'label': 'Config', 'default': '/default/config'},
                    {'key': 'DOWNLOADS_DIR', 'label': 'Downloads', 'default': '/default/dl'},
                    {'key': 'OTHER_FIELD', 'label': 'Other', 'default': 'unchanged'}
                ],
                'service': {'image': 'test:latest'}
            }, f)

        try:
            # Request with media paths applied
            response = authenticated_client.get('/api/catalog/test-app?apply_media_paths=true')
            assert response.status_code == 200
            data = json.loads(response.data)

            fields = {f['key']: f['default'] for f in data['item']['fields']}
            assert fields['CONFIG_DIR'] == '/custom/docker'
            assert fields['DOWNLOADS_DIR'] == '/custom/downloads'
            assert fields['OTHER_FIELD'] == 'unchanged'

            # Request without media paths
            response = authenticated_client.get('/api/catalog/test-app')
            assert response.status_code == 200
            data = json.loads(response.data)

            fields = {f['key']: f['default'] for f in data['item']['fields']}
            assert fields['CONFIG_DIR'] == '/default/config'
        finally:
            catalog_manager.MEDIA_PATHS_CONFIG = original_config
            catalog_manager.CATALOG_DIR = original_catalog
            shutil.rmtree(temp_catalog, ignore_errors=True)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
