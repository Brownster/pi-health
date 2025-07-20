"""Unit tests for SystemCommandExecutor."""

import unittest
from unittest.mock import Mock, patch
import subprocess

from nas.system_executor import SystemCommandExecutor, CommandType


class TestSystemCommandExecutor(unittest.TestCase):
    """Test cases for SystemCommandExecutor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.executor = SystemCommandExecutor(dry_run=True)
        self.executor_live = SystemCommandExecutor(dry_run=False)
    
    def test_validate_device_path_valid(self):
        """Test valid device path validation."""
        valid_paths = [
            '/dev/sda',
            '/dev/sdb1',
            '/dev/nvme0n1',
            '/dev/mmcblk0p1'
        ]
        
        for path in valid_paths:
            with self.subTest(path=path):
                self.assertTrue(self.executor._validate_device_path(path))
    
    def test_validate_device_path_invalid(self):
        """Test invalid device path validation."""
        invalid_paths = [
            '/dev/../etc/passwd',
            '/dev/sda; rm -rf /',
            'sda1',
            '/home/user/file',
            '/dev/',
            ''
        ]
        
        for path in invalid_paths:
            with self.subTest(path=path):
                self.assertFalse(self.executor._validate_device_path(path))
    
    def test_validate_file_path_valid(self):
        """Test valid file path validation."""
        valid_paths = [
            '/etc/snapraid.conf',
            '/mnt/disk1',
            '/home/user/config.txt',
            '/var/log/snapraid.log'
        ]
        
        for path in valid_paths:
            with self.subTest(path=path):
                self.assertTrue(self.executor._validate_file_path(path))
    
    def test_validate_file_path_invalid(self):
        """Test invalid file path validation."""
        invalid_paths = [
            '../etc/passwd',
            '/etc/passwd; cat /etc/shadow',
            'relative/path',
            '',
            '/path with spaces'  # Spaces not allowed in our pattern
        ]
        
        for path in invalid_paths:
            with self.subTest(path=path):
                self.assertFalse(self.executor._validate_file_path(path))
    
    def test_validate_label_valid(self):
        """Test valid filesystem label validation."""
        valid_labels = [
            'DATA1',
            'parity-drive',
            'disk_01',
            'BACKUP'
        ]
        
        for label in valid_labels:
            with self.subTest(label=label):
                self.assertTrue(self.executor._validate_label(label))
    
    def test_validate_label_invalid(self):
        """Test invalid filesystem label validation."""
        invalid_labels = [
            'label with spaces',
            'label@special',
            'very-long-label-name-exceeding-limit',
            '',
            'label;injection'
        ]
        
        for label in invalid_labels:
            with self.subTest(label=label):
                self.assertFalse(self.executor._validate_label(label))
    
    def test_validate_uuid_valid(self):
        """Test valid UUID validation."""
        valid_uuids = [
            '12345678-1234-1234-1234-123456789abc',
            'ABCDEF01-2345-6789-ABCD-EF0123456789',
            '00000000-0000-0000-0000-000000000000'
        ]
        
        for uuid in valid_uuids:
            with self.subTest(uuid=uuid):
                self.assertTrue(self.executor._validate_uuid(uuid))
    
    def test_validate_uuid_invalid(self):
        """Test invalid UUID validation."""
        invalid_uuids = [
            '12345678-1234-1234-1234-123456789ab',  # Too short
            '12345678-1234-1234-1234-123456789abcd',  # Too long
            '12345678-1234-1234-1234-123456789abg',  # Invalid character
            '12345678123412341234123456789abc',  # Missing dashes
            '',
            'not-a-uuid'
        ]
        
        for uuid in invalid_uuids:
            with self.subTest(uuid=uuid):
                self.assertFalse(self.executor._validate_uuid(uuid))
    
    def test_validate_filesystem_type_valid(self):
        """Test valid filesystem type validation."""
        valid_types = ['ext4', 'ext3', 'xfs', 'btrfs', 'ntfs']
        
        for fs_type in valid_types:
            with self.subTest(fs_type=fs_type):
                self.assertTrue(self.executor._validate_filesystem_type(fs_type))
    
    def test_validate_filesystem_type_invalid(self):
        """Test invalid filesystem type validation."""
        invalid_types = ['unknown', 'malicious', '', 'ext4; rm -rf /']
        
        for fs_type in invalid_types:
            with self.subTest(fs_type=fs_type):
                self.assertFalse(self.executor._validate_filesystem_type(fs_type))
    
    def test_validate_mount_options_valid(self):
        """Test valid mount options validation."""
        valid_options = [
            'rw',
            'ro,noatime',
            'defaults,user,noauto',
            'rw,relatime,exec'
        ]
        
        for options in valid_options:
            with self.subTest(options=options):
                self.assertTrue(self.executor._validate_mount_options(options))
    
    def test_validate_mount_options_invalid(self):
        """Test invalid mount options validation."""
        invalid_options = [
            'malicious',
            'rw,unknown',
            'defaults; rm -rf /',
            ''
        ]
        
        for options in invalid_options:
            with self.subTest(options=options):
                self.assertFalse(self.executor._validate_mount_options(options))
    
    def test_execute_snapraid_command_dry_run(self):
        """Test SnapRAID command execution in dry run mode."""
        success, stdout, stderr = self.executor.execute_snapraid_command('status')
        
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        self.assertEqual(stderr, "")
        
        # Check command history
        history = self.executor.get_command_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['type'], 'snapraid')
        self.assertTrue(history[0]['dry_run'])
    
    def test_execute_snapraid_command_with_config(self):
        """Test SnapRAID command with config file."""
        success, stdout, stderr = self.executor.execute_snapraid_command(
            'sync', 
            config_path='/etc/snapraid.conf'
        )
        
        self.assertTrue(success)
        
        # Check that the command includes the config path
        history = self.executor.get_command_history()
        self.assertIn('-c', history[0]['command'])
        self.assertIn('/etc/snapraid.conf', history[0]['command'])
    
    def test_execute_snapraid_command_invalid_config_path(self):
        """Test SnapRAID command with invalid config path."""
        with self.assertRaises(ValueError) as context:
            self.executor.execute_snapraid_command('status', config_path='../etc/passwd')
        
        self.assertIn("Invalid config path", str(context.exception))
    
    def test_execute_smart_command_dry_run(self):
        """Test SMART command execution in dry run mode."""
        success, stdout, stderr = self.executor.execute_smart_command('/dev/sdb', '-H')
        
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        self.assertEqual(stderr, "")
    
    def test_execute_smart_command_with_test(self):
        """Test SMART command with test type."""
        success, stdout, stderr = self.executor.execute_smart_command(
            '/dev/sdb', 
            '-t', 
            test_type='short'
        )
        
        self.assertTrue(success)
        
        # Check command history
        history = self.executor.get_command_history()
        self.assertIn('short', history[0]['command'])
    
    def test_execute_smart_command_invalid_device(self):
        """Test SMART command with invalid device path."""
        with self.assertRaises(ValueError) as context:
            self.executor.execute_smart_command('../dev/sdb', '-H')
        
        self.assertIn("Invalid device path", str(context.exception))
    
    def test_execute_smart_command_invalid_test_type(self):
        """Test SMART command with invalid test type."""
        with self.assertRaises(ValueError) as context:
            self.executor.execute_smart_command('/dev/sdb', '-t', test_type='malicious')
        
        self.assertIn("Invalid test type", str(context.exception))
    
    def test_execute_filesystem_command_dry_run(self):
        """Test filesystem command execution in dry run mode."""
        success, stdout, stderr = self.executor.execute_filesystem_command('/dev/sdb1')
        
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        self.assertEqual(stderr, "")
    
    def test_execute_filesystem_command_with_label(self):
        """Test filesystem command with label."""
        success, stdout, stderr = self.executor.execute_filesystem_command(
            '/dev/sdb1', 
            label='DATA1'
        )
        
        self.assertTrue(success)
        
        # Check command history
        history = self.executor.get_command_history()
        self.assertIn('-L', history[0]['command'])
        self.assertIn('DATA1', history[0]['command'])
    
    def test_execute_filesystem_command_invalid_filesystem(self):
        """Test filesystem command with invalid filesystem type."""
        with self.assertRaises(ValueError) as context:
            self.executor.execute_filesystem_command('/dev/sdb1', filesystem_type='malicious')
        
        self.assertIn("Unsupported filesystem type", str(context.exception))
    
    def test_execute_mount_command_dry_run(self):
        """Test mount command execution in dry run mode."""
        success, stdout, stderr = self.executor.execute_mount_command(
            '/dev/sdb1', 
            '/mnt/disk1'
        )
        
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        self.assertEqual(stderr, "")
    
    def test_execute_blkid_command_dry_run(self):
        """Test blkid command execution in dry run mode."""
        success, stdout, stderr = self.executor.execute_blkid_command(device_path='/dev/sdb1')
        
        self.assertTrue(success)
        self.assertEqual(stdout, "DRY RUN")
        self.assertEqual(stderr, "")
    
    @patch('subprocess.run')
    def test_execute_command_live_success(self, mock_run):
        """Test live command execution success."""
        # Mock successful subprocess result
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "Command output"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, stdout, stderr = self.executor_live.execute_blkid_command(device_path='/dev/sdb1')
        
        self.assertTrue(success)
        self.assertEqual(stdout, "Command output")
        self.assertEqual(stderr, "")
        
        # Verify subprocess.run was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[0], 'blkid')
        self.assertIn('/dev/sdb1', call_args)
    
    @patch('subprocess.run')
    def test_execute_command_live_failure(self, mock_run):
        """Test live command execution failure."""
        # Mock failed subprocess result
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Command failed"
        mock_run.return_value = mock_result
        
        success, stdout, stderr = self.executor_live.execute_blkid_command(device_path='/dev/sdb1')
        
        self.assertFalse(success)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "Command failed")
    
    @patch('subprocess.run')
    def test_execute_command_timeout(self, mock_run):
        """Test command execution timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired('blkid', 300)
        
        success, stdout, stderr = self.executor_live.execute_blkid_command(device_path='/dev/sdb1')
        
        self.assertFalse(success)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "Command timed out")
    
    def test_command_history_management(self):
        """Test command history management."""
        # Execute a few commands
        self.executor.execute_snapraid_command('status')
        self.executor.execute_smart_command('/dev/sdb', '-H')
        
        # Check history
        history = self.executor.get_command_history()
        self.assertEqual(len(history), 2)
        
        # Clear history
        self.executor.clear_command_history()
        history = self.executor.get_command_history()
        self.assertEqual(len(history), 0)
    
    def test_validate_command_args_snapraid(self):
        """Test command argument validation for SnapRAID."""
        # Valid arguments should not raise
        valid_args = ['status', '-c', '/etc/snapraid.conf', '-v']
        self.executor._validate_command_args(CommandType.SNAPRAID, valid_args)
        
        # Invalid arguments should raise
        invalid_args = ['status', '--malicious-flag']
        with self.assertRaises(ValueError):
            self.executor._validate_command_args(CommandType.SNAPRAID, invalid_args)
    
    def test_validate_command_args_smartctl(self):
        """Test command argument validation for smartctl."""
        # Valid arguments should not raise
        valid_args = ['-H', '/dev/sdb']
        self.executor._validate_command_args(CommandType.SMARTCTL, valid_args)
        
        # Invalid arguments should raise
        invalid_args = ['-H', '/dev/sdb', '--malicious']
        with self.assertRaises(ValueError):
            self.executor._validate_command_args(CommandType.SMARTCTL, invalid_args)


if __name__ == '__main__':
    unittest.main()