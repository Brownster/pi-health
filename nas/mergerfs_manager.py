"""MergerFS pool management and monitoring utilities."""

import os
import re
import subprocess
from typing import List, Optional, Dict, Tuple
import logging
from dataclasses import dataclass
from enum import Enum

from .models import DriveConfig
from .system_executor import SystemCommandExecutor

logger = logging.getLogger(__name__)


class MergerFSPolicy(Enum):
    """MergerFS policy types."""
    EPMFS = "epmfs"  # Existing Path, Most Free Space
    FF = "ff"        # First Found
    EPALL = "epall"  # Existing Path, All
    MSP = "msp"      # Most Shared Path
    RAND = "rand"    # Random


@dataclass
class MergerFSPool:
    """Configuration and status information for a MergerFS pool."""
    mount_point: str
    source_paths: List[str]
    filesystem: str
    options: Dict[str, str]
    total_size: int = 0
    used_size: int = 0
    available_size: int = 0
    
    @property
    def usage_percent(self) -> float:
        """Calculate usage percentage."""
        if self.total_size == 0:
            return 0.0
        return (self.used_size / self.total_size) * 100


@dataclass
class MergerFSBranchStats:
    """Statistics for a MergerFS branch (source path)."""
    path: str
    total_size: int
    used_size: int
    available_size: int
    
    @property
    def usage_percent(self) -> float:
        """Calculate usage percentage."""
        if self.total_size == 0:
            return 0.0
        return (self.used_size / self.total_size) * 100


class MergerFSManager:
    """Manages MergerFS pool detection, monitoring, and configuration."""
    
    def __init__(self, system_executor: Optional[SystemCommandExecutor] = None):
        """
        Initialize the MergerFS manager.
        
        Args:
            system_executor: System command executor for privileged operations
        """
        self._system_executor = system_executor or SystemCommandExecutor()
        self._pool_cache: Dict[str, MergerFSPool] = {}
    
    def discover_pools(self) -> List[MergerFSPool]:
        """
        Discover MergerFS pools by parsing /proc/mounts.
        
        Returns:
            List of MergerFSPool objects for active pools
        """
        pools = []
        
        try:
            # Read /proc/mounts to find MergerFS mount points
            with open('/proc/mounts', 'r') as f:
                mounts = f.readlines()
            
            for line in mounts:
                parts = line.strip().split()
                if len(parts) >= 4 and parts[2] == 'fuse.mergerfs':
                    pool = self._parse_mergerfs_mount(parts)
                    if pool:
                        pools.append(pool)
                        logger.info(f"Discovered MergerFS pool: {pool.mount_point}")
        
        except Exception as e:
            logger.error(f"Error discovering MergerFS pools: {e}")
        
        # Update cache
        self._pool_cache = {pool.mount_point: pool for pool in pools}
        
        return pools
    
    def get_pool_by_mount_point(self, mount_point: str) -> Optional[MergerFSPool]:
        """
        Get pool configuration by mount point.
        
        Args:
            mount_point: Mount point path (e.g., '/mnt/storage')
            
        Returns:
            MergerFSPool if found, None otherwise
        """
        return self._pool_cache.get(mount_point)
    
    def get_pool_statistics(self, mount_point: str) -> Optional[MergerFSPool]:
        """
        Get detailed statistics for a MergerFS pool.
        
        Args:
            mount_point: Mount point path
            
        Returns:
            Updated MergerFSPool with current statistics, None if not found
        """
        pool = self._pool_cache.get(mount_point)
        if not pool:
            return None
        
        try:
            # Update pool statistics using statvfs
            import os
            stat = os.statvfs(mount_point)
            
            pool.total_size = stat.f_blocks * stat.f_frsize
            pool.available_size = stat.f_bavail * stat.f_frsize
            pool.used_size = pool.total_size - pool.available_size
            
            return pool
        
        except Exception as e:
            logger.error(f"Error getting pool statistics for {mount_point}: {e}")
            return pool
    
    def get_branch_statistics(self, mount_point: str) -> List[MergerFSBranchStats]:
        """
        Get statistics for individual branches (source paths) of a MergerFS pool.
        
        Args:
            mount_point: Mount point path
            
        Returns:
            List of MergerFSBranchStats for each branch
        """
        pool = self._pool_cache.get(mount_point)
        if not pool:
            return []
        
        branch_stats = []
        
        for source_path in pool.source_paths:
            try:
                import os
                stat = os.statvfs(source_path)
                
                branch_stat = MergerFSBranchStats(
                    path=source_path,
                    total_size=stat.f_blocks * stat.f_frsize,
                    available_size=stat.f_bavail * stat.f_frsize,
                    used_size=(stat.f_blocks - stat.f_bavail) * stat.f_frsize
                )
                
                branch_stats.append(branch_stat)
                
            except Exception as e:
                logger.error(f"Error getting branch statistics for {source_path}: {e}")
                # Add empty stats for failed branches
                branch_stats.append(MergerFSBranchStats(
                    path=source_path,
                    total_size=0,
                    used_size=0,
                    available_size=0
                ))
        
        return branch_stats
    
    def get_mergerfsctl_info(self, mount_point: str) -> Optional[Dict]:
        """
        Get detailed information using mergerfsctl if available.
        
        Args:
            mount_point: Mount point path
            
        Returns:
            Dictionary with mergerfsctl information, None if not available
        """
        try:
            # Check if mergerfsctl is available
            result = subprocess.run(
                ['which', 'mergerfsctl'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.debug("mergerfsctl not available")
                return None
            
            # Get mergerfsctl info
            result = subprocess.run(
                ['mergerfsctl', '-m', mount_point, 'info'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # Parse mergerfsctl output
                info = {}
                for line in result.stdout.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        info[key.strip()] = value.strip()
                
                return info
            else:
                logger.warning(f"mergerfsctl failed: {result.stderr}")
                return None
        
        except Exception as e:
            logger.debug(f"Error getting mergerfsctl info: {e}")
            return None
    
    def _parse_mergerfs_mount(self, mount_parts: List[str]) -> Optional[MergerFSPool]:
        """
        Parse a MergerFS mount line from /proc/mounts.
        
        Args:
            mount_parts: Split mount line parts
            
        Returns:
            MergerFSPool if successfully parsed, None otherwise
        """
        try:
            source_paths_str = mount_parts[0]
            mount_point = mount_parts[1]
            filesystem = mount_parts[2]
            options_str = mount_parts[3]
            
            # Parse source paths (colon-separated)
            source_paths = source_paths_str.split(':')
            
            # Parse mount options
            options = {}
            for option in options_str.split(','):
                if '=' in option:
                    key, value = option.split('=', 1)
                    options[key] = value
                else:
                    options[option] = True
            
            return MergerFSPool(
                mount_point=mount_point,
                source_paths=source_paths,
                filesystem=filesystem,
                options=options
            )
        
        except Exception as e:
            logger.error(f"Error parsing MergerFS mount: {e}")
            return None
    
    def is_mergerfs_available(self) -> bool:
        """
        Check if MergerFS is available on the system.
        
        Returns:
            True if MergerFS is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['which', 'mergerfs'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def validate_source_paths(self, source_paths: List[str]) -> Tuple[bool, str]:
        """
        Validate that source paths exist and are accessible.
        
        Args:
            source_paths: List of source paths to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not source_paths:
            return False, "At least one source path is required"
        
        for path in source_paths:
            if not os.path.exists(path):
                return False, f"Source path does not exist: {path}"
            
            if not os.path.isdir(path):
                return False, f"Source path is not a directory: {path}"
            
            if not os.access(path, os.R_OK):
                return False, f"Source path is not readable: {path}"
        
        return True, ""
    
    def generate_mount_command(self, source_paths: List[str], mount_point: str, 
                             policies: Optional[Dict[str, str]] = None) -> List[str]:
        """
        Generate MergerFS mount command.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            
        Returns:
            List of command arguments for mounting
        """
        # Default policies from design document
        default_policies = {
            'category.create': 'epmfs',  # Existing Path, Most Free Space
            'category.search': 'ff',     # First Found
            'category.action': 'epall'   # Existing Path, All
        }
        
        # Merge with provided policies
        if policies:
            default_policies.update(policies)
        
        # Build mount options
        mount_options = [
            'defaults',
            'allow_other',
            'use_ino',
            'cache.files=partial',
            'dropcacheonclose=true'
        ]
        
        # Add policies
        for policy_key, policy_value in default_policies.items():
            mount_options.append(f"{policy_key}={policy_value}")
        
        # Build command
        source_str = ':'.join(source_paths)
        options_str = ','.join(mount_options)
        
        return [
            'mergerfs',
            source_str,
            mount_point,
            '-o',
            options_str
        ]
    
    def mount_pool(self, source_paths: List[str], mount_point: str, 
                   policies: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
        """
        Mount a MergerFS pool.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Validate inputs
            is_valid, error_msg = self.validate_source_paths(source_paths)
            if not is_valid:
                return False, error_msg
            
            # Check if MergerFS is available
            if not self.is_mergerfs_available():
                return False, "MergerFS is not available on this system"
            
            # Create mount point if it doesn't exist
            if not os.path.exists(mount_point):
                os.makedirs(mount_point, exist_ok=True)
            
            # Generate mount command
            mount_cmd = self.generate_mount_command(source_paths, mount_point, policies)
            
            # Execute mount command
            success, output, error = self._system_executor.execute_command(mount_cmd)
            
            if success:
                logger.info(f"Successfully mounted MergerFS pool at {mount_point}")
                # Refresh pool cache
                self.discover_pools()
                return True, f"MergerFS pool mounted successfully at {mount_point}"
            else:
                logger.error(f"Failed to mount MergerFS pool: {error}")
                return False, f"Failed to mount MergerFS pool: {error}"
        
        except Exception as e:
            logger.error(f"Error mounting MergerFS pool: {e}")
            return False, f"Error mounting MergerFS pool: {str(e)}"
    
    def unmount_pool(self, mount_point: str, force: bool = False) -> Tuple[bool, str]:
        """
        Unmount a MergerFS pool.
        
        Args:
            mount_point: Mount point to unmount
            force: Force unmount even if busy
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Build unmount command
            umount_cmd = ['umount']
            if force:
                umount_cmd.append('-f')
            umount_cmd.append(mount_point)
            
            # Execute unmount command
            success, output, error = self._system_executor.execute_command(umount_cmd)
            
            if success:
                logger.info(f"Successfully unmounted MergerFS pool at {mount_point}")
                # Remove from cache
                self._pool_cache.pop(mount_point, None)
                return True, f"MergerFS pool unmounted successfully from {mount_point}"
            else:
                logger.error(f"Failed to unmount MergerFS pool: {error}")
                return False, f"Failed to unmount MergerFS pool: {error}"
        
        except Exception as e:
            logger.error(f"Error unmounting MergerFS pool: {e}")
            return False, f"Error unmounting MergerFS pool: {str(e)}"
    
    def to_dict(self, pool: MergerFSPool) -> Dict:
        """
        Convert MergerFSPool to dictionary for JSON serialization.
        
        Args:
            pool: MergerFSPool object
            
        Returns:
            Dictionary representation
        """
        return {
            'mount_point': pool.mount_point,
            'source_paths': pool.source_paths,
            'filesystem': pool.filesystem,
            'options': pool.options,
            'total_size': pool.total_size,
            'used_size': pool.used_size,
            'available_size': pool.available_size,
            'usage_percent': round(pool.usage_percent, 2)
        }
    
    def branch_stats_to_dict(self, branch_stats: List[MergerFSBranchStats]) -> List[Dict]:
        """
        Convert list of MergerFSBranchStats to list of dictionaries.
        
        Args:
            branch_stats: List of MergerFSBranchStats objects
            
        Returns:
            List of dictionary representations
        """
        return [
            {
                'path': stats.path,
                'total_size': stats.total_size,
                'used_size': stats.used_size,
                'available_size': stats.available_size,
                'usage_percent': round(stats.usage_percent, 2)
            }
            for stats in branch_stats
        ]
    
    def generate_fstab_entry(self, source_paths: List[str], mount_point: str, 
                           policies: Optional[Dict[str, str]] = None) -> str:
        """
        Generate fstab entry for MergerFS pool.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            
        Returns:
            fstab entry string
        """
        # Default policies from design document
        default_policies = {
            'category.create': 'epmfs',  # Existing Path, Most Free Space
            'category.search': 'ff',     # First Found
            'category.action': 'epall'   # Existing Path, All
        }
        
        # Merge with provided policies
        if policies:
            default_policies.update(policies)
        
        # Build mount options
        mount_options = [
            'defaults',
            'allow_other',
            'use_ino',
            'cache.files=partial',
            'dropcacheonclose=true'
        ]
        
        # Add policies
        for policy_key, policy_value in default_policies.items():
            mount_options.append(f"{policy_key}={policy_value}")
        
        # Build fstab entry
        source_str = ':'.join(source_paths)
        options_str = ','.join(mount_options)
        
        return f"{source_str} {mount_point} fuse.mergerfs {options_str} 0 0"
    
    def update_fstab(self, source_paths: List[str], mount_point: str, 
                    policies: Optional[Dict[str, str]] = None,
                    backup: bool = True) -> Tuple[bool, str]:
        """
        Update /etc/fstab with MergerFS pool configuration.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            backup: Whether to create backup of fstab
            
        Returns:
            Tuple of (success, message)
        """
        try:
            fstab_path = '/etc/fstab'
            
            # Create backup if requested
            if backup:
                import shutil
                import datetime
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = f"{fstab_path}.backup_{timestamp}"
                shutil.copy2(fstab_path, backup_path)
                logger.info(f"Created fstab backup: {backup_path}")
            
            # Generate new fstab entry
            new_entry = self.generate_fstab_entry(source_paths, mount_point, policies)
            
            # Read current fstab
            with open(fstab_path, 'r') as f:
                lines = f.readlines()
            
            # Remove existing entries for this mount point
            filtered_lines = []
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == mount_point:
                    logger.info(f"Removing existing fstab entry for {mount_point}")
                    continue
                filtered_lines.append(line)
            
            # Add new entry
            if not new_entry.endswith('\n'):
                new_entry += '\n'
            filtered_lines.append(new_entry)
            
            # Write updated fstab
            with open(fstab_path, 'w') as f:
                f.writelines(filtered_lines)
            
            logger.info(f"Updated fstab with MergerFS entry for {mount_point}")
            return True, f"Successfully updated fstab for {mount_point}"
        
        except Exception as e:
            logger.error(f"Error updating fstab: {e}")
            return False, f"Failed to update fstab: {str(e)}"
    
    def remove_fstab_entry(self, mount_point: str, backup: bool = True) -> Tuple[bool, str]:
        """
        Remove MergerFS entry from /etc/fstab.
        
        Args:
            mount_point: Mount point to remove
            backup: Whether to create backup of fstab
            
        Returns:
            Tuple of (success, message)
        """
        try:
            fstab_path = '/etc/fstab'
            
            # Create backup if requested
            if backup:
                import shutil
                import datetime
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_path = f"{fstab_path}.backup_{timestamp}"
                shutil.copy2(fstab_path, backup_path)
                logger.info(f"Created fstab backup: {backup_path}")
            
            # Read current fstab
            with open(fstab_path, 'r') as f:
                lines = f.readlines()
            
            # Remove entries for this mount point
            filtered_lines = []
            removed_count = 0
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == mount_point:
                    logger.info(f"Removing fstab entry for {mount_point}")
                    removed_count += 1
                    continue
                filtered_lines.append(line)
            
            if removed_count == 0:
                return True, f"No fstab entry found for {mount_point}"
            
            # Write updated fstab
            with open(fstab_path, 'w') as f:
                f.writelines(filtered_lines)
            
            logger.info(f"Removed {removed_count} fstab entries for {mount_point}")
            return True, f"Successfully removed fstab entry for {mount_point}"
        
        except Exception as e:
            logger.error(f"Error removing fstab entry: {e}")
            return False, f"Failed to remove fstab entry: {str(e)}"
    
    def generate_systemd_mount_unit(self, source_paths: List[str], mount_point: str,
                                  policies: Optional[Dict[str, str]] = None) -> str:
        """
        Generate systemd mount unit file content for MergerFS pool.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            
        Returns:
            systemd mount unit file content
        """
        # Default policies from design document
        default_policies = {
            'category.create': 'epmfs',
            'category.search': 'ff',
            'category.action': 'epall'
        }
        
        # Merge with provided policies
        if policies:
            default_policies.update(policies)
        
        # Build mount options
        mount_options = [
            'defaults',
            'allow_other',
            'use_ino',
            'cache.files=partial',
            'dropcacheonclose=true'
        ]
        
        # Add policies
        for policy_key, policy_value in default_policies.items():
            mount_options.append(f"{policy_key}={policy_value}")
        
        # Build systemd unit content
        source_str = ':'.join(source_paths)
        options_str = ','.join(mount_options)
        
        # Convert mount point to systemd unit name format
        unit_name = mount_point.replace('/', '-')[1:] if mount_point.startswith('/') else mount_point.replace('/', '-')
        
        unit_content = f"""[Unit]
Description=MergerFS pool at {mount_point}
After=local-fs.target
Wants=local-fs.target

[Mount]
What={source_str}
Where={mount_point}
Type=fuse.mergerfs
Options={options_str}

[Install]
WantedBy=multi-user.target
"""
        
        return unit_content
    
    def create_systemd_mount_unit(self, source_paths: List[str], mount_point: str,
                                policies: Optional[Dict[str, str]] = None) -> Tuple[bool, str]:
        """
        Create systemd mount unit file for MergerFS pool.
        
        Args:
            source_paths: List of source paths to merge
            mount_point: Target mount point
            policies: Optional dictionary of MergerFS policies
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Generate unit content
            unit_content = self.generate_systemd_mount_unit(source_paths, mount_point, policies)
            
            # Convert mount point to systemd unit name
            unit_name = mount_point.replace('/', '-')[1:] if mount_point.startswith('/') else mount_point.replace('/', '-')
            unit_file = f"/etc/systemd/system/{unit_name}.mount"
            
            # Write unit file
            with open(unit_file, 'w') as f:
                f.write(unit_content)
            
            # Reload systemd and enable the unit
            reload_success, _, reload_error = self._system_executor.execute_command(['systemctl', 'daemon-reload'])
            if not reload_success:
                logger.warning(f"Failed to reload systemd: {reload_error}")
            
            enable_success, _, enable_error = self._system_executor.execute_command(['systemctl', 'enable', f"{unit_name}.mount"])
            if not enable_success:
                logger.warning(f"Failed to enable systemd unit: {enable_error}")
            
            logger.info(f"Created systemd mount unit: {unit_file}")
            return True, f"Successfully created systemd mount unit for {mount_point}"
        
        except Exception as e:
            logger.error(f"Error creating systemd mount unit: {e}")
            return False, f"Failed to create systemd mount unit: {str(e)}"
    
    def remove_systemd_mount_unit(self, mount_point: str) -> Tuple[bool, str]:
        """
        Remove systemd mount unit file for MergerFS pool.
        
        Args:
            mount_point: Mount point to remove unit for
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Convert mount point to systemd unit name
            unit_name = mount_point.replace('/', '-')[1:] if mount_point.startswith('/') else mount_point.replace('/', '-')
            unit_file = f"/etc/systemd/system/{unit_name}.mount"
            
            # Stop and disable the unit
            stop_success, _, stop_error = self._system_executor.execute_command(['systemctl', 'stop', f"{unit_name}.mount"])
            if not stop_success:
                logger.warning(f"Failed to stop systemd unit: {stop_error}")
            
            disable_success, _, disable_error = self._system_executor.execute_command(['systemctl', 'disable', f"{unit_name}.mount"])
            if not disable_success:
                logger.warning(f"Failed to disable systemd unit: {disable_error}")
            
            # Remove unit file
            if os.path.exists(unit_file):
                os.remove(unit_file)
                logger.info(f"Removed systemd mount unit: {unit_file}")
            
            # Reload systemd
            reload_success, _, reload_error = self._system_executor.execute_command(['systemctl', 'daemon-reload'])
            if not reload_success:
                logger.warning(f"Failed to reload systemd: {reload_error}")
            
            return True, f"Successfully removed systemd mount unit for {mount_point}"
        
        except Exception as e:
            logger.error(f"Error removing systemd mount unit: {e}")
            return False, f"Failed to remove systemd mount unit: {str(e)}"
    
    def get_policy_from_env(self, policy_name: str, default_value: str) -> str:
        """
        Get MergerFS policy from environment variables.
        
        Args:
            policy_name: Policy name (e.g., 'create', 'search', 'action')
            default_value: Default value if not set in environment
            
        Returns:
            Policy value from environment or default
        """
        env_var_name = f"MERGERFS_POLICY_{policy_name.upper()}"
        return os.getenv(env_var_name, default_value)
    
    def get_policies_from_env(self) -> Dict[str, str]:
        """
        Get all MergerFS policies from environment variables.
        
        Returns:
            Dictionary of policies with environment overrides
        """
        return {
            'category.create': self.get_policy_from_env('create', 'epmfs'),
            'category.search': self.get_policy_from_env('search', 'ff'),
            'category.action': self.get_policy_from_env('action', 'epall')
        }
    
    def generate_config_from_drives(self, drives: List[DriveConfig], 
                                  mount_point: str = '/mnt/storage') -> Tuple[bool, str, Dict]:
        """
        Generate MergerFS configuration based on available drives.
        
        Args:
            drives: List of DriveConfig objects for data drives
            mount_point: Target mount point for the pool
            
        Returns:
            Tuple of (success, message, config_dict)
        """
        try:
            # Filter for data drives only
            data_drives = [drive for drive in drives if drive.role.value == 'data']
            
            if not data_drives:
                return False, "No data drives available for MergerFS pool", {}
            
            # Extract source paths
            source_paths = [drive.mount_point for drive in data_drives]
            
            # Get policies from environment
            policies = self.get_policies_from_env()
            
            # Generate configuration
            config = {
                'source_paths': source_paths,
                'mount_point': mount_point,
                'policies': policies,
                'fstab_entry': self.generate_fstab_entry(source_paths, mount_point, policies),
                'systemd_unit_content': self.generate_systemd_mount_unit(source_paths, mount_point, policies),
                'mount_command': self.generate_mount_command(source_paths, mount_point, policies)
            }
            
            logger.info(f"Generated MergerFS configuration for {len(data_drives)} drives")
            return True, f"Generated configuration for {len(data_drives)} data drives", config
        
        except Exception as e:
            logger.error(f"Error generating MergerFS configuration: {e}")
            return False, f"Failed to generate configuration: {str(e)}", {}
    
    def expand_pool(self, mount_point: str, new_source_paths: List[str],
                   update_fstab: bool = True, update_systemd: bool = True) -> Tuple[bool, str]:
        """
        Expand an existing MergerFS pool with new source paths.
        
        Args:
            mount_point: Mount point of the existing pool
            new_source_paths: List of new source paths to add
            update_fstab: Whether to update fstab configuration
            update_systemd: Whether to update systemd unit
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Get existing pool configuration
            existing_pool = self.get_pool_by_mount_point(mount_point)
            if not existing_pool:
                return False, f"No existing pool found at {mount_point}"
            
            # Validate new source paths
            is_valid, error_msg = self.validate_source_paths(new_source_paths)
            if not is_valid:
                return False, f"Invalid new source paths: {error_msg}"
            
            # Check for duplicates
            existing_paths = set(existing_pool.source_paths)
            new_paths = set(new_source_paths)
            duplicates = existing_paths.intersection(new_paths)
            if duplicates:
                return False, f"Duplicate source paths found: {', '.join(duplicates)}"
            
            # Combine source paths
            all_source_paths = existing_pool.source_paths + new_source_paths
            
            # Get current policies from existing pool options
            policies = {}
            for key, value in existing_pool.options.items():
                if key.startswith('category.'):
                    policies[key] = value
            
            # Unmount the existing pool
            logger.info(f"Unmounting existing pool at {mount_point}")
            unmount_success, unmount_msg = self.unmount_pool(mount_point)
            if not unmount_success:
                return False, f"Failed to unmount existing pool: {unmount_msg}"
            
            # Mount the expanded pool
            logger.info(f"Mounting expanded pool with {len(all_source_paths)} source paths")
            mount_success, mount_msg = self.mount_pool(all_source_paths, mount_point, policies)
            if not mount_success:
                # Try to remount the original pool if expansion fails
                logger.error("Expansion failed, attempting to restore original pool")
                restore_success, restore_msg = self.mount_pool(existing_pool.source_paths, mount_point, policies)
                if not restore_success:
                    return False, f"Expansion failed and could not restore original pool: {mount_msg}. Restore error: {restore_msg}"
                return False, f"Pool expansion failed: {mount_msg}. Original pool restored."
            
            # Update fstab if requested
            if update_fstab:
                fstab_success, fstab_msg = self.update_fstab(all_source_paths, mount_point, policies)
                if not fstab_success:
                    logger.warning(f"Failed to update fstab: {fstab_msg}")
            
            # Update systemd unit if requested
            if update_systemd:
                systemd_success, systemd_msg = self.create_systemd_mount_unit(all_source_paths, mount_point, policies)
                if not systemd_success:
                    logger.warning(f"Failed to update systemd unit: {systemd_msg}")
            
            logger.info(f"Successfully expanded pool at {mount_point} with {len(new_source_paths)} new drives")
            return True, f"Successfully expanded pool with {len(new_source_paths)} new drives"
        
        except Exception as e:
            logger.error(f"Error expanding MergerFS pool: {e}")
            return False, f"Failed to expand pool: {str(e)}"
    
    def validate_pool_integrity(self, mount_point: str) -> Tuple[bool, str, Dict]:
        """
        Validate the integrity of a MergerFS pool.
        
        Args:
            mount_point: Mount point to validate
            
        Returns:
            Tuple of (is_valid, message, validation_details)
        """
        try:
            validation_details = {
                'mount_point_accessible': False,
                'all_sources_accessible': False,
                'pool_statistics_available': False,
                'source_paths': [],
                'inaccessible_sources': [],
                'total_sources': 0,
                'accessible_sources': 0
            }
            
            # Check if pool exists
            pool = self.get_pool_by_mount_point(mount_point)
            if not pool:
                return False, f"Pool not found at {mount_point}", validation_details
            
            validation_details['source_paths'] = pool.source_paths
            validation_details['total_sources'] = len(pool.source_paths)
            
            # Check if mount point is accessible
            try:
                if os.path.exists(mount_point) and os.access(mount_point, os.R_OK):
                    validation_details['mount_point_accessible'] = True
                else:
                    return False, f"Mount point {mount_point} is not accessible", validation_details
            except Exception as e:
                return False, f"Cannot access mount point {mount_point}: {e}", validation_details
            
            # Check if all source paths are accessible
            accessible_count = 0
            for source_path in pool.source_paths:
                try:
                    if os.path.exists(source_path) and os.access(source_path, os.R_OK):
                        accessible_count += 1
                    else:
                        validation_details['inaccessible_sources'].append(source_path)
                except Exception as e:
                    validation_details['inaccessible_sources'].append(f"{source_path} (error: {e})")
            
            validation_details['accessible_sources'] = accessible_count
            validation_details['all_sources_accessible'] = accessible_count == len(pool.source_paths)
            
            # Check if pool statistics are available
            try:
                updated_pool = self.get_pool_statistics(mount_point)
                if updated_pool and updated_pool.total_size > 0:
                    validation_details['pool_statistics_available'] = True
            except Exception as e:
                logger.debug(f"Could not get pool statistics: {e}")
            
            # Determine overall validity
            is_valid = (validation_details['mount_point_accessible'] and 
                       validation_details['all_sources_accessible'] and
                       validation_details['pool_statistics_available'])
            
            if is_valid:
                return True, "Pool integrity validation passed", validation_details
            else:
                issues = []
                if not validation_details['mount_point_accessible']:
                    issues.append("mount point not accessible")
                if not validation_details['all_sources_accessible']:
                    issues.append(f"{len(validation_details['inaccessible_sources'])} source paths not accessible")
                if not validation_details['pool_statistics_available']:
                    issues.append("pool statistics not available")
                
                return False, f"Pool integrity issues: {', '.join(issues)}", validation_details
        
        except Exception as e:
            logger.error(f"Error validating pool integrity: {e}")
            return False, f"Validation error: {str(e)}", validation_details
    
    def auto_expand_pool_with_drives(self, mount_point: str, available_drives: List[DriveConfig]) -> Tuple[bool, str]:
        """
        Automatically expand a pool with newly available data drives.
        
        Args:
            mount_point: Mount point of the pool to expand
            available_drives: List of all available drives
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Get existing pool
            existing_pool = self.get_pool_by_mount_point(mount_point)
            if not existing_pool:
                return False, f"No existing pool found at {mount_point}"
            
            # Filter for data drives only
            data_drives = [drive for drive in available_drives if drive.role.value == 'data']
            
            # Find new drives not already in the pool
            existing_paths = set(existing_pool.source_paths)
            new_drives = [drive for drive in data_drives if drive.mount_point not in existing_paths]
            
            if not new_drives:
                return True, "No new drives available for expansion"
            
            # Extract new source paths
            new_source_paths = [drive.mount_point for drive in new_drives]
            
            # Expand the pool
            success, message = self.expand_pool(mount_point, new_source_paths)
            
            if success:
                logger.info(f"Auto-expanded pool {mount_point} with {len(new_drives)} new drives")
                return True, f"Auto-expanded pool with {len(new_drives)} new drives: {', '.join(new_source_paths)}"
            else:
                return False, f"Auto-expansion failed: {message}"
        
        except Exception as e:
            logger.error(f"Error auto-expanding pool: {e}")
            return False, f"Auto-expansion error: {str(e)}"
    
    def create_expansion_workflow(self, mount_point: str, new_source_paths: List[str]) -> Dict:
        """
        Create a workflow plan for pool expansion.
        
        Args:
            mount_point: Mount point of the pool to expand
            new_source_paths: List of new source paths to add
            
        Returns:
            Dictionary with expansion workflow steps
        """
        workflow = {
            'mount_point': mount_point,
            'new_source_paths': new_source_paths,
            'steps': [],
            'estimated_downtime': '30-60 seconds',
            'rollback_plan': [],
            'validation_checks': []
        }
        
        try:
            # Get existing pool
            existing_pool = self.get_pool_by_mount_point(mount_point)
            if existing_pool:
                workflow['current_source_paths'] = existing_pool.source_paths
                workflow['final_source_paths'] = existing_pool.source_paths + new_source_paths
            
            # Define workflow steps
            workflow['steps'] = [
                {
                    'step': 1,
                    'action': 'Validate new source paths',
                    'description': 'Check that new source paths exist and are accessible',
                    'critical': True
                },
                {
                    'step': 2,
                    'action': 'Validate pool integrity',
                    'description': 'Ensure existing pool is healthy before expansion',
                    'critical': True
                },
                {
                    'step': 3,
                    'action': 'Unmount existing pool',
                    'description': f'Temporarily unmount pool at {mount_point}',
                    'critical': True,
                    'downtime_start': True
                },
                {
                    'step': 4,
                    'action': 'Mount expanded pool',
                    'description': f'Mount pool with {len(new_source_paths)} additional drives',
                    'critical': True,
                    'downtime_end': True
                },
                {
                    'step': 5,
                    'action': 'Update fstab configuration',
                    'description': 'Update /etc/fstab with expanded pool configuration',
                    'critical': False
                },
                {
                    'step': 6,
                    'action': 'Update systemd unit',
                    'description': 'Update systemd mount unit for persistent mounting',
                    'critical': False
                },
                {
                    'step': 7,
                    'action': 'Validate expanded pool',
                    'description': 'Verify that expanded pool is working correctly',
                    'critical': True
                }
            ]
            
            # Define rollback plan
            workflow['rollback_plan'] = [
                'Stop any running applications using the pool',
                'Unmount the expanded pool',
                'Remount the original pool with previous configuration',
                'Restore fstab and systemd configurations from backup',
                'Validate original pool functionality'
            ]
            
            # Define validation checks
            workflow['validation_checks'] = [
                'All new source paths are accessible',
                'No duplicate source paths',
                'Existing pool is healthy',
                'Sufficient system resources available',
                'No applications currently using the pool'
            ]
            
        except Exception as e:
            workflow['error'] = f"Error creating workflow: {str(e)}"
        
        return workflow