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

    def test_mount_helper_error(self, authenticated_client):
        """Test mount returns 503 when helper raises."""
        import disk_manager
        from helper_client import HelperError

        with patch('disk_manager.helper_call', side_effect=HelperError("no helper")):
            response = authenticated_client.post(
                '/api/disks/mount',
                data=json.dumps({'uuid': 'abc-123', 'mountpoint': '/mnt/test'}),
                content_type='application/json'
            )
        assert response.status_code == 503

    def test_mount_adds_fstab_and_mounts(self, authenticated_client):
        """Test mount with fstab add and mount success."""
        def helper_call_side_effect(command, params=None):
            if command == 'fstab_add':
                return {'success': True}
            if command == 'mount':
                return {'success': True}
            return {'success': False, 'error': 'unexpected'}

        with patch('disk_manager.helper_call', side_effect=helper_call_side_effect):
            response = authenticated_client.post(
                '/api/disks/mount',
                data=json.dumps({
                    'uuid': 'abc-123',
                    'mountpoint': '/mnt/test',
                    'fstype': 'ext4',
                    'options': 'defaults',
                    'add_to_fstab': True
                }),
                content_type='application/json'
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'mounted'

    def test_mount_without_fstab_resolves_device(self, authenticated_client):
        """Test mount without fstab resolves device via blkid."""
        def helper_call_side_effect(command, params=None):
            if command == 'blkid':
                return {'success': True, 'data': [{'UUID': 'abc-123', 'DEVNAME': '/dev/sda1'}]}
            if command == 'mount':
                return {'success': True}
            return {'success': False}

        with patch('disk_manager.helper_call', side_effect=helper_call_side_effect):
            response = authenticated_client.post(
                '/api/disks/mount',
                data=json.dumps({
                    'uuid': 'abc-123',
                    'mountpoint': '/mnt/test',
                    'add_to_fstab': False
                }),
                content_type='application/json'
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'mounted'

    def test_mount_without_fstab_device_not_found(self, authenticated_client):
        """Test mount without fstab fails when device not found."""
        with patch('disk_manager.helper_call', return_value={'success': True, 'data': []}):
            response = authenticated_client.post(
                '/api/disks/mount',
                data=json.dumps({
                    'uuid': 'abc-123',
                    'mountpoint': '/mnt/test',
                    'add_to_fstab': False
                }),
                content_type='application/json'
            )
        assert response.status_code == 400

    def test_mount_fstab_add_failure(self, authenticated_client):
        """Test mount returns error when fstab add fails."""
        with patch('disk_manager.helper_call', return_value={'success': False, 'error': 'nope'}):
            response = authenticated_client.post(
                '/api/disks/mount',
                data=json.dumps({'uuid': 'abc-123', 'mountpoint': '/mnt/test'}),
                content_type='application/json'
            )
        assert response.status_code == 400

    def test_unmount_remove_from_fstab_warning(self, authenticated_client):
        """Test unmount warns when fstab removal fails."""
        def helper_call_side_effect(command, params=None):
            if command == 'umount':
                return {'success': True}
            if command == 'fstab_remove':
                return {'success': False, 'error': 'failed'}
            return {'success': False}

        with patch('disk_manager.helper_call', side_effect=helper_call_side_effect):
            response = authenticated_client.post(
                '/api/disks/unmount',
                data=json.dumps({'mountpoint': '/mnt/test', 'remove_from_fstab': True}),
                content_type='application/json'
            )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'unmounted'
        assert 'warning' in data


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

    def test_seedbox_requires_auth(self, client):
        """Test that /api/disks/seedbox GET requires authentication."""
        response = client.get('/api/disks/seedbox')
        assert response.status_code == 401

    def test_seedbox_set_requires_auth(self, client):
        """Test that /api/disks/seedbox POST requires authentication."""
        response = client.post('/api/disks/seedbox',
                              data=json.dumps({'enabled': True}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_startup_service_requires_auth(self, client):
        """Test that /api/disks/startup-service requires authentication."""
        response = client.post('/api/disks/startup-service')
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

    def test_startup_service_unavailable(self, authenticated_client, temp_config_dir):
        """Test startup service returns 503 when helper unavailable."""
        import disk_manager
        original_config = disk_manager.MEDIA_PATHS_CONFIG
        disk_manager.MEDIA_PATHS_CONFIG = os.path.join(temp_config_dir, 'media_paths.json')

        try:
            response = authenticated_client.post('/api/disks/startup-service')
            assert response.status_code == 503
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            disk_manager.MEDIA_PATHS_CONFIG = original_config

    def test_seedbox_unavailable(self, authenticated_client, temp_config_dir):
        """Test seedbox returns 503 when helper unavailable."""
        import disk_manager
        original_config = disk_manager.SEEDBOX_CONFIG
        original_helper_available = disk_manager.helper_available
        disk_manager.SEEDBOX_CONFIG = os.path.join(temp_config_dir, 'seedbox_mount.json')

        try:
            disk_manager.helper_available = lambda: False
            response = authenticated_client.post('/api/disks/seedbox',
                                                 data=json.dumps({'enabled': True, 'host': 'x', 'username': 'u', 'remote_path': '/data', 'password': 'p'}),
                                                 content_type='application/json')
            assert response.status_code == 503
        finally:
            disk_manager.SEEDBOX_CONFIG = original_config
            disk_manager.helper_available = original_helper_available

    def test_build_startup_script_includes_mounts(self):
        """Test startup script includes mount points."""
        import disk_manager
        script = disk_manager._build_startup_script({
            'storage': '/mnt/storage',
            'downloads': '/mnt/downloads',
            'backup': '/mnt/backup'
        })
        assert '/mnt/storage' in script
        assert '/mnt/downloads' in script
        assert '/mnt/backup' in script

    def test_build_startup_service(self):
        """Test startup service contents."""
        import disk_manager
        content = disk_manager._build_startup_service()
        assert 'ExecStart=/usr/local/bin/check_mount_and_start.sh' in content

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

    def test_suggested_mounts_with_nvme(self, authenticated_client):
        """Test suggested mounts include NVMe downloads suggestion."""
        import disk_manager

        inventory = {
            'disks': [
                {
                    'name': 'nvme0n1',
                    'transport': 'nvme',
                    'size': '500G',
                    'mounted': False,
                    'uuid': 'abc',
                    'fstype': 'ext4',
                    'partitions': [
                        {
                            'path': '/dev/nvme0n1p1',
                            'uuid': 'abc',
                            'fstype': 'ext4',
                            'size': '500G',
                            'mounted': False
                        }
                    ]
                }
            ]
        }

        with patch('disk_manager.get_disk_inventory', return_value=inventory):
            response = authenticated_client.get('/api/disks/suggested-mounts')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['suggestions'][0]['suggested_mount'] == '/mnt/downloads'


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

    def test_build_startup_script_no_mounts(self):
        """Test startup script when no /mnt mounts present."""
        import disk_manager
        script = disk_manager._build_startup_script({'config': '/home/pi/docker'})
        assert "MOUNT_POINTS=()" in script

    def test_seedbox_is_mounted_false(self):
        """Test seedbox mount detection false path."""
        import disk_manager
        with patch('disk_manager.os.path.ismount', return_value=False):
            assert disk_manager._seedbox_is_mounted() is False

    def test_process_device_filters_loop(self):
        """Test _process_device skips loop devices."""
        import disk_manager
        result = disk_manager._process_device(
            {'name': 'loop0', 'type': 'loop'},
            {}, {}, {}, {}, {}
        )
        assert result is None

    def test_process_device_usage_from_df(self):
        """Test _process_device includes usage when mounted."""
        import disk_manager
        device = {
            'name': 'sda1',
            'type': 'part',
            'size': '1G',
            'mountpoint': '/mnt/storage',
            'fstype': 'ext4',
            'children': []
        }
        mounts = {'/dev/sda1': {'mountpoint': '/mnt/storage', 'options': 'rw'}}
        df_map = {'/mnt/storage': {'size': '100', 'used': '50', 'avail': '50', 'pcent': '50%'}}
        result = disk_manager._process_device(device, {}, mounts, {}, {}, df_map)
        assert result['usage']['percent'] == '50'

    def test_get_disk_inventory_helper_unavailable(self):
        """Test get_disk_inventory returns helper_available False."""
        import disk_manager
        with patch('disk_manager.helper_available', return_value=False):
            result = disk_manager.get_disk_inventory()
        assert result['helper_available'] is False

    def test_update_startup_service_unavailable(self):
        """Test update_startup_service returns error if helper missing."""
        import disk_manager
        with patch('disk_manager.helper_available', return_value=False):
            result = disk_manager.update_startup_service({})
        assert result['success'] is False


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
