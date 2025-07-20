"""Unit tests for SnapRAID configuration management."""

import unittest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path
import tempfile
import os

from nas.snapraid_manager import SnapRAIDManager
from nas.config_manager import ConfigManager, NASConfig


class TestSnapRAIDConfigManagement(unittest.TestCase):
    """Test cases for SnapRAID configuration management."""
    
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
    
    def test_generate_config_basic(self):
        """Test basic configuration generation."""
        data_drives = ["/mnt/disk1", "/mnt/disk2"]
        parity_drives = ["/mnt/parity1"]
        
        config_content = self.snapraid_manager.generate_config(
            data_drives=data_drives,
            parity_drives=parity_drives
        )
        
        # Verify basic structure
        self.assertIn("# SnapRAID configuration file", config_content)
        self.assertIn("parity /mnt/parity1/snapraid.parity", config_content)
        self.assertIn("data d1 /mnt/disk1", config_content)
        self.assertIn("data d2 /mnt/disk2", config_content)
        self.assertIn("content /var/snapraid/snapraid.content", config_content)
        self.assertIn("exclude *.tmp", config_content)
        self.assertIn("block_size 256", config_content)
    
    def test_generate_config_multiple_parity(self):
        """Test configuration generation with multiple parity drives."""
        data_drives = ["/mnt/disk1", "/mnt/disk2", "/mnt/disk3"]
        parity_drives = ["/mnt/parity1", "/mnt/parity2"]
        
        config_content = self.snapraid_manager.generate_config(
            data_drives=data_drives,
            parity_drives=parity_drives
        )
        
        # Verify parity drives
        self.assertIn("parity /mnt/parity1/snapraid.parity", config_content)
        self.assertIn("2-parity /mnt/parity2/snapraid.2-parity", config_content)
        
        # Verify data drives
        self.assertIn("data d1 /mnt/disk1", config_content)
        self.assertIn("data d2 /mnt/disk2", config_content)
        self.assertIn("data d3 /mnt/disk3", config_content)
    
    def test_generate_config_custom_content_locations(self):
        """Test configuration generation with custom content locations."""
        data_drives = ["/mnt/disk1"]
        parity_drives = ["/mnt/parity1"]
        content_locations = ["/custom/content1", "/custom/content2"]
        
        config_content = self.snapraid_manager.generate_config(
            data_drives=data_drives,
            parity_drives=parity_drives,
            content_locations=content_locations
        )
        
        # Verify custom content locations
        self.assertIn("content /custom/content1", config_content)
        self.assertIn("content /custom/content2", config_content)
        # Should not contain default content locations
        self.assertNotIn("content /var/snapraid/snapraid.content", config_content)
    
    def test_generate_config_no_data_drives(self):
        """Test configuration generation with no data drives."""
        with self.assertRaises(ValueError) as context:
            self.snapraid_manager.generate_config(
                data_drives=[],
                parity_drives=["/mnt/parity1"]
            )
        
        self.assertIn("At least one data drive is required", str(context.exception))
    
    def test_generate_config_no_parity_drives(self):
        """Test configuration generation with no parity drives."""
        with self.assertRaises(ValueError) as context:
            self.snapraid_manager.generate_config(
                data_drives=["/mnt/disk1"],
                parity_drives=[]
            )
        
        self.assertIn("At least one parity drive is required", str(context.exception))
    
    def test_validate_config_valid(self):
        """Test validation of valid configuration."""
        valid_config = """# SnapRAID configuration
parity /mnt/parity1/snapraid.parity
content /var/snapraid/snapraid.content
content /mnt/disk1/snapraid.content
data d1 /mnt/disk1
data d2 /mnt/disk2
exclude *.tmp
"""
        
        with patch('pathlib.Path.exists', return_value=True):
            is_valid, errors = self.snapraid_manager.validate_config(valid_config)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_validate_config_missing_parity(self):
        """Test validation of configuration missing parity."""
        invalid_config = """# SnapRAID configuration
content /var/snapraid/snapraid.content
data d1 /mnt/disk1
"""
        
        with patch('pathlib.Path.exists', return_value=True):
            is_valid, errors = self.snapraid_manager.validate_config(invalid_config)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("missing required 'parity' directive" in error for error in errors))
    
    def test_validate_config_missing_content(self):
        """Test validation of configuration missing content."""
        invalid_config = """# SnapRAID configuration
parity /mnt/parity1/snapraid.parity
data d1 /mnt/disk1
"""
        
        with patch('pathlib.Path.exists', return_value=True):
            is_valid, errors = self.snapraid_manager.validate_config(invalid_config)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("missing required 'content' directive" in error for error in errors))
    
    def test_validate_config_missing_data(self):
        """Test validation of configuration missing data drives."""
        invalid_config = """# SnapRAID configuration
parity /mnt/parity1/snapraid.parity
content /var/snapraid/snapraid.content
"""
        
        with patch('pathlib.Path.exists', return_value=True):
            is_valid, errors = self.snapraid_manager.validate_config(invalid_config)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("missing required 'data' directive" in error for error in errors))
    
    def test_validate_config_duplicate_data_drives(self):
        """Test validation of configuration with duplicate data drive names."""
        invalid_config = """# SnapRAID configuration
parity /mnt/parity1/snapraid.parity
content /var/snapraid/snapraid.content
data d1 /mnt/disk1
data d1 /mnt/disk2
"""
        
        with patch('pathlib.Path.exists', return_value=True):
            is_valid, errors = self.snapraid_manager.validate_config(invalid_config)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("Duplicate data drive name: d1" in error for error in errors))
    
    def test_validate_config_nonexistent_paths(self):
        """Test validation of configuration with nonexistent paths."""
        config_with_bad_paths = """# SnapRAID configuration
parity /nonexistent/parity1/snapraid.parity
content /nonexistent/snapraid.content
data d1 /nonexistent/disk1
"""
        
        with patch('pathlib.Path.exists', return_value=False):
            is_valid, errors = self.snapraid_manager.validate_config(config_with_bad_paths)
        
        self.assertFalse(is_valid)
        self.assertTrue(any("does not exist" in error for error in errors))
    
    @patch('shutil.copy2')
    @patch('pathlib.Path.exists')
    def test_backup_config(self, mock_exists, mock_copy):
        """Test configuration backup functionality."""
        mock_exists.return_value = True
        config_path = "/etc/snapraid.conf"
        
        backup_path = self.snapraid_manager.backup_config(config_path)
        
        # Verify backup path format
        self.assertTrue(backup_path.startswith(config_path + ".backup_"))
        self.assertTrue(backup_path.endswith("_" + backup_path.split("_")[-1]))
        
        # Verify copy was called
        mock_copy.assert_called_once_with(config_path, backup_path)
    
    @patch('pathlib.Path.exists')
    def test_backup_config_file_not_found(self, mock_exists):
        """Test backup when configuration file doesn't exist."""
        mock_exists.return_value = False
        config_path = "/etc/snapraid.conf"
        
        with self.assertRaises(FileNotFoundError):
            self.snapraid_manager.backup_config(config_path)
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.mkdir')
    def test_update_config_success(self, mock_mkdir, mock_exists, mock_file):
        """Test successful configuration update."""
        mock_exists.return_value = True
        
        data_drives = ["/mnt/disk1", "/mnt/disk2"]
        parity_drives = ["/mnt/parity1"]
        
        success, message = self.snapraid_manager.update_config(
            data_drives=data_drives,
            parity_drives=parity_drives,
            backup=False  # Skip backup for this test
        )
        
        self.assertTrue(success)
        self.assertIn("updated successfully", message)
        
        # Verify file was written
        mock_file.assert_called_once()
        
        # Verify directory creation was attempted
        mock_mkdir.assert_called_once()
    
    @patch('pathlib.Path.exists')
    def test_update_config_with_backup(self, mock_exists):
        """Test configuration update with backup."""
        mock_exists.return_value = True
        
        with patch.object(self.snapraid_manager, 'backup_config') as mock_backup:
            mock_backup.return_value = "/etc/snapraid.conf.backup_123"
            
            with patch('builtins.open', mock_open()):
                with patch('pathlib.Path.mkdir'):
                    success, message = self.snapraid_manager.update_config(
                        data_drives=["/mnt/disk1"],
                        parity_drives=["/mnt/parity1"],
                        backup=True
                    )
            
            self.assertTrue(success)
            mock_backup.assert_called_once()
    
    def test_auto_update_config_from_drives(self):
        """Test automatic configuration update from detected drives."""
        # Mock drive manager
        mock_drive_manager = Mock()
        
        # Mock drives
        from nas.models import DriveConfig, DriveRole, HealthStatus
        mock_drives = [
            DriveConfig(
                device_path="/dev/sdb1",
                uuid="uuid1",
                mount_point="/mnt/disk1",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.HEALTHY
            ),
            DriveConfig(
                device_path="/dev/sdc1",
                uuid="uuid2",
                mount_point="/mnt/disk2",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=600000000,
                health_status=HealthStatus.HEALTHY
            ),
            DriveConfig(
                device_path="/dev/sdd1",
                uuid="uuid3",
                mount_point="/mnt/parity1",
                filesystem="ext4",
                role=DriveRole.PARITY,
                size_bytes=2000000000,
                used_bytes=0,
                health_status=HealthStatus.HEALTHY
            )
        ]
        
        mock_drive_manager.discover_drives.return_value = mock_drives
        
        # Mock update_config method
        with patch.object(self.snapraid_manager, 'update_config') as mock_update:
            mock_update.return_value = (True, "Configuration updated successfully")
            
            success, message = self.snapraid_manager.auto_update_config_from_drives(mock_drive_manager)
            
            self.assertTrue(success)
            self.assertIn("updated successfully", message)
            
            # Verify update_config was called with correct drives
            mock_update.assert_called_once_with(
                data_drives=["/mnt/disk1", "/mnt/disk2"],
                parity_drives=["/mnt/parity1"]
            )
    
    def test_auto_update_config_no_data_drives(self):
        """Test auto-update when no data drives are detected."""
        mock_drive_manager = Mock()
        mock_drive_manager.discover_drives.return_value = []
        
        success, message = self.snapraid_manager.auto_update_config_from_drives(mock_drive_manager)
        
        self.assertFalse(success)
        self.assertIn("No data drives detected", message)
    
    def test_auto_update_config_no_parity_drives(self):
        """Test auto-update when no parity drives are detected."""
        mock_drive_manager = Mock()
        
        # Mock only data drives, no parity
        from nas.models import DriveConfig, DriveRole, HealthStatus
        mock_drives = [
            DriveConfig(
                device_path="/dev/sdb1",
                uuid="uuid1",
                mount_point="/mnt/disk1",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=1000000000,
                used_bytes=500000000,
                health_status=HealthStatus.HEALTHY
            )
        ]
        
        mock_drive_manager.discover_drives.return_value = mock_drives
        
        success, message = self.snapraid_manager.auto_update_config_from_drives(mock_drive_manager)
        
        self.assertFalse(success)
        self.assertIn("No parity drives detected", message)


if __name__ == '__main__':
    unittest.main()