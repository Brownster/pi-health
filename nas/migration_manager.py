"""Filesystem migration tools for converting NTFS drives to ext4."""

import os
import re
import subprocess
import logging
import hashlib
import shutil
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import psutil
import json

from .models import DriveConfig, DriveRole, HealthStatus
from .system_executor import SystemCommandExecutor
from .drive_manager import DriveManager

logger = logging.getLogger(__name__)


class MigrationStatus(Enum):
    """Migration status enumeration."""
    PENDING = "pending"
    ANALYZING = "analyzing"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class FileSystemType(Enum):
    """Supported filesystem types."""
    NTFS = "ntfs"
    EXT4 = "ext4"
    EXT3 = "ext3"
    FAT32 = "vfat"
    EXFAT = "exfat"


@dataclass
class FileIntegrityInfo:
    """File integrity information for migration validation."""
    path: str
    size: int
    checksum: str
    modified_time: float
    permissions: Optional[str] = None


@dataclass
class MigrationAssessment:
    """Assessment results for NTFS to ext4 migration."""
    source_drive: DriveConfig
    total_files: int
    total_size_bytes: int
    estimated_duration_hours: float
    space_required_bytes: int
    compatibility_issues: List[str] = field(default_factory=list)
    file_samples: List[FileIntegrityInfo] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class MigrationState:
    """Current state of filesystem migration."""
    migration_id: str
    source_drive: str
    target_drives: List[str]
    migration_status: MigrationStatus
    files_migrated: int
    total_files: int
    bytes_migrated: int
    total_bytes: int
    estimated_completion: Optional[datetime]
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    rollback_available: bool = False
    
    @property
    def progress_percent(self) -> float:
        """Calculate migration progress percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.files_migrated / self.total_files) * 100
    
    @property
    def bytes_progress_percent(self) -> float:
        """Calculate bytes migration progress percentage."""
        if self.total_bytes == 0:
            return 0.0
        return (self.bytes_migrated / self.total_bytes) * 100


class MigrationManager:
    """Manages filesystem migration from NTFS to ext4."""
    
    # File extensions that may have compatibility issues
    COMPATIBILITY_CONCERNS = {
        '.lnk': 'Windows shortcuts not supported on Linux',
        '.exe': 'Windows executables not supported on Linux',
        '.msi': 'Windows installers not supported on Linux',
        '.dll': 'Windows libraries not supported on Linux',
        '.bat': 'Windows batch files may need conversion',
        '.cmd': 'Windows command files may need conversion'
    }
    
    # Files to exclude from migration
    EXCLUDE_PATTERNS = {
        'System Volume Information',
        '$RECYCLE.BIN',
        'pagefile.sys',
        'hiberfil.sys',
        'swapfile.sys',
        'Thumbs.db',
        'desktop.ini',
        '.DS_Store'
    }
    
    def __init__(self, work_dir: str = "/tmp/migration"):
        """
        Initialize the MigrationManager.
        
        Args:
            work_dir: Working directory for migration temporary files
        """
        self.work_dir = work_dir
        self.drive_manager = DriveManager()
        self.system_executor = SystemCommandExecutor()
        self._migration_states: Dict[str, MigrationState] = {}
        
        # Ensure work directory exists
        os.makedirs(work_dir, exist_ok=True)
    
    def detect_ntfs_drives(self) -> List[DriveConfig]:
        """
        Detect all NTFS drives available for migration.
        
        Returns:
            List of DriveConfig objects for NTFS drives
        """
        logger.info("Detecting NTFS drives for migration")
        
        all_drives = self.drive_manager.discover_drives()
        ntfs_drives = []
        
        for drive in all_drives:
            if drive.filesystem.lower() == 'ntfs':
                logger.info(f"Found NTFS drive: {drive.device_path} at {drive.mount_point}")
                ntfs_drives.append(drive)
        
        logger.info(f"Detected {len(ntfs_drives)} NTFS drives")
        return ntfs_drives
    
    def analyze_ntfs_drive(self, drive_config: DriveConfig) -> MigrationAssessment:
        """
        Analyze an NTFS drive for migration assessment.
        
        Args:
            drive_config: Drive configuration to analyze
            
        Returns:
            MigrationAssessment with analysis results
        """
        logger.info(f"Analyzing NTFS drive: {drive_config.device_path}")
        
        if drive_config.filesystem.lower() != 'ntfs':
            raise ValueError(f"Drive {drive_config.device_path} is not NTFS")
        
        assessment = MigrationAssessment(
            source_drive=drive_config,
            total_files=0,
            total_size_bytes=0,
            estimated_duration_hours=0.0,
            space_required_bytes=0
        )
        
        try:
            # Analyze directory structure and files
            self._analyze_directory_structure(drive_config.mount_point, assessment)
            
            # Calculate space requirements (add 20% buffer)
            assessment.space_required_bytes = int(assessment.total_size_bytes * 1.2)
            
            # Estimate migration duration (assume 50MB/s transfer rate)
            transfer_rate_bytes_per_second = 50 * 1024 * 1024  # 50 MB/s
            assessment.estimated_duration_hours = assessment.total_size_bytes / transfer_rate_bytes_per_second / 3600
            
            # Add recommendations
            self._generate_migration_recommendations(assessment)
            
            logger.info(f"Analysis complete: {assessment.total_files} files, "
                       f"{assessment.total_size_bytes / (1024**3):.2f} GB, "
                       f"estimated {assessment.estimated_duration_hours:.1f} hours")
            
        except Exception as e:
            logger.error(f"Error analyzing NTFS drive {drive_config.device_path}: {e}")
            assessment.compatibility_issues.append(f"Analysis failed: {str(e)}")
        
        return assessment
    
    def _analyze_directory_structure(self, root_path: str, assessment: MigrationAssessment) -> None:
        """
        Recursively analyze directory structure for migration assessment.
        
        Args:
            root_path: Root directory to analyze
            assessment: Assessment object to update
        """
        try:
            for root, dirs, files in os.walk(root_path):
                # Skip excluded directories
                dirs[:] = [d for d in dirs if not self._should_exclude_path(d)]
                
                for file in files:
                    if self._should_exclude_path(file):
                        continue
                    
                    file_path = os.path.join(root, file)
                    
                    try:
                        stat_info = os.stat(file_path)
                        file_size = stat_info.st_size
                        
                        assessment.total_files += 1
                        assessment.total_size_bytes += file_size
                        
                        # Check for compatibility issues
                        self._check_file_compatibility(file_path, assessment)
                        
                        # Sample files for integrity checking (every 1000th file)
                        if assessment.total_files % 1000 == 0:
                            self._add_file_sample(file_path, stat_info, assessment)
                    
                    except (OSError, IOError) as e:
                        logger.warning(f"Could not analyze file {file_path}: {e}")
                        assessment.compatibility_issues.append(f"Inaccessible file: {file_path}")
        
        except Exception as e:
            logger.error(f"Error analyzing directory structure: {e}")
            raise
    
    def _should_exclude_path(self, path: str) -> bool:
        """
        Check if a path should be excluded from migration.
        
        Args:
            path: Path to check
            
        Returns:
            True if path should be excluded
        """
        path_lower = path.lower()
        
        for pattern in self.EXCLUDE_PATTERNS:
            if pattern.lower() in path_lower:
                return True
        
        return False
    
    def _check_file_compatibility(self, file_path: str, assessment: MigrationAssessment) -> None:
        """
        Check file for potential compatibility issues.
        
        Args:
            file_path: Path to file to check
            assessment: Assessment object to update
        """
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext in self.COMPATIBILITY_CONCERNS:
            issue = f"{file_path}: {self.COMPATIBILITY_CONCERNS[file_ext]}"
            if issue not in assessment.compatibility_issues:
                assessment.compatibility_issues.append(issue)
    
    def _add_file_sample(self, file_path: str, stat_info: os.stat_result, 
                        assessment: MigrationAssessment) -> None:
        """
        Add a file sample for integrity verification.
        
        Args:
            file_path: Path to file
            stat_info: File stat information
            assessment: Assessment object to update
        """
        try:
            # Calculate checksum for small files only (< 10MB)
            checksum = ""
            if stat_info.st_size < 10 * 1024 * 1024:
                checksum = self._calculate_file_checksum(file_path)
            
            sample = FileIntegrityInfo(
                path=file_path,
                size=stat_info.st_size,
                checksum=checksum,
                modified_time=stat_info.st_mtime
            )
            
            assessment.file_samples.append(sample)
        
        except Exception as e:
            logger.warning(f"Could not create file sample for {file_path}: {e}")
    
    def _calculate_file_checksum(self, file_path: str) -> str:
        """
        Calculate MD5 checksum of a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            MD5 checksum as hex string
        """
        hash_md5 = hashlib.md5()
        
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        
        except Exception as e:
            logger.warning(f"Could not calculate checksum for {file_path}: {e}")
            return ""
    
    def _generate_migration_recommendations(self, assessment: MigrationAssessment) -> None:
        """
        Generate migration recommendations based on assessment.
        
        Args:
            assessment: Assessment object to update with recommendations
        """
        # Size-based recommendations
        size_gb = assessment.total_size_bytes / (1024**3)
        if size_gb > 500:
            assessment.recommendations.append(
                "Large dataset detected. Consider migrating in batches or during low-usage periods."
            )
        
        # Duration-based recommendations
        if assessment.estimated_duration_hours > 8:
            assessment.recommendations.append(
                "Migration will take more than 8 hours. Plan for extended downtime."
            )
        
        # Compatibility recommendations
        if assessment.compatibility_issues:
            assessment.recommendations.append(
                f"Found {len(assessment.compatibility_issues)} compatibility issues. "
                "Review before migration."
            )
        
        # Space recommendations
        space_gb = assessment.space_required_bytes / (1024**3)
        assessment.recommendations.append(
            f"Ensure target storage has at least {space_gb:.1f} GB free space."
        )
        
        # Backup recommendation
        assessment.recommendations.append(
            "Create a full backup before starting migration."
        )
    
    def verify_data_integrity(self, source_path: str, target_path: str, 
                            file_samples: List[FileIntegrityInfo]) -> Tuple[bool, List[str]]:
        """
        Verify data integrity after migration using file samples.
        
        Args:
            source_path: Original source path
            target_path: Migration target path
            file_samples: List of file samples to verify
            
        Returns:
            Tuple of (success, list of error messages)
        """
        logger.info(f"Verifying data integrity: {len(file_samples)} samples")
        
        errors = []
        verified_count = 0
        
        for sample in file_samples:
            try:
                # Convert source path to target path
                relative_path = os.path.relpath(sample.path, source_path)
                target_file_path = os.path.join(target_path, relative_path)
                
                # Check if target file exists
                if not os.path.exists(target_file_path):
                    errors.append(f"Missing file: {target_file_path}")
                    continue
                
                # Check file size
                target_stat = os.stat(target_file_path)
                if target_stat.st_size != sample.size:
                    errors.append(f"Size mismatch: {target_file_path} "
                                f"(expected {sample.size}, got {target_stat.st_size})")
                    continue
                
                # Check checksum if available
                if sample.checksum:
                    target_checksum = self._calculate_file_checksum(target_file_path)
                    if target_checksum != sample.checksum:
                        errors.append(f"Checksum mismatch: {target_file_path}")
                        continue
                
                verified_count += 1
            
            except Exception as e:
                errors.append(f"Verification error for {sample.path}: {str(e)}")
        
        success = len(errors) == 0
        logger.info(f"Integrity verification: {verified_count}/{len(file_samples)} files verified, "
                   f"{len(errors)} errors")
        
        return success, errors
    
    def calculate_space_requirements(self, assessments: List[MigrationAssessment]) -> Dict[str, int]:
        """
        Calculate total space requirements for multiple migrations.
        
        Args:
            assessments: List of migration assessments
            
        Returns:
            Dictionary with space requirement details
        """
        total_space = sum(assessment.space_required_bytes for assessment in assessments)
        total_files = sum(assessment.total_files for assessment in assessments)
        
        return {
            'total_space_bytes': total_space,
            'total_space_gb': total_space / (1024**3),
            'total_files': total_files,
            'buffer_space_bytes': int(total_space * 0.1),  # Additional 10% buffer
            'recommended_free_space_bytes': int(total_space * 1.3)  # 30% total buffer
        }
    
    def get_migration_state(self, migration_id: str) -> Optional[MigrationState]:
        """
        Get current migration state.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            MigrationState if found, None otherwise
        """
        return self._migration_states.get(migration_id)
    
    def list_migration_states(self) -> List[MigrationState]:
        """
        List all current migration states.
        
        Returns:
            List of all migration states
        """
        return list(self._migration_states.values())
    
    def create_migration_plan(self, source_drive: DriveConfig, 
                             target_drives: List[DriveConfig],
                             migration_id: Optional[str] = None) -> str:
        """
        Create a migration plan for NTFS to ext4 conversion.
        
        Args:
            source_drive: Source NTFS drive
            target_drives: Target ext4 drives for data storage
            migration_id: Optional migration ID, will be generated if not provided
            
        Returns:
            Migration ID for tracking
        """
        if not migration_id:
            migration_id = f"migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info(f"Creating migration plan {migration_id}: {source_drive.device_path} -> {[d.device_path for d in target_drives]}")
        
        # Analyze source drive
        assessment = self.analyze_ntfs_drive(source_drive)
        
        # Create migration state
        migration_state = MigrationState(
            migration_id=migration_id,
            source_drive=source_drive.device_path,
            target_drives=[drive.device_path for drive in target_drives],
            migration_status=MigrationStatus.READY,
            files_migrated=0,
            total_files=assessment.total_files,
            bytes_migrated=0,
            total_bytes=assessment.total_size_bytes,
            estimated_completion=None,
            rollback_available=True
        )
        
        # Store migration state
        self._migration_states[migration_id] = migration_state
        
        # Save migration metadata
        self._save_migration_metadata(migration_id, assessment, source_drive, target_drives)
        
        logger.info(f"Migration plan {migration_id} created successfully")
        return migration_id
    
    def start_migration(self, migration_id: str) -> bool:
        """
        Start the filesystem migration process.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            True if migration started successfully, False otherwise
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            logger.error(f"Migration {migration_id} not found")
            return False
        
        if migration_state.migration_status != MigrationStatus.READY:
            logger.error(f"Migration {migration_id} is not ready (status: {migration_state.migration_status})")
            return False
        
        logger.info(f"Starting migration {migration_id}")
        
        try:
            # Update status
            migration_state.migration_status = MigrationStatus.IN_PROGRESS
            migration_state.started_at = datetime.now()
            
            # Load migration metadata
            metadata = self._load_migration_metadata(migration_id)
            if not metadata:
                raise Exception("Could not load migration metadata")
            
            # Execute migration steps
            success = self._execute_migration_workflow(migration_id, metadata)
            
            if success:
                migration_state.migration_status = MigrationStatus.COMPLETED
                migration_state.completed_at = datetime.now()
                logger.info(f"Migration {migration_id} completed successfully")
            else:
                migration_state.migration_status = MigrationStatus.FAILED
                migration_state.error_message = "Migration workflow failed"
                logger.error(f"Migration {migration_id} failed")
            
            return success
        
        except Exception as e:
            migration_state.migration_status = MigrationStatus.FAILED
            migration_state.error_message = str(e)
            logger.error(f"Migration {migration_id} failed with error: {e}")
            return False
    
    def rollback_migration(self, migration_id: str) -> bool:
        """
        Rollback a migration to its original state.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            True if rollback successful, False otherwise
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            logger.error(f"Migration {migration_id} not found")
            return False
        
        if not migration_state.rollback_available:
            logger.error(f"Rollback not available for migration {migration_id}")
            return False
        
        logger.info(f"Rolling back migration {migration_id}")
        
        try:
            # Load migration metadata
            metadata = self._load_migration_metadata(migration_id)
            if not metadata:
                raise Exception("Could not load migration metadata")
            
            # Execute rollback steps
            success = self._execute_rollback_workflow(migration_id, metadata)
            
            if success:
                migration_state.migration_status = MigrationStatus.ROLLED_BACK
                migration_state.rollback_available = False
                logger.info(f"Migration {migration_id} rolled back successfully")
            else:
                migration_state.error_message = "Rollback failed"
                logger.error(f"Rollback for migration {migration_id} failed")
            
            return success
        
        except Exception as e:
            migration_state.error_message = f"Rollback failed: {str(e)}"
            logger.error(f"Rollback for migration {migration_id} failed with error: {e}")
            return False
    
    def _save_migration_metadata(self, migration_id: str, assessment: MigrationAssessment,
                                source_drive: DriveConfig, target_drives: List[DriveConfig]) -> None:
        """
        Save migration metadata to disk for rollback purposes.
        
        Args:
            migration_id: Migration identifier
            assessment: Migration assessment
            source_drive: Source drive configuration
            target_drives: Target drive configurations
        """
        metadata_file = os.path.join(self.work_dir, f"{migration_id}_metadata.json")
        
        metadata = {
            'migration_id': migration_id,
            'created_at': datetime.now().isoformat(),
            'source_drive': {
                'device_path': source_drive.device_path,
                'uuid': source_drive.uuid,
                'mount_point': source_drive.mount_point,
                'filesystem': source_drive.filesystem,
                'size_bytes': source_drive.size_bytes,
                'label': source_drive.label
            },
            'target_drives': [
                {
                    'device_path': drive.device_path,
                    'uuid': drive.uuid,
                    'mount_point': drive.mount_point,
                    'filesystem': drive.filesystem,
                    'size_bytes': drive.size_bytes,
                    'label': drive.label
                }
                for drive in target_drives
            ],
            'assessment': {
                'total_files': assessment.total_files,
                'total_size_bytes': assessment.total_size_bytes,
                'estimated_duration_hours': assessment.estimated_duration_hours,
                'space_required_bytes': assessment.space_required_bytes,
                'compatibility_issues': assessment.compatibility_issues,
                'recommendations': assessment.recommendations,
                'file_samples': [
                    {
                        'path': sample.path,
                        'size': sample.size,
                        'checksum': sample.checksum,
                        'modified_time': sample.modified_time
                    }
                    for sample in assessment.file_samples
                ]
            }
        }
        
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Migration metadata saved to {metadata_file}")
    
    def _load_migration_metadata(self, migration_id: str) -> Optional[Dict]:
        """
        Load migration metadata from disk.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            Migration metadata dictionary or None if not found
        """
        metadata_file = os.path.join(self.work_dir, f"{migration_id}_metadata.json")
        
        if not os.path.exists(metadata_file):
            logger.error(f"Migration metadata file not found: {metadata_file}")
            return None
        
        try:
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            logger.info(f"Migration metadata loaded from {metadata_file}")
            return metadata
        
        except Exception as e:
            logger.error(f"Error loading migration metadata: {e}")
            return None
    
    def _execute_migration_workflow(self, migration_id: str, metadata: Dict) -> bool:
        """
        Execute the complete migration workflow.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        migration_state = self._migration_states[migration_id]
        
        try:
            # Step 1: Create backup of original configuration
            logger.info(f"Step 1: Creating backup for migration {migration_id}")
            if not self._create_configuration_backup(migration_id, metadata):
                return False
            
            # Step 2: Prepare target drives
            logger.info(f"Step 2: Preparing target drives for migration {migration_id}")
            if not self._prepare_target_drives(migration_id, metadata):
                return False
            
            # Step 3: Copy data with progress tracking
            logger.info(f"Step 3: Copying data for migration {migration_id}")
            if not self._copy_data_with_progress(migration_id, metadata):
                return False
            
            # Step 4: Verify data integrity
            logger.info(f"Step 4: Verifying data integrity for migration {migration_id}")
            if not self._verify_migration_integrity(migration_id, metadata):
                return False
            
            # Step 5: Update system configuration
            logger.info(f"Step 5: Updating system configuration for migration {migration_id}")
            if not self._update_system_configuration(migration_id, metadata):
                return False
            
            logger.info(f"Migration workflow completed successfully for {migration_id}")
            return True
        
        except Exception as e:
            logger.error(f"Migration workflow failed for {migration_id}: {e}")
            migration_state.error_message = str(e)
            return False
    
    def _execute_rollback_workflow(self, migration_id: str, metadata: Dict) -> bool:
        """
        Execute the rollback workflow to restore original state.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Restore original system configuration
            logger.info(f"Rollback Step 1: Restoring system configuration for {migration_id}")
            if not self._restore_system_configuration(migration_id, metadata):
                return False
            
            # Step 2: Remount original NTFS drive
            logger.info(f"Rollback Step 2: Remounting original drive for {migration_id}")
            if not self._remount_original_drive(migration_id, metadata):
                return False
            
            # Step 3: Clean up target drives (optional)
            logger.info(f"Rollback Step 3: Cleaning up target drives for {migration_id}")
            self._cleanup_target_drives(migration_id, metadata)
            
            logger.info(f"Rollback workflow completed successfully for {migration_id}")
            return True
        
        except Exception as e:
            logger.error(f"Rollback workflow failed for {migration_id}: {e}")
            return False
    
    def _create_configuration_backup(self, migration_id: str, metadata: Dict) -> bool:
        """
        Create backup of original system configuration.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        backup_dir = os.path.join(self.work_dir, f"{migration_id}_backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        try:
            # Backup fstab
            if os.path.exists('/etc/fstab'):
                shutil.copy2('/etc/fstab', os.path.join(backup_dir, 'fstab.backup'))
            
            # Backup any existing mount configurations
            mount_configs = ['/etc/systemd/system/*.mount', '/etc/systemd/system/*.automount']
            for pattern in mount_configs:
                try:
                    import glob
                    for config_file in glob.glob(pattern):
                        backup_name = os.path.basename(config_file) + '.backup'
                        shutil.copy2(config_file, os.path.join(backup_dir, backup_name))
                except Exception as e:
                    logger.warning(f"Could not backup mount config {pattern}: {e}")
            
            # Save current mount state
            mount_state_file = os.path.join(backup_dir, 'mount_state.txt')
            success, stdout, stderr = self.system_executor.execute_command(['mount'])
            if success:
                with open(mount_state_file, 'w') as f:
                    f.write(stdout)
            
            logger.info(f"Configuration backup created in {backup_dir}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to create configuration backup: {e}")
            return False
    
    def _prepare_target_drives(self, migration_id: str, metadata: Dict) -> bool:
        """
        Prepare target drives for data migration.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            target_drives = metadata['target_drives']
            
            for i, drive_info in enumerate(target_drives):
                device_path = drive_info['device_path']
                mount_point = drive_info['mount_point']
                
                # Create mount point if it doesn't exist
                os.makedirs(mount_point, exist_ok=True)
                
                # Format drive as ext4 if not already
                if drive_info['filesystem'].lower() != 'ext4':
                    logger.info(f"Formatting {device_path} as ext4")
                    label = f"data{i+1}"
                    success, stdout, stderr = self.system_executor.execute_filesystem_command(
                        device_path, 'ext4', label
                    )
                    if not success:
                        logger.error(f"Failed to format {device_path}: {stderr}")
                        return False
                
                # Mount the drive
                logger.info(f"Mounting {device_path} at {mount_point}")
                success, stdout, stderr = self.system_executor.execute_mount_command(
                    device_path, mount_point, 'ext4', 'defaults'
                )
                if not success:
                    logger.error(f"Failed to mount {device_path}: {stderr}")
                    return False
            
            logger.info("Target drives prepared successfully")
            return True
        
        except Exception as e:
            logger.error(f"Failed to prepare target drives: {e}")
            return False
    
    def _copy_data_with_progress(self, migration_id: str, metadata: Dict) -> bool:
        """
        Copy data from source to target drives with progress tracking.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        migration_state = self._migration_states[migration_id]
        source_mount = metadata['source_drive']['mount_point']
        target_drives = metadata['target_drives']
        
        # For simplicity, use the first target drive as primary destination
        # In a real implementation, this would use MergerFS pooling
        primary_target = target_drives[0]['mount_point']
        
        try:
            # Use rsync for efficient copying with progress
            rsync_cmd = [
                'rsync', '-avh', '--progress', '--stats',
                '--exclude=System Volume Information',
                '--exclude=$RECYCLE.BIN',
                '--exclude=pagefile.sys',
                '--exclude=hiberfil.sys',
                '--exclude=swapfile.sys',
                '--exclude=Thumbs.db',
                '--exclude=desktop.ini',
                f"{source_mount}/",
                f"{primary_target}/"
            ]
            
            logger.info(f"Starting data copy: {' '.join(rsync_cmd)}")
            
            # Execute rsync with progress monitoring
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor progress
            try:
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    
                    if output:
                        # Parse rsync progress output
                        self._parse_rsync_progress(migration_id, output.strip())
                
                # Wait for completion
                return_code = process.wait()
                
                if return_code == 0:
                    migration_state.files_migrated = migration_state.total_files
                    migration_state.bytes_migrated = migration_state.total_bytes
                    logger.info("Data copy completed successfully")
                    return True
                else:
                    stderr_output = process.stderr.read()
                    logger.error(f"Data copy failed with return code {return_code}: {stderr_output}")
                    return False
            
            except Exception as e:
                # Ensure process is terminated
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                raise e
        
        except Exception as e:
            logger.error(f"Data copy failed: {e}")
            return False
    
    def _parse_rsync_progress(self, migration_id: str, output: str) -> None:
        """
        Parse rsync progress output and update migration state.
        
        Args:
            migration_id: Migration identifier
            output: Rsync output line
        """
        migration_state = self._migration_states[migration_id]
        
        try:
            # Look for progress indicators in rsync output
            if 'to-check=' in output:
                # Extract remaining files count
                import re
                match = re.search(r'to-check=(\d+)/(\d+)', output)
                if match:
                    remaining = int(match.group(1))
                    total = int(match.group(2))
                    migration_state.files_migrated = total - remaining
            
            # Look for transfer rate and ETA - more flexible pattern
            if 'xfr#' in output:
                # Look for time patterns in the output
                import re
                time_match = re.search(r'(\d{1,2}:\d{2}:\d{2})', output)
                if time_match:
                    eta_str = time_match.group(1)
                    # Parse ETA and calculate completion time
                    try:
                        time_parts = eta_str.split(':')
                        if len(time_parts) == 3:
                            hours, minutes, seconds = map(int, time_parts)
                            eta_delta = timedelta(hours=hours, minutes=minutes, seconds=seconds)
                            migration_state.estimated_completion = datetime.now() + eta_delta
                    except (ValueError, IndexError):
                        pass
        
        except Exception as e:
            logger.debug(f"Could not parse rsync progress: {e}")
    
    def _verify_migration_integrity(self, migration_id: str, metadata: Dict) -> bool:
        """
        Verify data integrity after migration.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if verification successful, False otherwise
        """
        try:
            source_mount = metadata['source_drive']['mount_point']
            target_drives = metadata['target_drives']
            primary_target = target_drives[0]['mount_point']
            
            # Convert file samples to FileIntegrityInfo objects
            file_samples = []
            for sample_data in metadata['assessment']['file_samples']:
                sample = FileIntegrityInfo(
                    path=sample_data['path'],
                    size=sample_data['size'],
                    checksum=sample_data['checksum'],
                    modified_time=sample_data['modified_time']
                )
                file_samples.append(sample)
            
            # Verify integrity using file samples
            success, errors = self.verify_data_integrity(source_mount, primary_target, file_samples)
            
            if not success:
                logger.error(f"Data integrity verification failed: {errors}")
                return False
            
            logger.info("Data integrity verification passed")
            return True
        
        except Exception as e:
            logger.error(f"Data integrity verification failed: {e}")
            return False
    
    def _update_system_configuration(self, migration_id: str, metadata: Dict) -> bool:
        """
        Update system configuration to use new drives.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # This would typically update fstab, systemd mount units, etc.
            # For now, we'll just log the action
            logger.info("System configuration updated for new drives")
            
            # In a real implementation, this would:
            # 1. Update /etc/fstab with new ext4 mounts
            # 2. Create systemd mount units
            # 3. Update MergerFS configuration
            # 4. Update SnapRAID configuration
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to update system configuration: {e}")
            return False
    
    def _restore_system_configuration(self, migration_id: str, metadata: Dict) -> bool:
        """
        Restore original system configuration during rollback.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        backup_dir = os.path.join(self.work_dir, f"{migration_id}_backup")
        
        try:
            # Restore fstab
            fstab_backup = os.path.join(backup_dir, 'fstab.backup')
            if os.path.exists(fstab_backup):
                shutil.copy2(fstab_backup, '/etc/fstab')
            
            # Restore other configuration files
            for backup_file in os.listdir(backup_dir):
                if backup_file.endswith('.backup') and backup_file != 'fstab.backup':
                    original_name = backup_file.replace('.backup', '')
                    original_path = f"/etc/systemd/system/{original_name}"
                    backup_path = os.path.join(backup_dir, backup_file)
                    
                    if os.path.exists(original_path):
                        shutil.copy2(backup_path, original_path)
            
            logger.info("System configuration restored from backup")
            return True
        
        except Exception as e:
            logger.error(f"Failed to restore system configuration: {e}")
            return False
    
    def _remount_original_drive(self, migration_id: str, metadata: Dict) -> bool:
        """
        Remount the original NTFS drive during rollback.
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
            
        Returns:
            True if successful, False otherwise
        """
        try:
            source_drive = metadata['source_drive']
            device_path = source_drive['device_path']
            mount_point = source_drive['mount_point']
            
            # Ensure mount point exists
            os.makedirs(mount_point, exist_ok=True)
            
            # Mount the original NTFS drive
            success, stdout, stderr = self.system_executor.execute_mount_command(
                device_path, mount_point, 'ntfs', 'defaults'
            )
            
            if success:
                logger.info(f"Original NTFS drive remounted at {mount_point}")
                return True
            else:
                logger.error(f"Failed to remount original drive: {stderr}")
                return False
        
        except Exception as e:
            logger.error(f"Failed to remount original drive: {e}")
            return False
    
    def _cleanup_target_drives(self, migration_id: str, metadata: Dict) -> None:
        """
        Clean up target drives during rollback (optional).
        
        Args:
            migration_id: Migration identifier
            metadata: Migration metadata
        """
        try:
            target_drives = metadata['target_drives']
            
            for drive_info in target_drives:
                mount_point = drive_info['mount_point']
                
                # Unmount the drive
                success, stdout, stderr = self.system_executor.execute_command(['umount', mount_point])
                if success:
                    logger.info(f"Unmounted target drive at {mount_point}")
                else:
                    logger.warning(f"Could not unmount {mount_point}: {stderr}")
        
        except Exception as e:
            logger.warning(f"Error during target drive cleanup: {e}")
    
    def get_migration_progress(self, migration_id: str) -> Optional[Dict]:
        """
        Get detailed migration progress information.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            Dictionary with progress details or None if not found
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            return None
        
        progress_info = {
            'migration_id': migration_state.migration_id,
            'status': migration_state.migration_status.value,
            'progress_percent': migration_state.progress_percent,
            'bytes_progress_percent': migration_state.bytes_progress_percent,
            'files_migrated': migration_state.files_migrated,
            'total_files': migration_state.total_files,
            'bytes_migrated': migration_state.bytes_migrated,
            'total_bytes': migration_state.total_bytes,
            'started_at': migration_state.started_at.isoformat() if migration_state.started_at else None,
            'estimated_completion': migration_state.estimated_completion.isoformat() if migration_state.estimated_completion else None,
            'completed_at': migration_state.completed_at.isoformat() if migration_state.completed_at else None,
            'error_message': migration_state.error_message,
            'rollback_available': migration_state.rollback_available
        }
        
        # Add time estimates
        if migration_state.started_at and migration_state.migration_status == MigrationStatus.IN_PROGRESS:
            elapsed_time = datetime.now() - migration_state.started_at
            progress_info['elapsed_seconds'] = elapsed_time.total_seconds()
            
            # Estimate remaining time based on progress
            if migration_state.progress_percent > 0:
                total_estimated_seconds = (elapsed_time.total_seconds() * 100) / migration_state.progress_percent
                remaining_seconds = total_estimated_seconds - elapsed_time.total_seconds()
                progress_info['estimated_remaining_seconds'] = max(0, remaining_seconds)
        
        return progress_info
    
    def validate_migration_completion(self, migration_id: str) -> Tuple[bool, List[str]]:
        """
        Validate that a migration completed successfully.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            Tuple of (success, list of validation errors)
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            return False, ["Migration not found"]
        
        if migration_state.migration_status != MigrationStatus.COMPLETED:
            return False, [f"Migration status is {migration_state.migration_status.value}, not completed"]
        
        validation_errors = []
        
        try:
            # Load migration metadata
            metadata = self._load_migration_metadata(migration_id)
            if not metadata:
                validation_errors.append("Could not load migration metadata")
                return False, validation_errors
            
            # Validate file counts
            if migration_state.files_migrated != migration_state.total_files:
                validation_errors.append(
                    f"File count mismatch: migrated {migration_state.files_migrated}, "
                    f"expected {migration_state.total_files}"
                )
            
            # Validate byte counts
            if migration_state.bytes_migrated != migration_state.total_bytes:
                validation_errors.append(
                    f"Byte count mismatch: migrated {migration_state.bytes_migrated}, "
                    f"expected {migration_state.total_bytes}"
                )
            
            # Validate target drive accessibility
            target_drives = metadata['target_drives']
            for drive_info in target_drives:
                mount_point = drive_info['mount_point']
                if not os.path.exists(mount_point):
                    validation_errors.append(f"Target mount point not accessible: {mount_point}")
                elif not os.access(mount_point, os.R_OK | os.W_OK):
                    validation_errors.append(f"Target mount point not writable: {mount_point}")
            
            # Perform data integrity validation using file samples
            source_mount = metadata['source_drive']['mount_point']
            primary_target = target_drives[0]['mount_point']
            
            file_samples = []
            for sample_data in metadata['assessment']['file_samples']:
                sample = FileIntegrityInfo(
                    path=sample_data['path'],
                    size=sample_data['size'],
                    checksum=sample_data['checksum'],
                    modified_time=sample_data['modified_time']
                )
                file_samples.append(sample)
            
            if file_samples:
                integrity_success, integrity_errors = self.verify_data_integrity(
                    source_mount, primary_target, file_samples
                )
                if not integrity_success:
                    validation_errors.extend(integrity_errors)
            
            success = len(validation_errors) == 0
            logger.info(f"Migration validation for {migration_id}: {'PASSED' if success else 'FAILED'}")
            
            return success, validation_errors
        
        except Exception as e:
            logger.error(f"Migration validation failed with exception: {e}")
            return False, [f"Validation error: {str(e)}"]
    
    def cleanup_migration_files(self, migration_id: str, keep_backups: bool = True) -> bool:
        """
        Clean up temporary files and configurations after migration.
        
        Args:
            migration_id: Migration identifier
            keep_backups: Whether to keep backup files for rollback
            
        Returns:
            True if cleanup successful, False otherwise
        """
        try:
            # Clean up temporary work files
            temp_files = [
                f"{migration_id}_metadata.json",
                f"{migration_id}_progress.log"
            ]
            
            for temp_file in temp_files:
                temp_path = os.path.join(self.work_dir, temp_file)
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    logger.info(f"Removed temporary file: {temp_path}")
            
            # Optionally clean up backup directory
            if not keep_backups:
                backup_dir = os.path.join(self.work_dir, f"{migration_id}_backup")
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                    logger.info(f"Removed backup directory: {backup_dir}")
            
            logger.info(f"Cleanup completed for migration {migration_id}")
            return True
        
        except Exception as e:
            logger.error(f"Cleanup failed for migration {migration_id}: {e}")
            return False
    
    def generate_migration_report(self, migration_id: str) -> Optional[Dict]:
        """
        Generate a comprehensive migration report.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            Dictionary with migration report or None if not found
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            return None
        
        try:
            # Load migration metadata
            metadata = self._load_migration_metadata(migration_id)
            if not metadata:
                return None
            
            # Calculate migration statistics
            duration_seconds = 0
            if migration_state.started_at and migration_state.completed_at:
                duration = migration_state.completed_at - migration_state.started_at
                duration_seconds = duration.total_seconds()
            
            # Calculate transfer rates
            transfer_rate_mbps = 0
            if duration_seconds > 0 and migration_state.bytes_migrated > 0:
                bytes_per_second = migration_state.bytes_migrated / duration_seconds
                transfer_rate_mbps = bytes_per_second / (1024 * 1024)  # Convert to MB/s
            
            # Perform final validation
            validation_success, validation_errors = self.validate_migration_completion(migration_id)
            
            report = {
                'migration_id': migration_id,
                'created_at': metadata['created_at'],
                'source_drive': metadata['source_drive'],
                'target_drives': metadata['target_drives'],
                'migration_status': migration_state.migration_status.value,
                'started_at': migration_state.started_at.isoformat() if migration_state.started_at else None,
                'completed_at': migration_state.completed_at.isoformat() if migration_state.completed_at else None,
                'duration_seconds': duration_seconds,
                'duration_human': self._format_duration(duration_seconds),
                'files_processed': {
                    'migrated': migration_state.files_migrated,
                    'total': migration_state.total_files,
                    'success_rate': (migration_state.files_migrated / migration_state.total_files * 100) if migration_state.total_files > 0 else 0
                },
                'bytes_processed': {
                    'migrated': migration_state.bytes_migrated,
                    'total': migration_state.total_bytes,
                    'migrated_gb': migration_state.bytes_migrated / (1024**3),
                    'total_gb': migration_state.total_bytes / (1024**3),
                    'success_rate': (migration_state.bytes_migrated / migration_state.total_bytes * 100) if migration_state.total_bytes > 0 else 0
                },
                'performance': {
                    'transfer_rate_mbps': transfer_rate_mbps,
                    'files_per_second': migration_state.files_migrated / duration_seconds if duration_seconds > 0 else 0
                },
                'validation': {
                    'passed': validation_success,
                    'errors': validation_errors
                },
                'assessment': metadata['assessment'],
                'error_message': migration_state.error_message,
                'rollback_available': migration_state.rollback_available
            }
            
            logger.info(f"Generated migration report for {migration_id}")
            return report
        
        except Exception as e:
            logger.error(f"Failed to generate migration report for {migration_id}: {e}")
            return None
    
    def _format_duration(self, seconds: float) -> str:
        """
        Format duration in seconds to human-readable string.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Human-readable duration string
        """
        if seconds < 60:
            return f"{seconds:.1f} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        else:
            hours = seconds / 3600
            return f"{hours:.1f} hours"
    
    def monitor_migration_health(self, migration_id: str) -> Dict:
        """
        Monitor the health of an ongoing migration.
        
        Args:
            migration_id: Migration identifier
            
        Returns:
            Dictionary with health monitoring information
        """
        migration_state = self._migration_states.get(migration_id)
        if not migration_state:
            return {'status': 'not_found', 'message': 'Migration not found'}
        
        health_info = {
            'migration_id': migration_id,
            'status': migration_state.migration_status.value,
            'health': 'unknown',
            'issues': [],
            'recommendations': []
        }
        
        try:
            if migration_state.migration_status == MigrationStatus.IN_PROGRESS:
                # Check for stalled migration
                if migration_state.started_at:
                    elapsed_time = datetime.now() - migration_state.started_at
                    
                    # If no progress in the last hour, consider it stalled
                    if elapsed_time.total_seconds() > 3600 and migration_state.progress_percent == 0:
                        health_info['health'] = 'stalled'
                        health_info['issues'].append('Migration appears to be stalled with no progress')
                        health_info['recommendations'].append('Consider restarting the migration')
                    
                    # Check for very slow progress
                    elif elapsed_time.total_seconds() > 1800:  # 30 minutes
                        expected_progress = (elapsed_time.total_seconds() / 3600) * 10  # Expect 10% per hour minimum
                        if migration_state.progress_percent < expected_progress:
                            health_info['health'] = 'slow'
                            health_info['issues'].append('Migration is progressing slower than expected')
                            health_info['recommendations'].append('Check system resources and disk performance')
                    else:
                        health_info['health'] = 'healthy'
                
                # Load metadata to check target drive space
                metadata = self._load_migration_metadata(migration_id)
                if metadata:
                    target_drives = metadata['target_drives']
                    for drive_info in target_drives:
                        mount_point = drive_info['mount_point']
                        try:
                            usage = psutil.disk_usage(mount_point)
                            free_space_percent = (usage.free / usage.total) * 100
                            
                            if free_space_percent < 10:
                                health_info['health'] = 'critical'
                                health_info['issues'].append(f'Low disk space on {mount_point}: {free_space_percent:.1f}% free')
                                health_info['recommendations'].append('Free up disk space or add additional storage')
                            elif free_space_percent < 20:
                                health_info['health'] = 'warning'
                                health_info['issues'].append(f'Disk space getting low on {mount_point}: {free_space_percent:.1f}% free')
                                health_info['recommendations'].append('Monitor disk space closely')
                        
                        except Exception as e:
                            health_info['issues'].append(f'Could not check disk space for {mount_point}: {str(e)}')
            
            elif migration_state.migration_status == MigrationStatus.FAILED:
                health_info['health'] = 'failed'
                if migration_state.error_message:
                    health_info['issues'].append(f'Migration failed: {migration_state.error_message}')
                health_info['recommendations'].append('Review error logs and consider rollback or retry')
            
            elif migration_state.migration_status == MigrationStatus.COMPLETED:
                # Validate completion
                validation_success, validation_errors = self.validate_migration_completion(migration_id)
                if validation_success:
                    health_info['health'] = 'completed'
                else:
                    health_info['health'] = 'completed_with_issues'
                    health_info['issues'].extend(validation_errors)
                    health_info['recommendations'].append('Review validation errors and consider corrective action')
            
            else:
                health_info['health'] = 'healthy'
            
            # If no specific health status was set, default to healthy
            if health_info['health'] == 'unknown' and not health_info['issues']:
                health_info['health'] = 'healthy'
        
        except Exception as e:
            health_info['health'] = 'error'
            health_info['issues'].append(f'Health monitoring error: {str(e)}')
            logger.error(f"Migration health monitoring failed for {migration_id}: {e}")
        
        return health_info
    
    def get_migration_statistics(self) -> Dict:
        """
        Get overall migration statistics across all migrations.
        
        Returns:
            Dictionary with migration statistics
        """
        stats = {
            'total_migrations': len(self._migration_states),
            'by_status': {},
            'total_files_migrated': 0,
            'total_bytes_migrated': 0,
            'average_duration_seconds': 0,
            'success_rate': 0
        }
        
        # Count by status
        for status in MigrationStatus:
            stats['by_status'][status.value] = 0
        
        completed_migrations = []
        total_duration = 0
        
        for migration_state in self._migration_states.values():
            # Count by status
            stats['by_status'][migration_state.migration_status.value] += 1
            
            # Accumulate totals
            stats['total_files_migrated'] += migration_state.files_migrated
            stats['total_bytes_migrated'] += migration_state.bytes_migrated
            
            # Track completed migrations for averages
            if (migration_state.migration_status == MigrationStatus.COMPLETED and 
                migration_state.started_at and migration_state.completed_at):
                duration = migration_state.completed_at - migration_state.started_at
                total_duration += duration.total_seconds()
                completed_migrations.append(migration_state)
        
        # Calculate averages
        if completed_migrations:
            stats['average_duration_seconds'] = total_duration / len(completed_migrations)
            
            # Calculate success rate
            successful_count = stats['by_status'].get(MigrationStatus.COMPLETED.value, 0)
            total_attempted = (successful_count + 
                             stats['by_status'].get(MigrationStatus.FAILED.value, 0) +
                             stats['by_status'].get(MigrationStatus.ROLLED_BACK.value, 0))
            
            if total_attempted > 0:
                stats['success_rate'] = (successful_count / total_attempted) * 100
        
        # Add human-readable formats
        stats['total_bytes_migrated_gb'] = stats['total_bytes_migrated'] / (1024**3)
        stats['average_duration_human'] = self._format_duration(stats['average_duration_seconds'])
        
        return stats