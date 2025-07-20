"""Integration tests for NAS management components."""

import unittest
from unittest.mock import patch, Mock
import tempfile
import os

from nas.drive_manager import DriveManager
from nas.system_executor import SystemCommandExecutor
from nas.config_manager import ConfigManager, NASConfig
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestNASIntegration(unittest.TestCase):
    """Integration tests for NAS management system."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, 'nas_config.json')
        
        # Initialize components
        self.drive_manager = DriveManager()
        self.system_executor = SystemCommandExecutor(dry_run=True)
        self.config_manager = ConfigManager(self.config_file)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_complete_nas_workflow(self):
        """Test a complete NAS management workflow."""
        # 1. Load configuration
        config = self.config_manager.load_config()
        self.assertIsInstance(config, NASConfig)
        
        # 2. Update configuration
        success = self.config_manager.set_config_value('log_level', 'DEBUG')
        self.assertTrue(success)
        
        # 3. Save configuration
        success = self.config_manager.save_config(config, self.config_file)
        self.assertTrue(success)
        
        # 4. Mock drive discovery
        with patch('psutil.disk_partitions') as mock_partitions, \
             patch('psutil.disk_usage') as mock_usage, \
             patch.object(self.drive_manager, '_get_partition_uuid', return_value='test-uuid'):
            
            # Mock partition data
            mock_partitions.return_value = [
                Mock(device='/dev/sdb1', mountpoint='/mnt/disk1', fstype='ext4'),
                Mock(device='/dev/sdc1', mountpoint='/mnt/disk2', fstype='ext4'),
            ]
            
            # Mock disk usage
            mock_usage_result = Mock()
            mock_usage_result.total = 1000000000
            mock_usage_result.used = 500000000
            mock_usage.return_value = mock_usage_result
            
            # Discover drives
            drives = self.drive_manager.discover_drives()
            self.assertEqual(len(drives), 2)
            
            # Verify drive properties
            drive1 = drives[0]
            self.assertEqual(drive1.device_path, '/dev/sdb1')
            self.assertEqual(drive1.mount_point, '/mnt/disk1')
            self.assertEqual(drive1.filesystem, 'ext4')
            self.assertEqual(drive1.role, DriveRole.DATA)
            self.assertEqual(drive1.size_bytes, 1000000000)
            self.assertEqual(drive1.used_bytes, 500000000)
        
        # 5. Execute system commands
        success, stdout, stderr = self.system_executor.execute_snapraid_command('status')
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        
        success, stdout, stderr = self.system_executor.execute_smart_command('/dev/sdb1', '-H')
        self.assertTrue(success)
        
        # 6. Verify command history
        history = self.system_executor.get_command_history()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['type'], 'snapraid')
        self.assertEqual(history[1]['type'], 'smartctl')
    
    def test_configuration_drive_integration(self):
        """Test integration between configuration and drive management."""
        # Set up configuration with specific drive paths
        config = NASConfig(
            data_drive_paths=['/dev/sdb1', '/dev/sdc1'],
            parity_drive_paths=['/dev/sdd1'],
            mergerfs_mount_points=['/mnt/disk1', '/mnt/disk2']
        )
        
        # Save configuration
        success = self.config_manager.save_config(config, self.config_file)
        self.assertTrue(success)
        
        # Reload configuration
        reloaded_config = self.config_manager.reload_config()
        self.assertEqual(reloaded_config.data_drive_paths, ['/dev/sdb1', '/dev/sdc1'])
        self.assertEqual(reloaded_config.parity_drive_paths, ['/dev/sdd1'])
        
        # Mock drive discovery to match configuration
        with patch('psutil.disk_partitions') as mock_partitions, \
             patch('psutil.disk_usage') as mock_usage, \
             patch.object(self.drive_manager, '_get_partition_uuid', return_value='test-uuid'):
            
            mock_partitions.return_value = [
                Mock(device='/dev/sdb1', mountpoint='/mnt/disk1', fstype='ext4'),
                Mock(device='/dev/sdc1', mountpoint='/mnt/disk2', fstype='ext4'),
                Mock(device='/dev/sdd1', mountpoint='/mnt/parity1', fstype='ext4'),
            ]
            
            mock_usage_result = Mock()
            mock_usage_result.total = 1000000000
            mock_usage_result.used = 500000000
            mock_usage.return_value = mock_usage_result
            
            drives = self.drive_manager.discover_drives()
            
            # Verify drives match configuration expectations
            data_drives = [d for d in drives if d.role == DriveRole.DATA]
            parity_drives = [d for d in drives if d.role == DriveRole.PARITY]
            
            self.assertEqual(len(data_drives), 2)
            self.assertEqual(len(parity_drives), 1)
            
            # Verify specific devices
            device_paths = [d.device_path for d in drives]
            self.assertIn('/dev/sdb1', device_paths)
            self.assertIn('/dev/sdc1', device_paths)
            self.assertIn('/dev/sdd1', device_paths)
    
    def test_system_executor_with_config(self):
        """Test system executor using configuration values."""
        # Set up configuration with custom SnapRAID path
        config = NASConfig(
            snapraid_config_path='/custom/snapraid.conf',
            max_command_timeout=600
        )
        
        success = self.config_manager.save_config(config, self.config_file)
        self.assertTrue(success)
        
        # Load configuration
        loaded_config = self.config_manager.load_config()
        
        # Execute SnapRAID command with config path from configuration
        success, stdout, stderr = self.system_executor.execute_snapraid_command(
            'status',
            config_path=loaded_config.snapraid_config_path
        )
        
        self.assertTrue(success)
        
        # Verify command includes the custom config path
        history = self.system_executor.get_command_history()
        self.assertIn('/custom/snapraid.conf', history[0]['command'])
    
    def test_error_handling_integration(self):
        """Test error handling across components."""
        # Test invalid configuration
        with self.assertRaises(ValueError):
            invalid_config = NASConfig(max_command_timeout=-1)
            self.config_manager._validate_config(invalid_config)
        
        # Test invalid system command
        with self.assertRaises(ValueError):
            self.system_executor.execute_smart_command('../invalid/path', '-H')
        
        # Test drive manager with no drives
        with patch('psutil.disk_partitions', return_value=[]):
            drives = self.drive_manager.discover_drives()
            self.assertEqual(len(drives), 0)
    
    def test_component_initialization(self):
        """Test that all components can be initialized together."""
        # This test ensures there are no import or initialization conflicts
        drive_manager = DriveManager()
        system_executor = SystemCommandExecutor()
        config_manager = ConfigManager()
        
        # Verify basic functionality
        self.assertIsNotNone(drive_manager)
        self.assertIsNotNone(system_executor)
        self.assertIsNotNone(config_manager)
        
        # Test basic operations
        config = config_manager.load_config()
        self.assertIsInstance(config, NASConfig)
        
        # Test dry run command
        system_executor_dry = SystemCommandExecutor(dry_run=True)
        success, stdout, stderr = system_executor_dry.execute_blkid_command(device_path='/dev/test')
        self.assertTrue(success)


if __name__ == '__main__':
    unittest.main()