"""Unit tests for ConfigManager."""

import unittest
import tempfile
import os
import json
from unittest.mock import patch, mock_open

from nas.config_manager import ConfigManager, NASConfig


class TestConfigManager(unittest.TestCase):
    """Test cases for ConfigManager class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config_manager = ConfigManager()
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_default_config_creation(self):
        """Test creation of default configuration."""
        config = NASConfig()
        
        self.assertEqual(config.snapraid_config_path, "/etc/snapraid.conf")
        self.assertEqual(config.pool_mount_point, "/mnt/storage")
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.max_command_timeout, 300)
        self.assertTrue(config.enable_smart_monitoring)
        self.assertIsInstance(config.mergerfs_mount_points, list)
        self.assertIsInstance(config.smart_test_intervals, dict)
    
    def test_config_post_init(self):
        """Test configuration post-initialization."""
        config = NASConfig()
        
        # Check default values are set
        self.assertIn("/mnt/disk1", config.mergerfs_mount_points)
        self.assertEqual(config.smart_test_intervals["short"], 24)
        self.assertEqual(config.smart_test_intervals["long"], 168)
        self.assertIsInstance(config.data_drive_paths, list)
        self.assertIsInstance(config.parity_drive_paths, list)
    
    @patch.dict(os.environ, {
        'SNAPRAID_CONFIG_PATH': '/custom/snapraid.conf',
        'LOG_LEVEL': 'DEBUG',
        'MAX_COMMAND_TIMEOUT': '600',
        'ENABLE_SMART_MONITORING': 'false'
    })
    def test_load_from_environment(self):
        """Test loading configuration from environment variables."""
        config = self.config_manager.load_config()
        
        self.assertEqual(config.snapraid_config_path, '/custom/snapraid.conf')
        self.assertEqual(config.log_level, 'DEBUG')
        self.assertEqual(config.max_command_timeout, 600)
        self.assertFalse(config.enable_smart_monitoring)
    
    @patch.dict(os.environ, {
        'MERGERFS_MOUNT_POINTS': '/mnt/disk1,/mnt/disk2,/mnt/disk3',
        'DATA_DRIVE_PATHS': '/dev/sdb1,/dev/sdc1',
        'PARITY_DRIVE_PATHS': '/dev/sdd1'
    })
    def test_load_list_values_from_environment(self):
        """Test loading list values from environment variables."""
        config = self.config_manager.load_config()
        
        expected_mount_points = ['/mnt/disk1', '/mnt/disk2', '/mnt/disk3']
        expected_data_paths = ['/dev/sdb1', '/dev/sdc1']
        expected_parity_paths = ['/dev/sdd1']
        
        self.assertEqual(config.mergerfs_mount_points, expected_mount_points)
        self.assertEqual(config.data_drive_paths, expected_data_paths)
        self.assertEqual(config.parity_drive_paths, expected_parity_paths)
    
    @patch.dict(os.environ, {
        'SMART_TEST_INTERVALS': '{"short": 12, "long": 72}'
    })
    def test_load_json_values_from_environment(self):
        """Test loading JSON values from environment variables."""
        config = self.config_manager.load_config()
        
        expected_intervals = {"short": 12, "long": 72}
        self.assertEqual(config.smart_test_intervals, expected_intervals)
    
    @patch.dict(os.environ, {
        'SMART_TEST_INTERVALS': 'invalid-json'
    })
    def test_load_invalid_json_from_environment(self):
        """Test handling of invalid JSON in environment variables."""
        config = self.config_manager.load_config()
        
        # Should fall back to default
        expected_intervals = {"short": 24, "long": 168}
        self.assertEqual(config.smart_test_intervals, expected_intervals)
    
    def test_parse_boolean_env_values(self):
        """Test parsing of boolean environment values."""
        test_cases = [
            ('true', True),
            ('True', True),
            ('1', True),
            ('yes', True),
            ('on', True),
            ('false', False),
            ('False', False),
            ('0', False),
            ('no', False),
            ('off', False),
            ('invalid', False)
        ]
        
        for env_value, expected in test_cases:
            with self.subTest(env_value=env_value):
                result = self.config_manager._parse_env_value('ENABLE_SMART_MONITORING', env_value)
                self.assertEqual(result, expected)
    
    def test_parse_integer_env_values(self):
        """Test parsing of integer environment values."""
        # Valid integer
        result = self.config_manager._parse_env_value('MAX_COMMAND_TIMEOUT', '600')
        self.assertEqual(result, 600)
        
        # Invalid integer - should return default
        result = self.config_manager._parse_env_value('MAX_COMMAND_TIMEOUT', 'invalid')
        self.assertEqual(result, 300)
    
    def test_save_config_json(self):
        """Test saving configuration as JSON file."""
        config = NASConfig(
            snapraid_config_path='/test/snapraid.conf',
            log_level='DEBUG'
        )
        
        json_file = os.path.join(self.temp_dir, 'config.json')
        success = self.config_manager.save_config(config, json_file)
        
        self.assertTrue(success)
        self.assertTrue(os.path.exists(json_file))
        
        # Verify content
        with open(json_file, 'r') as f:
            saved_data = json.load(f)
        
        self.assertEqual(saved_data['snapraid_config_path'], '/test/snapraid.conf')
        self.assertEqual(saved_data['log_level'], 'DEBUG')
    
    def test_save_config_env(self):
        """Test saving configuration as environment file."""
        config = NASConfig(
            snapraid_config_path='/test/snapraid.conf',
            log_level='DEBUG',
            enable_smart_monitoring=False
        )
        
        env_file = os.path.join(self.temp_dir, 'config.env')
        success = self.config_manager.save_config(config, env_file)
        
        self.assertTrue(success)
        self.assertTrue(os.path.exists(env_file))
        
        # Verify content
        with open(env_file, 'r') as f:
            content = f.read()
        
        self.assertIn('SNAPRAID_CONFIG_PATH=/test/snapraid.conf', content)
        self.assertIn('LOG_LEVEL=DEBUG', content)
        self.assertIn('ENABLE_SMART_MONITORING=false', content)
    
    def test_load_config_file_json(self):
        """Test loading configuration from JSON file."""
        config_data = {
            'snapraid_config_path': '/test/snapraid.conf',
            'log_level': 'DEBUG',
            'max_command_timeout': 600
        }
        
        json_file = os.path.join(self.temp_dir, 'config.json')
        with open(json_file, 'w') as f:
            json.dump(config_data, f)
        
        config_manager = ConfigManager(json_file)
        config = config_manager.load_config()
        
        self.assertEqual(config.snapraid_config_path, '/test/snapraid.conf')
        self.assertEqual(config.log_level, 'DEBUG')
        self.assertEqual(config.max_command_timeout, 600)
    
    def test_load_config_file_env(self):
        """Test loading configuration from environment file."""
        env_content = """# Test config
SNAPRAID_CONFIG_PATH=/test/snapraid.conf
LOG_LEVEL=DEBUG
MAX_COMMAND_TIMEOUT=600
ENABLE_SMART_MONITORING=false
"""
        
        env_file = os.path.join(self.temp_dir, 'config.env')
        with open(env_file, 'w') as f:
            f.write(env_content)
        
        config_manager = ConfigManager(env_file)
        config = config_manager.load_config()
        
        self.assertEqual(config.snapraid_config_path, '/test/snapraid.conf')
        self.assertEqual(config.log_level, 'DEBUG')
        self.assertEqual(config.max_command_timeout, 600)
        self.assertFalse(config.enable_smart_monitoring)
    
    def test_get_config_value(self):
        """Test getting specific configuration values."""
        with patch.dict(os.environ, {'LOG_LEVEL': 'DEBUG'}):
            value = self.config_manager.get_config_value('log_level')
            self.assertEqual(value, 'DEBUG')
            
            # Test default value
            value = self.config_manager.get_config_value('nonexistent', 'default')
            self.assertEqual(value, 'default')
    
    def test_set_config_value(self):
        """Test setting specific configuration values."""
        # Load initial config
        config = self.config_manager.load_config()
        original_log_level = config.log_level
        
        # Set new value
        success = self.config_manager.set_config_value('log_level', 'ERROR')
        self.assertTrue(success)
        
        # Verify change
        new_value = self.config_manager.get_config_value('log_level')
        self.assertEqual(new_value, 'ERROR')
        
        # Test invalid key
        success = self.config_manager.set_config_value('invalid_key', 'value')
        self.assertFalse(success)
    
    def test_validate_paths(self):
        """Test path validation functionality."""
        with patch('os.path.exists') as mock_exists:
            # Mock some paths as existing, others as not
            def exists_side_effect(path):
                return path in ['/mnt/disk1', '/mnt/storage']
            
            mock_exists.side_effect = exists_side_effect
            
            results = self.config_manager.validate_paths()
            
            # Check that validation results are returned
            self.assertIsInstance(results, dict)
            self.assertIn('pool_mount_point', results)
    
    def test_config_validation_positive(self):
        """Test configuration validation with valid config."""
        config = NASConfig(
            max_command_timeout=300,
            log_level='INFO',
            smart_test_intervals={'short': 24, 'long': 168}
        )
        
        # Should not raise exception
        self.config_manager._validate_config(config)
    
    def test_config_validation_invalid_timeout(self):
        """Test configuration validation with invalid timeout."""
        config = NASConfig(max_command_timeout=0)
        
        with self.assertRaises(ValueError) as context:
            self.config_manager._validate_config(config)
        
        self.assertIn("max_command_timeout must be positive", str(context.exception))
    
    def test_config_validation_invalid_log_level(self):
        """Test configuration validation with invalid log level."""
        config = NASConfig(log_level='INVALID')
        
        with self.assertRaises(ValueError) as context:
            self.config_manager._validate_config(config)
        
        self.assertIn("Invalid log level", str(context.exception))
    
    def test_config_validation_invalid_smart_intervals(self):
        """Test configuration validation with invalid SMART intervals."""
        config = NASConfig(smart_test_intervals={'short': -1})
        
        with self.assertRaises(ValueError) as context:
            self.config_manager._validate_config(config)
        
        self.assertIn("Invalid SMART test interval", str(context.exception))
    
    def test_config_validation_relative_paths(self):
        """Test configuration validation with relative paths."""
        config = NASConfig(snapraid_config_path='relative/path')
        
        with self.assertRaises(ValueError) as context:
            self.config_manager._validate_config(config)
        
        self.assertIn("Path must be absolute", str(context.exception))
    
    def test_format_env_value(self):
        """Test formatting values for environment file output."""
        # Test list
        result = self.config_manager._format_env_value(['/mnt/disk1', '/mnt/disk2'])
        self.assertEqual(result, '/mnt/disk1,/mnt/disk2')
        
        # Test dict
        result = self.config_manager._format_env_value({'short': 24, 'long': 168})
        self.assertEqual(result, '{"short": 24, "long": 168}')
        
        # Test boolean
        result = self.config_manager._format_env_value(True)
        self.assertEqual(result, 'true')
        
        result = self.config_manager._format_env_value(False)
        self.assertEqual(result, 'false')
        
        # Test string
        result = self.config_manager._format_env_value('test')
        self.assertEqual(result, 'test')
    
    def test_config_caching(self):
        """Test configuration caching behavior."""
        # First load
        config1 = self.config_manager.load_config()
        
        # Second load should use cache
        config2 = self.config_manager.load_config()
        
        self.assertIs(config1, config2)  # Should be same object
        
        # Reload should create new object
        config3 = self.config_manager.reload_config()
        
        self.assertIsNot(config1, config3)  # Should be different objects


if __name__ == '__main__':
    unittest.main()