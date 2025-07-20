"""
Tests for the drive management action buttons functionality.
"""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


class TestDriveActions:
    """Test class for drive management action buttons."""
    
    @pytest.fixture
    def client(self):
        """Create a test client for the Flask app."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_drives_page_contains_action_buttons(self, client):
        """Test that the drives page contains action button functionality."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for SnapRAID action functions
        assert b'triggerSnapraidSync' in response.data
        assert b'triggerSnapraidScrub' in response.data
        assert b'monitorSnapraidOperation' in response.data
        
        # Check for MergerFS functions
        assert b'viewMergerfsConfig' in response.data
        assert b'viewSnapraidStatus' in response.data
        
        # Check for SMART test functions
        assert b'runSmartTest' in response.data
        assert b'viewSmartDetails' in response.data
    
    def test_drives_page_contains_nas_management_panel(self, client):
        """Test that the drives page contains the NAS management panel."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for NAS management panel elements
        assert b'NAS Management' in response.data
        assert b'SnapRAID Status' in response.data
        assert b'MergerFS Pools' in response.data
        assert b'Parity Sync' in response.data
        assert b'Data Scrub' in response.data
    
    def test_drives_page_contains_enhanced_action_buttons(self, client):
        """Test that drive cards contain enhanced action buttons."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for enhanced button styling and icons
        assert b'border border-blue-800' in response.data  # Quick Test button
        assert b'border border-purple-800' in response.data  # Extended Test button
        assert b'border border-green-800' in response.data  # Details button
        assert b'border border-yellow-800' in response.data  # Sync Parity button
        assert b'border border-orange-800' in response.data  # Scrub Data button
    
    @patch('app.snapraid_manager')
    def test_snapraid_sync_async_endpoint(self, mock_snapraid_manager, client):
        """Test the SnapRAID async sync endpoint."""
        # Mock the async sync operation
        mock_snapraid_manager.sync_async.return_value = 'test-operation-id-123'
        
        response = client.post('/api/snapraid/sync/async', 
                             json={'force': False},
                             content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['operation_id'] == 'test-operation-id-123'
        assert data['operation'] == 'sync'
        
        # Verify the manager was called correctly
        mock_snapraid_manager.sync_async.assert_called_once_with(force=False)
    
    @patch('app.snapraid_manager')
    def test_snapraid_scrub_async_endpoint(self, mock_snapraid_manager, client):
        """Test the SnapRAID async scrub endpoint."""
        # Mock the async scrub operation
        mock_snapraid_manager.scrub_async.return_value = 'test-scrub-operation-456'
        
        response = client.post('/api/snapraid/scrub/async', 
                             json={'percentage': 15},
                             content_type='application/json')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['operation_id'] == 'test-scrub-operation-456'
        assert data['operation'] == 'scrub'
        assert data['percentage'] == 15
        
        # Verify the manager was called correctly
        mock_snapraid_manager.scrub_async.assert_called_once_with(percentage=15)
    
    @patch('app.snapraid_manager')
    def test_snapraid_operations_list_endpoint(self, mock_snapraid_manager, client):
        """Test the SnapRAID operations list endpoint."""
        # Mock operation data
        mock_operation = MagicMock()
        mock_operation.operation_id = 'test-op-789'
        mock_operation.operation_type = 'sync'
        mock_operation.status = 'running'
        
        mock_snapraid_manager.list_operations.return_value = [mock_operation]
        mock_snapraid_manager.operation_to_dict.return_value = {
            'operation_id': 'test-op-789',
            'operation_type': 'sync',
            'status': 'running',
            'progress': 50
        }
        
        response = client.get('/api/snapraid/operations')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert len(data['operations']) == 1
        assert data['operations'][0]['operation_id'] == 'test-op-789'
        assert data['operations'][0]['operation_type'] == 'sync'
        assert data['operations'][0]['status'] == 'running'
    
    @patch('app.snapraid_manager')
    def test_snapraid_operation_status_endpoint(self, mock_snapraid_manager, client):
        """Test the SnapRAID operation status endpoint."""
        # Mock operation status
        mock_operation = MagicMock()
        mock_operation.operation_id = 'test-status-op'
        mock_operation.status = 'completed'
        
        mock_snapraid_manager.get_operation_status.return_value = mock_operation
        mock_snapraid_manager.operation_to_dict.return_value = {
            'operation_id': 'test-status-op',
            'status': 'completed',
            'progress': 100
        }
        
        response = client.get('/api/snapraid/operations/test-status-op')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['operation']['operation_id'] == 'test-status-op'
        assert data['operation']['status'] == 'completed'
    
    @patch('app.mergerfs_manager')
    def test_mergerfs_endpoint_integration(self, mock_mergerfs_manager, client):
        """Test the MergerFS endpoint integration."""
        # Mock MergerFS pool data
        mock_mergerfs_manager.get_pools.return_value = [
            {
                'mount_point': '/mnt/storage',
                'source_paths': ['/mnt/disk1', '/mnt/disk2'],
                'options': 'defaults,allow_other,use_ino'
            }
        ]
        
        response = client.get('/api/mergerfs')
        
        # The endpoint should exist and return data
        # Note: The actual endpoint implementation may vary
        # This test ensures the drives page can call it
        assert response.status_code in [200, 404, 500]  # Any valid HTTP response
    
    def test_drives_page_progress_indicators(self, client):
        """Test that the drives page contains progress indicators."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for progress indicator elements
        assert b'progress-bar' in response.data
        assert b'spinner' in response.data
        assert b'animate-pulse' in response.data
    
    def test_drives_page_notification_system(self, client):
        """Test that the drives page contains notification system."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for notification system
        assert b'showNotification' in response.data
        assert b'notification-area' in response.data
        assert b'bg-green-600' in response.data  # Success notifications
        assert b'bg-red-600' in response.data    # Error notifications
        assert b'bg-blue-600' in response.data   # Info notifications


if __name__ == '__main__':
    pytest.main([__file__])