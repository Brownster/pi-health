"""SnapRAID management and monitoring system."""

import re
import json
import logging
import threading
import uuid
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

from .system_executor import SystemCommandExecutor, CommandType
from .config_manager import ConfigManager


logger = logging.getLogger(__name__)


class SnapRAIDStatus(Enum):
    """SnapRAID system status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    SYNCING = "syncing"
    ERROR = "error"
    UNKNOWN = "unknown"


class ParityStatus(Enum):
    """Parity status."""
    UP_TO_DATE = "up_to_date"
    OUT_OF_SYNC = "out_of_sync"
    MISSING = "missing"
    ERROR = "error"
    UNKNOWN = "unknown"


class OperationStatus(Enum):
    """Asynchronous operation status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncOperation:
    """Information about an asynchronous SnapRAID operation."""
    operation_id: str
    operation_type: str  # sync, scrub, diff
    status: OperationStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    progress_percent: float = 0.0
    message: str = ""
    error_message: str = ""
    parameters: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize default values for mutable fields."""
        if self.parameters is None:
            self.parameters = {}


@dataclass
class DriveStatus:
    """Status information for a single drive in SnapRAID."""
    name: str
    device: str
    mount_point: str
    size_gb: float
    used_gb: float
    free_gb: float
    files: int
    status: str
    errors: int = 0
    
    @property
    def usage_percent(self) -> float:
        """Calculate usage percentage."""
        if self.size_gb == 0:
            return 0.0
        return (self.used_gb / self.size_gb) * 100


@dataclass
class ParityInfo:
    """Parity information."""
    status: ParityStatus
    coverage_percent: float
    last_sync: Optional[datetime]
    sync_duration: Optional[timedelta]
    errors: int = 0
    warnings: int = 0


@dataclass
class SnapRAIDStatusInfo:
    """Complete SnapRAID status information."""
    overall_status: SnapRAIDStatus
    parity_info: ParityInfo
    data_drives: List[DriveStatus]
    parity_drives: List[DriveStatus]
    total_files: int
    total_size_gb: float
    last_check: datetime
    config_path: str
    version: Optional[str] = None


class SnapRAIDManager:
    """Manages SnapRAID operations and status monitoring."""
    
    def __init__(self, config_manager: ConfigManager, dry_run: bool = False):
        """
        Initialize SnapRAID manager.
        
        Args:
            config_manager: Configuration manager instance
            dry_run: If True, commands will be logged but not executed
        """
        self.config_manager = config_manager
        self.executor = SystemCommandExecutor(dry_run=dry_run)
        self._status_cache: Optional[SnapRAIDStatusInfo] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self._async_operations: Dict[str, AsyncOperation] = {}
        self._operation_lock = threading.Lock()
    
    def get_status(self, use_cache: bool = True) -> Optional[SnapRAIDStatusInfo]:
        """
        Get SnapRAID status information.
        
        Args:
            use_cache: Whether to use cached status if available
            
        Returns:
            SnapRAIDStatusInfo object or None if status unavailable
        """
        # Check cache validity
        if (use_cache and self._status_cache and self._cache_timestamp and 
            datetime.now() - self._cache_timestamp < self._cache_ttl):
            return self._status_cache
        
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            # Execute snapraid status command
            success, stdout, stderr = self.executor.execute_snapraid_command(
                'status', config_path=config_path
            )
            
            if not success:
                logger.error(f"SnapRAID status command failed: {stderr}")
                return None
            
            # Parse the status output
            status_info = self._parse_status_output(stdout, config_path)
            
            # Update cache
            self._status_cache = status_info
            self._cache_timestamp = datetime.now()
            
            return status_info
        
        except Exception as e:
            logger.error(f"Error getting SnapRAID status: {e}")
            return None
    
    def sync(self, force: bool = False) -> Tuple[bool, str]:
        """
        Trigger SnapRAID parity synchronization.
        
        Args:
            force: Force sync even if no changes detected
            
        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            args = []
            if force:
                args.append('-f')
            
            logger.info("Starting SnapRAID sync operation")
            success, stdout, stderr = self.executor.execute_snapraid_command(
                'sync', config_path=config_path, additional_args=args
            )
            
            if success:
                # Invalidate status cache
                self._invalidate_cache()
                message = "SnapRAID sync completed successfully"
                logger.info(message)
                return True, message
            else:
                message = f"SnapRAID sync failed: {stderr}"
                logger.error(message)
                return False, message
        
        except Exception as e:
            message = f"Error during SnapRAID sync: {e}"
            logger.error(message)
            return False, message
    
    def scrub(self, percentage: int = 10) -> Tuple[bool, str]:
        """
        Start SnapRAID scrub operation for data integrity checking.
        
        Args:
            percentage: Percentage of data to scrub (1-100)
            
        Returns:
            Tuple of (success, message)
        """
        if not 1 <= percentage <= 100:
            raise ValueError("Percentage must be between 1 and 100")
        
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            args = ['-p', str(percentage)]
            
            logger.info(f"Starting SnapRAID scrub operation ({percentage}%)")
            success, stdout, stderr = self.executor.execute_snapraid_command(
                'scrub', config_path=config_path, additional_args=args
            )
            
            if success:
                message = f"SnapRAID scrub ({percentage}%) completed successfully"
                logger.info(message)
                return True, message
            else:
                message = f"SnapRAID scrub failed: {stderr}"
                logger.error(message)
                return False, message
        
        except Exception as e:
            message = f"Error during SnapRAID scrub: {e}"
            logger.error(message)
            return False, message
    
    def diff(self) -> Tuple[bool, str, List[str]]:
        """
        Show pending changes before sync.
        
        Returns:
            Tuple of (success, message, list of changes)
        """
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            logger.info("Getting SnapRAID diff")
            success, stdout, stderr = self.executor.execute_snapraid_command(
                'diff', config_path=config_path
            )
            
            if success:
                changes = self._parse_diff_output(stdout)
                message = f"Found {len(changes)} pending changes"
                logger.info(message)
                return True, message, changes
            else:
                message = f"SnapRAID diff failed: {stderr}"
                logger.error(message)
                return False, message, []
        
        except Exception as e:
            message = f"Error getting SnapRAID diff: {e}"
            logger.error(message)
            return False, message, []
    
    def check_config(self) -> Tuple[bool, str]:
        """
        Check SnapRAID configuration validity.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            # Check if config file exists
            if not Path(config_path).exists():
                return False, f"SnapRAID config file not found: {config_path}"
            
            # Try to run status command to validate config
            success, stdout, stderr = self.executor.execute_snapraid_command(
                'status', config_path=config_path
            )
            
            if success:
                return True, "SnapRAID configuration is valid"
            else:
                return False, f"SnapRAID configuration error: {stderr}"
        
        except Exception as e:
            return False, f"Error checking SnapRAID configuration: {e}"
    
    def _parse_status_output(self, output: str, config_path: str) -> SnapRAIDStatusInfo:
        """
        Parse SnapRAID status command output.
        
        Args:
            output: Raw status output
            config_path: Path to config file
            
        Returns:
            Parsed SnapRAIDStatusInfo object
        """
        lines = output.strip().split('\n')
        
        # Initialize data structures
        data_drives = []
        parity_drives = []
        parity_info = ParityInfo(
            status=ParityStatus.UNKNOWN,
            coverage_percent=0.0,
            last_sync=None,
            sync_duration=None
        )
        overall_status = SnapRAIDStatus.UNKNOWN
        total_files = 0
        total_size_gb = 0.0
        version = None
        
        # Parse line by line
        current_section = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Version information
            if line.startswith('SnapRAID'):
                version_match = re.search(r'SnapRAID\s+(\d+\.\d+)', line)
                if version_match:
                    version = version_match.group(1)
            
            # Section headers
            if 'Self test...' in line:
                current_section = 'self_test'
            elif 'Loading state from' in line:
                current_section = 'loading'
            elif 'Comparing...' in line:
                current_section = 'comparing'
            elif 'SUMMARY' in line:
                current_section = 'summary'
            
            # Parse drive information - look for lines with drive data
            # Format: Files Size Used Free Use Name
            # Example: 1234 500.0 GB 400.0 GB 100.0 GB 80% d1
            drive_match = re.match(r'^\s*(\d+)\s+([\d.]+)\s+GB\s+([\d.]+)\s+GB\s+([\d.]+)\s+GB\s+(\d+)%\s+(\w+)', line)
            if drive_match:
                files, size_gb, used_gb, free_gb, usage_pct, name = drive_match.groups()
                
                drive_status = DriveStatus(
                    name=name,
                    device=f"/dev/{name}",  # Placeholder device path
                    mount_point=f"/mnt/{name}",  # Placeholder mount point
                    size_gb=float(size_gb),
                    used_gb=float(used_gb),
                    free_gb=float(free_gb),
                    files=int(files),
                    status="healthy"
                )
                
                if name.startswith('parity'):
                    parity_drives.append(drive_status)
                else:
                    data_drives.append(drive_status)
            
            # Parse parity status
            if 'parity is' in line.lower():
                if 'up-to-date' in line.lower():
                    parity_info.status = ParityStatus.UP_TO_DATE
                elif 'out-of-sync' in line.lower():
                    parity_info.status = ParityStatus.OUT_OF_SYNC
                elif 'missing' in line.lower():
                    parity_info.status = ParityStatus.MISSING
            
            # Parse sync information
            sync_match = re.search(r'last sync was (\d+) days ago', line)
            if sync_match:
                days_ago = int(sync_match.group(1))
                parity_info.last_sync = datetime.now() - timedelta(days=days_ago)
            
            # Parse coverage percentage
            coverage_match = re.search(r'You have a (\d+)% of coverage', line)
            if coverage_match:
                parity_info.coverage_percent = float(coverage_match.group(1))
            
            # Parse totals
            if 'Total files:' in line:
                total_match = re.search(r'Total files:\s+(\d+)', line)
                if total_match:
                    total_files = int(total_match.group(1))
            
            if 'Total size:' in line:
                size_match = re.search(r'Total size:\s+([\d.]+)\s*GB', line)
                if size_match:
                    total_size_gb = float(size_match.group(1))
        
        # Determine overall status
        if parity_info.status == ParityStatus.UP_TO_DATE:
            overall_status = SnapRAIDStatus.HEALTHY
        elif parity_info.status == ParityStatus.OUT_OF_SYNC:
            overall_status = SnapRAIDStatus.DEGRADED
        elif parity_info.status == ParityStatus.MISSING:
            overall_status = SnapRAIDStatus.ERROR
        
        return SnapRAIDStatusInfo(
            overall_status=overall_status,
            parity_info=parity_info,
            data_drives=data_drives,
            parity_drives=parity_drives,
            total_files=total_files,
            total_size_gb=total_size_gb,
            last_check=datetime.now(),
            config_path=config_path,
            version=version
        )
    
    def _parse_diff_output(self, output: str) -> List[str]:
        """
        Parse SnapRAID diff command output.
        
        Args:
            output: Raw diff output
            
        Returns:
            List of change descriptions
        """
        changes = []
        lines = output.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for change indicators
            if any(indicator in line for indicator in ['add', 'remove', 'move', 'update', 'copy']):
                changes.append(line)
        
        return changes
    
    def _invalidate_cache(self) -> None:
        """Invalidate the status cache."""
        self._status_cache = None
        self._cache_timestamp = None
    
    def sync_async(self, force: bool = False) -> str:
        """
        Start SnapRAID parity synchronization asynchronously.
        
        Args:
            force: Force sync even if no changes detected
            
        Returns:
            Operation ID for tracking progress
        """
        operation_id = str(uuid.uuid4())
        
        with self._operation_lock:
            operation = AsyncOperation(
                operation_id=operation_id,
                operation_type="sync",
                status=OperationStatus.PENDING,
                start_time=datetime.now(),
                parameters={"force": force}
            )
            self._async_operations[operation_id] = operation
        
        # Start operation in background thread
        thread = threading.Thread(
            target=self._run_async_sync,
            args=(operation_id, force),
            daemon=True
        )
        thread.start()
        
        return operation_id
    
    def scrub_async(self, percentage: int = 10) -> str:
        """
        Start SnapRAID scrub operation asynchronously.
        
        Args:
            percentage: Percentage of data to scrub (1-100)
            
        Returns:
            Operation ID for tracking progress
        """
        if not 1 <= percentage <= 100:
            raise ValueError("Percentage must be between 1 and 100")
        
        operation_id = str(uuid.uuid4())
        
        with self._operation_lock:
            operation = AsyncOperation(
                operation_id=operation_id,
                operation_type="scrub",
                status=OperationStatus.PENDING,
                start_time=datetime.now(),
                parameters={"percentage": percentage}
            )
            self._async_operations[operation_id] = operation
        
        # Start operation in background thread
        thread = threading.Thread(
            target=self._run_async_scrub,
            args=(operation_id, percentage),
            daemon=True
        )
        thread.start()
        
        return operation_id
    
    def get_operation_status(self, operation_id: str) -> Optional[AsyncOperation]:
        """
        Get the status of an asynchronous operation.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            AsyncOperation object or None if not found
        """
        with self._operation_lock:
            return self._async_operations.get(operation_id)
    
    def list_operations(self, active_only: bool = False) -> List[AsyncOperation]:
        """
        List all operations.
        
        Args:
            active_only: If True, only return pending/running operations
            
        Returns:
            List of AsyncOperation objects
        """
        with self._operation_lock:
            operations = list(self._async_operations.values())
            
            if active_only:
                active_statuses = {OperationStatus.PENDING, OperationStatus.RUNNING}
                operations = [op for op in operations if op.status in active_statuses]
            
            return sorted(operations, key=lambda x: x.start_time, reverse=True)
    
    def cancel_operation(self, operation_id: str) -> bool:
        """
        Cancel an asynchronous operation.
        
        Args:
            operation_id: Operation ID
            
        Returns:
            True if operation was cancelled, False if not found or already completed
        """
        with self._operation_lock:
            operation = self._async_operations.get(operation_id)
            if operation and operation.status in {OperationStatus.PENDING, OperationStatus.RUNNING}:
                operation.status = OperationStatus.CANCELLED
                operation.end_time = datetime.now()
                operation.message = "Operation cancelled by user"
                return True
            return False
    
    def _run_async_sync(self, operation_id: str, force: bool) -> None:
        """
        Run sync operation asynchronously.
        
        Args:
            operation_id: Operation ID
            force: Force sync flag
        """
        try:
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if not operation or operation.status == OperationStatus.CANCELLED:
                    return
                operation.status = OperationStatus.RUNNING
            
            # Run the sync operation
            success, message = self.sync(force=force)
            
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if operation:
                    operation.end_time = datetime.now()
                    operation.progress_percent = 100.0
                    if success:
                        operation.status = OperationStatus.COMPLETED
                        operation.message = message
                    else:
                        operation.status = OperationStatus.FAILED
                        operation.error_message = message
        
        except Exception as e:
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if operation:
                    operation.end_time = datetime.now()
                    operation.status = OperationStatus.FAILED
                    operation.error_message = str(e)
    
    def _run_async_scrub(self, operation_id: str, percentage: int) -> None:
        """
        Run scrub operation asynchronously.
        
        Args:
            operation_id: Operation ID
            percentage: Scrub percentage
        """
        try:
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if not operation or operation.status == OperationStatus.CANCELLED:
                    return
                operation.status = OperationStatus.RUNNING
            
            # Run the scrub operation
            success, message = self.scrub(percentage=percentage)
            
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if operation:
                    operation.end_time = datetime.now()
                    operation.progress_percent = 100.0
                    if success:
                        operation.status = OperationStatus.COMPLETED
                        operation.message = message
                    else:
                        operation.status = OperationStatus.FAILED
                        operation.error_message = message
        
        except Exception as e:
            with self._operation_lock:
                operation = self._async_operations.get(operation_id)
                if operation:
                    operation.end_time = datetime.now()
                    operation.status = OperationStatus.FAILED
                    operation.error_message = str(e)
    
    def to_dict(self, status_info: SnapRAIDStatusInfo) -> Dict[str, Any]:
        """
        Convert SnapRAIDStatusInfo to dictionary for JSON serialization.
        
        Args:
            status_info: Status information to convert
            
        Returns:
            Dictionary representation
        """
        result = asdict(status_info)
        
        # Convert enums to strings
        result['overall_status'] = status_info.overall_status.value
        result['parity_info']['status'] = status_info.parity_info.status.value
        
        # Add usage_percent property to drive data
        for drive_data in result['data_drives']:
            drive_data['usage_percent'] = round((drive_data['used_gb'] / drive_data['size_gb']) * 100, 2) if drive_data['size_gb'] > 0 else 0.0
        
        for drive_data in result['parity_drives']:
            drive_data['usage_percent'] = round((drive_data['used_gb'] / drive_data['size_gb']) * 100, 2) if drive_data['size_gb'] > 0 else 0.0
        
        # Convert datetime objects to ISO strings
        if status_info.parity_info.last_sync:
            result['parity_info']['last_sync'] = status_info.parity_info.last_sync.isoformat()
        
        if status_info.parity_info.sync_duration:
            result['parity_info']['sync_duration'] = str(status_info.parity_info.sync_duration)
        
        result['last_check'] = status_info.last_check.isoformat()
        
        return result
    
    def generate_config(self, data_drives: List[str], parity_drives: List[str], 
                       content_locations: Optional[List[str]] = None) -> str:
        """
        Generate SnapRAID configuration file content based on detected drives.
        
        Args:
            data_drives: List of data drive mount points
            parity_drives: List of parity drive mount points
            content_locations: Optional list of content file locations
            
        Returns:
            Generated configuration file content
        """
        if not data_drives:
            raise ValueError("At least one data drive is required")
        
        if not parity_drives:
            raise ValueError("At least one parity drive is required")
        
        config_lines = [
            "# SnapRAID configuration file",
            "# Generated automatically by NAS management system",
            f"# Generated on: {datetime.now().isoformat()}",
            "",
        ]
        
        # Add parity drives
        for i, parity_drive in enumerate(parity_drives):
            if i == 0:
                config_lines.append(f"parity {parity_drive}/snapraid.parity")
            else:
                config_lines.append(f"2-parity {parity_drive}/snapraid.2-parity")
        
        config_lines.append("")
        
        # Add content file locations
        if content_locations:
            for location in content_locations:
                config_lines.append(f"content {location}")
        else:
            # Default content locations
            config_lines.extend([
                "content /var/snapraid/snapraid.content",
                f"content {data_drives[0]}/snapraid.content",
                f"content {parity_drives[0]}/snapraid.content"
            ])
        
        config_lines.append("")
        
        # Add data drives
        for i, data_drive in enumerate(data_drives):
            drive_name = f"d{i+1}"
            config_lines.append(f"data {drive_name} {data_drive}")
        
        config_lines.extend([
            "",
            "# Exclusions",
            "exclude *.tmp",
            "exclude *.temp",
            "exclude *.log",
            "exclude /lost+found/",
            "exclude *.!sync",
            "exclude .AppleDouble",
            "exclude .DS_Store",
            "exclude .Thumbs.db",
            "exclude .fseventsd",
            "exclude .Spotlight-V100",
            "exclude .TemporaryItems",
            "exclude .Trashes",
            "",
            "# Block size (default is 256KB)",
            "block_size 256",
            "",
            "# Hash size (default is 16 bytes)",
            "hash_size 16",
            "",
            "# Auto-save state every 10GB processed",
            "autosave 10",
            ""
        ])
        
        return "\n".join(config_lines)
    
    def validate_config(self, config_content: str) -> Tuple[bool, List[str]]:
        """
        Validate SnapRAID configuration content.
        
        Args:
            config_content: Configuration file content to validate
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        lines = config_content.strip().split('\n')
        
        # Track required elements
        has_parity = False
        has_content = False
        has_data = False
        data_drives = set()
        parity_paths = set()
        content_paths = set()
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse configuration directives
            parts = line.split()
            if len(parts) < 2:
                continue
            
            directive = parts[0].lower()
            
            if directive == 'parity':
                has_parity = True
                parity_path = parts[1]
                if parity_path in parity_paths:
                    errors.append(f"Line {line_num}: Duplicate parity path: {parity_path}")
                parity_paths.add(parity_path)
                
                # Check if path exists (directory part)
                parity_dir = str(Path(parity_path).parent)
                if not Path(parity_dir).exists():
                    errors.append(f"Line {line_num}: Parity directory does not exist: {parity_dir}")
            
            elif directive == '2-parity':
                parity_path = parts[1]
                if parity_path in parity_paths:
                    errors.append(f"Line {line_num}: Duplicate parity path: {parity_path}")
                parity_paths.add(parity_path)
                
                # Check if path exists (directory part)
                parity_dir = str(Path(parity_path).parent)
                if not Path(parity_dir).exists():
                    errors.append(f"Line {line_num}: Parity directory does not exist: {parity_dir}")
            
            elif directive == 'content':
                has_content = True
                content_path = parts[1]
                if content_path in content_paths:
                    errors.append(f"Line {line_num}: Duplicate content path: {content_path}")
                content_paths.add(content_path)
                
                # Check if directory exists
                content_dir = str(Path(content_path).parent)
                if not Path(content_dir).exists():
                    errors.append(f"Line {line_num}: Content directory does not exist: {content_dir}")
            
            elif directive == 'data':
                has_data = True
                if len(parts) < 3:
                    errors.append(f"Line {line_num}: Data directive requires name and path")
                    continue
                
                drive_name = parts[1]
                drive_path = parts[2]
                
                if drive_name in data_drives:
                    errors.append(f"Line {line_num}: Duplicate data drive name: {drive_name}")
                data_drives.add(drive_name)
                
                # Check if path exists
                if not Path(drive_path).exists():
                    errors.append(f"Line {line_num}: Data drive path does not exist: {drive_path}")
        
        # Check for required elements
        if not has_parity:
            errors.append("Configuration missing required 'parity' directive")
        
        if not has_content:
            errors.append("Configuration missing required 'content' directive")
        
        if not has_data:
            errors.append("Configuration missing required 'data' directive")
        
        return len(errors) == 0, errors
    
    def backup_config(self, config_path: str) -> str:
        """
        Create a backup of the current configuration file.
        
        Args:
            config_path: Path to configuration file
            
        Returns:
            Path to backup file
        """
        if not Path(config_path).exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{config_path}.backup_{timestamp}"
        
        # Copy the file
        import shutil
        shutil.copy2(config_path, backup_path)
        
        logger.info(f"Configuration backed up to: {backup_path}")
        return backup_path
    
    def update_config(self, data_drives: List[str], parity_drives: List[str],
                     content_locations: Optional[List[str]] = None,
                     backup: bool = True) -> Tuple[bool, str]:
        """
        Update SnapRAID configuration file with new drive configuration.
        
        Args:
            data_drives: List of data drive mount points
            parity_drives: List of parity drive mount points
            content_locations: Optional list of content file locations
            backup: Whether to backup existing config before updating
            
        Returns:
            Tuple of (success, message)
        """
        try:
            config = self.config_manager.load_config()
            config_path = config.snapraid_config_path
            
            # Backup existing config if requested and file exists
            if backup and Path(config_path).exists():
                backup_path = self.backup_config(config_path)
                logger.info(f"Existing configuration backed up to: {backup_path}")
            
            # Generate new configuration
            new_config_content = self.generate_config(
                data_drives=data_drives,
                parity_drives=parity_drives,
                content_locations=content_locations
            )
            
            # Validate the new configuration
            is_valid, errors = self.validate_config(new_config_content)
            if not is_valid:
                error_msg = "Generated configuration is invalid:\n" + "\n".join(errors)
                logger.error(error_msg)
                return False, error_msg
            
            # Ensure directory exists
            config_dir = Path(config_path).parent
            config_dir.mkdir(parents=True, exist_ok=True)
            
            # Write new configuration
            with open(config_path, 'w') as f:
                f.write(new_config_content)
            
            # Invalidate status cache since config changed
            self._invalidate_cache()
            
            message = f"SnapRAID configuration updated successfully: {config_path}"
            logger.info(message)
            return True, message
        
        except Exception as e:
            error_msg = f"Failed to update SnapRAID configuration: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def auto_update_config_from_drives(self, drive_manager) -> Tuple[bool, str]:
        """
        Automatically update SnapRAID configuration based on detected drives.
        
        Args:
            drive_manager: DriveManager instance to discover drives
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Discover available drives
            drives = drive_manager.discover_drives()
            
            # Separate data and parity drives
            data_drives = []
            parity_drives = []
            
            for drive in drives:
                if drive.role.value == "data":
                    data_drives.append(drive.mount_point)
                elif drive.role.value == "parity":
                    parity_drives.append(drive.mount_point)
            
            if not data_drives:
                return False, "No data drives detected for SnapRAID configuration"
            
            if not parity_drives:
                return False, "No parity drives detected for SnapRAID configuration"
            
            # Update configuration
            return self.update_config(
                data_drives=data_drives,
                parity_drives=parity_drives
            )
        
        except Exception as e:
            error_msg = f"Failed to auto-update SnapRAID configuration: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def operation_to_dict(self, operation: AsyncOperation) -> Dict[str, Any]:
        """
        Convert AsyncOperation to dictionary for JSON serialization.
        
        Args:
            operation: Operation to convert
            
        Returns:
            Dictionary representation
        """
        result = asdict(operation)
        
        # Convert enums to strings
        result['status'] = operation.status.value
        
        # Convert datetime objects to ISO strings
        result['start_time'] = operation.start_time.isoformat()
        if operation.end_time:
            result['end_time'] = operation.end_time.isoformat()
        
        return result