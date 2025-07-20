"""Unit tests for SMARTManager."""

import unittest
from unittest.mock import Mock, patch, call
from datetime import datetime
import sys
import os

# Add the parent directory to the path so we can import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nas.smart_manager import SMARTManager, SMARTTestType, SMARTTestStatus, SMARTHealthStatus, SMARTTestResult


class TestSMARTManager(unittest.TestCase):
    """Test cases for SMARTManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.smart_manager = SMARTManager()
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_get_health_status_success(self, mock_run_smartctl):
        """Test successful SMART health status retrieval."""
        # Mock smartctl outputs
        health_output = """
smartctl 7.2 2020-12-30 r5155 [x86_64-linux-5.4.0] (local build)
Copyright (C) 2002-20, Bruce Allen, Christian Franke, www.smartmontools.org

=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED
"""
        
        attributes_output = """
SMART Attributes Data Structure revision number: 16
Vendor Specific SMART Attributes with Thresholds:
ID# ATTRIBUTE_NAME          FLAGS    VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate     POSR-K   100   100   062    Old_age   Always       -       0
  5 Reallocated_Sector_Ct   PO--CK   100   100   005    Old_age   Always       -       0
  9 Power_On_Hours          -O--CK   100   100   000    Old_age   Always       -       1234
 12 Power_Cycle_Count       -O--CK   100   100   000    Old_age   Always       -       56
194 Temperature_Celsius     -O---K   035   035   000    Old_age   Always       -       35 (Min/Max 20/45)
196 Reallocated_Event_Count -O--CK   100   100   000    Old_age   Always       -       0
197 Current_Pending_Sector  -O--CK   100   100   000    Old_age   Always       -       0
198 Offline_Uncorrectable   ----CK   100   100   000    Old_age   Always       -       0
"""
        
        mock_run_smartctl.side_effect = [health_output, attributes_output]
        
        # Test the method
        result = self.smart_manager.get_health_status('/dev/sdb', use_cache=False)
        
        # Verify results
        self.assertIsNotNone(result)
        self.assertEqual(result.device_path, '/dev/sdb')
        self.assertEqual(result.overall_health, 'PASSED')
        self.assertEqual(result.temperature, 35)
        self.assertEqual(result.power_on_hours, 1234)
        self.assertEqual(result.power_cycle_count, 56)
        self.assertEqual(result.reallocated_sectors, 0)
        self.assertEqual(result.pending_sectors, 0)
        self.assertEqual(result.uncorrectable_sectors, 0)
        
        # Verify smartctl was called correctly
        expected_calls = [
            call(['-H', '/dev/sdb']),
            call(['-A', '/dev/sdb'])
        ]
        mock_run_smartctl.assert_has_calls(expected_calls)
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_get_health_status_failed_health(self, mock_run_smartctl):
        """Test SMART health status with failed health."""
        health_output = """
SMART overall-health self-assessment test result: FAILED!
Drive failure expected in less than 24 hours. SAVE ALL DATA.
"""
        
        mock_run_smartctl.side_effect = [health_output, None]
        
        result = self.smart_manager.get_health_status('/dev/sdb', use_cache=False)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.overall_health, 'FAILED')
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_get_health_status_cache_usage(self, mock_run_smartctl):
        """Test that cache is used when requested."""
        # First call - should hit smartctl twice (health + attributes)
        health_output = "SMART overall-health self-assessment test result: PASSED"
        mock_run_smartctl.return_value = health_output
        
        result1 = self.smart_manager.get_health_status('/dev/sdb', use_cache=False)
        self.assertIsNotNone(result1)
        
        # Second call with cache - should not hit smartctl again
        result2 = self.smart_manager.get_health_status('/dev/sdb', use_cache=True)
        self.assertIsNotNone(result2)
        self.assertEqual(result1.device_path, result2.device_path)
        
        # Should have been called twice for first call (health + attributes), none for second
        self.assertEqual(mock_run_smartctl.call_count, 2)
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_start_test_success(self, mock_run_smartctl):
        """Test successful SMART test start."""
        # Mock both get_test_status call (returns None) and start test call
        mock_run_smartctl.side_effect = [None, "Background short self-test started"]
        
        result = self.smart_manager.start_test('/dev/sdb', SMARTTestType.SHORT)
        
        self.assertTrue(result)
        
        # Should be called twice: once for get_test_status, once for start_test
        expected_calls = [
            call(['-l', 'selftest', '/dev/sdb']),  # get_test_status check
            call(['-t', 'short', '/dev/sdb'])      # actual test start
        ]
        mock_run_smartctl.assert_has_calls(expected_calls)
        
        # Check that test result is cached
        self.assertIn('/dev/sdb', self.smart_manager._test_cache)
        test_result = self.smart_manager._test_cache['/dev/sdb']
        self.assertEqual(test_result.test_type, SMARTTestType.SHORT)
        self.assertEqual(test_result.status, SMARTTestStatus.RUNNING)
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_start_test_already_running(self, mock_run_smartctl):
        """Test starting a test when one is already running."""
        # Set up existing running test
        existing_test = SMARTTestResult(
            device_path='/dev/sdb',
            test_type=SMARTTestType.SHORT,
            status=SMARTTestStatus.RUNNING
        )
        self.smart_manager._test_cache['/dev/sdb'] = existing_test
        
        # Mock get_test_status to return running test
        with patch.object(self.smart_manager, 'get_test_status', return_value=existing_test):
            result = self.smart_manager.start_test('/dev/sdb', SMARTTestType.LONG)
        
        self.assertFalse(result)
        mock_run_smartctl.assert_not_called()
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_get_test_status_running(self, mock_run_smartctl):
        """Test getting status of a running test."""
        test_output = """
SMART Self-test log structure revision number 1
Num  Test_Description    Status                  Remaining  LifeTime(hours)  LBA_of_first_error
# 1  Short offline       Self-test routine in progress 90% of test remaining.     -         -
"""
        
        mock_run_smartctl.return_value = test_output
        
        result = self.smart_manager.get_test_status('/dev/sdb')
        
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SMARTTestStatus.RUNNING)
        self.assertEqual(result.progress, 10)  # 100 - 90
        mock_run_smartctl.assert_called_once_with(['-l', 'selftest', '/dev/sdb'])
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_get_test_status_completed(self, mock_run_smartctl):
        """Test getting status of a completed test."""
        test_output = """
SMART Self-test log structure revision number 1
Num  Test_Description    Status                  Remaining  LifeTime(hours)  LBA_of_first_error
# 1  Short offline       Completed without error       00%      1234         -
"""
        
        mock_run_smartctl.return_value = test_output
        
        result = self.smart_manager.get_test_status('/dev/sdb')
        
        self.assertIsNotNone(result)
        self.assertEqual(result.status, SMARTTestStatus.COMPLETED)
        self.assertEqual(result.test_type, SMARTTestType.SHORT)
        self.assertEqual(result.progress, 100)
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_is_smart_available_true(self, mock_run_smartctl):
        """Test SMART availability check - positive case."""
        info_output = """
SMART support is: Available - device has SMART capability.
SMART support is: Enabled
"""
        
        mock_run_smartctl.return_value = info_output
        
        result = self.smart_manager.is_smart_available('/dev/sdb')
        
        self.assertTrue(result)
        mock_run_smartctl.assert_called_once_with(['-i', '/dev/sdb'])
    
    @patch('nas.smart_manager.SMARTManager._run_smartctl')
    def test_is_smart_available_false(self, mock_run_smartctl):
        """Test SMART availability check - negative case."""
        info_output = """
SMART support is: Unavailable - device lacks SMART capability.
"""
        
        mock_run_smartctl.return_value = info_output
        
        result = self.smart_manager.is_smart_available('/dev/sdb')
        
        self.assertFalse(result)
    
    @patch('subprocess.run')
    def test_run_smartctl_success(self, mock_subprocess):
        """Test successful smartctl command execution."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "SMART test output"
        mock_subprocess.return_value = mock_result
        
        result = self.smart_manager._run_smartctl(['-H', '/dev/sdb'])
        
        self.assertEqual(result, "SMART test output")
        mock_subprocess.assert_called_once_with(
            ['smartctl', '-H', '/dev/sdb'],
            capture_output=True,
            text=True,
            timeout=30
        )
    
    @patch('subprocess.run')
    def test_run_smartctl_acceptable_error_codes(self, mock_subprocess):
        """Test smartctl command with acceptable error codes."""
        mock_result = Mock()
        mock_result.returncode = 1  # Acceptable error code
        mock_result.stdout = "SMART output with warnings"
        mock_subprocess.return_value = mock_result
        
        result = self.smart_manager._run_smartctl(['-H', '/dev/sdb'])
        
        self.assertEqual(result, "SMART output with warnings")
    
    @patch('subprocess.run')
    def test_run_smartctl_failure(self, mock_subprocess):
        """Test smartctl command failure."""
        mock_result = Mock()
        mock_result.returncode = 8  # Unacceptable error code
        mock_result.stderr = "Device not found"
        mock_subprocess.return_value = mock_result
        
        result = self.smart_manager._run_smartctl(['-H', '/dev/sdb'])
        
        self.assertIsNone(result)
    
    @patch('subprocess.run')
    def test_run_smartctl_timeout(self, mock_subprocess):
        """Test smartctl command timeout."""
        import subprocess
        mock_subprocess.side_effect = subprocess.TimeoutExpired(['smartctl'], 30)
        
        result = self.smart_manager._run_smartctl(['-H', '/dev/sdb'])
        
        self.assertIsNone(result)
    
    @patch('subprocess.run')
    def test_run_smartctl_command_not_found(self, mock_subprocess):
        """Test smartctl command not found."""
        mock_subprocess.side_effect = FileNotFoundError()
        
        result = self.smart_manager._run_smartctl(['-H', '/dev/sdb'])
        
        self.assertIsNone(result)
    
    def test_parse_smart_attributes(self):
        """Test parsing of SMART attributes."""
        attributes_output = """
SMART Attributes Data Structure revision number: 16
Vendor Specific SMART Attributes with Thresholds:
ID# ATTRIBUTE_NAME          FLAGS    VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate     POSR-K   100   100   062    Old_age   Always       -       0
  5 Reallocated_Sector_Ct   PO--CK   100   100   005    Old_age   Always       -       0
  9 Power_On_Hours          -O--CK   099   099   000    Old_age   Always       -       1234
194 Temperature_Celsius     -O---K   035   035   000    Old_age   Always       -       35 (Min/Max 20/45)
"""
        
        attributes = self.smart_manager._parse_smart_attributes(attributes_output)
        
        self.assertEqual(len(attributes), 4)
        
        # Check first attribute
        attr1 = attributes[0]
        self.assertEqual(attr1.id, 1)
        self.assertEqual(attr1.name, 'Raw_Read_Error_Rate')
        self.assertEqual(attr1.value, 100)
        self.assertEqual(attr1.worst, 100)
        self.assertEqual(attr1.threshold, 62)
        self.assertEqual(attr1.raw_value, '0')
        
        # Check temperature attribute
        temp_attr = next(attr for attr in attributes if attr.id == 194)
        self.assertEqual(temp_attr.name, 'Temperature_Celsius')
        self.assertEqual(temp_attr.value, 35)
        self.assertEqual(temp_attr.raw_value, '35 (Min/Max 20/45)')


if __name__ == '__main__':
    # Import subprocess here to avoid issues with mocking
    import subprocess
    unittest.main()