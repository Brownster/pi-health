"""
Tests for the drives management UI functionality.
"""
import pytest
import requests
from unittest.mock import patch, MagicMock
import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


class TestDrivesUI:
    """Test class for drives management UI."""
    
    @pytest.fixture
    def client(self):
        """Create a test client for the Flask app."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_drives_page_route(self, client):
        """Test that the drives page route exists and returns HTML."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        assert b'<!DOCTYPE html>' in response.data
        assert b'Drives Management' in response.data
    
    def test_drives_page_contains_navigation(self, client):
        """Test that the drives page contains proper navigation."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for navigation links
        assert b'href="/"' in response.data
        assert b'href="/system.html"' in response.data
        assert b'href="/containers.html"' in response.data
        assert b'href="/drives.html"' in response.data
        assert b'href="/edit.html"' in response.data
    
    def test_drives_page_contains_required_elements(self, client):
        """Test that the drives page contains required UI elements."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for key UI elements
        assert b'drives-grid' in response.data  # Main drives grid container
        assert b'refresh-btn' in response.data  # Refresh button
        assert b'last-updated' in response.data  # Last updated timestamp
        assert b'notification-area' in response.data  # Notification area
    
    def test_drives_page_javascript_functions(self, client):
        """Test that the drives page contains required JavaScript functions."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for key JavaScript functions
        assert b'fetchDriveData' in response.data
        assert b'createDriveCard' in response.data
        assert b'runSmartTest' in response.data
        assert b'viewSmartDetails' in response.data
        assert b'showNotification' in response.data
    
    def test_drives_page_styling(self, client):
        """Test that the drives page contains proper styling."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for Coraline theme styling
        assert b'coraline-button' in response.data
        assert b'drive-card' in response.data
        assert b'health-healthy' in response.data
        assert b'status-badge' in response.data
    
    @patch('app.drive_manager')
    def test_api_disks_endpoint_integration(self, mock_drive_manager, client):
        """Test that the /api/disks endpoint works with the drives page."""
        # Mock drive data
        mock_drive = MagicMock()
        mock_drive.device_path = '/dev/sdb1'
        mock_drive.uuid = 'test-uuid-123'
        mock_drive.mount_point = '/mnt/disk1'
        mock_drive.filesystem = 'ext4'
        mock_drive.role.value = 'data'
        mock_drive.size_bytes = 1000000000000  # 1TB
        mock_drive.used_bytes = 500000000000   # 500GB
        mock_drive.free_bytes = 500000000000   # 500GB
        mock_drive.usage_percent = 50.0
        mock_drive.health_status.value = 'healthy'
        mock_drive.label = 'Test Drive'
        
        mock_drive_manager.discover_drives.return_value = [mock_drive]
        mock_drive_manager.is_usb_drive.return_value = True
        mock_drive_manager.get_smart_health.return_value = {
            'overall_health': 'PASSED',
            'temperature': 35,
            'power_on_hours': 1000,
            'power_cycle_count': 50
        }
        
        # Test the API endpoint
        response = client.get('/api/disks')
        assert response.status_code == 200
        
        data = response.get_json()
        assert data['status'] == 'success'
        assert len(data['drives']) == 1
        assert data['drives'][0]['device_path'] == '/dev/sdb1'
        assert data['drives'][0]['role'] == 'data'
        assert data['drives'][0]['usage_percent'] == 50.0


if __name__ == '__main__':
    pytest.main([__file__])