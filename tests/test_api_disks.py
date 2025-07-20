"""Integration tests for the /api/disks endpoint."""

import unittest
from unittest.mock import Mock, patch
import json
import sys
import os

# Add the parent directory to the path so we can import the app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestDisksAPI(unittest.TestCase):
    """Test cases for the /api/disks endpoint."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.app = app.test_client()
        self.app.testing = True
    
    @patch('app.drive_manager.discover_drives')
    def test_api_disks_success(self, mock_discover):
        """Test successful drive discovery API call."""
        # Mock drive data
        mock_drives = [
            DriveConfig(
                device_path='/dev/sdb1',
                uuid='12345678-1234-1234-1234-123456789abc',
                mount_point='/mnt/disk1',
                filesystem='ext4',
                role=DriveRole.DATA,
                size_bytes=1000000000000,  # 1TB
                used_bytes=500000000000,   # 500GB
                health_status=HealthStatus.HEALTHY,
                label='Data Drive 1'
            ),
            DriveConfig(
                device_path='/dev/sdc1',
                uuid='87654321-4321-4321-4321-cba987654321',
                mount_point='/mnt/parity1',
                filesystem='ext4',
                role=DriveRole.PARITY,
                size_bytes=2000000000000,  # 2TB
                used_bytes=750000000000,   # 750GB
                health_status=HealthStatus.HEALTHY,
                label='Parity Drive 1'
            )
        ]
        mock_discover.return_value = mock_drives
        
        # Mock SMART health data
        mock_smart_health = {
            'overall_health': 'PASSED',
            'temperature': 35,
            'power_on_hours': 1234,
            'power_cycle_count': 56,
            'reallocated_sectors': 0,
            'pending_sectors': 0,
            'uncorrectable_sectors': 0,
            'last_updated': '2023-01-01T12:00:00'
        }
        
        # Mock is_usb_drive and get_smart_health methods
        with patch('app.drive_manager.is_usb_drive') as mock_is_usb, \
             patch('app.drive_manager.get_smart_health') as mock_smart:
            mock_is_usb.return_value = True
            mock_smart.return_value = mock_smart_health
            
            # Make API call
            response = self.app.get('/api/disks')
            
            # Verify response
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            self.assertEqual(data['status'], 'success')
            self.assertEqual(data['total_drives'], 2)
            self.assertEqual(len(data['drives']), 2)
            
            # Verify first drive data
            drive1 = data['drives'][0]
            self.assertEqual(drive1['device_path'], '/dev/sdb1')
            self.assertEqual(drive1['uuid'], '12345678-1234-1234-1234-123456789abc')
            self.assertEqual(drive1['mount_point'], '/mnt/disk1')
            self.assertEqual(drive1['filesystem'], 'ext4')
            self.assertEqual(drive1['role'], 'data')
            self.assertEqual(drive1['size_bytes'], 1000000000000)
            self.assertEqual(drive1['used_bytes'], 500000000000)
            self.assertEqual(drive1['free_bytes'], 500000000000)
            self.assertEqual(drive1['usage_percent'], 50.0)
            self.assertEqual(drive1['health_status'], 'healthy')
            self.assertEqual(drive1['label'], 'Data Drive 1')
            self.assertTrue(drive1['is_usb'])
            
            # Verify SMART health data is included
            self.assertIsNotNone(drive1['smart_health'])
            self.assertEqual(drive1['smart_health']['overall_health'], 'PASSED')
            self.assertEqual(drive1['smart_health']['temperature'], 35)
            
            # Verify second drive data
            drive2 = data['drives'][1]
            self.assertEqual(drive2['device_path'], '/dev/sdc1')
            self.assertEqual(drive2['role'], 'parity')
            self.assertEqual(drive2['size_bytes'], 2000000000000)
            self.assertEqual(drive2['used_bytes'], 750000000000)
            self.assertEqual(drive2['free_bytes'], 1250000000000)
            self.assertEqual(drive2['usage_percent'], 37.5)
            self.assertIsNotNone(drive2['smart_health'])
    
    @patch('app.drive_manager.discover_drives')
    def test_api_disks_empty_result(self, mock_discover):
        """Test API call when no drives are found."""
        mock_discover.return_value = []
        
        response = self.app.get('/api/disks')
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['total_drives'], 0)
        self.assertEqual(len(data['drives']), 0)
    
    @patch('app.drive_manager.discover_drives')
    def test_api_disks_error_handling(self, mock_discover):
        """Test API error handling when drive discovery fails."""
        mock_discover.side_effect = Exception("Drive discovery failed")
        
        response = self.app.get('/api/disks')
        
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Failed to discover drives', data['message'])
        self.assertEqual(data['total_drives'], 0)
        self.assertEqual(len(data['drives']), 0)
    
    @patch('app.drive_manager.discover_drives')
    def test_api_disks_drive_with_no_label(self, mock_discover):
        """Test API call with drive that has no label."""
        mock_drives = [
            DriveConfig(
                device_path='/dev/sdb1',
                uuid='test-uuid',
                mount_point='/mnt/disk1',
                filesystem='ext4',
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.HEALTHY,
                label=None  # No label
            )
        ]
        mock_discover.return_value = mock_drives
        
        with patch('app.drive_manager.is_usb_drive', return_value=False):
            response = self.app.get('/api/disks')
            
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            drive = data['drives'][0]
            self.assertIsNone(drive['label'])
            self.assertFalse(drive['is_usb'])
    
    @patch('app.drive_manager.discover_drives')
    def test_api_disks_various_health_statuses(self, mock_discover):
        """Test API call with drives having different health statuses."""
        mock_drives = [
            DriveConfig(
                device_path='/dev/sdb1',
                uuid='uuid1',
                mount_point='/mnt/disk1',
                filesystem='ext4',
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.HEALTHY
            ),
            DriveConfig(
                device_path='/dev/sdc1',
                uuid='uuid2',
                mount_point='/mnt/disk2',
                filesystem='ext4',
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.DEGRADED
            ),
            DriveConfig(
                device_path='/dev/sdd1',
                uuid='uuid3',
                mount_point='/mnt/disk3',
                filesystem='ext4',
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.FAILED
            )
        ]
        mock_discover.return_value = mock_drives
        
        with patch('app.drive_manager.is_usb_drive', return_value=True):
            response = self.app.get('/api/disks')
            
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            self.assertEqual(len(data['drives']), 3)
            
            # Check health statuses
            health_statuses = [drive['health_status'] for drive in data['drives']]
            self.assertIn('healthy', health_statuses)
            self.assertIn('degraded', health_statuses)
            self.assertIn('failed', health_statuses)
    
    def test_api_disks_method_not_allowed(self):
        """Test that only GET method is allowed."""
        response = self.app.post('/api/disks')
        self.assertEqual(response.status_code, 405)
        
        response = self.app.put('/api/disks')
        self.assertEqual(response.status_code, 405)
        
        response = self.app.delete('/api/disks')
        self.assertEqual(response.status_code, 405)
    
    @patch('app.drive_manager.get_smart_health')
    def test_api_smart_health_success(self, mock_smart_health):
        """Test successful SMART health API call."""
        mock_health_data = {
            'overall_health': 'PASSED',
            'temperature': 42,
            'power_on_hours': 5678,
            'power_cycle_count': 123,
            'reallocated_sectors': 0,
            'pending_sectors': 0,
            'uncorrectable_sectors': 0,
            'last_updated': '2023-01-01T15:30:00'
        }
        mock_smart_health.return_value = mock_health_data
        
        response = self.app.get('/api/smart/dev/sdb1/health')
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertEqual(data['health']['overall_health'], 'PASSED')
        self.assertEqual(data['health']['temperature'], 42)
        
        mock_smart_health.assert_called_once_with('/dev/sdb1', use_cache=False)
    
    @patch('app.drive_manager.get_smart_health')
    def test_api_smart_health_not_available(self, mock_smart_health):
        """Test SMART health API when SMART is not available."""
        mock_smart_health.return_value = None
        
        response = self.app.get('/api/smart/dev/sdb1/health')
        
        self.assertEqual(response.status_code, 404)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('SMART not available', data['message'])
        self.assertIsNone(data['health'])
    
    @patch('app.drive_manager.get_smart_health')
    def test_api_smart_health_error(self, mock_smart_health):
        """Test SMART health API error handling."""
        mock_smart_health.side_effect = Exception("SMART error")
        
        response = self.app.get('/api/smart/dev/sdb1/health')
        
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Failed to get SMART health', data['message'])
    
    @patch('app.drive_manager.start_smart_test')
    def test_api_smart_test_start_success(self, mock_start_test):
        """Test successful SMART test start."""
        mock_start_test.return_value = True
        
        response = self.app.post('/api/smart/dev/sdb1/short')
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertEqual(data['test_type'], 'short')
        self.assertIn('Started short SMART test', data['message'])
        
        mock_start_test.assert_called_once_with('/dev/sdb1', 'short')
    
    @patch('app.drive_manager.start_smart_test')
    def test_api_smart_test_start_failure(self, mock_start_test):
        """Test SMART test start failure."""
        mock_start_test.return_value = False
        
        response = self.app.post('/api/smart/dev/sdb1/short')
        
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Failed to start SMART test', data['message'])
    
    def test_api_smart_test_invalid_type(self):
        """Test SMART test with invalid test type."""
        response = self.app.post('/api/smart/dev/sdb1/invalid')
        
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Invalid test type', data['message'])
    
    @patch('app.drive_manager.start_smart_test')
    def test_api_smart_test_error(self, mock_start_test):
        """Test SMART test API error handling."""
        mock_start_test.side_effect = Exception("Test start error")
        
        response = self.app.post('/api/smart/dev/sdb1/short')
        
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Failed to start SMART test', data['message'])
    
    @patch('app.drive_manager.get_smart_test_status')
    def test_api_smart_test_status_success(self, mock_test_status):
        """Test successful SMART test status retrieval."""
        mock_status_data = {
            'test_type': 'short',
            'status': 'running',
            'progress': 75,
            'estimated_completion': '2023-01-01T16:00:00',
            'result_message': None,
            'started_at': '2023-01-01T15:45:00',
            'completed_at': None
        }
        mock_test_status.return_value = mock_status_data
        
        response = self.app.get('/api/smart/dev/sdb1/test-status')
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertEqual(data['test_status']['test_type'], 'short')
        self.assertEqual(data['test_status']['status'], 'running')
        self.assertEqual(data['test_status']['progress'], 75)
        
        mock_test_status.assert_called_once_with('/dev/sdb1')
    
    @patch('app.drive_manager.get_smart_test_status')
    def test_api_smart_test_status_no_test(self, mock_test_status):
        """Test SMART test status when no test information is available."""
        mock_test_status.return_value = None
        
        response = self.app.get('/api/smart/dev/sdb1/test-status')
        
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertIsNone(data['test_status'])
        self.assertIn('No test information available', data['message'])
    
    @patch('app.drive_manager.get_smart_test_status')
    def test_api_smart_test_status_error(self, mock_test_status):
        """Test SMART test status API error handling."""
        mock_test_status.side_effect = Exception("Status error")
        
        response = self.app.get('/api/smart/dev/sdb1/test-status')
        
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Failed to get SMART test status', data['message'])
    
    @patch('app.drive_manager.get_smart_health_history')
    def test_api_smart_health_history_success(self, mock_health_history):
        """Test successful SMART health history API call."""
        mock_history_data = [
            {
                'device_path': '/dev/sdb',
                'timestamp': '2024-01-01T12:00:00',
                'overall_health': 'PASSED',
                'temperature': 45,
                'power_on_hours': 1000,
                'reallocated_sectors': 0,
                'pending_sectors': 0
            },
            {
                'device_path': '/dev/sdb',
                'timestamp': '2024-01-02T12:00:00',
                'overall_health': 'PASSED',
                'temperature': 47,
                'power_on_hours': 1024,
                'reallocated_sectors': 0,
                'pending_sectors': 0
            }
        ]
        mock_health_history.return_value = mock_history_data
        
        response = self.app.get('/api/smart/dev/sdb1/history')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertEqual(data['days'], 7)  # Default
        self.assertEqual(len(data['history']), 2)
        self.assertEqual(data['history_count'], 2)
    
    @patch('app.drive_manager.get_smart_health_history')
    def test_api_smart_health_history_with_days_parameter(self, mock_health_history):
        """Test SMART health history API with days parameter."""
        mock_health_history.return_value = []
        
        response = self.app.get('/api/smart/dev/sdb1/history?days=14')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['days'], 14)
        
        # Verify the mock was called with correct parameters
        mock_health_history.assert_called_once_with('/dev/sdb1', 14)
    
    def test_api_smart_health_history_invalid_days(self):
        """Test SMART health history API with invalid days parameter."""
        # Test days too high
        response = self.app.get('/api/smart/dev/sdb1/history?days=50')
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('between 1 and 30', data['message'])
        
        # Test days too low
        response = self.app.get('/api/smart/dev/sdb1/history?days=0')
        self.assertEqual(response.status_code, 400)
        
        # Test non-numeric days
        response = self.app.get('/api/smart/dev/sdb1/history?days=invalid')
        self.assertEqual(response.status_code, 400)
    
    @patch('app.drive_manager.get_smart_health_history')
    def test_api_smart_health_history_error(self, mock_health_history):
        """Test SMART health history API error handling."""
        mock_health_history.side_effect = Exception("History error")
        
        response = self.app.get('/api/smart/dev/sdb1/history')
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('History error', data['message'])
    
    @patch('app.drive_manager.get_smart_trend_analysis')
    def test_api_smart_trend_analysis_success(self, mock_trend_analysis):
        """Test successful SMART trend analysis API call."""
        mock_analysis_data = {
            'device_path': '/dev/sdb',
            'analysis_period_days': 7,
            'temperature_trend': 'increasing',
            'temperature_avg': 45.5,
            'temperature_max': 50,
            'reallocated_sectors_trend': 'stable',
            'pending_sectors_trend': 'stable',
            'health_degradation_risk': 'medium',
            'recommendations': ['Monitor drive temperature - consider improving cooling']
        }
        mock_trend_analysis.return_value = mock_analysis_data
        
        response = self.app.get('/api/smart/dev/sdb1/trends')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['device_path'], '/dev/sdb1')
        self.assertEqual(data['analysis']['temperature_trend'], 'increasing')
        self.assertEqual(data['analysis']['health_degradation_risk'], 'medium')
    
    @patch('app.drive_manager.get_smart_trend_analysis')
    def test_api_smart_trend_analysis_insufficient_data(self, mock_trend_analysis):
        """Test SMART trend analysis API with insufficient data."""
        mock_trend_analysis.return_value = None
        
        response = self.app.get('/api/smart/dev/sdb1/trends')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')
        self.assertIn('Insufficient data', data['message'])
        self.assertIsNone(data['analysis'])
    
    def test_api_smart_trend_analysis_invalid_days(self):
        """Test SMART trend analysis API with invalid days parameter."""
        # Test days too low (need at least 2 for trends)
        response = self.app.get('/api/smart/dev/sdb1/trends?days=1')
        self.assertEqual(response.status_code, 400)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('between 2 and 30', data['message'])
    
    @patch('app.drive_manager.get_smart_trend_analysis')
    def test_api_smart_trend_analysis_error(self, mock_trend_analysis):
        """Test SMART trend analysis API error handling."""
        mock_trend_analysis.side_effect = Exception("Trend analysis error")
        
        response = self.app.get('/api/smart/dev/sdb1/trends')
        self.assertEqual(response.status_code, 500)
        
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'error')
        self.assertIn('Trend analysis error', data['message'])


if __name__ == '__main__':
    unittest.main()