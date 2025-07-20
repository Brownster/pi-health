"""
Tests for the real-time dashboard updates functionality.
"""
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


class TestRealtimeUpdates:
    """Test class for real-time dashboard updates."""
    
    @pytest.fixture
    def client(self):
        """Create a test client for the Flask app."""
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client
    
    def test_drives_page_contains_realtime_functions(self, client):
        """Test that the drives page contains real-time update functions."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for real-time update functions
        assert b'startRealTimeUpdates' in response.data
        assert b'enableFastUpdates' in response.data
        assert b'enableNormalUpdates' in response.data
        assert b'checkActiveOperations' in response.data
        assert b'updateOperationStatus' in response.data
        assert b'monitorConnectionStatus' in response.data
    
    def test_drives_page_contains_change_detection(self, client):
        """Test that the drives page contains change detection functionality."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for change detection functions
        assert b'fetchDriveDataWithChangeDetection' in response.data
        assert b'detectDriveChanges' in response.data
        assert b'showOperationNotification' in response.data
    
    def test_drives_page_contains_update_intervals(self, client):
        """Test that the drives page contains update interval configuration."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for update interval variables
        assert b'updateInterval' in response.data
        assert b'fastUpdateInterval' in response.data
        assert b'currentUpdateInterval' in response.data
        assert b'updateTimer' in response.data
        assert b'activeOperations' in response.data
    
    def test_drives_page_contains_connection_monitoring(self, client):
        """Test that the drives page contains connection status monitoring."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for connection monitoring elements
        assert b'updateConnectionStatus' in response.data
        assert b'connection-status' in response.data
        assert b'Connected' in response.data
        assert b'Disconnected' in response.data
    
    def test_drives_page_contains_operation_status_display(self, client):
        """Test that the drives page contains operation status display."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for operation status display elements
        assert b'operation-status-display' in response.data
        assert b'Active Operations' in response.data
        assert b'removeOperationStatusDisplay' in response.data
    
    def test_drives_page_contains_visibility_handling(self, client):
        """Test that the drives page contains page visibility change handling."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for visibility change handling
        assert b'visibilitychange' in response.data
        assert b'document.hidden' in response.data
    
    def test_drives_page_contains_animation_features(self, client):
        """Test that the drives page contains animation features for updates."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for animation-related code
        assert b'translateY(20px)' in response.data  # Card animation
        assert b'opacity: 0' in response.data  # Fade-in animation
        assert b'transition:' in response.data  # CSS transitions
        assert b'setTimeout' in response.data  # Staggered animations
    
    def test_drives_page_contains_notification_enhancements(self, client):
        """Test that the drives page contains enhanced notification system."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for enhanced notification features
        assert b'persistent' in response.data  # Persistent notifications
        assert b'New drive detected' in response.data  # Drive change notifications
        assert b'Drive removed' in response.data  # Drive removal notifications
        assert b'health changed' in response.data  # Health change notifications
    
    @patch('app.snapraid_manager')
    def test_snapraid_operations_active_only_endpoint(self, mock_snapraid_manager, client):
        """Test the SnapRAID operations endpoint with active_only filter."""
        # Mock active operation data
        mock_operation = MagicMock()
        mock_operation.operation_id = 'active-op-123'
        mock_operation.operation_type = 'sync'
        mock_operation.status = 'running'
        mock_operation.progress = 75
        
        mock_snapraid_manager.list_operations.return_value = [mock_operation]
        mock_snapraid_manager.operation_to_dict.return_value = {
            'operation_id': 'active-op-123',
            'operation_type': 'sync',
            'status': 'running',
            'progress': 75
        }
        
        response = client.get('/api/snapraid/operations?active_only=true')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'success'
        assert data['active_only'] == True
        assert len(data['operations']) == 1
        assert data['operations'][0]['status'] == 'running'
        
        # Verify the manager was called with active_only=True
        mock_snapraid_manager.list_operations.assert_called_once_with(active_only=True)
    
    def test_drives_page_update_mode_switching(self, client):
        """Test that the drives page contains update mode switching logic."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for update mode switching
        assert b'30000' in response.data  # Normal update interval (30 seconds)
        assert b'5000' in response.data   # Fast update interval (5 seconds)
        assert b'fast update mode' in response.data
        assert b'normal update mode' in response.data
    
    def test_drives_page_progress_tracking(self, client):
        """Test that the drives page contains progress tracking for operations."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for progress tracking elements
        assert b'progressPercent' in response.data
        assert b'bg-purple-500' in response.data  # Progress bar color
        assert b'ETA:' in response.data  # Estimated completion time
        assert b'Status:' in response.data  # Operation status
    
    def test_drives_page_error_handling(self, client):
        """Test that the drives page contains proper error handling for real-time updates."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for error handling in real-time functions
        assert b'catch (error)' in response.data
        assert b'console.error' in response.data
        assert b'Error checking active operations' in response.data
        assert b'Error monitoring operation' in response.data
    
    def test_drives_page_cleanup_functions(self, client):
        """Test that the drives page contains cleanup functions for real-time features."""
        response = client.get('/drives.html')
        assert response.status_code == 200
        
        # Check for cleanup functions
        assert b'clearInterval' in response.data
        assert b'activeOperations.delete' in response.data
        assert b'removeOperationStatusDisplay' in response.data
        assert b'notification.remove()' in response.data


if __name__ == '__main__':
    pytest.main([__file__])