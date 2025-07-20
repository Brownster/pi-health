"""Unit tests for SnapRAID manager."""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json

from nas.snapraid_manager import (
    SnapRAIDManager, SnapRAIDStatus, ParityStatus, DriveStatus, 
    ParityInfo, SnapRAIDStatusInfo
)
from nas.config_manager import ConfigManager, NASConfig


class TestSnapRAIDManager(unittest.TestCase):
    """Test cases for SnapRAID manager."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_config_manager = Mock(spec=ConfigManager)
        self.mock_config = NASConfig(
            snapraid_config_path="/etc/snapraid.conf"
        )
        self.mock_config_manager.load_config.return_value = self.mock_config
        
        self.snapraid_manager = SnapRAIDManager(
            config_manager=self.mock_config_manager,
            dry_run=True
        )
    
    def test_init(self):
        """Test SnapRAID manager initialization."""
        self.assertIsNotNone(self.snapraid_manager.config_manager)
        self.assertIsNotNone(self.snapraid_manager.executor)
        self.assertIsNone(self.snapraid_manager._status_cache)
        self.assertIsNone(self.snapraid_manager._cache_timestamp)
    
    @patch('nas.snapraid_manager.datetime')
    def test_get_status_success(self, mock_datetime):
        """Test successful status retrieval."""
        # Mock datetime.now()
        mock_now = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        
        # Mock executor response
        mock_status_output = """SnapRAID 12.0
Loading state from /var/snapraid/snapraid.content...
Comparing...

Self test...
Loading state from /var/snapraid/snapraid.content...
Comparing...

SUMMARY
       Files        Size     Used    Free  Use Name
        1234    500.0 GB  400.0 GB  100.0 GB   80% d1
        5678    750.0 GB  600.0 GB  150.0 GB   80% d2
           0   1000.0 GB    0.0 GB 1000.0 GB    0% parity

The parity is up-to-date.
You have a 95% of coverage.
Total files: 6912
Total size: 1250.0 GB
"""
        
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, mock_status_output, "")
        )
        
        # Test status retrieval
        status = self.snapraid_manager.get_status()
        
        # Verify status object
        self.assertIsNotNone(status)
        self.assertEqual(status.overall_status, SnapRAIDStatus.HEALTHY)
        self.assertEqual(status.parity_info.status, ParityStatus.UP_TO_DATE)
        self.assertEqual(status.parity_info.coverage_percent, 95.0)
        self.assertEqual(len(status.data_drives), 2)
        self.assertEqual(len(status.parity_drives), 1)
        self.assertEqual(status.total_files, 6912)
        self.assertEqual(status.total_size_gb, 1250.0)
        self.assertEqual(status.version, "12.0")
        
        # Verify data drives
        d1 = status.data_drives[0]
        self.assertEqual(d1.name, "d1")
        self.assertEqual(d1.size_gb, 500.0)
        self.assertEqual(d1.used_gb, 400.0)
        self.assertEqual(d1.files, 1234)
        
        d2 = status.data_drives[1]
        self.assertEqual(d2.name, "d2")
        self.assertEqual(d2.size_gb, 750.0)
        self.assertEqual(d2.used_gb, 600.0)
        self.assertEqual(d2.files, 5678)
        
        # Verify parity drive
        parity = status.parity_drives[0]
        self.assertEqual(parity.name, "parity")
        self.assertEqual(parity.size_gb, 1000.0)
        self.assertEqual(parity.used_gb, 0.0)
        self.assertEqual(parity.files, 0)
    
    def test_get_status_command_failure(self):
        """Test status retrieval when command fails."""
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(False, "", "SnapRAID command failed")
        )
        
        status = self.snapraid_manager.get_status()
        self.assertIsNone(status)
    
    @patch('nas.snapraid_manager.datetime')
    def test_get_status_cache(self, mock_datetime):
        """Test status caching functionality."""
        # Mock datetime.now()
        mock_now = datetime(2023, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        
        # Create a cached status
        cached_status = SnapRAIDStatusInfo(
            overall_status=SnapRAIDStatus.HEALTHY,
            parity_info=ParityInfo(
                status=ParityStatus.UP_TO_DATE,
                coverage_percent=100.0,
                last_sync=None,
                sync_duration=None
            ),
            data_drives=[],
            parity_drives=[],
            total_files=0,
            total_size_gb=0.0,
            last_check=mock_now,
            config_path="/etc/snapraid.conf"
        )
        
        self.snapraid_manager._status_cache = cached_status
        self.snapraid_manager._cache_timestamp = mock_now
        
        # Mock executor to ensure it's not called
        self.snapraid_manager.executor.execute_snapraid_command = Mock()
        
        # Test cache hit
        status = self.snapraid_manager.get_status(use_cache=True)
        self.assertEqual(status, cached_status)
        self.snapraid_manager.executor.execute_snapraid_command.assert_not_called()
        
        # Test cache miss (expired)
        mock_datetime.now.return_value = mock_now + timedelta(minutes=10)
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, "SnapRAID 12.0\nThe parity is up-to-date.", "")
        )
        
        status = self.snapraid_manager.get_status(use_cache=True)
        self.snapraid_manager.executor.execute_snapraid_command.assert_called_once()
    
    def test_sync_success(self):
        """Test successful sync operation."""
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, "Sync completed successfully", "")
        )
        
        success, message = self.snapraid_manager.sync()
        
        self.assertTrue(success)
        self.assertIn("completed successfully", message)
        self.snapraid_manager.executor.execute_snapraid_command.assert_called_once_with(
            'sync', config_path="/etc/snapraid.conf", additional_args=[]
        )
    
    def test_sync_with_force(self):
        """Test sync operation with force flag."""
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, "Sync completed successfully", "")
        )
        
        success, message = self.snapraid_manager.sync(force=True)
        
        self.assertTrue(success)
        self.snapraid_manager.executor.execute_snapraid_command.assert_called_once_with(
            'sync', config_path="/etc/snapraid.conf", additional_args=['-f']
        )
    
    def test_sync_failure(self):
        """Test sync operation failure."""
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(False, "", "Sync failed: disk error")
        )
        
        success, message = self.snapraid_manager.sync()
        
        self.assertFalse(success)
        self.assertIn("failed", message)
        self.assertIn("disk error", message)
    
    def test_scrub_success(self):
        """Test successful scrub operation."""
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, "Scrub completed successfully", "")
        )
        
        success, message = self.snapraid_manager.scrub(percentage=15)
        
        self.assertTrue(success)
        self.assertIn("completed successfully", message)
        self.snapraid_manager.executor.execute_snapraid_command.assert_called_once_with(
            'scrub', config_path="/etc/snapraid.conf", additional_args=['-p', '15']
        )
    
    def test_scrub_invalid_percentage(self):
        """Test scrub with invalid percentage."""
        with self.assertRaises(ValueError):
            self.snapraid_manager.scrub(percentage=0)
        
        with self.assertRaises(ValueError):
            self.snapraid_manager.scrub(percentage=101)
    
    def test_diff_success(self):
        """Test successful diff operation."""
        mock_diff_output = """add file1.txt
remove file2.txt
update file3.txt
move file4.txt -> file5.txt
"""
        
        self.snapraid_manager.executor.execute_snapraid_command = Mock(
            return_value=(True, mock_diff_output, "")
        )
        
        success, message, changes = self.snapraid_manager.diff()
        
        self.assertTrue(success)
        self.assertEqual(len(changes), 4)
        self.assertIn("add file1.txt", changes)
        self.assertIn("remove file2.txt", changes)
        self.assertIn("update file3.txt", changes)
        self.assertIn("move file4.txt -> file5.txt", changes)
    
    def test_check_config_success(self):
        """Test successful config check."""
        with patch('pathlib.Path.exists', return_value=True):
            self.snapraid_manager.executor.execute_snapraid_command = Mock(
                return_value=(True, "Config is valid", "")
            )
            
            success, message = self.snapraid_manager.check_config()
            
            self.assertTrue(success)
            self.assertIn("valid", message)
    
    def test_check_config_file_not_found(self):
        """Test config check when file doesn't exist."""
        with patch('pathlib.Path.exists', return_value=False):
            success, message = self.snapraid_manager.check_config()
            
            self.assertFalse(success)
            self.assertIn("not found", message)
    
    def test_parse_status_output_degraded(self):
        """Test parsing status output for degraded state."""
        mock_status_output = """SnapRAID 12.0
The parity is out-of-sync.
You have a 85% of coverage.
Total files: 1000
Total size: 500.0 GB
"""
        
        status = self.snapraid_manager._parse_status_output(
            mock_status_output, "/etc/snapraid.conf"
        )
        
        self.assertEqual(status.overall_status, SnapRAIDStatus.DEGRADED)
        self.assertEqual(status.parity_info.status, ParityStatus.OUT_OF_SYNC)
        self.assertEqual(status.parity_info.coverage_percent, 85.0)
    
    def test_parse_diff_output(self):
        """Test parsing diff output."""
        mock_diff_output = """Comparing...
add /path/to/new/file.txt
remove /path/to/old/file.txt
update /path/to/changed/file.txt
Some other line without change indicators
copy /path/to/source.txt -> /path/to/dest.txt
"""
        
        changes = self.snapraid_manager._parse_diff_output(mock_diff_output)
        
        self.assertEqual(len(changes), 4)
        self.assertIn("add /path/to/new/file.txt", changes)
        self.assertIn("remove /path/to/old/file.txt", changes)
        self.assertIn("update /path/to/changed/file.txt", changes)
        self.assertIn("copy /path/to/source.txt -> /path/to/dest.txt", changes)
    
    def test_to_dict_conversion(self):
        """Test conversion of status info to dictionary."""
        # Create test status info
        status_info = SnapRAIDStatusInfo(
            overall_status=SnapRAIDStatus.HEALTHY,
            parity_info=ParityInfo(
                status=ParityStatus.UP_TO_DATE,
                coverage_percent=95.5,
                last_sync=datetime(2023, 1, 1, 10, 0, 0),
                sync_duration=timedelta(hours=2, minutes=30)
            ),
            data_drives=[
                DriveStatus(
                    name="d1",
                    device="/dev/sdb1",
                    mount_point="/mnt/disk1",
                    size_gb=1000.0,
                    used_gb=800.0,
                    free_gb=200.0,
                    files=5000,
                    status="healthy"
                )
            ],
            parity_drives=[
                DriveStatus(
                    name="parity",
                    device="/dev/sdc1",
                    mount_point="/mnt/parity1",
                    size_gb=1000.0,
                    used_gb=0.0,
                    free_gb=1000.0,
                    files=0,
                    status="healthy"
                )
            ],
            total_files=5000,
            total_size_gb=1000.0,
            last_check=datetime(2023, 1, 1, 12, 0, 0),
            config_path="/etc/snapraid.conf",
            version="12.0"
        )
        
        result_dict = self.snapraid_manager.to_dict(status_info)
        
        # Verify structure and enum conversions
        self.assertEqual(result_dict['overall_status'], 'healthy')
        self.assertEqual(result_dict['parity_info']['status'], 'up_to_date')
        self.assertEqual(result_dict['parity_info']['coverage_percent'], 95.5)
        self.assertEqual(result_dict['parity_info']['last_sync'], '2023-01-01T10:00:00')
        self.assertEqual(result_dict['parity_info']['sync_duration'], '2:30:00')
        self.assertEqual(result_dict['last_check'], '2023-01-01T12:00:00')
        self.assertEqual(len(result_dict['data_drives']), 1)
        self.assertEqual(len(result_dict['parity_drives']), 1)
        
        # Verify drive data
        data_drive = result_dict['data_drives'][0]
        self.assertEqual(data_drive['name'], 'd1')
        self.assertEqual(data_drive['size_gb'], 1000.0)
        self.assertEqual(data_drive['usage_percent'], 80.0)
    
    def test_cache_invalidation(self):
        """Test cache invalidation."""
        # Set up cache
        self.snapraid_manager._status_cache = Mock()
        self.snapraid_manager._cache_timestamp = datetime.now()
        
        # Invalidate cache
        self.snapraid_manager._invalidate_cache()
        
        # Verify cache is cleared
        self.assertIsNone(self.snapraid_manager._status_cache)
        self.assertIsNone(self.snapraid_manager._cache_timestamp)


class TestSnapRAIDStatusParsing(unittest.TestCase):
    """Test cases for SnapRAID status output parsing."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_config_manager = Mock(spec=ConfigManager)
        self.snapraid_manager = SnapRAIDManager(self.mock_config_manager, dry_run=True)
    
    def test_parse_complex_status_output(self):
        """Test parsing complex status output with multiple drives."""
        complex_output = """SnapRAID 12.0 by Andrea Mazzoleni, http://www.snapraid.it

Loading state from /var/snapraid/snapraid.content...
Comparing...

Self test...
Loading state from /var/snapraid/snapraid.content...
Comparing...

SUMMARY
       Files        Size     Used    Free  Use Name
        1234    500.0 GB  400.0 GB  100.0 GB   80% d1
        5678    750.0 GB  600.0 GB  150.0 GB   80% d2
        9012   1200.0 GB  900.0 GB  300.0 GB   75% d3
           0   2000.0 GB    0.0 GB 2000.0 GB    0% parity

The parity is up-to-date.
You have a 98% of coverage.
The oldest block was scrubbed 5 days ago, the median 3 days ago.
The newest block was scrubbed 1 days ago.

Total files: 15924
Total size: 2450.0 GB
Fragmentation: 2%
"""
        
        status = self.snapraid_manager._parse_status_output(complex_output, "/etc/snapraid.conf")
        
        # Verify overall status
        self.assertEqual(status.overall_status, SnapRAIDStatus.HEALTHY)
        self.assertEqual(status.version, "12.0")
        self.assertEqual(status.total_files, 15924)
        self.assertEqual(status.total_size_gb, 2450.0)
        
        # Verify parity info
        self.assertEqual(status.parity_info.status, ParityStatus.UP_TO_DATE)
        self.assertEqual(status.parity_info.coverage_percent, 98.0)
        
        # Verify drives
        self.assertEqual(len(status.data_drives), 3)
        self.assertEqual(len(status.parity_drives), 1)
        
        # Check specific drive details
        d1 = next(d for d in status.data_drives if d.name == "d1")
        self.assertEqual(d1.size_gb, 500.0)
        self.assertEqual(d1.used_gb, 400.0)
        self.assertEqual(d1.files, 1234)
        self.assertEqual(d1.usage_percent, 80.0)


if __name__ == '__main__':
    unittest.main()