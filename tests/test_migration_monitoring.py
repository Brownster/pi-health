"""Tests for migration monitoring and validation functionality."""

import os
import tempfile
import shutil
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from nas.migration_manager import (
    MigrationManager, MigrationState, MigrationStatus, MigrationAssessment,
    FileIntegrityInfo
)
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestMigrationMonitoring:
    """Test cases for migration monitoring and validation."""
    
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
    def sample_migration_state(self):
        """Create a sample migration state."""
        return MigrationState(
            migration_id="test_migration_123",
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=500,
            total_files=1000,
            bytes_migrated=500000000,  # 500MB
            total_bytes=1000000000,    # 1GB
            estimated_completion=datetime.now() + timedelta(hours=1),
            started_at=datetime.now() - timedelta(minutes=30),
            rollback_available=True
        )
    
    def test_get_migration_progress(self, migration_manager, sample_migration_state):
        """Test getting migration progress information."""
        migration_id = sample_migration_state.migration_id
        migration_manager._migration_states[migration_id] = sample_migration_state
        
        progress = migration_manager.get_migration_progress(migration_id)
        
        assert progress is not None
        assert progress['migration_id'] == migration_id
        assert progress['status'] == MigrationStatus.IN_PROGRESS.value
        assert progress['progress_percent'] == 50.0
        assert progress['bytes_progress_percent'] == 50.0
        assert progress['files_migrated'] == 500
        assert progress['total_files'] == 1000
        assert progress['bytes_migrated'] == 500000000
        assert progress['total_bytes'] == 1000000000
        assert progress['started_at'] is not None
        assert progress['estimated_completion'] is not None
        assert progress['rollback_available'] is True
        assert 'elapsed_seconds' in progress
        assert 'estimated_remaining_seconds' in progress
    
    def test_get_migration_progress_nonexistent(self, migration_manager):
        """Test getting progress for nonexistent migration."""
        progress = migration_manager.get_migration_progress("nonexistent")
        assert progress is None
    
    def test_get_migration_progress_completed(self, migration_manager):
        """Test getting progress for completed migration."""
        completed_state = MigrationState(
            migration_id="completed_migration",
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.COMPLETED,
            files_migrated=1000,
            total_files=1000,
            bytes_migrated=1000000000,
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(hours=2),
            completed_at=datetime.now() - timedelta(minutes=30),
            rollback_available=True
        )
        
        migration_manager._migration_states["completed_migration"] = completed_state
        
        progress = migration_manager.get_migration_progress("completed_migration")
        
        assert progress is not None
        assert progress['status'] == MigrationStatus.COMPLETED.value
        assert progress['progress_percent'] == 100.0
        assert progress['bytes_progress_percent'] == 100.0
        assert progress['completed_at'] is not None
        assert 'elapsed_seconds' not in progress  # Not in progress
    
    @patch('nas.migration_manager.MigrationManager._load_migration_metadata')
    def test_validate_migration_completion_success(self, mock_load_metadata, migration_manager):
        """Test successful migration validation."""
        migration_id = "test_validation_123"
        
        # Create completed migration state
        completed_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.COMPLETED,
            files_migrated=100,
            total_files=100,
            bytes_migrated=1000000,
            total_bytes=1000000,
            estimated_completion=None,
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = completed_state
        
        # Mock metadata
        mock_metadata = {
            'source_drive': {'mount_point': '/mnt/source'},
            'target_drives': [{'mount_point': '/mnt/target'}],
            'assessment': {'file_samples': []}
        }
        mock_load_metadata.return_value = mock_metadata
        
        # Mock os.path.exists and os.access
        with patch('os.path.exists', return_value=True), \
             patch('os.access', return_value=True):
            
            success, errors = migration_manager.validate_migration_completion(migration_id)
        
        assert success is True
        assert len(errors) == 0
    
    def test_validate_migration_completion_not_found(self, migration_manager):
        """Test validation for nonexistent migration."""
        success, errors = migration_manager.validate_migration_completion("nonexistent")
        
        assert success is False
        assert len(errors) == 1
        assert "Migration not found" in errors[0]
    
    def test_validate_migration_completion_wrong_status(self, migration_manager):
        """Test validation for migration with wrong status."""
        migration_id = "test_wrong_status"
        
        # Create migration with wrong status
        wrong_status_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=50,
            total_files=100,
            bytes_migrated=500000,
            total_bytes=1000000,
            estimated_completion=None,
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = wrong_status_state
        
        success, errors = migration_manager.validate_migration_completion(migration_id)
        
        assert success is False
        assert len(errors) == 1
        assert "not completed" in errors[0]
    
    @patch('nas.migration_manager.MigrationManager._load_migration_metadata')
    def test_validate_migration_completion_file_count_mismatch(self, mock_load_metadata, migration_manager):
        """Test validation with file count mismatch."""
        migration_id = "test_file_mismatch"
        
        # Create completed migration state with mismatched counts
        mismatch_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.COMPLETED,
            files_migrated=90,  # Mismatch
            total_files=100,
            bytes_migrated=1000000,
            total_bytes=1000000,
            estimated_completion=None,
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = mismatch_state
        
        # Mock metadata
        mock_metadata = {
            'source_drive': {'mount_point': '/mnt/source'},
            'target_drives': [{'mount_point': '/mnt/target'}],
            'assessment': {'file_samples': []}
        }
        mock_load_metadata.return_value = mock_metadata
        
        # Mock os.path.exists and os.access
        with patch('os.path.exists', return_value=True), \
             patch('os.access', return_value=True):
            
            success, errors = migration_manager.validate_migration_completion(migration_id)
        
        assert success is False
        assert len(errors) == 1
        assert "File count mismatch" in errors[0]
    
    def test_cleanup_migration_files(self, migration_manager, temp_dir):
        """Test cleaning up migration files."""
        migration_id = "test_cleanup_123"
        
        # Create some temporary files
        metadata_file = os.path.join(temp_dir, f"{migration_id}_metadata.json")
        progress_file = os.path.join(temp_dir, f"{migration_id}_progress.log")
        backup_dir = os.path.join(temp_dir, f"{migration_id}_backup")
        
        # Create files and directories
        with open(metadata_file, 'w') as f:
            f.write('{"test": "data"}')
        with open(progress_file, 'w') as f:
            f.write('progress log')
        os.makedirs(backup_dir, exist_ok=True)
        with open(os.path.join(backup_dir, 'test_backup.txt'), 'w') as f:
            f.write('backup data')
        
        # Test cleanup with keeping backups
        success = migration_manager.cleanup_migration_files(migration_id, keep_backups=True)
        
        assert success is True
        assert not os.path.exists(metadata_file)
        assert not os.path.exists(progress_file)
        assert os.path.exists(backup_dir)  # Should be kept
        
        # Test cleanup without keeping backups
        success = migration_manager.cleanup_migration_files(migration_id, keep_backups=False)
        
        assert success is True
        assert not os.path.exists(backup_dir)  # Should be removed
    
    @patch('nas.migration_manager.MigrationManager._load_migration_metadata')
    @patch('nas.migration_manager.MigrationManager.validate_migration_completion')
    def test_generate_migration_report(self, mock_validate, mock_load_metadata, migration_manager):
        """Test generating migration report."""
        migration_id = "test_report_123"
        
        # Create completed migration state
        completed_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.COMPLETED,
            files_migrated=1000,
            total_files=1000,
            bytes_migrated=1000000000,  # 1GB
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(hours=2),
            completed_at=datetime.now() - timedelta(minutes=30),
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = completed_state
        
        # Mock metadata
        mock_metadata = {
            'created_at': '2023-01-01T12:00:00',
            'source_drive': {'device_path': '/dev/sdb1'},
            'target_drives': [{'device_path': '/dev/sdc1'}],
            'assessment': {
                'total_files': 1000,
                'total_size_bytes': 1000000000,
                'compatibility_issues': [],
                'recommendations': ['Test recommendation']
            }
        }
        mock_load_metadata.return_value = mock_metadata
        
        # Mock validation
        mock_validate.return_value = (True, [])
        
        report = migration_manager.generate_migration_report(migration_id)
        
        assert report is not None
        assert report['migration_id'] == migration_id
        assert report['migration_status'] == MigrationStatus.COMPLETED.value
        assert report['files_processed']['migrated'] == 1000
        assert report['files_processed']['total'] == 1000
        assert report['files_processed']['success_rate'] == 100.0
        assert report['bytes_processed']['migrated'] == 1000000000
        assert report['bytes_processed']['success_rate'] == 100.0
        assert report['performance']['transfer_rate_mbps'] > 0
        assert report['validation']['passed'] is True
        assert len(report['validation']['errors']) == 0
        assert 'duration_human' in report
    
    def test_generate_migration_report_nonexistent(self, migration_manager):
        """Test generating report for nonexistent migration."""
        report = migration_manager.generate_migration_report("nonexistent")
        assert report is None
    
    def test_format_duration(self, migration_manager):
        """Test duration formatting."""
        # Test seconds
        assert "30.0 seconds" in migration_manager._format_duration(30)
        
        # Test minutes
        assert "2.0 minutes" in migration_manager._format_duration(120)
        
        # Test hours
        assert "1.5 hours" in migration_manager._format_duration(5400)
    
    @patch('psutil.disk_usage')
    @patch('nas.migration_manager.MigrationManager._load_migration_metadata')
    def test_monitor_migration_health_healthy(self, mock_load_metadata, mock_disk_usage, migration_manager):
        """Test monitoring healthy migration."""
        migration_id = "test_health_123"
        
        # Create in-progress migration state
        in_progress_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=500,
            total_files=1000,
            bytes_migrated=500000000,
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(minutes=15),  # Recent start
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = in_progress_state
        
        # Mock metadata
        mock_metadata = {
            'target_drives': [{'mount_point': '/mnt/target'}]
        }
        mock_load_metadata.return_value = mock_metadata
        
        # Mock disk usage (plenty of space)
        mock_usage = Mock()
        mock_usage.total = 1000000000
        mock_usage.free = 500000000  # 50% free
        mock_disk_usage.return_value = mock_usage
        
        health = migration_manager.monitor_migration_health(migration_id)
        
        assert health['migration_id'] == migration_id
        assert health['status'] == MigrationStatus.IN_PROGRESS.value
        assert health['health'] == 'healthy'
        assert len(health['issues']) == 0
    
    @patch('psutil.disk_usage')
    @patch('nas.migration_manager.MigrationManager._load_migration_metadata')
    def test_monitor_migration_health_low_disk_space(self, mock_load_metadata, mock_disk_usage, migration_manager):
        """Test monitoring migration with low disk space."""
        migration_id = "test_health_low_space"
        
        # Create in-progress migration state
        in_progress_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=500,
            total_files=1000,
            bytes_migrated=500000000,
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(minutes=15),
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = in_progress_state
        
        # Mock metadata
        mock_metadata = {
            'target_drives': [{'mount_point': '/mnt/target'}]
        }
        mock_load_metadata.return_value = mock_metadata
        
        # Mock disk usage (low space)
        mock_usage = Mock()
        mock_usage.total = 1000000000
        mock_usage.free = 50000000  # 5% free
        mock_disk_usage.return_value = mock_usage
        
        health = migration_manager.monitor_migration_health(migration_id)
        
        assert health['health'] == 'critical'
        assert len(health['issues']) > 0
        assert 'Low disk space' in health['issues'][0]
        assert len(health['recommendations']) > 0
    
    def test_monitor_migration_health_stalled(self, migration_manager):
        """Test monitoring stalled migration."""
        migration_id = "test_health_stalled"
        
        # Create stalled migration state (started long ago with no progress)
        stalled_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.IN_PROGRESS,
            files_migrated=0,  # No progress
            total_files=1000,
            bytes_migrated=0,
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(hours=2),  # Started 2 hours ago
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = stalled_state
        
        health = migration_manager.monitor_migration_health(migration_id)
        
        assert health['health'] == 'stalled'
        assert len(health['issues']) > 0
        assert 'stalled' in health['issues'][0]
        assert 'restarting' in health['recommendations'][0]
    
    def test_monitor_migration_health_failed(self, migration_manager):
        """Test monitoring failed migration."""
        migration_id = "test_health_failed"
        
        # Create failed migration state
        failed_state = MigrationState(
            migration_id=migration_id,
            source_drive="/dev/sdb1",
            target_drives=["/dev/sdc1"],
            migration_status=MigrationStatus.FAILED,
            files_migrated=300,
            total_files=1000,
            bytes_migrated=300000000,
            total_bytes=1000000000,
            estimated_completion=None,
            started_at=datetime.now() - timedelta(hours=1),
            error_message="Disk I/O error",
            rollback_available=True
        )
        
        migration_manager._migration_states[migration_id] = failed_state
        
        health = migration_manager.monitor_migration_health(migration_id)
        
        assert health['health'] == 'failed'
        assert len(health['issues']) > 0
        assert 'Disk I/O error' in health['issues'][0]
        assert 'rollback' in health['recommendations'][0]
    
    def test_monitor_migration_health_nonexistent(self, migration_manager):
        """Test monitoring nonexistent migration."""
        health = migration_manager.monitor_migration_health("nonexistent")
        
        assert health['status'] == 'not_found'
        assert 'not found' in health['message']
    
    def test_get_migration_statistics(self, migration_manager):
        """Test getting overall migration statistics."""
        # Add multiple migration states
        states = [
            MigrationState(
                migration_id="migration_1",
                source_drive="/dev/sdb1",
                target_drives=["/dev/sdc1"],
                migration_status=MigrationStatus.COMPLETED,
                files_migrated=1000,
                total_files=1000,
                bytes_migrated=1000000000,
                total_bytes=1000000000,
                estimated_completion=None,
                started_at=datetime.now() - timedelta(hours=2),
                completed_at=datetime.now() - timedelta(hours=1),
                rollback_available=True
            ),
            MigrationState(
                migration_id="migration_2",
                source_drive="/dev/sdd1",
                target_drives=["/dev/sde1"],
                migration_status=MigrationStatus.FAILED,
                files_migrated=500,
                total_files=1000,
                bytes_migrated=500000000,
                total_bytes=1000000000,
                estimated_completion=None,
                started_at=datetime.now() - timedelta(hours=1),
                rollback_available=True
            ),
            MigrationState(
                migration_id="migration_3",
                source_drive="/dev/sdf1",
                target_drives=["/dev/sdg1"],
                migration_status=MigrationStatus.IN_PROGRESS,
                files_migrated=300,
                total_files=1000,
                bytes_migrated=300000000,
                total_bytes=1000000000,
                estimated_completion=None,
                started_at=datetime.now() - timedelta(minutes=30),
                rollback_available=True
            )
        ]
        
        for state in states:
            migration_manager._migration_states[state.migration_id] = state
        
        stats = migration_manager.get_migration_statistics()
        
        assert stats['total_migrations'] == 3
        assert stats['by_status'][MigrationStatus.COMPLETED.value] == 1
        assert stats['by_status'][MigrationStatus.FAILED.value] == 1
        assert stats['by_status'][MigrationStatus.IN_PROGRESS.value] == 1
        assert stats['total_files_migrated'] == 1800  # 1000 + 500 + 300
        assert stats['total_bytes_migrated'] == 1800000000  # 1GB + 500MB + 300MB
        assert stats['success_rate'] == 50.0  # 1 success out of 2 completed (1 success + 1 failure)
        assert abs(stats['average_duration_seconds'] - 3600) < 1  # 1 hour for the completed migration (allow small precision difference)
        assert 'total_bytes_migrated_gb' in stats
        assert 'average_duration_human' in stats
    
    def test_get_migration_statistics_empty(self, migration_manager):
        """Test getting statistics with no migrations."""
        stats = migration_manager.get_migration_statistics()
        
        assert stats['total_migrations'] == 0
        assert stats['total_files_migrated'] == 0
        assert stats['total_bytes_migrated'] == 0
        assert stats['success_rate'] == 0
        assert stats['average_duration_seconds'] == 0