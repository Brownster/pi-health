#!/usr/bin/env python3
"""
Demonstration script for NAS management infrastructure.

This script shows how to use the core NAS management components:
- DriveManager: Discover and manage drives
- SystemCommandExecutor: Execute system commands securely
- ConfigManager: Handle configuration management
"""

import logging
from nas.drive_manager import DriveManager
from nas.system_executor import SystemCommandExecutor
from nas.config_manager import ConfigManager, NASConfig

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    """Demonstrate NAS management functionality."""
    print("=== NAS Management Infrastructure Demo ===\n")
    
    # 1. Configuration Management
    print("1. Configuration Management:")
    config_manager = ConfigManager()
    config = config_manager.load_config()
    
    print(f"   - SnapRAID config path: {config.snapraid_config_path}")
    print(f"   - Pool mount point: {config.pool_mount_point}")
    print(f"   - Log level: {config.log_level}")
    print(f"   - SMART monitoring enabled: {config.enable_smart_monitoring}")
    print(f"   - MergerFS mount points: {config.mergerfs_mount_points}")
    print()
    
    # 2. Drive Discovery
    print("2. Drive Discovery:")
    drive_manager = DriveManager()
    drives = drive_manager.discover_drives()
    
    if drives:
        print(f"   Found {len(drives)} drives:")
        for drive in drives:
            print(f"   - {drive.device_path} -> {drive.mount_point}")
            print(f"     Filesystem: {drive.filesystem}, Role: {drive.role.value}")
            print(f"     Size: {drive.size_bytes // (1024**3):.1f} GB, "
                  f"Used: {drive.usage_percent:.1f}%")
            print(f"     Health: {drive.health_status.value}")
    else:
        print("   No data drives found (this is normal in a test environment)")
    print()
    
    # 3. System Command Execution (Dry Run)
    print("3. System Command Execution (Dry Run Mode):")
    system_executor = SystemCommandExecutor(dry_run=True)
    
    # Demonstrate SnapRAID command
    print("   Executing SnapRAID status command...")
    success, stdout, stderr = system_executor.execute_snapraid_command('status')
    print(f"   Success: {success}, Output: {stdout}")
    
    # Demonstrate SMART command
    print("   Executing SMART health check...")
    success, stdout, stderr = system_executor.execute_smart_command('/dev/sdb', '-H')
    print(f"   Success: {success}, Output: {stdout}")
    
    # Show command history
    history = system_executor.get_command_history()
    print(f"   Command history: {len(history)} commands executed")
    for i, cmd in enumerate(history, 1):
        print(f"     {i}. {cmd['command']} (type: {cmd['type']})")
    print()
    
    # 4. Configuration Validation
    print("4. Configuration Validation:")
    try:
        # Test with valid configuration
        valid_config = NASConfig(
            snapraid_config_path="/etc/snapraid.conf",
            max_command_timeout=300,
            log_level="INFO"
        )
        config_manager._validate_config(valid_config)
        print("   ✓ Configuration validation passed")
        
        # Test path validation
        path_results = config_manager.validate_paths()
        print(f"   Path validation results: {len(path_results)} paths checked")
        
    except ValueError as e:
        print(f"   ✗ Configuration validation failed: {e}")
    print()
    
    # 5. Integration Example
    print("5. Integration Example:")
    print("   This demonstrates how components work together:")
    
    # Update configuration
    config_manager.set_config_value('log_level', 'DEBUG')
    updated_config = config_manager.get_config_value('log_level')
    print(f"   - Updated log level to: {updated_config}")
    
    # Use configuration in system executor
    snapraid_path = config_manager.get_config_value('snapraid_config_path')
    print(f"   - Using SnapRAID config from configuration: {snapraid_path}")
    
    # Execute command with config
    success, stdout, stderr = system_executor.execute_snapraid_command(
        'diff', 
        config_path=snapraid_path
    )
    print(f"   - SnapRAID diff command executed: {success}")
    
    print("\n=== Demo Complete ===")
    print("The NAS management infrastructure is ready for use!")
    print("Next steps would be to implement the API endpoints and web UI.")


if __name__ == '__main__':
    main()