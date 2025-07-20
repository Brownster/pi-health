"""Unit tests for MergerFS manager."""

import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import os
import tempfile
from nas.mergerfs_manager import MergerFSManager, MergerFSPool, MergerFSBranchStats, MergerFSPolicy
from nas.system_executor import SystemCommandExecutor


class TestMergerFSManager(unittest.TestCase):
    """Test cases for MergerFSManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_executor = Mock(spec=SystemCommandExecutor)
        self.manager = MergerFSManager(self.mock_executor)
    
    def test_init(self):
        """Test MergerFSManager initialization."""
        # Test with provided executor
        manager = MergerFSManager(self.mock_executor)
        self.assertEqual(manager._system_executor, self.mock_executor)
        
        # Test with default executor
        manager = MergerFSManager()
        self.assertIsInstance(manager._system_executor, SystemCommandExecutor)
    
    @patch('builtins.open', new_callable=mock_open, read_data="""/dev/sda1:/dev/sdb1 /mnt/storage fuse.mergerfs defaults,allow_other,use_ino 0 0
/dev/sdc1 /mnt/disk3 ext4 defaults 0 0
/dev/sdd1:/dev/sde1:/dev/sdf1 /mnt/pool2 fuse.mergerfs category.create=epmfs,category.search=ff 0 0
""")
    def test_discover_pools(self, mock_file):
        """Test discovering MergerFS pools from /proc/mounts."""
        pools = self.manager.discover_pools()
        
        # Should find 2 MergerFS pools
        self.assertEqual(len(pools), 2)
        
        # Check first pool
        pool1 = pools[0]
        self.assertEqual(pool1.mount_point, '/mnt/storage')
        self.assertEqual(pool1.source_paths, ['/dev/sda1', '/dev/sdb1'])
        self.assertEqual(pool1.filesystem, 'fuse.mergerfs')
        self.assertIn('defaults', pool1.options)
        self.assertIn('allow_other', pool1.options)
        
        # Check second pool
        pool2 = pools[1]
        self.assertEqual(pool2.mount_point, '/mnt/pool2')
        self.assertEqual(pool2.source_paths, ['/dev/sdd1', '/dev/sde1', '/dev/sdf1'])
        self.assertIn('category.create', pool2.options)
        self.assertEqual(pool2.options['category.create'], 'epmfs')
        
        # Check cache is updated
        self.assertEqual(len(self.manager._pool_cache), 2)
        self.assertIn('/mnt/storage', self.manager._pool_cache)
        self.assertIn('/mnt/pool2', self.manager._pool_cache)
    
    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_discover_pools_file_not_found(self, mock_file):
        """Test discovering pools when /proc/mounts is not accessible."""
        pools = self.manager.discover_pools()
        self.assertEqual(len(pools), 0)
        self.assertEqual(len(self.manager._pool_cache), 0)
    
    def test_get_pool_by_mount_point(self):
        """Test getting pool by mount point."""
        # Create test pool
        test_pool = MergerFSPool(
            mount_point='/mnt/test',
            source_paths=['/mnt/disk1', '/mnt/disk2'],
            filesystem='fuse.mergerfs',
            options={'defaults': True}
        )
        self.manager._pool_cache['/mnt/test'] = test_pool
        
        # Test existing pool
        result = self.manager.get_pool_by_mount_point('/mnt/test')
        self.assertEqual(result, test_pool)
        
        # Test non-existing pool
        result = self.manager.get_pool_by_mount_point('/mnt/nonexistent')
        self.assertIsNone(result)
    
    @patch('os.statvfs')
    def test_get_pool_statistics(self, mock_statvfs):
        """Test getting pool statistics."""
        # Setup mock statvfs
        mock_stat = Mock()
        mock_stat.f_blocks = 1000
        mock_stat.f_frsize = 4096
        mock_stat.f_bavail = 600
        mock_statvfs.return_value = mock_stat
        
        # Create test pool
        test_pool = MergerFSPool(
            mount_point='/mnt/test',
            source_paths=['/mnt/disk1'],
            filesystem='fuse.mergerfs',
            options={}
        )
        self.manager._pool_cache['/mnt/test'] = test_pool
        
        # Get statistics
        result = self.manager.get_pool_statistics('/mnt/test')
        
        # Verify calculations
        expected_total = 1000 * 4096  # 4,096,000
        expected_available = 600 * 4096  # 2,457,600
        expected_used = expected_total - expected_available  # 1,638,400
        
        self.assertEqual(result.total_size, expected_total)
        self.assertEqual(result.available_size, expected_available)
        self.assertEqual(result.used_size, expected_used)
        
        mock_statvfs.assert_called_once_with('/mnt/test')
    
    @patch('os.statvfs')
    def test_get_pool_statistics_not_found(self, mock_statvfs):
        """Test getting statistics for non-existent pool."""
        result = self.manager.get_pool_statistics('/mnt/nonexistent')
        self.assertIsNone(result)
        mock_statvfs.assert_not_called()
    
    @patch('os.statvfs')
    def test_get_branch_statistics(self, mock_statvfs):
        """Test getting branch statistics."""
        # Setup mock statvfs to return different values for each call
        def statvfs_side_effect(path):
            mock_stat = Mock()
            if path == '/mnt/disk1':
                mock_stat.f_blocks = 500
                mock_stat.f_frsize = 4096
                mock_stat.f_bavail = 300
            elif path == '/mnt/disk2':
                mock_stat.f_blocks = 800
                mock_stat.f_frsize = 4096
                mock_stat.f_bavail = 200
            return mock_stat
        
        mock_statvfs.side_effect = statvfs_side_effect
        
        # Create test pool
        test_pool = MergerFSPool(
            mount_point='/mnt/test',
            source_paths=['/mnt/disk1', '/mnt/disk2'],
            filesystem='fuse.mergerfs',
            options={}
        )
        self.manager._pool_cache['/mnt/test'] = test_pool
        
        # Get branch statistics
        branch_stats = self.manager.get_branch_statistics('/mnt/test')
        
        # Verify results
        self.assertEqual(len(branch_stats), 2)
        
        # Check first branch
        branch1 = branch_stats[0]
        self.assertEqual(branch1.path, '/mnt/disk1')
        self.assertEqual(branch1.total_size, 500 * 4096)
        self.assertEqual(branch1.available_size, 300 * 4096)
        self.assertEqual(branch1.used_size, (500 - 300) * 4096)
        
        # Check second branch
        branch2 = branch_stats[1]
        self.assertEqual(branch2.path, '/mnt/disk2')
        self.assertEqual(branch2.total_size, 800 * 4096)
        self.assertEqual(branch2.available_size, 200 * 4096)
        self.assertEqual(branch2.used_size, (800 - 200) * 4096)
    
    @patch('subprocess.run')
    def test_get_mergerfsctl_info_available(self, mock_run):
        """Test getting mergerfsctl info when available."""
        # Mock which command success
        mock_run.side_effect = [
            Mock(returncode=0),  # which mergerfsctl
            Mock(returncode=0, stdout="version: 2.35.1\nfuse_version: 3.10.5\n")  # mergerfsctl info
        ]
        
        result = self.manager.get_mergerfsctl_info('/mnt/test')
        
        expected = {
            'version': '2.35.1',
            'fuse_version': '3.10.5'
        }
        self.assertEqual(result, expected)
        
        # Verify calls
        self.assertEqual(mock_run.call_count, 2)
        mock_run.assert_any_call(['which', 'mergerfsctl'], capture_output=True, text=True, timeout=5)
        mock_run.assert_any_call(['mergerfsctl', '-m', '/mnt/test', 'info'], capture_output=True, text=True, timeout=30)
    
    @patch('subprocess.run')
    def test_get_mergerfsctl_info_not_available(self, mock_run):
        """Test getting mergerfsctl info when not available."""
        # Mock which command failure
        mock_run.return_value = Mock(returncode=1)
        
        result = self.manager.get_mergerfsctl_info('/mnt/test')
        self.assertIsNone(result)
        
        mock_run.assert_called_once_with(['which', 'mergerfsctl'], capture_output=True, text=True, timeout=5)
    
    def test_parse_mergerfs_mount(self):
        """Test parsing MergerFS mount line."""
        mount_parts = [
            '/dev/sda1:/dev/sdb1:/dev/sdc1',
            '/mnt/storage',
            'fuse.mergerfs',
            'defaults,allow_other,use_ino,category.create=epmfs,category.search=ff'
        ]
        
        pool = self.manager._parse_mergerfs_mount(mount_parts)
        
        self.assertIsNotNone(pool)
        self.assertEqual(pool.mount_point, '/mnt/storage')
        self.assertEqual(pool.source_paths, ['/dev/sda1', '/dev/sdb1', '/dev/sdc1'])
        self.assertEqual(pool.filesystem, 'fuse.mergerfs')
        self.assertIn('defaults', pool.options)
        self.assertIn('allow_other', pool.options)
        self.assertEqual(pool.options['category.create'], 'epmfs')
        self.assertEqual(pool.options['category.search'], 'ff')
    
    def test_parse_mergerfs_mount_invalid(self):
        """Test parsing invalid mount line."""
        # Test with insufficient parts
        mount_parts = ['/dev/sda1', '/mnt/storage']
        
        pool = self.manager._parse_mergerfs_mount(mount_parts)
        self.assertIsNone(pool)
    
    @patch('subprocess.run')
    def test_is_mergerfs_available(self, mock_run):
        """Test checking if MergerFS is available."""
        # Test when available
        mock_run.return_value = Mock(returncode=0)
        self.assertTrue(self.manager.is_mergerfs_available())
        
        # Test when not available
        mock_run.return_value = Mock(returncode=1)
        self.assertFalse(self.manager.is_mergerfs_available())
        
        # Test when command fails
        mock_run.side_effect = Exception("Command failed")
        self.assertFalse(self.manager.is_mergerfs_available())
    
    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.access')
    def test_validate_source_paths(self, mock_access, mock_isdir, mock_exists):
        """Test validating source paths."""
        # Test empty paths
        is_valid, error = self.manager.validate_source_paths([])
        self.assertFalse(is_valid)
        self.assertIn("At least one source path", error)
        
        # Test valid paths
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_access.return_value = True
        
        is_valid, error = self.manager.validate_source_paths(['/mnt/disk1', '/mnt/disk2'])
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
        
        # Test non-existent path
        mock_exists.side_effect = lambda path: path != '/mnt/nonexistent'
        
        is_valid, error = self.manager.validate_source_paths(['/mnt/disk1', '/mnt/nonexistent'])
        self.assertFalse(is_valid)
        self.assertIn("does not exist", error)
        
        # Test non-directory path
        mock_exists.return_value = True
        mock_isdir.side_effect = lambda path: path != '/mnt/file'
        
        is_valid, error = self.manager.validate_source_paths(['/mnt/disk1', '/mnt/file'])
        self.assertFalse(is_valid)
        self.assertIn("not a directory", error)
        
        # Test non-readable path
        mock_isdir.return_value = True
        mock_access.side_effect = lambda path, mode: path != '/mnt/readonly'
        
        is_valid, error = self.manager.validate_source_paths(['/mnt/disk1', '/mnt/readonly'])
        self.assertFalse(is_valid)
        self.assertIn("not readable", error)
    
    def test_generate_mount_command(self):
        """Test generating MergerFS mount command."""
        source_paths = ['/mnt/disk1', '/mnt/disk2', '/mnt/disk3']
        mount_point = '/mnt/storage'
        
        # Test with default policies
        cmd = self.manager.generate_mount_command(source_paths, mount_point)
        
        expected_source = '/mnt/disk1:/mnt/disk2:/mnt/disk3'
        self.assertEqual(cmd[0], 'mergerfs')
        self.assertEqual(cmd[1], expected_source)
        self.assertEqual(cmd[2], mount_point)
        self.assertEqual(cmd[3], '-o')
        
        # Check options string contains expected policies
        options = cmd[4]
        self.assertIn('defaults', options)
        self.assertIn('allow_other', options)
        self.assertIn('use_ino', options)
        self.assertIn('category.create=epmfs', options)
        self.assertIn('category.search=ff', options)
        self.assertIn('category.action=epall', options)
        
        # Test with custom policies
        custom_policies = {'category.create': 'mfs', 'custom_option': 'value'}
        cmd = self.manager.generate_mount_command(source_paths, mount_point, custom_policies)
        
        options = cmd[4]
        self.assertIn('category.create=mfs', options)
        self.assertIn('custom_option=value', options)
    
    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_mount_pool_success(self, mock_makedirs, mock_exists):
        """Test successful pool mounting."""
        # Setup mocks
        mock_exists.return_value = False  # Mount point doesn't exist
        self.mock_executor.execute_command.return_value = (True, "Mounted successfully", "")
        
        # Mock validation
        with patch.object(self.manager, 'validate_source_paths', return_value=(True, "")):
            with patch.object(self.manager, 'is_mergerfs_available', return_value=True):
                with patch.object(self.manager, 'discover_pools'):
                    success, message = self.manager.mount_pool(['/mnt/disk1'], '/mnt/storage')
        
        self.assertTrue(success)
        self.assertIn("mounted successfully", message)
        mock_makedirs.assert_called_once_with('/mnt/storage', exist_ok=True)
        self.mock_executor.execute_command.assert_called_once()
    
    def test_mount_pool_validation_failure(self):
        """Test pool mounting with validation failure."""
        with patch.object(self.manager, 'validate_source_paths', return_value=(False, "Invalid path")):
            success, message = self.manager.mount_pool(['/invalid'], '/mnt/storage')
        
        self.assertFalse(success)
        self.assertEqual(message, "Invalid path")
        self.mock_executor.execute_command.assert_not_called()
    
    def test_mount_pool_mergerfs_not_available(self):
        """Test pool mounting when MergerFS is not available."""
        with patch.object(self.manager, 'validate_source_paths', return_value=(True, "")):
            with patch.object(self.manager, 'is_mergerfs_available', return_value=False):
                success, message = self.manager.mount_pool(['/mnt/disk1'], '/mnt/storage')
        
        self.assertFalse(success)
        self.assertIn("not available", message)
        self.mock_executor.execute_command.assert_not_called()
    
    def test_unmount_pool_success(self):
        """Test successful pool unmounting."""
        # Setup mock
        self.mock_executor.execute_command.return_value = (True, "Unmounted successfully", "")
        
        # Add pool to cache
        test_pool = MergerFSPool('/mnt/test', ['/mnt/disk1'], 'fuse.mergerfs', {})
        self.manager._pool_cache['/mnt/test'] = test_pool
        
        success, message = self.manager.unmount_pool('/mnt/test')
        
        self.assertTrue(success)
        self.assertIn("unmounted successfully", message)
        self.assertNotIn('/mnt/test', self.manager._pool_cache)
        
        # Verify command
        expected_cmd = ['umount', '/mnt/test']
        self.mock_executor.execute_command.assert_called_once_with(expected_cmd)
    
    def test_unmount_pool_force(self):
        """Test force unmounting pool."""
        self.mock_executor.execute_command.return_value = (True, "Force unmounted", "")
        
        success, message = self.manager.unmount_pool('/mnt/test', force=True)
        
        self.assertTrue(success)
        
        # Verify force flag is used
        expected_cmd = ['umount', '-f', '/mnt/test']
        self.mock_executor.execute_command.assert_called_once_with(expected_cmd)
    
    def test_unmount_pool_failure(self):
        """Test failed pool unmounting."""
        self.mock_executor.execute_command.return_value = (False, "", "Device busy")
        
        success, message = self.manager.unmount_pool('/mnt/test')
        
        self.assertFalse(success)
        self.assertIn("Device busy", message)
    
    def test_to_dict(self):
        """Test converting MergerFSPool to dictionary."""
        pool = MergerFSPool(
            mount_point='/mnt/storage',
            source_paths=['/mnt/disk1', '/mnt/disk2'],
            filesystem='fuse.mergerfs',
            options={'defaults': True, 'allow_other': True},
            total_size=1000000,
            used_size=600000,
            available_size=400000
        )
        
        result = self.manager.to_dict(pool)
        
        expected = {
            'mount_point': '/mnt/storage',
            'source_paths': ['/mnt/disk1', '/mnt/disk2'],
            'filesystem': 'fuse.mergerfs',
            'options': {'defaults': True, 'allow_other': True},
            'total_size': 1000000,
            'used_size': 600000,
            'available_size': 400000,
            'usage_percent': 60.0
        }
        
        self.assertEqual(result, expected)
    
    def test_branch_stats_to_dict(self):
        """Test converting branch statistics to dictionary list."""
        branch_stats = [
            MergerFSBranchStats('/mnt/disk1', 500000, 300000, 200000),
            MergerFSBranchStats('/mnt/disk2', 800000, 600000, 200000)
        ]
        
        result = self.manager.branch_stats_to_dict(branch_stats)
        
        expected = [
            {
                'path': '/mnt/disk1',
                'total_size': 500000,
                'used_size': 300000,
                'available_size': 200000,
                'usage_percent': 60.0
            },
            {
                'path': '/mnt/disk2',
                'total_size': 800000,
                'used_size': 600000,
                'available_size': 200000,
                'usage_percent': 75.0
            }
        ]
        
        self.assertEqual(result, expected)


class TestMergerFSPool(unittest.TestCase):
    """Test cases for MergerFSPool class."""
    
    def test_usage_percent(self):
        """Test usage percentage calculation."""
        # Test normal case
        pool = MergerFSPool('/mnt/test', [], 'fuse.mergerfs', {}, 1000, 600, 400)
        self.assertEqual(pool.usage_percent, 60.0)
        
        # Test zero total size
        pool = MergerFSPool('/mnt/test', [], 'fuse.mergerfs', {}, 0, 0, 0)
        self.assertEqual(pool.usage_percent, 0.0)


class TestMergerFSBranchStats(unittest.TestCase):
    """Test cases for MergerFSBranchStats class."""
    
    def test_usage_percent(self):
        """Test usage percentage calculation."""
        # Test normal case
        stats = MergerFSBranchStats('/mnt/disk1', 1000, 750, 250)
        self.assertEqual(stats.usage_percent, 75.0)
        
        # Test zero total size
        stats = MergerFSBranchStats('/mnt/disk1', 0, 0, 0)
        self.assertEqual(stats.usage_percent, 0.0)


class TestMergerFSConfigurationManagement(unittest.TestCase):
    """Test cases for MergerFS configuration management."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_executor = Mock(spec=SystemCommandExecutor)
        self.manager = MergerFSManager(self.mock_executor)
    
    def test_generate_fstab_entry(self):
        """Test generating fstab entry."""
        source_paths = ['/mnt/disk1', '/mnt/disk2']
        mount_point = '/mnt/storage'
        
        entry = self.manager.generate_fstab_entry(source_paths, mount_point)
        
        expected_source = '/mnt/disk1:/mnt/disk2'
        self.assertIn(expected_source, entry)
        self.assertIn(mount_point, entry)
        self.assertIn('fuse.mergerfs', entry)
        self.assertIn('category.create=epmfs', entry)
        self.assertIn('category.search=ff', entry)
        self.assertIn('category.action=epall', entry)
    
    def test_generate_fstab_entry_custom_policies(self):
        """Test generating fstab entry with custom policies."""
        source_paths = ['/mnt/disk1']
        mount_point = '/mnt/test'
        policies = {'category.create': 'mfs', 'custom_option': 'value'}
        
        entry = self.manager.generate_fstab_entry(source_paths, mount_point, policies)
        
        self.assertIn('category.create=mfs', entry)
        self.assertIn('custom_option=value', entry)
    
    @patch('shutil.copy2')
    @patch('datetime.datetime')
    def test_update_fstab(self, mock_datetime, mock_copy):
        """Test updating fstab with MergerFS entry."""
        # Mock datetime for backup filename
        mock_datetime.now.return_value.strftime.return_value = '20240101_120000'
        
        source_paths = ['/mnt/disk1', '/mnt/disk2']
        mount_point = '/mnt/storage'
        
        # Mock file operations
        original_content = "# fstab\n/dev/sda1 / ext4 defaults 0 1\n"
        
        with patch('builtins.open', mock_open(read_data=original_content)) as mock_file:
            success, message = self.manager.update_fstab(source_paths, mount_point)
            
            self.assertTrue(success)
            self.assertIn("Successfully updated", message)
            
            # Verify backup was created
            mock_copy.assert_called_once_with('/etc/fstab', '/etc/fstab.backup_20240101_120000')
            
            # Verify file was written with new entry
            # Get the write calls (should be the second call after read)
            write_calls = [call for call in mock_file.call_args_list if call[0][1] == 'w']
            self.assertEqual(len(write_calls), 1)
            
            # Get the writelines call
            handle = mock_file.return_value
            writelines_calls = handle.writelines.call_args_list
            self.assertEqual(len(writelines_calls), 1)
            
            # Check the content that was written
            written_lines = writelines_calls[0][0][0]  # First arg of first call
            written_content = ''.join(written_lines)
            self.assertIn('/mnt/disk1:/mnt/disk2', written_content)
            self.assertIn('/mnt/storage', written_content)
    
    @patch('builtins.open', new_callable=mock_open, read_data="# fstab\n/mnt/disk1:/mnt/disk2 /mnt/storage fuse.mergerfs defaults 0 0\n")
    @patch('shutil.copy2')
    def test_remove_fstab_entry(self, mock_copy, mock_file):
        """Test removing fstab entry."""
        mount_point = '/mnt/storage'
        
        success, message = self.manager.remove_fstab_entry(mount_point)
        
        self.assertTrue(success)
        self.assertIn("Successfully removed", message)
        
        # Verify backup was created
        mock_copy.assert_called_once()
        
        # Verify entry was removed
        handle = mock_file()
        written_content = ''.join(call.args[0] for call in handle.write.call_args_list)
        self.assertNotIn('/mnt/storage', written_content)
    
    def test_generate_systemd_mount_unit(self):
        """Test generating systemd mount unit content."""
        source_paths = ['/mnt/disk1', '/mnt/disk2']
        mount_point = '/mnt/storage'
        
        unit_content = self.manager.generate_systemd_mount_unit(source_paths, mount_point)
        
        self.assertIn('[Unit]', unit_content)
        self.assertIn('[Mount]', unit_content)
        self.assertIn('[Install]', unit_content)
        self.assertIn('What=/mnt/disk1:/mnt/disk2', unit_content)
        self.assertIn('Where=/mnt/storage', unit_content)
        self.assertIn('Type=fuse.mergerfs', unit_content)
        self.assertIn('category.create=epmfs', unit_content)
    
    @patch('builtins.open', new_callable=mock_open)
    def test_create_systemd_mount_unit(self, mock_file):
        """Test creating systemd mount unit file."""
        source_paths = ['/mnt/disk1']
        mount_point = '/mnt/storage'
        
        # Mock successful systemctl commands
        self.mock_executor.execute_command.return_value = (True, "", "")
        
        success, message = self.manager.create_systemd_mount_unit(source_paths, mount_point)
        
        self.assertTrue(success)
        self.assertIn("Successfully created", message)
        
        # Verify file was written
        mock_file.assert_called_with('/etc/systemd/system/mnt-storage.mount', 'w')
        
        # Verify systemctl commands were called
        self.assertEqual(self.mock_executor.execute_command.call_count, 2)
        calls = self.mock_executor.execute_command.call_args_list
        self.assertEqual(calls[0][0][0], ['systemctl', 'daemon-reload'])
        self.assertEqual(calls[1][0][0], ['systemctl', 'enable', 'mnt-storage.mount'])
    
    @patch('os.path.exists')
    @patch('os.remove')
    def test_remove_systemd_mount_unit(self, mock_remove, mock_exists):
        """Test removing systemd mount unit."""
        mount_point = '/mnt/storage'
        mock_exists.return_value = True
        
        # Mock successful systemctl commands
        self.mock_executor.execute_command.return_value = (True, "", "")
        
        success, message = self.manager.remove_systemd_mount_unit(mount_point)
        
        self.assertTrue(success)
        self.assertIn("Successfully removed", message)
        
        # Verify file was removed
        mock_remove.assert_called_once_with('/etc/systemd/system/mnt-storage.mount')
        
        # Verify systemctl commands were called
        self.assertEqual(self.mock_executor.execute_command.call_count, 3)
        calls = self.mock_executor.execute_command.call_args_list
        self.assertEqual(calls[0][0][0], ['systemctl', 'stop', 'mnt-storage.mount'])
        self.assertEqual(calls[1][0][0], ['systemctl', 'disable', 'mnt-storage.mount'])
        self.assertEqual(calls[2][0][0], ['systemctl', 'daemon-reload'])
    
    @patch.dict(os.environ, {'MERGERFS_POLICY_CREATE': 'mfs', 'MERGERFS_POLICY_SEARCH': 'epall'})
    def test_get_policies_from_env(self):
        """Test getting policies from environment variables."""
        policies = self.manager.get_policies_from_env()
        
        expected = {
            'category.create': 'mfs',      # From environment
            'category.search': 'epall',    # From environment
            'category.action': 'epall'     # Default value
        }
        
        self.assertEqual(policies, expected)
    
    def test_get_policy_from_env(self):
        """Test getting individual policy from environment."""
        with patch.dict(os.environ, {'MERGERFS_POLICY_CREATE': 'test_value'}):
            value = self.manager.get_policy_from_env('create', 'default')
            self.assertEqual(value, 'test_value')
        
        # Test default value when not set
        value = self.manager.get_policy_from_env('nonexistent', 'default')
        self.assertEqual(value, 'default')
    
    def test_generate_config_from_drives(self):
        """Test generating configuration from drive list."""
        from nas.models import DriveConfig, DriveRole, HealthStatus
        
        drives = [
            DriveConfig('/dev/sda1', 'uuid1', '/mnt/disk1', 'ext4', DriveRole.DATA, 1000, 500, HealthStatus.HEALTHY),
            DriveConfig('/dev/sdb1', 'uuid2', '/mnt/disk2', 'ext4', DriveRole.DATA, 2000, 800, HealthStatus.HEALTHY),
            DriveConfig('/dev/sdc1', 'uuid3', '/mnt/parity1', 'ext4', DriveRole.PARITY, 3000, 1000, HealthStatus.HEALTHY)
        ]
        
        success, message, config = self.manager.generate_config_from_drives(drives)
        
        self.assertTrue(success)
        self.assertIn("2 data drives", message)
        
        # Verify configuration
        self.assertEqual(config['source_paths'], ['/mnt/disk1', '/mnt/disk2'])
        self.assertEqual(config['mount_point'], '/mnt/storage')
        self.assertIn('policies', config)
        self.assertIn('fstab_entry', config)
        self.assertIn('systemd_unit_content', config)
        self.assertIn('mount_command', config)
    
    def test_generate_config_from_drives_no_data_drives(self):
        """Test generating configuration with no data drives."""
        from nas.models import DriveConfig, DriveRole, HealthStatus
        
        drives = [
            DriveConfig('/dev/sdc1', 'uuid3', '/mnt/parity1', 'ext4', DriveRole.PARITY, 3000, 1000, HealthStatus.HEALTHY)
        ]
        
        success, message, config = self.manager.generate_config_from_drives(drives)
        
        self.assertFalse(success)
        self.assertIn("No data drives", message)
        self.assertEqual(config, {})


class TestMergerFSPoolExpansion(unittest.TestCase):
    """Test cases for MergerFS pool expansion functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_executor = Mock(spec=SystemCommandExecutor)
        self.manager = MergerFSManager(self.mock_executor)
        
        # Create test pool in cache
        self.test_pool = MergerFSPool(
            mount_point='/mnt/storage',
            source_paths=['/mnt/disk1', '/mnt/disk2'],
            filesystem='fuse.mergerfs',
            options={'category.create': 'epmfs', 'category.search': 'ff'}
        )
        self.manager._pool_cache['/mnt/storage'] = self.test_pool
    
    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.access')
    def test_expand_pool_success(self, mock_access, mock_isdir, mock_exists):
        """Test successful pool expansion."""
        # Mock validation
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_access.return_value = True
        
        # Mock successful commands
        self.mock_executor.execute_command.return_value = (True, "", "")
        
        # Mock MergerFS availability and other methods
        with patch.object(self.manager, 'is_mergerfs_available', return_value=True):
            with patch.object(self.manager, 'discover_pools'):
                success, message = self.manager.expand_pool('/mnt/storage', ['/mnt/disk3'])
        
        self.assertTrue(success)
        self.assertIn("Successfully expanded", message)
        
        # Verify unmount and mount commands were called
        self.assertEqual(self.mock_executor.execute_command.call_count, 2)
        calls = self.mock_executor.execute_command.call_args_list
        
        # Check unmount command
        unmount_cmd = calls[0][0][0]
        self.assertEqual(unmount_cmd[0], 'umount')
        self.assertIn('/mnt/storage', unmount_cmd)
        
        # Check mount command
        mount_cmd = calls[1][0][0]
        self.assertEqual(mount_cmd[0], 'mergerfs')
        self.assertIn('/mnt/disk1:/mnt/disk2:/mnt/disk3', mount_cmd[1])
    
    def test_expand_pool_no_existing_pool(self):
        """Test expansion when no existing pool found."""
        success, message = self.manager.expand_pool('/mnt/nonexistent', ['/mnt/disk3'])
        
        self.assertFalse(success)
        self.assertIn("No existing pool found", message)
        self.mock_executor.execute_command.assert_not_called()
    
    @patch('os.path.exists')
    def test_expand_pool_invalid_new_paths(self, mock_exists):
        """Test expansion with invalid new source paths."""
        mock_exists.return_value = False
        
        success, message = self.manager.expand_pool('/mnt/storage', ['/mnt/invalid'])
        
        self.assertFalse(success)
        self.assertIn("Invalid new source paths", message)
        self.mock_executor.execute_command.assert_not_called()
    
    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.access')
    def test_expand_pool_duplicate_paths(self, mock_access, mock_isdir, mock_exists):
        """Test expansion with duplicate source paths."""
        # Mock validation to pass so we can test duplicate check
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_access.return_value = True
        
        success, message = self.manager.expand_pool('/mnt/storage', ['/mnt/disk1'])
        
        self.assertFalse(success)
        self.assertIn("Duplicate source paths", message)
        self.mock_executor.execute_command.assert_not_called()
    
    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.access')
    def test_expand_pool_unmount_failure(self, mock_access, mock_isdir, mock_exists):
        """Test expansion when unmount fails."""
        # Mock validation
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_access.return_value = True
        
        # Mock failed unmount
        self.mock_executor.execute_command.return_value = (False, "", "Device busy")
        
        success, message = self.manager.expand_pool('/mnt/storage', ['/mnt/disk3'])
        
        self.assertFalse(success)
        self.assertIn("Failed to unmount", message)
        
        # Only unmount should be called
        self.assertEqual(self.mock_executor.execute_command.call_count, 1)
    
    @patch('os.path.exists')
    @patch('os.path.isdir')
    @patch('os.access')
    def test_expand_pool_mount_failure_with_restore(self, mock_access, mock_isdir, mock_exists):
        """Test expansion when mount fails and original pool is restored."""
        # Mock validation
        mock_exists.return_value = True
        mock_isdir.return_value = True
        mock_access.return_value = True
        
        # Mock successful unmount, failed mount, successful restore
        self.mock_executor.execute_command.side_effect = [
            (True, "", ""),      # unmount success
            (False, "", "Mount failed"),  # mount failure
            (True, "", "")       # restore success
        ]
        
        # Mock MergerFS availability and other methods
        with patch.object(self.manager, 'is_mergerfs_available', return_value=True):
            with patch.object(self.manager, 'discover_pools'):
                success, message = self.manager.expand_pool('/mnt/storage', ['/mnt/disk3'])
        
        self.assertFalse(success)
        self.assertIn("expansion failed", message.lower())
        self.assertIn("restored", message.lower())
        
        # Unmount, failed mount, restore mount should be called
        self.assertEqual(self.mock_executor.execute_command.call_count, 3)
    
    @patch('os.path.exists')
    @patch('os.access')
    def test_validate_pool_integrity_success(self, mock_access, mock_exists):
        """Test successful pool integrity validation."""
        # Mock all paths exist and are accessible
        mock_exists.return_value = True
        mock_access.return_value = True
        
        # Mock pool statistics
        with patch.object(self.manager, 'get_pool_statistics') as mock_stats:
            mock_pool = MergerFSPool('/mnt/storage', ['/mnt/disk1'], 'fuse.mergerfs', {}, 1000, 500, 500)
            mock_stats.return_value = mock_pool
            
            is_valid, message, details = self.manager.validate_pool_integrity('/mnt/storage')
        
        self.assertTrue(is_valid)
        self.assertIn("validation passed", message)
        self.assertTrue(details['mount_point_accessible'])
        self.assertTrue(details['all_sources_accessible'])
        self.assertTrue(details['pool_statistics_available'])
        self.assertEqual(details['accessible_sources'], 2)
        self.assertEqual(details['total_sources'], 2)
    
    @patch('os.path.exists')
    @patch('os.access')
    def test_validate_pool_integrity_inaccessible_sources(self, mock_access, mock_exists):
        """Test pool integrity validation with inaccessible sources."""
        # Mock mount point exists and is accessible
        def exists_side_effect(path):
            if path == '/mnt/storage':
                return True
            elif path == '/mnt/disk2':
                return False  # Second disk doesn't exist
            else:
                return True
        
        def access_side_effect(path, mode):
            return path != '/mnt/disk2'
        
        mock_exists.side_effect = exists_side_effect
        mock_access.side_effect = access_side_effect
        
        is_valid, message, details = self.manager.validate_pool_integrity('/mnt/storage')
        
        self.assertFalse(is_valid)
        self.assertIn("source paths not accessible", message)
        self.assertEqual(details['accessible_sources'], 1)
        self.assertEqual(details['total_sources'], 2)
        self.assertIn('/mnt/disk2', details['inaccessible_sources'])
    
    def test_validate_pool_integrity_no_pool(self):
        """Test pool integrity validation when pool doesn't exist."""
        is_valid, message, details = self.manager.validate_pool_integrity('/mnt/nonexistent')
        
        self.assertFalse(is_valid)
        self.assertIn("Pool not found", message)
        self.assertEqual(details['total_sources'], 0)
    
    def test_auto_expand_pool_with_drives(self):
        """Test automatic pool expansion with new drives."""
        from nas.models import DriveConfig, DriveRole, HealthStatus
        
        # Create available drives including new ones
        drives = [
            DriveConfig('/dev/sda1', 'uuid1', '/mnt/disk1', 'ext4', DriveRole.DATA, 1000, 500, HealthStatus.HEALTHY),
            DriveConfig('/dev/sdb1', 'uuid2', '/mnt/disk2', 'ext4', DriveRole.DATA, 2000, 800, HealthStatus.HEALTHY),
            DriveConfig('/dev/sdc1', 'uuid3', '/mnt/disk3', 'ext4', DriveRole.DATA, 3000, 1000, HealthStatus.HEALTHY),  # New
            DriveConfig('/dev/sdd1', 'uuid4', '/mnt/parity1', 'ext4', DriveRole.PARITY, 4000, 1500, HealthStatus.HEALTHY)
        ]
        
        # Mock successful expansion
        with patch.object(self.manager, 'expand_pool', return_value=(True, "Expanded successfully")):
            success, message = self.manager.auto_expand_pool_with_drives('/mnt/storage', drives)
        
        self.assertTrue(success)
        self.assertIn("Auto-expanded", message)
        self.assertIn("/mnt/disk3", message)
    
    def test_auto_expand_pool_no_new_drives(self):
        """Test automatic expansion when no new drives are available."""
        from nas.models import DriveConfig, DriveRole, HealthStatus
        
        # Only existing drives
        drives = [
            DriveConfig('/dev/sda1', 'uuid1', '/mnt/disk1', 'ext4', DriveRole.DATA, 1000, 500, HealthStatus.HEALTHY),
            DriveConfig('/dev/sdb1', 'uuid2', '/mnt/disk2', 'ext4', DriveRole.DATA, 2000, 800, HealthStatus.HEALTHY)
        ]
        
        success, message = self.manager.auto_expand_pool_with_drives('/mnt/storage', drives)
        
        self.assertTrue(success)
        self.assertIn("No new drives", message)
    
    def test_create_expansion_workflow(self):
        """Test creating expansion workflow plan."""
        new_paths = ['/mnt/disk3', '/mnt/disk4']
        
        workflow = self.manager.create_expansion_workflow('/mnt/storage', new_paths)
        
        self.assertEqual(workflow['mount_point'], '/mnt/storage')
        self.assertEqual(workflow['new_source_paths'], new_paths)
        self.assertEqual(workflow['current_source_paths'], ['/mnt/disk1', '/mnt/disk2'])
        self.assertEqual(workflow['final_source_paths'], ['/mnt/disk1', '/mnt/disk2', '/mnt/disk3', '/mnt/disk4'])
        
        # Check workflow steps
        self.assertEqual(len(workflow['steps']), 7)
        self.assertTrue(any(step['action'] == 'Validate new source paths' for step in workflow['steps']))
        self.assertTrue(any(step['action'] == 'Mount expanded pool' for step in workflow['steps']))
        
        # Check rollback plan and validation checks exist
        self.assertIn('rollback_plan', workflow)
        self.assertIn('validation_checks', workflow)
        self.assertTrue(len(workflow['rollback_plan']) > 0)
        self.assertTrue(len(workflow['validation_checks']) > 0)


if __name__ == '__main__':
    unittest.main()