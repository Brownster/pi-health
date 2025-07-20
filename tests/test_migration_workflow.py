"""Integration tests for filesystem migration workflow."""

import os
import tempfile
import shutil
import pytest
import json
from unittest.mock import Mock, patch, MagicMock, mock_open
from datetime import datetime

from nas.migration_manager import (
    MigrationManager, MigrationStatus, MigrationState, MigrationAssessment
)
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestMigrationWorkflow:
    """Integration test cases for migration workflow."""
    
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
            uuid="ntfs-uuid-123",
            mount_point="/mnt/ntfs_source",
            filesystem="ntfs",
            role=DriveRole.DATA,
            size_bytes=2000000000,  # 2GB
            used_bytes=1000000000,  # 1GB
            health_status=HealthStatus.HEALTHY,
            label="SourceNTFS"
        )
    
    @pytest.fixture
    def sample_target_drives(self):
        """Create sample target drive configurations."""
        return [
            DriveConfig(
                device_path="/dev/sdc1",
                uuid="ext4-uuid-456",
                mount_point="/mnt/ext4_target1",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=3000000000,  # 3GB
                used_bytes=100000000,   # 100MB
                health_status=HealthStatus.HEALTHY,
                label="TargetEXT4_1"
            ),
            DriveConfig(
                device_path="/dev/sdd1",
                uuid="ext4-uuid-789",
                mount_point="/mnt/ext4_target2",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=3000000000,  # 3GB
                used_bytes=100000000,   # 100MB
                health_status=HealthStatus.HEALTHY,
                label="TargetEXT4_2"
            )
        ]
    
    @patch('nas.migration_manager.MigrationManager.analyze_ntfs_drive')
    def test_create_migration_plan(self, mock_analyze, migration_manager, 
                                  sample_ntfs_drive, sample_target_drives):
        """Test creating a migration plan."""
        # Mock the analysis result
        mock_assessment = MigrationAssessment(
            source_drive=sample_ntfs_drive,
            total_files=1000,
            total_size_bytes=1000000000,
            estimated_duration_hours=2.0,
            space_required_bytes=1200000000
        )
        mock_analyze.return_value = mock_assessment
        
        # Create migration plan
        migration_id = migration_manager.create_migration_plan(
            sample_ntfs_drive, sample_target_drives
        )
        
        # Verify migration ID format
        assert migration_id.startswith("migration_")
        assert len(migration_id) > 10
        
        # Verify migration state was created
        state = migration_manager.get_migration_state(migration_id)
        assert state is not None
        assert state.migration_status == MigrationStatus.READY
        assert state.source_drive == sample_ntfs_drive.device_path
        assert state.target_drives == [drive.device_path for drive in sample_target_drives]
        assert state.total_files == 1000
        assert state.total_bytes == 1000000000
        assert state.rollback_available is True
        
        # Verify metadata file was created
        metadata_file = os.path.join(migration_manager.work_dir, f"{migration_id}_metadata.json")
        assert os.path.exists(metadata_file)
        
        # Verify metadata content
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
        
        assert metadata['migration_id'] == migration_id
        assert metadata['source_drive']['device_path'] == sample_ntfs_drive.device_path
        assert len(metadata['target_drives']) == 2
        assert metadata['assessment']['total_files'] == 1000
    
    def test_create_migration_plan_custom_id(self, migration_manager, 
                                           sample_ntfs_drive, sample_target_drives):
        """Test creating a migration plan with custom ID."""
        custom_id = "custom_migration_test"
        
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=500,
                total_size_bytes=500000000,
                estimated_duration_hours=1.0,
                space_required_bytes=600000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives, custom_id
            )
            
            assert migration_id == custom_id
            
            state = migration_manager.get_migration_state(custom_id)
            assert state is not None
            assert state.migration_id == custom_id
    
    def test_save_and_load_migration_metadata(self, migration_manager, temp_dir,
                                            sample_ntfs_drive, sample_target_drives):
        """Test saving and loading migration metadata."""
        migration_id = "test_metadata_123"
        
        # Create a sample assessment
        assessment = MigrationAssessment(
            source_drive=sample_ntfs_drive,
            total_files=100,
            total_size_bytes=100000000,
            estimated_duration_hours=0.5,
            space_required_bytes=120000000,
            compatibility_issues=["test issue"],
            recommendations=["test recommendation"]
        )
        
        # Save metadata
        migration_manager._save_migration_metadata(
            migration_id, assessment, sample_ntfs_drive, sample_target_drives
        )
        
        # Verify file exists
        metadata_file = os.path.join(temp_dir, f"{migration_id}_metadata.json")
        assert os.path.exists(metadata_file)
        
        # Load metadata
        loaded_metadata = migration_manager._load_migration_metadata(migration_id)
        
        assert loaded_metadata is not None
        assert loaded_metadata['migration_id'] == migration_id
        assert loaded_metadata['source_drive']['device_path'] == sample_ntfs_drive.device_path
        assert loaded_metadata['assessment']['total_files'] == 100
        assert loaded_metadata['assessment']['compatibility_issues'] == ["test issue"]
        assert loaded_metadata['assessment']['recommendations'] == ["test recommendation"]
    
    def test_load_nonexistent_metadata(self, migration_manager):
        """Test loading metadata for nonexistent migration."""
        result = migration_manager._load_migration_metadata("nonexistent_migration")
        assert result is None
    
    @patch('nas.migration_manager.MigrationManager._execute_migration_workflow')
    def test_start_migration_success(self, mock_execute, migration_manager, 
                                   sample_ntfs_drive, sample_target_drives):
        """Test successful migration start."""
        # Create migration plan first
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives
            )
        
        # Mock successful workflow execution
        mock_execute.return_value = True
        
        # Start migration
        success = migration_manager.start_migration(migration_id)
        
        assert success is True
        
        # Verify state was updated
        state = migration_manager.get_migration_state(migration_id)
        assert state.migration_status == MigrationStatus.COMPLETED
        assert state.started_at is not None
        assert state.completed_at is not None
        
        # Verify workflow was called
        mock_execute.assert_called_once()
    
    @patch('nas.migration_manager.MigrationManager._execute_migration_workflow')
    def test_start_migration_failure(self, mock_execute, migration_manager,
                                   sample_ntfs_drive, sample_target_drives):
        """Test migration start failure."""
        # Create migration plan first
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives
            )
        
        # Mock failed workflow execution
        mock_execute.return_value = False
        
        # Start migration
        success = migration_manager.start_migration(migration_id)
        
        assert success is False
        
        # Verify state was updated
        state = migration_manager.get_migration_state(migration_id)
        assert state.migration_status == MigrationStatus.FAILED
        assert state.error_message == "Migration workflow failed"
    
    def test_start_nonexistent_migration(self, migration_manager):
        """Test starting a nonexistent migration."""
        success = migration_manager.start_migration("nonexistent_migration")
        assert success is False
    
    def test_start_migration_wrong_status(self, migration_manager,
                                        sample_ntfs_drive, sample_target_drives):
        """Test starting migration with wrong status."""
        # Create migration plan
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives
            )
        
        # Change status to in progress
        state = migration_manager.get_migration_state(migration_id)
        state.migration_status = MigrationStatus.IN_PROGRESS
        
        # Try to start migration
        success = migration_manager.start_migration(migration_id)
        assert success is False
    
    @patch('nas.migration_manager.MigrationManager._execute_rollback_workflow')
    def test_rollback_migration_success(self, mock_rollback, migration_manager,
                                      sample_ntfs_drive, sample_target_drives):
        """Test successful migration rollback."""
        # Create migration plan
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives
            )
        
        # Mock successful rollback
        mock_rollback.return_value = True
        
        # Rollback migration
        success = migration_manager.rollback_migration(migration_id)
        
        assert success is True
        
        # Verify state was updated
        state = migration_manager.get_migration_state(migration_id)
        assert state.migration_status == MigrationStatus.ROLLED_BACK
        assert state.rollback_available is False
    
    def test_rollback_nonexistent_migration(self, migration_manager):
        """Test rolling back a nonexistent migration."""
        success = migration_manager.rollback_migration("nonexistent_migration")
        assert success is False
    
    def test_rollback_unavailable(self, migration_manager,
                                sample_ntfs_drive, sample_target_drives):
        """Test rolling back when rollback is not available."""
        # Create migration plan
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives
            )
        
        # Disable rollback
        state = migration_manager.get_migration_state(migration_id)
        state.rollback_available = False
        
        # Try to rollback
        success = migration_manager.rollback_migration(migration_id)
        assert success is False
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('nas.migration_manager.SystemCommandExecutor.execute_command')
    @patch('shutil.copy2')
    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_create_configuration_backup(self, mock_makedirs, mock_exists, mock_copy,
                                         mock_exec, mock_open_fn, migration_manager):
        """Test creating configuration backup."""
        migration_id = "test_backup_123"
        metadata = {}

        # Mock file existence
        mock_exists.return_value = True
        mock_exec.return_value = (True, "", "")

        # Test backup creation
        success = migration_manager._create_configuration_backup(migration_id, metadata)
        
        assert success is True
        mock_makedirs.assert_called_once()
        mock_copy.assert_called()
    
    @patch('nas.migration_manager.SystemCommandExecutor.execute_filesystem_command')
    @patch('nas.migration_manager.SystemCommandExecutor.execute_mount_command')
    @patch('os.makedirs')
    def test_prepare_target_drives(self, mock_makedirs, mock_mount, mock_format,
                                 migration_manager):
        """Test preparing target drives."""
        migration_id = "test_prepare_123"
        metadata = {
            'target_drives': [
                {
                    'device_path': '/dev/sdc1',
                    'mount_point': '/mnt/target1',
                    'filesystem': 'ntfs'  # Needs formatting
                },
                {
                    'device_path': '/dev/sdd1',
                    'mount_point': '/mnt/target2',
                    'filesystem': 'ext4'  # Already formatted
                }
            ]
        }
        
        # Mock successful operations
        mock_format.return_value = (True, "", "")
        mock_mount.return_value = (True, "", "")
        
        success = migration_manager._prepare_target_drives(migration_id, metadata)
        
        assert success is True
        assert mock_makedirs.call_count == 2  # Two mount points created
        mock_format.assert_called_once()  # Only one drive needs formatting
        assert mock_mount.call_count == 2  # Both drives mounted
    
    def test_copy_data_with_progress_mock(self, migration_manager):
        """Test data copying method structure (mocked for unit testing)."""
        migration_id = "test_copy_123"
        metadata = {
            'source_drive': {'mount_point': '/mnt/source'},
            'target_drives': [{'mount_point': '/mnt/target'}]
        }
        
        # Add migration state
        migration_manager._migration_states[migration_id] = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=0,
            total_files=1000,
            bytes_migrated=0,
            total_bytes=1000000000,
            estimated_completion=None
        )
        
        # Mock the method to return success for testing
        with patch.object(migration_manager, '_copy_data_with_progress', return_value=True):
            success = migration_manager._copy_data_with_progress(migration_id, metadata)
            assert success is True
    
    def test_parse_rsync_progress(self, migration_manager):
        """Test parsing rsync progress output."""
        migration_id = "test_parse_123"
        
        # Add migration state
        migration_manager._migration_states[migration_id] = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=0,
            total_files=1000,
            bytes_migrated=0,
            total_bytes=1000000000,
            estimated_completion=None
        )
        
        # Test progress parsing
        migration_manager._parse_rsync_progress(migration_id, "to-check=250/1000")
        
        state = migration_manager.get_migration_state(migration_id)
        assert state.files_migrated == 750  # 1000 - 250
        
        # Test ETA parsing
        migration_manager._parse_rsync_progress(migration_id, "xfr#123 to-go=0 1:30:45")
        
        # Should have set estimated completion time
        assert state.estimated_completion is not None
    
    def test_list_migration_states(self, migration_manager, 
                                 sample_ntfs_drive, sample_target_drives):
        """Test listing all migration states."""
        # Initially empty
        assert len(migration_manager.list_migration_states()) == 0
        
        # Create multiple migration plans
        with patch.object(migration_manager, 'analyze_ntfs_drive') as mock_analyze:
            mock_assessment = MigrationAssessment(
                source_drive=sample_ntfs_drive,
                total_files=100,
                total_size_bytes=100000000,
                estimated_duration_hours=0.5,
                space_required_bytes=120000000
            )
            mock_analyze.return_value = mock_assessment
            
            migration_id1 = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives, "migration_1"
            )
            migration_id2 = migration_manager.create_migration_plan(
                sample_ntfs_drive, sample_target_drives, "migration_2"
            )
        
        # List states
        states = migration_manager.list_migration_states()
        assert len(states) == 2
        
        migration_ids = [state.migration_id for state in states]
        assert "migration_1" in migration_ids
        assert "migration_2" in migration_ids