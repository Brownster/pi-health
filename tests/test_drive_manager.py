"""Unit tests for DriveManager."""

import unittest
from unittest.mock import Mock, patch, mock_open
import os
from collections import namedtuple

from nas.drive_manager import DriveManager
from nas.models import DriveConfig, DriveRole, HealthStatus


# Mock partition object
MockPartition = namedtuple('MockPartition', ['device', 'mountpoint', 'fstype'])


class TestDriveManager(unittest.TestCase):
    """Test cases for DriveManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.drive_manager = DriveManager()
    
    def test_is_system_partition_system_mount_points(self):
        """Test that system mount points are correctly identified."""
        system_partitions = [
            MockPartition('/dev/sda1', '/', 'ext4'),
            MockPartition('/dev/sda2', '/boot', 'vfat'),
            MockPartition('/dev/sda3', '/boot/efi', 'vfat'),
            MockPartition('/dev/sda4', '/tmp', 'tmpfs'),
            MockPartition('/dev/sda5', '/var/log', 'ext4'),  # subdirectory of /var
        ]
        
        for partition in system_partitions:
            with self.subTest(partition=partition):
                self.assertTrue(
                    self.drive_manager._is_system_partition(partition),
                    f"Should identify {partition.mountpoint} as system partition"
                )
    
    def test_is_system_partition_system_filesystems(self):
        """Test that system filesystem types are correctly identified."""
        system_fs_partitions = [
            MockPartition('proc', '/proc', 'proc'),
            MockPartition('sysfs', '/sys', 'sysfs'),
            MockPartition('devtmpfs', '/dev', 'devtmpfs'),
            MockPartition('tmpfs', '/run', 'tmpfs'),
        ]
        
        for partition in system_fs_partitions:
            with self.subTest(partition=partition):
                self.assertTrue(
                    self.drive_manager._is_system_partition(partition),
                    f"Should identify {partition.fstype} as system filesystem"
                )
    
    def test_is_system_partition_loop_devices(self):
        """Test that loop devices are correctly identified as system."""
        loop_partitions = [
            MockPartition('/dev/loop0', '/snap/core/123', 'squashfs'),
            MockPartition('/dev/loop1', '/snap/firefox/456', 'squashfs'),
        ]
        
        for partition in loop_partitions:
            with self.subTest(partition=partition):
                self.assertTrue(
                    self.drive_manager._is_system_partition(partition),
                    f"Should identify {partition.device} as system partition"
                )
    
    def test_is_system_partition_data_drives(self):
        """Test that data drives are not identified as system partitions."""
        data_partitions = [
            MockPartition('/dev/sdb1', '/mnt/disk1', 'ext4'),
            MockPartition('/dev/sdc1', '/mnt/data', 'ext4'),
            MockPartition('/dev/sdd1', '/media/usb', 'ntfs'),
            MockPartition('/dev/sde1', '/mnt/parity1', 'ext4'),
        ]
        
        for partition in data_partitions:
            with self.subTest(partition=partition):
                self.assertFalse(
                    self.drive_manager._is_system_partition(partition),
                    f"Should not identify {partition.mountpoint} as system partition"
                )
    
    def test_determine_drive_role_parity(self):
        """Test parity drive role detection."""
        parity_mount_points = [
            '/mnt/parity1',
            '/mnt/parity',
            '/media/PARITY_DRIVE',
        ]
        
        for mount_point in parity_mount_points:
            with self.subTest(mount_point=mount_point):
                role = self.drive_manager._determine_drive_role(mount_point)
                self.assertEqual(role, DriveRole.PARITY)
    
    def test_determine_drive_role_data(self):
        """Test data drive role detection."""
        data_mount_points = [
            '/mnt/disk1',
            '/mnt/data',
            '/media/DATA_DRIVE',
        ]
        
        for mount_point in data_mount_points:
            with self.subTest(mount_point=mount_point):
                role = self.drive_manager._determine_drive_role(mount_point)
                self.assertEqual(role, DriveRole.DATA)
    
    def test_determine_drive_role_unknown(self):
        """Test unknown drive role detection."""
        unknown_mount_points = [
            '/media/unknown',
            '/custom/mount',
        ]
        
        for mount_point in unknown_mount_points:
            with self.subTest(mount_point=mount_point):
                role = self.drive_manager._determine_drive_role(mount_point)
                self.assertEqual(role, DriveRole.UNKNOWN)
    
    @patch('os.path.exists')
    @patch('os.access')
    def test_get_basic_health_status_healthy(self, mock_access, mock_exists):
        """Test healthy drive status detection."""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        status = self.drive_manager._get_basic_health_status('/mnt/disk1')
        self.assertEqual(status, HealthStatus.HEALTHY)
    
    @patch('os.path.exists')
    @patch('os.access')
    def test_get_basic_health_status_degraded(self, mock_access, mock_exists):
        """Test degraded drive status detection."""
        mock_exists.return_value = True
        mock_access.return_value = False
        
        status = self.drive_manager._get_basic_health_status('/mnt/disk1')
        self.assertEqual(status, HealthStatus.DEGRADED)
    
    @patch('os.path.exists')
    def test_get_basic_health_status_failed(self, mock_exists):
        """Test failed drive status detection."""
        mock_exists.return_value = False
        
        status = self.drive_manager._get_basic_health_status('/mnt/disk1')
        self.assertEqual(status, HealthStatus.DEGRADED)
    
    @patch('subprocess.run')
    def test_get_partition_uuid_success(self, mock_run):
        """Test successful UUID retrieval."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "12345678-1234-1234-1234-123456789abc\n"
        mock_run.return_value = mock_result
        
        uuid = self.drive_manager._get_partition_uuid('/dev/sdb1')
        self.assertEqual(uuid, "12345678-1234-1234-1234-123456789abc")
        
        mock_run.assert_called_once_with(
            ['blkid', '-s', 'UUID', '-o', 'value', '/dev/sdb1'],
            capture_output=True,
            text=True,
            timeout=10
        )
    
    @patch('subprocess.run')
    def test_get_partition_uuid_failure(self, mock_run):
        """Test UUID retrieval failure."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_run.return_value = mock_result
        
        uuid = self.drive_manager._get_partition_uuid('/dev/sdb1')
        self.assertIsNone(uuid)
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='1\n')
    def test_is_usb_drive_true(self, mock_file, mock_exists):
        """Test USB drive detection - positive case."""
        mock_exists.return_value = True
        
        result = self.drive_manager.is_usb_drive('/dev/sdb1')
        self.assertTrue(result)
        
        mock_exists.assert_called_once_with('/sys/block/sdb/removable')
        mock_file.assert_called_once_with('/sys/block/sdb/removable', 'r')
    
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data='0\n')
    def test_is_usb_drive_false(self, mock_file, mock_exists):
        """Test USB drive detection - negative case."""
        mock_exists.return_value = True
        
        result = self.drive_manager.is_usb_drive('/dev/sda1')
        self.assertFalse(result)
    
    @patch('os.path.exists')
    def test_is_usb_drive_no_file(self, mock_exists):
        """Test USB drive detection when removable file doesn't exist."""
        mock_exists.return_value = False
        
        result = self.drive_manager.is_usb_drive('/dev/sdb1')
        self.assertFalse(result)
    
    @patch('psutil.disk_partitions')
    @patch('psutil.disk_usage')
    def test_discover_drives_filters_system_partitions(self, mock_usage, mock_partitions):
        """Test that discover_drives filters out system partitions."""
        # Mock partitions including both system and data drives
        mock_partitions.return_value = [
            MockPartition('/dev/sda1', '/', 'ext4'),  # System
            MockPartition('/dev/sda2', '/boot', 'vfat'),  # System
            MockPartition('/dev/sdb1', '/mnt/disk1', 'ext4'),  # Data
            MockPartition('proc', '/proc', 'proc'),  # System
        ]
        
        # Mock disk usage for the data drive
        mock_usage_result = Mock()
        mock_usage_result.total = 1000000000
        mock_usage_result.used = 500000000
        mock_usage.return_value = mock_usage_result
        
        with patch.object(self.drive_manager, '_get_partition_uuid', return_value='test-uuid'):
            drives = self.drive_manager.discover_drives()
        
        # Should only return the data drive
        self.assertEqual(len(drives), 1)
        self.assertEqual(drives[0].device_path, '/dev/sdb1')
        self.assertEqual(drives[0].mount_point, '/mnt/disk1')
    
    def test_get_drive_by_device(self):
        """Test retrieving drive by device path."""
        # Create a mock drive and add to cache
        drive = DriveConfig(
            device_path='/dev/sdb1',
            uuid='test-uuid',
            mount_point='/mnt/disk1',
            filesystem='ext4',
            role=DriveRole.DATA,
            size_bytes=1000000000,
            used_bytes=500000000,
            health_status=HealthStatus.HEALTHY
        )
        self.drive_manager._drive_cache['/dev/sdb1'] = drive
        
        result = self.drive_manager.get_drive_by_device('/dev/sdb1')
        self.assertEqual(result, drive)
        
        # Test non-existent device
        result = self.drive_manager.get_drive_by_device('/dev/nonexistent')
        self.assertIsNone(result)
    
    def test_get_drive_by_mount_point(self):
        """Test retrieving drive by mount point."""
        # Create a mock drive and add to cache
        drive = DriveConfig(
            device_path='/dev/sdb1',
            uuid='test-uuid',
            mount_point='/mnt/disk1',
            filesystem='ext4',
            role=DriveRole.DATA,
            size_bytes=1000000000,
            used_bytes=500000000,
            health_status=HealthStatus.HEALTHY
        )
        self.drive_manager._drive_cache['/dev/sdb1'] = drive
        
        result = self.drive_manager.get_drive_by_mount_point('/mnt/disk1')
        self.assertEqual(result, drive)
        
        # Test non-existent mount point
        result = self.drive_manager.get_drive_by_mount_point('/mnt/nonexistent')
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()