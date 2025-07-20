"""Tests for filesystem migration manager."""

import os
import tempfile
import shutil
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from nas.migration_manager import (
    MigrationManager, MigrationAssessment, MigrationState, MigrationStatus,
    FileIntegrityInfo, FileSystemType
)
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestMigrationManager:
    """Test cases for MigrationManager."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def migration_manager(self, temp_dir):
        """Create a MigrationManager instance for testing."""
        return MigrationManager(work_dir=temp_dir)
    
    @pytest.fixture
    def sample_ntfs_drive(self):
        """Create a sample NTFS drive configuration."""
        return DriveConfig(
            device_path="/dev/sdb1",
            uuid="test-uuid-123",
            mount_point="/mnt/ntfs_drive",
            filesystem="ntfs",
            role=DriveRole.DATA,
            size_bytes=1000000000,  # 1GB
            used_bytes=500000000,   # 500MB
            health_status=HealthStatus.HEALTHY,
            label="TestNTFS"
        )
    
    @pytest.fixture
    def sample_ext4_drive(self):
        """Create a sample ext4 drive configuration."""
        return DriveConfig(
            device_path="/dev/sdc1",
            uuid="test-uuid-456",
            mount_point="/mnt/ext4_drive",
            filesystem="ext4",
            role=DriveRole.DATA,
            size_bytes=2000000000,  # 2GB
            used_bytes=100000000,   # 100MB
            health_status=HealthStatus.HEALTHY,
            label="TestEXT4"
        )
    
    def test_init(self, temp_dir):
        """Test MigrationManager initialization."""
        manager = MigrationManager(work_dir=temp_dir)
        
        assert manager.work_dir == temp_dir
        assert os.path.exists(temp_dir)
        assert isinstance(manager._migration_states, dict)
    
    @patch('nas.migration_manager.DriveManager')
    def test_detect_ntfs_drives(self, mock_drive_manager, migration_manager, sample_ntfs_drive, sample_ext4_drive):
        """Test NTFS drive detection."""
        # Mock drive manager to return mixed drives
        mock_instance = Mock()
        mock_instance.discover_drives.return_value = [sample_ntfs_drive, sample_ext4_drive]
        mock_drive_manager.return_value = mock_instance
        
        # Create new manager with mocked drive manager
        manager = MigrationManager()
        manager.drive_manager = mock_instance
        
        ntfs_drives = manager.detect_ntfs_drives()
        
        assert len(ntfs_drives) == 1
        assert ntfs_drives[0].filesystem == "ntfs"
        assert ntfs_drives[0].device_path == "/dev/sdb1"
    
    def test_should_exclude_path(self, migration_manager):
        """Test path exclusion logic."""
        manager = migration_manager
        
        # Test excluded patterns
        assert manager._should_exclude_path("System Volume Information")
        assert manager._should_exclude_path("$RECYCLE.BIN")
        assert manager._should_exclude_path("Thumbs.db")
        assert manager._should_exclude_path("desktop.ini")
        
        # Test case insensitive
        assert manager._should_exclude_path("thumbs.db")
        assert manager._should_exclude_path("DESKTOP.INI")
        
        # Test normal files
        assert not manager._should_exclude_path("document.txt")
        assert not manager._should_exclude_path("photo.jpg")
        assert not manager._should_exclude_path("video.mp4")
    
    def test_check_file_compatibility(self, migration_manager):
        """Test file compatibility checking."""
        manager = migration_manager
        assessment = MigrationAssessment(
            source_drive=Mock(),
            total_files=0,
            total_size_bytes=0,
            estimated_duration_hours=0.0,
            space_required_bytes=0
        )
        
        # Test Windows-specific files
        manager._check_file_compatibility("test.exe", assessment)
        manager._check_file_compatibility("installer.msi", assessment)
        manager._check_file_compatibility("shortcut.lnk", assessment)
        
        assert len(assessment.compatibility_issues) == 3
        assert any("Windows executables" in issue for issue in assessment.compatibility_issues)
        assert any("Windows installers" in issue for issue in assessment.compatibility_issues)
        assert any("Windows shortcuts" in issue for issue in assessment.compatibility_issues)
        
        # Test compatible files
        manager._check_file_compatibility("document.txt", assessment)
        manager._check_file_compatibility("photo.jpg", assessment)
        
        # Should not add more issues
        assert len(assessment.compatibility_issues) == 3
    
    def test_calculate_file_checksum(self, migration_manager, temp_dir):
        """Test file checksum calculation."""
        manager = migration_manager
        
        # Create a test file
        test_file = os.path.join(temp_dir, "test.txt")
        test_content = "Hello, World!"
        
        with open(test_file, "w") as f:
            f.write(test_content)
        
        checksum = manager._calculate_file_checksum(test_file)
        
        # Verify checksum is not empty and is hex
        assert checksum
        assert len(checksum) == 32  # MD5 hex length
        assert all(c in "0123456789abcdef" for c in checksum.lower())
        
        # Test same content produces same checksum
        checksum2 = manager._calculate_file_checksum(test_file)
        assert checksum == checksum2
    
    def test_calculate_file_checksum_nonexistent(self, migration_manager):
        """Test checksum calculation for nonexistent file."""
        manager = migration_manager
        
        checksum = manager._calculate_file_checksum("/nonexistent/file.txt")
        assert checksum == ""
    
    @patch('os.walk')
    @patch('os.stat')
    def test_analyze_directory_structure(self, mock_stat, mock_walk, migration_manager):
        """Test directory structure analysis."""
        manager = migration_manager
        
        # Mock os.walk to return test directory structure
        mock_walk.return_value = [
            ("/test", ["subdir"], ["file1.txt", "file2.jpg", "file3.exe"]),
            ("/test/subdir", [], ["file4.doc"])
        ]
        
        # Mock os.stat to return file info
        mock_stat_result = Mock()
        mock_stat_result.st_size = 1000
        mock_stat_result.st_mtime = 1234567890
        mock_stat.return_value = mock_stat_result
        
        assessment = MigrationAssessment(
            source_drive=Mock(),
            total_files=0,
            total_size_bytes=0,
            estimated_duration_hours=0.0,
            space_required_bytes=0
        )
        
        manager._analyze_directory_structure("/test", assessment)
        
        # Should count 4 files (excluding .exe due to compatibility check)
        assert assessment.total_files == 4
        assert assessment.total_size_bytes == 4000  # 4 files * 1000 bytes each
        
        # Should have compatibility issue for .exe file
        assert len(assessment.compatibility_issues) == 1
        assert "file3.exe" in assessment.compatibility_issues[0]
    
    def test_generate_migration_recommendations(self, migration_manager, sample_ntfs_drive):
        """Test migration recommendation generation."""
        manager = migration_manager
        
        # Test large dataset
        assessment = MigrationAssessment(
            source_drive=sample_ntfs_drive,
            total_files=1000,
            total_size_bytes=600 * 1024**3,  # 600 GB
            estimated_duration_hours=12.0,
            space_required_bytes=720 * 1024**3  # 720 GB with buffer
        )
        assessment.compatibility_issues = ["test issue 1", "test issue 2"]
        
        manager._generate_migration_recommendations(assessment)
        
        assert len(assessment.recommendations) >= 4
        
        # Check for specific recommendations
        recommendations_text = " ".join(assessment.recommendations)
        assert "Large dataset" in recommendations_text
        assert "8 hours" in recommendations_text
        assert "compatibility issues" in recommendations_text
        assert "backup" in recommendations_text.lower()
    
    def test_calculate_space_requirements(self, migration_manager, sample_ntfs_drive):
        """Test space requirements calculation."""
        manager = migration_manager
        
        assessment1 = MigrationAssessment(
            source_drive=sample_ntfs_drive,
            total_files=100,
            total_size_bytes=1000000000,  # 1GB
            estimated_duration_hours=1.0,
            space_required_bytes=1200000000  # 1.2GB with buffer
        )
        
        assessment2 = MigrationAssessment(
            source_drive=sample_ntfs_drive,
            total_files=200,
            total_size_bytes=2000000000,  # 2GB
            estimated_duration_hours=2.0,
            space_required_bytes=2400000000  # 2.4GB with buffer
        )
        
        requirements = manager.calculate_space_requirements([assessment1, assessment2])
        
        assert requirements['total_space_bytes'] == 3600000000  # 3.6GB
        assert requirements['total_files'] == 300
        assert requirements['buffer_space_bytes'] == 360000000  # 10% of total
        assert requirements['recommended_free_space_bytes'] == 4680000000  # 30% buffer
        # Check GB conversion (allowing for floating point precision)
        expected_gb = 3600000000 / (1024**3)
        assert abs(requirements['total_space_gb'] - expected_gb) < 0.01
    
    def test_verify_data_integrity_success(self, migration_manager, temp_dir):
        """Test successful data integrity verification."""
        manager = migration_manager
        
        # Create source and target directories
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        os.makedirs(source_dir)
        os.makedirs(target_dir)
        
        # Create test files
        test_content = "Test file content"
        source_file = os.path.join(source_dir, "test.txt")
        target_file = os.path.join(target_dir, "test.txt")
        
        with open(source_file, "w") as f:
            f.write(test_content)
        with open(target_file, "w") as f:
            f.write(test_content)
        
        # Create file sample
        stat_info = os.stat(source_file)
        checksum = manager._calculate_file_checksum(source_file)
        
        file_sample = FileIntegrityInfo(
            path=source_file,
            size=stat_info.st_size,
            checksum=checksum,
            modified_time=stat_info.st_mtime
        )
        
        success, errors = manager.verify_data_integrity(source_dir, target_dir, [file_sample])
        
        assert success
        assert len(errors) == 0
    
    def test_verify_data_integrity_missing_file(self, migration_manager, temp_dir):
        """Test data integrity verification with missing file."""
        manager = migration_manager
        
        # Create source directory only
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        os.makedirs(source_dir)
        os.makedirs(target_dir)
        
        # Create source file but not target
        source_file = os.path.join(source_dir, "test.txt")
        with open(source_file, "w") as f:
            f.write("Test content")
        
        # Create file sample
        stat_info = os.stat(source_file)
        file_sample = FileIntegrityInfo(
            path=source_file,
            size=stat_info.st_size,
            checksum="dummy_checksum",
            modified_time=stat_info.st_mtime
        )
        
        success, errors = manager.verify_data_integrity(source_dir, target_dir, [file_sample])
        
        assert not success
        assert len(errors) == 1
        assert "Missing file" in errors[0]
    
    def test_verify_data_integrity_size_mismatch(self, migration_manager, temp_dir):
        """Test data integrity verification with size mismatch."""
        manager = migration_manager
        
        # Create source and target directories
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        os.makedirs(source_dir)
        os.makedirs(target_dir)
        
        # Create files with different sizes
        source_file = os.path.join(source_dir, "test.txt")
        target_file = os.path.join(target_dir, "test.txt")
        
        with open(source_file, "w") as f:
            f.write("Short content")
        with open(target_file, "w") as f:
            f.write("Much longer content that doesn't match")
        
        # Create file sample
        stat_info = os.stat(source_file)
        file_sample = FileIntegrityInfo(
            path=source_file,
            size=stat_info.st_size,
            checksum="",
            modified_time=stat_info.st_mtime
        )
        
        success, errors = manager.verify_data_integrity(source_dir, target_dir, [file_sample])
        
        assert not success
        assert len(errors) == 1
        assert "Size mismatch" in errors[0]
    
    def test_verify_data_integrity_checksum_mismatch(self, migration_manager, temp_dir):
        """Test data integrity verification with checksum mismatch."""
        manager = migration_manager
        
        # Create source and target directories
        source_dir = os.path.join(temp_dir, "source")
        target_dir = os.path.join(temp_dir, "target")
        os.makedirs(source_dir)
        os.makedirs(target_dir)
        
        # Create files with same size but different content
        source_file = os.path.join(source_dir, "test.txt")
        target_file = os.path.join(target_dir, "test.txt")
        
        with open(source_file, "w") as f:
            f.write("Original content")
        with open(target_file, "w") as f:
            f.write("Modified content")  # Same length, different content
        
        # Create file sample with original checksum
        stat_info = os.stat(source_file)
        checksum = manager._calculate_file_checksum(source_file)
        
        file_sample = FileIntegrityInfo(
            path=source_file,
            size=stat_info.st_size,
            checksum=checksum,
            modified_time=stat_info.st_mtime
        )
        
        success, errors = manager.verify_data_integrity(source_dir, target_dir, [file_sample])
        
        assert not success
        assert len(errors) == 1
        assert "Checksum mismatch" in errors[0]
    
    def test_migration_state_properties(self):
        """Test MigrationState property calculations."""
        state = MigrationState(
            migration_id="test-123",
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=250,
            total_files=1000,
            bytes_migrated=500000000,  # 500MB
            total_bytes=2000000000,    # 2GB
            estimated_completion=None
        )
        
        assert state.progress_percent == 25.0
        assert state.bytes_progress_percent == 25.0
        
        # Test zero division handling
        state.total_files = 0
        state.total_bytes = 0
        assert state.progress_percent == 0.0
        assert state.bytes_progress_percent == 0.0
    
    def test_get_migration_state(self, migration_manager):
        """Test getting migration state."""
        manager = migration_manager
        
        # Test non-existent state
        assert manager.get_migration_state("nonexistent") is None
        
        # Add a state
        state = MigrationState(
            migration_id="test-123",
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.PENDING,
            files_migrated=0,
            total_files=100,
            bytes_migrated=0,
            total_bytes=1000000,
            estimated_completion=None
        )
        
        manager._migration_states["test-123"] = state
        
        retrieved_state = manager.get_migration_state("test-123")
        assert retrieved_state is not None
        assert retrieved_state.migration_id == "test-123"
        assert retrieved_state.migration_status == MigrationStatus.PENDING
    
    def test_list_migration_states(self, migration_manager):
        """Test listing all migration states."""
        manager = migration_manager
        
        # Initially empty
        assert len(manager.list_migration_states()) == 0
        
        # Add multiple states
        state1 = MigrationState(
            migration_id="test-1",
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.PENDING,
            files_migrated=0,
            total_files=100,
            bytes_migrated=0,
            total_bytes=1000000,
            estimated_completion=None
        )
        
        state2 = MigrationState(
            migration_id="test-2",
            source_drive="/dev/sdd1",
            target_drives=["/dev/sde1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=50,
            total_files=200,
            bytes_migrated=500000,
            total_bytes=2000000,
            estimated_completion=None
        )
        
        manager._migration_states["test-1"] = state1
        manager._migration_states["test-2"] = state2
        
        states = manager.list_migration_states()
        assert len(states) == 2
        
        migration_ids = [state.migration_id for state in states]
        assert "test-1" in migration_ids
        assert "test-2" in migration_ids
    
    def test_analyze_ntfs_drive_invalid_filesystem(self, migration_manager, sample_ext4_drive):
        """Test analyzing non-NTFS drive raises error."""
        manager = migration_manager
        
        with pytest.raises(ValueError, match="is not NTFS"):
            manager.analyze_ntfs_drive(sample_ext4_drive)
    
    @patch('os.walk')
    def test_analyze_ntfs_drive_success(self, mock_walk, migration_manager, sample_ntfs_drive):
        """Test successful NTFS drive analysis."""
        manager = migration_manager
        
        # Mock os.walk to return simple structure
        mock_walk.return_value = [
            ("/mnt/ntfs_drive", [], ["test1.txt", "test2.jpg"])
        ]
        
        # Mock os.stat
        with patch('os.stat') as mock_stat:
            mock_stat_result = Mock()
            mock_stat_result.st_size = 1000
            mock_stat_result.st_mtime = 1234567890
            mock_stat.return_value = mock_stat_result
            
            assessment = manager.analyze_ntfs_drive(sample_ntfs_drive)
        
        assert assessment.source_drive == sample_ntfs_drive
        assert assessment.total_files == 2
        assert assessment.total_size_bytes == 2000
        assert assessment.space_required_bytes == int(2000 * 1.2)  # 20% buffer
        assert assessment.estimated_duration_hours > 0
        assert len(assessment.recommendations) > 0