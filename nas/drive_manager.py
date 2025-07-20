"""Drive detection and management utilities."""

import os
import re
import subprocess
from typing import List, Optional, Dict
import psutil
import logging

from .models import DriveConfig, DriveRole, HealthStatus
from .smart_manager import SMARTManager

logger = logging.getLogger(__name__)


class DriveManager:
    """Manages drive detection and enumeration for NAS operations."""
    
    # System partitions to exclude from NAS management
    SYSTEM_MOUNT_POINTS = {
        '/', '/boot', '/boot/efi', '/boot/firmware', '/tmp', '/var', '/usr',
        '/home', '/opt', '/srv', '/proc', '/sys', '/dev', '/run'
    }
    
    # System filesystem types to exclude
    SYSTEM_FILESYSTEMS = {
        'proc', 'sysfs', 'devtmpfs', 'devpts', 'tmpfs', 'securityfs',
        'cgroup', 'cgroup2', 'pstore', 'bpf', 'tracefs', 'debugfs',
        'mqueue', 'hugetlbfs', 'fusectl', 'configfs', 'overlay'
    }
    
    def __init__(self):
        """Initialize the DriveManager."""
        self._drive_cache: Dict[str, DriveConfig] = {}
        self._smart_manager = SMARTManager()
    
    def discover_drives(self) -> List[DriveConfig]:
        """
        Discover and enumerate USB drives using psutil.disk_partitions().
        
        Returns:
            List of DriveConfig objects for data drives
        """
        drives = []
        
        try:
            # Get all disk partitions
            partitions = psutil.disk_partitions(all=True)
            
            for partition in partitions:
                # Skip if this is a system partition
                if self._is_system_partition(partition):
                    continue
                
                # Try to get drive information
                drive_config = self._create_drive_config(partition)
                if drive_config:
                    drives.append(drive_config)
                    logger.info(f"Discovered drive: {drive_config.device_path} at {drive_config.mount_point}")
        
        except Exception as e:
            logger.error(f"Error discovering drives: {e}")
        
        # Update cache
        self._drive_cache = {drive.device_path: drive for drive in drives}
        
        return drives
    
    def get_drive_by_device(self, device_path: str) -> Optional[DriveConfig]:
        """
        Get drive configuration by device path.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            
        Returns:
            DriveConfig if found, None otherwise
        """
        return self._drive_cache.get(device_path)
    
    def get_drive_by_mount_point(self, mount_point: str) -> Optional[DriveConfig]:
        """
        Get drive configuration by mount point.
        
        Args:
            mount_point: Mount point path (e.g., '/mnt/disk1')
            
        Returns:
            DriveConfig if found, None otherwise
        """
        for drive in self._drive_cache.values():
            if drive.mount_point == mount_point:
                return drive
        return None
    
    def refresh_drive_usage(self, device_path: str) -> bool:
        """
        Refresh usage statistics for a specific drive.
        
        Args:
            device_path: Device path to refresh
            
        Returns:
            True if successful, False otherwise
        """
        drive = self._drive_cache.get(device_path)
        if not drive:
            return False
        
        try:
            usage = psutil.disk_usage(drive.mount_point)
            drive.size_bytes = usage.total
            drive.used_bytes = usage.used
            return True
        except Exception as e:
            logger.error(f"Error refreshing usage for {device_path}: {e}")
            return False
    
    def _is_system_partition(self, partition) -> bool:
        """
        Check if a partition is a system partition that should be excluded.
        
        Args:
            partition: psutil partition object
            
        Returns:
            True if this is a system partition
        """
        # Check mount point
        if partition.mountpoint in self.SYSTEM_MOUNT_POINTS:
            return True
        
        # Check if mount point starts with system paths
        for sys_path in self.SYSTEM_MOUNT_POINTS:
            if partition.mountpoint.startswith(sys_path + '/'):
                return True
        
        # Check filesystem type
        if partition.fstype.lower() in self.SYSTEM_FILESYSTEMS:
            return True
        
        # Check if it's a loop device (often used for system images)
        if '/dev/loop' in partition.device:
            return True
        
        # Check if it's a RAM disk
        if partition.device.startswith('/dev/ram'):
            return True
        
        return False
    
    def _create_drive_config(self, partition) -> Optional[DriveConfig]:
        """
        Create a DriveConfig from a psutil partition.
        
        Args:
            partition: psutil partition object
            
        Returns:
            DriveConfig if successful, None otherwise
        """
        try:
            # Get disk usage
            usage = psutil.disk_usage(partition.mountpoint)
            
            # Get UUID
            uuid = self._get_partition_uuid(partition.device)
            
            # Determine drive role (default to DATA for now)
            role = self._determine_drive_role(partition.mountpoint)
            
            # Get health status (basic check for now)
            health = self._get_basic_health_status(partition.mountpoint)
            
            return DriveConfig(
                device_path=partition.device,
                uuid=uuid or "unknown",
                mount_point=partition.mountpoint,
                filesystem=partition.fstype,
                role=role,
                size_bytes=usage.total,
                used_bytes=usage.used,
                health_status=health
            )
        
        except Exception as e:
            logger.error(f"Error creating drive config for {partition.device}: {e}")
            return None
    
    def _get_partition_uuid(self, device_path: str) -> Optional[str]:
        """
        Get the UUID of a partition using blkid.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            
        Returns:
            UUID string if found, None otherwise
        """
        try:
            result = subprocess.run(
                ['blkid', '-s', 'UUID', '-o', 'value', device_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        
        except Exception as e:
            logger.debug(f"Could not get UUID for {device_path}: {e}")
        
        return None
    
    def _determine_drive_role(self, mount_point: str) -> DriveRole:
        """
        Determine the role of a drive based on its mount point.
        
        Args:
            mount_point: Mount point path
            
        Returns:
            DriveRole enum value
        """
        # Check for parity drive patterns
        if 'parity' in mount_point.lower():
            return DriveRole.PARITY
        
        # Check for data drive patterns
        if any(pattern in mount_point.lower() for pattern in ['disk', 'data', 'mnt']):
            return DriveRole.DATA
        
        return DriveRole.UNKNOWN
    
    def _get_basic_health_status(self, mount_point: str) -> HealthStatus:
        """
        Get basic health status by checking if the mount point is accessible.
        
        Args:
            mount_point: Mount point path
            
        Returns:
            HealthStatus enum value
        """
        try:
            # Try to access the mount point
            if os.path.exists(mount_point) and os.access(mount_point, os.R_OK):
                return HealthStatus.HEALTHY
            else:
                return HealthStatus.DEGRADED
        except Exception:
            return HealthStatus.FAILED
    
    def is_usb_drive(self, device_path: str) -> bool:
        """
        Check if a device is a USB drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            
        Returns:
            True if it's a USB drive, False otherwise
        """
        try:
            # Extract the base device (e.g., 'sdb' from '/dev/sdb1')
            base_device = re.sub(r'\d+$', '', device_path.split('/')[-1])
            
            # Check if it's connected via USB
            usb_path = f"/sys/block/{base_device}/removable"
            if os.path.exists(usb_path):
                with open(usb_path, 'r') as f:
                    return f.read().strip() == '1'
        
        except Exception as e:
            logger.debug(f"Could not determine if {device_path} is USB: {e}")
        
        return False
    
    def get_smart_health(self, device_path: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get SMART health status for a drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with SMART health information, None if not available
        """
        try:
            # Convert partition path to base device path for SMART
            base_device = self._get_base_device_path(device_path)
            
            # Check if SMART is available
            if not self._smart_manager.is_smart_available(base_device):
                return None
            
            # Get SMART health status
            smart_status = self._smart_manager.get_health_status(base_device, use_cache)
            if not smart_status:
                return None
            
            # Convert to dictionary for API response
            return {
                'overall_health': smart_status.overall_health,
                'temperature': smart_status.temperature,
                'power_on_hours': smart_status.power_on_hours,
                'power_cycle_count': smart_status.power_cycle_count,
                'reallocated_sectors': smart_status.reallocated_sectors,
                'pending_sectors': smart_status.pending_sectors,
                'uncorrectable_sectors': smart_status.uncorrectable_sectors,
                'last_updated': smart_status.last_updated.isoformat() if smart_status.last_updated else None
            }
        
        except Exception as e:
            logger.error(f"Error getting SMART health for {device_path}: {e}")
            return None
    
    def start_smart_test(self, device_path: str, test_type: str) -> bool:
        """
        Start a SMART test on a drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            test_type: Type of test ('short', 'long', 'conveyance')
            
        Returns:
            True if test started successfully, False otherwise
        """
        try:
            from .smart_manager import SMARTTestType
            
            # Convert partition path to base device path
            base_device = self._get_base_device_path(device_path)
            
            # Map test type string to enum
            test_type_map = {
                'short': SMARTTestType.SHORT,
                'long': SMARTTestType.LONG,
                'conveyance': SMARTTestType.CONVEYANCE
            }
            
            if test_type not in test_type_map:
                logger.error(f"Invalid SMART test type: {test_type}")
                return False
            
            return self._smart_manager.start_test(base_device, test_type_map[test_type])
        
        except Exception as e:
            logger.error(f"Error starting SMART test on {device_path}: {e}")
            return False
    
    def get_smart_test_status(self, device_path: str) -> Optional[Dict]:
        """
        Get SMART test status for a drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            
        Returns:
            Dictionary with test status information, None if not available
        """
        try:
            # Convert partition path to base device path
            base_device = self._get_base_device_path(device_path)
            
            test_result = self._smart_manager.get_test_status(base_device)
            if not test_result:
                return None
            
            return {
                'test_type': test_result.test_type.value,
                'status': test_result.status.value,
                'progress': test_result.progress,
                'estimated_completion': test_result.estimated_completion.isoformat() if test_result.estimated_completion else None,
                'result_message': test_result.result_message,
                'started_at': test_result.started_at.isoformat() if test_result.started_at else None,
                'completed_at': test_result.completed_at.isoformat() if test_result.completed_at else None
            }
        
        except Exception as e:
            logger.error(f"Error getting SMART test status for {device_path}: {e}")
            return None
    
    def get_smart_health_with_history(self, device_path: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Get SMART health status and record it to history.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            use_cache: Whether to use cached data
            
        Returns:
            Dictionary with SMART health information, None if not available
        """
        try:
            # Convert partition path to base device path for SMART
            base_device = self._get_base_device_path(device_path)
            
            # Check if SMART is available
            if not self._smart_manager.is_smart_available(base_device):
                return None
            
            # Get SMART health status with history recording
            smart_status = self._smart_manager.get_health_status_with_history(base_device, use_cache)
            if not smart_status:
                return None
            
            # Convert to dictionary for API response
            return {
                'overall_health': smart_status.overall_health,
                'temperature': smart_status.temperature,
                'power_on_hours': smart_status.power_on_hours,
                'power_cycle_count': smart_status.power_cycle_count,
                'reallocated_sectors': smart_status.reallocated_sectors,
                'pending_sectors': smart_status.pending_sectors,
                'uncorrectable_sectors': smart_status.uncorrectable_sectors,
                'last_updated': smart_status.last_updated.isoformat() if smart_status.last_updated else None
            }
        
        except Exception as e:
            logger.error(f"Error getting SMART health with history for {device_path}: {e}")
            return None
    
    def get_smart_health_history(self, device_path: str, days: int = 7) -> List[Dict]:
        """
        Get SMART health history for a drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            days: Number of days of history to retrieve
            
        Returns:
            List of health history entries as dictionaries
        """
        try:
            # Convert partition path to base device path
            base_device = self._get_base_device_path(device_path)
            
            history = self._smart_manager.get_health_history(base_device, days)
            
            # Convert to dictionaries for API response
            return [
                {
                    'device_path': entry.device_path,
                    'timestamp': entry.timestamp.isoformat(),
                    'overall_health': entry.overall_health,
                    'temperature': entry.temperature,
                    'power_on_hours': entry.power_on_hours,
                    'power_cycle_count': entry.power_cycle_count,
                    'reallocated_sectors': entry.reallocated_sectors,
                    'pending_sectors': entry.pending_sectors,
                    'uncorrectable_sectors': entry.uncorrectable_sectors
                }
                for entry in history
            ]
        
        except Exception as e:
            logger.error(f"Error getting SMART health history for {device_path}: {e}")
            return []
    
    def get_smart_trend_analysis(self, device_path: str, days: int = 7) -> Optional[Dict]:
        """
        Get SMART trend analysis for a drive.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb1')
            days: Number of days to analyze
            
        Returns:
            Dictionary with trend analysis results, None if insufficient data
        """
        try:
            # Convert partition path to base device path
            base_device = self._get_base_device_path(device_path)
            
            analysis = self._smart_manager.analyze_health_trends(base_device, days)
            if not analysis:
                return None
            
            # Convert to dictionary for API response
            return {
                'device_path': analysis.device_path,
                'analysis_period_days': analysis.analysis_period_days,
                'temperature_trend': analysis.temperature_trend,
                'temperature_avg': analysis.temperature_avg,
                'temperature_max': analysis.temperature_max,
                'reallocated_sectors_trend': analysis.reallocated_sectors_trend,
                'pending_sectors_trend': analysis.pending_sectors_trend,
                'health_degradation_risk': analysis.health_degradation_risk,
                'recommendations': analysis.recommendations
            }
        
        except Exception as e:
            logger.error(f"Error getting SMART trend analysis for {device_path}: {e}")
            return None
    
    def _get_base_device_path(self, device_path: str) -> str:
        """
        Convert a partition device path to base device path for SMART operations.
        
        Args:
            device_path: Partition device path (e.g., '/dev/sdb1')
            
        Returns:
            Base device path (e.g., '/dev/sdb')
        """
        # Remove partition number from device path
        base_device = re.sub(r'\d+$', '', device_path)
        return base_device