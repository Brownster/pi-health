"""Configuration management system for NAS operations."""

import os
import json
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum


logger = logging.getLogger(__name__)


class ConfigFormat(Enum):
    """Supported configuration file formats."""
    JSON = "json"
    ENV = "env"


@dataclass
class NASConfig:
    """NAS configuration data structure."""
    snapraid_config_path: str = "/etc/snapraid.conf"
    mergerfs_mount_points: List[str] = None
    smart_test_intervals: Dict[str, int] = None
    data_drive_paths: List[str] = None
    parity_drive_paths: List[str] = None
    pool_mount_point: str = "/mnt/storage"
    log_level: str = "INFO"
    max_command_timeout: int = 300
    enable_smart_monitoring: bool = True
    snapraid_sync_schedule: str = "0 2 * * *"  # Daily at 2 AM
    snapraid_scrub_schedule: str = "0 3 * * 0"  # Weekly on Sunday at 3 AM
    
    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.mergerfs_mount_points is None:
            self.mergerfs_mount_points = ["/mnt/disk1", "/mnt/disk2", "/mnt/disk4", "/mnt/disk5"]
        
        if self.smart_test_intervals is None:
            self.smart_test_intervals = {
                "short": 24,  # Hours
                "long": 168   # Hours (weekly)
            }
        
        if self.data_drive_paths is None:
            self.data_drive_paths = []
        
        if self.parity_drive_paths is None:
            self.parity_drive_paths = []


class ConfigManager:
    """Manages configuration loading, validation, and persistence."""
    
    # Environment variable mappings
    ENV_MAPPINGS = {
        'SNAPRAID_CONFIG_PATH': 'snapraid_config_path',
        'MERGERFS_MOUNT_POINTS': 'mergerfs_mount_points',
        'SMART_TEST_INTERVALS': 'smart_test_intervals',
        'DATA_DRIVE_PATHS': 'data_drive_paths',
        'PARITY_DRIVE_PATHS': 'parity_drive_paths',
        'POOL_MOUNT_POINT': 'pool_mount_point',
        'LOG_LEVEL': 'log_level',
        'MAX_COMMAND_TIMEOUT': 'max_command_timeout',
        'ENABLE_SMART_MONITORING': 'enable_smart_monitoring',
        'SNAPRAID_SYNC_SCHEDULE': 'snapraid_sync_schedule',
        'SNAPRAID_SCRUB_SCHEDULE': 'snapraid_scrub_schedule'
    }
    
    def __init__(self, config_file_path: Optional[str] = None):
        """
        Initialize the ConfigManager.
        
        Args:
            config_file_path: Optional path to configuration file
        """
        self.config_file_path = config_file_path
        self._config: Optional[NASConfig] = None
        self._config_cache_valid = False
    
    def load_config(self) -> NASConfig:
        """
        Load configuration from environment variables and config file.
        
        Returns:
            NASConfig object with loaded configuration
        """
        if self._config_cache_valid and self._config:
            return self._config
        
        # Start with default configuration
        config_dict = asdict(NASConfig())
        
        # Load from config file if specified
        if self.config_file_path and os.path.exists(self.config_file_path):
            file_config = self._load_config_file(self.config_file_path)
            config_dict.update(file_config)
        
        # Override with environment variables
        env_config = self._load_from_environment()
        config_dict.update(env_config)
        
        # Create and validate configuration
        self._config = NASConfig(**config_dict)
        self._validate_config(self._config)
        
        self._config_cache_valid = True
        logger.info("Configuration loaded successfully")
        
        return self._config
    
    def save_config(self, config: NASConfig, file_path: Optional[str] = None) -> bool:
        """
        Save configuration to file.
        
        Args:
            config: Configuration to save
            file_path: Optional file path (uses default if not specified)
            
        Returns:
            True if successful, False otherwise
        """
        target_path = file_path or self.config_file_path
        if not target_path:
            logger.error("No config file path specified for saving")
            return False
        
        try:
            config_dict = asdict(config)
            
            # Determine format based on file extension
            path_obj = Path(target_path)
            if path_obj.suffix.lower() == '.json':
                format_type = ConfigFormat.JSON
            else:
                format_type = ConfigFormat.ENV
            
            # Ensure directory exists
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            if format_type == ConfigFormat.JSON:
                with open(target_path, 'w') as f:
                    json.dump(config_dict, f, indent=2)
            else:
                self._save_as_env_file(config_dict, target_path)
            
            logger.info(f"Configuration saved to {target_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error saving configuration to {target_path}: {e}")
            return False
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a specific configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        config = self.load_config()
        return getattr(config, key, default)
    
    def set_config_value(self, key: str, value: Any) -> bool:
        """
        Set a specific configuration value.
        
        Args:
            key: Configuration key
            value: Value to set
            
        Returns:
            True if successful, False otherwise
        """
        try:
            config = self.load_config()
            if hasattr(config, key):
                setattr(config, key, value)
                # Keep cache valid since we modified the cached object
                return True
            else:
                logger.error(f"Unknown configuration key: {key}")
                return False
        except Exception as e:
            logger.error(f"Error setting configuration value {key}: {e}")
            return False
    
    def reload_config(self) -> NASConfig:
        """
        Force reload configuration from sources.
        
        Returns:
            Reloaded NASConfig object
        """
        self._config_cache_valid = False
        return self.load_config()
    
    def validate_paths(self) -> Dict[str, bool]:
        """
        Validate all file and directory paths in configuration.
        
        Returns:
            Dictionary mapping path names to validation results
        """
        config = self.load_config()
        results = {}
        
        # Check SnapRAID config path directory
        snapraid_dir = os.path.dirname(config.snapraid_config_path)
        results['snapraid_config_dir'] = os.path.exists(snapraid_dir)
        
        # Check MergerFS mount points
        for i, mount_point in enumerate(config.mergerfs_mount_points):
            results[f'mergerfs_mount_{i}'] = os.path.exists(mount_point)
        
        # Check data drive paths
        for i, drive_path in enumerate(config.data_drive_paths):
            results[f'data_drive_{i}'] = os.path.exists(drive_path)
        
        # Check parity drive paths
        for i, drive_path in enumerate(config.parity_drive_paths):
            results[f'parity_drive_{i}'] = os.path.exists(drive_path)
        
        # Check pool mount point
        results['pool_mount_point'] = os.path.exists(config.pool_mount_point)
        
        return results
    
    def _load_config_file(self, file_path: str) -> Dict[str, Any]:
        """
        Load configuration from file.
        
        Args:
            file_path: Path to configuration file
            
        Returns:
            Dictionary of configuration values
        """
        try:
            path_obj = Path(file_path)
            
            if path_obj.suffix.lower() == '.json':
                with open(file_path, 'r') as f:
                    return json.load(f)
            else:
                return self._load_env_file(file_path)
        
        except Exception as e:
            logger.error(f"Error loading config file {file_path}: {e}")
            return {}
    
    def _load_env_file(self, file_path: str) -> Dict[str, Any]:
        """
        Load configuration from environment-style file.
        
        Args:
            file_path: Path to .env file
            
        Returns:
            Dictionary of configuration values
        """
        config = {}
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"\'')
                            
                            if key in self.ENV_MAPPINGS:
                                config_key = self.ENV_MAPPINGS[key]
                                config[config_key] = self._parse_env_value(key, value)
        
        except Exception as e:
            logger.error(f"Error loading env file {file_path}: {e}")
        
        return config
    
    def _save_as_env_file(self, config_dict: Dict[str, Any], file_path: str) -> None:
        """
        Save configuration as environment-style file.
        
        Args:
            config_dict: Configuration dictionary
            file_path: Target file path
        """
        reverse_mappings = {v: k for k, v in self.ENV_MAPPINGS.items()}
        
        with open(file_path, 'w') as f:
            f.write("# NAS Configuration File\n")
            f.write("# Generated automatically - modify with care\n\n")
            
            for config_key, value in config_dict.items():
                if config_key in reverse_mappings:
                    env_key = reverse_mappings[config_key]
                    env_value = self._format_env_value(value)
                    f.write(f"{env_key}={env_value}\n")
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """
        Load configuration from environment variables.
        
        Returns:
            Dictionary of configuration values from environment
        """
        config = {}
        
        for env_key, config_key in self.ENV_MAPPINGS.items():
            env_value = os.getenv(env_key)
            if env_value is not None:
                config[config_key] = self._parse_env_value(env_key, env_value)
        
        return config
    
    def _parse_env_value(self, env_key: str, value: str) -> Any:
        """
        Parse environment variable value to appropriate type.
        
        Args:
            env_key: Environment variable key
            value: String value from environment
            
        Returns:
            Parsed value in appropriate type
        """
        # Handle list values (comma-separated)
        if env_key in {'MERGERFS_MOUNT_POINTS', 'DATA_DRIVE_PATHS', 'PARITY_DRIVE_PATHS'}:
            return [item.strip() for item in value.split(',') if item.strip()]
        
        # Handle JSON values
        if env_key == 'SMART_TEST_INTERVALS':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {env_key}, using default")
                return {"short": 24, "long": 168}
        
        # Handle boolean values
        if env_key == 'ENABLE_SMART_MONITORING':
            return value.lower() in {'true', '1', 'yes', 'on'}
        
        # Handle integer values
        if env_key == 'MAX_COMMAND_TIMEOUT':
            try:
                return int(value)
            except ValueError:
                logger.warning(f"Invalid integer for {env_key}, using default")
                return 300
        
        # Default to string
        return value
    
    def _format_env_value(self, value: Any) -> str:
        """
        Format a value for environment file output.
        
        Args:
            value: Value to format
            
        Returns:
            Formatted string value
        """
        if isinstance(value, list):
            return ','.join(str(item) for item in value)
        elif isinstance(value, dict):
            return json.dumps(value)
        elif isinstance(value, bool):
            return 'true' if value else 'false'
        else:
            return str(value)
    
    def _validate_config(self, config: NASConfig) -> None:
        """
        Validate configuration values.
        
        Args:
            config: Configuration to validate
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Validate timeout
        if config.max_command_timeout <= 0:
            raise ValueError("max_command_timeout must be positive")
        
        # Validate log level
        valid_log_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if config.log_level.upper() not in valid_log_levels:
            raise ValueError(f"Invalid log level: {config.log_level}")
        
        # Validate SMART test intervals
        if config.smart_test_intervals:
            for test_type, interval in config.smart_test_intervals.items():
                if not isinstance(interval, int) or interval <= 0:
                    raise ValueError(f"Invalid SMART test interval for {test_type}: {interval}")
        
        # Validate paths are absolute
        paths_to_check = [
            config.snapraid_config_path,
            config.pool_mount_point
        ] + config.mergerfs_mount_points + config.data_drive_paths + config.parity_drive_paths
        
        for path in paths_to_check:
            if path and not os.path.isabs(path):
                raise ValueError(f"Path must be absolute: {path}")
        
        logger.debug("Configuration validation passed")