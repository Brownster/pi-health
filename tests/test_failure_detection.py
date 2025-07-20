"""Tests for drive failure detection and handling."""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

from nas.failure_detector import (
    FailureDetector, FailureEvent, DriveHealthAssessment, 
    FailureRisk, FailureType
)
from nas.notification_manager import (
    NotificationManager, NotificationLevel, NotificationChannel,
    NotificationConfig, Notification
)
from nas.smart_manager import SMARTHealthStatus, SMARTTrendAnalysis
from nas.models import DriveConfig, DriveRole, HealthStatus


class TestFailureDetector:
    """Test cases for FailureDetector class."""
    
    @pytest.fixture
    def mock_drive_manager(self):
        """Create mock drive manager."""
        mock = Mock()
        mock.discover_drives.return_value = [
            DriveConfig(
                device_path="/dev/sdb1",
                uuid="test-uuid-1",
                mount_point="/mnt/disk1",
                filesystem="ext4",
                role=DriveRole.DATA,
                size_bytes=1000000000000,
                used_bytes=500000000000,
                health_status=HealthStatus.HEALTHY
            )
        ]
        mock.get_drive_by_device.return_value = mock.discover_drives.return_value[0]
        return mock
    
    @pytest.fixture
    def mock_snapraid_manager(self):
        """Create mock SnapRAID manager."""
        mock = Mock()
        mock.get_status.return_value = Mock(
            overall_status="healthy",
            data_drives=[],
            parity_drives=[]
        )
        return mock
    
    @pytest.fixture
    def failure_detector(self, mock_drive_manager, mock_snapraid_manager):
        """Create FailureDetector instance with mocked dependencies."""
        return FailureDetector(mock_drive_manager, mock_snapraid_manager)
    
    def test_assess_drive_health_healthy(self, failure_detector):
        """Test health assessment for healthy drive."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - healthy
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="PASSED",
            temperature=45,
            reallocated_sectors=0,
            pending_sectors=0
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=None):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.device_path == device_path
        assert assessment.overall_risk == FailureRisk.LOW
        assert len(assessment.failure_events) == 0
        assert assessment.degraded_mode_capable is True
    
    def test_assess_drive_health_smart_failure(self, failure_detector):
        """Test health assessment for drive with SMART failure."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - failed
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="FAILED",
            temperature=45,
            reallocated_sectors=0,
            pending_sectors=0
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=None):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.overall_risk == FailureRisk.CRITICAL
        assert len(assessment.failure_events) == 1
        assert assessment.failure_events[0].failure_type == FailureType.SMART_FAILURE
        assert assessment.failure_events[0].is_critical is True
    
    def test_assess_drive_health_high_temperature(self, failure_detector):
        """Test health assessment for drive with high temperature."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - high temperature
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="PASSED",
            temperature=65,  # Above critical threshold
            reallocated_sectors=0,
            pending_sectors=0
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=None):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.overall_risk == FailureRisk.HIGH
        assert len(assessment.failure_events) == 1
        assert assessment.failure_events[0].failure_type == FailureType.TEMPERATURE_CRITICAL
    
    def test_assess_drive_health_reallocated_sectors(self, failure_detector):
        """Test health assessment for drive with reallocated sectors."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - reallocated sectors
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="PASSED",
            temperature=45,
            reallocated_sectors=10,  # Above threshold
            pending_sectors=0
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=None):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.overall_risk == FailureRisk.MEDIUM
        assert len(assessment.failure_events) == 1
        assert assessment.failure_events[0].failure_type == FailureType.REALLOCATED_SECTORS
    
    def test_assess_drive_health_pending_sectors(self, failure_detector):
        """Test health assessment for drive with pending sectors."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - pending sectors
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="PASSED",
            temperature=45,
            reallocated_sectors=0,
            pending_sectors=3  # Above threshold
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=None):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.overall_risk == FailureRisk.MEDIUM
        assert len(assessment.failure_events) == 1
        assert assessment.failure_events[0].failure_type == FailureType.PENDING_SECTORS
    
    def test_assess_drive_health_with_trends(self, failure_detector):
        """Test health assessment with trend analysis."""
        device_path = "/dev/sdb1"
        
        # Mock SMART status - healthy
        mock_smart_status = SMARTHealthStatus(
            device_path=device_path,
            overall_health="PASSED",
            temperature=45,
            reallocated_sectors=0,
            pending_sectors=0
        )
        
        # Mock trend analysis - increasing reallocated sectors
        mock_trend_analysis = SMARTTrendAnalysis(
            device_path=device_path,
            analysis_period_days=7,
            reallocated_sectors_trend="increasing",
            health_degradation_risk="medium"
        )
        
        with patch.object(failure_detector.smart_manager, 'get_health_status', return_value=mock_smart_status):
            with patch.object(failure_detector.smart_manager, 'analyze_health_trends', return_value=mock_trend_analysis):
                assessment = failure_detector.assess_drive_health(device_path)
        
        assert assessment.overall_risk == FailureRisk.MEDIUM
        assert len(assessment.failure_events) == 1
        assert assessment.failure_events[0].failure_type == FailureType.REALLOCATED_SECTORS
    
    def test_get_failed_drives(self, failure_detector):
        """Test getting list of failed drives."""
        # Create mock assessments
        critical_assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[]
        )
        
        medium_assessment = DriveHealthAssessment(
            device_path="/dev/sdc1",
            overall_risk=FailureRisk.MEDIUM,
            failure_events=[]
        )
        
        failure_detector._health_assessments = {
            "/dev/sdb1": critical_assessment,
            "/dev/sdc1": medium_assessment
        }
        
        failed_drives = failure_detector.get_failed_drives()
        assert "/dev/sdb1" in failed_drives
        assert "/dev/sdc1" not in failed_drives
    
    def test_get_degraded_drives(self, failure_detector):
        """Test getting list of degraded drives."""
        # Create mock assessments
        high_assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.HIGH,
            failure_events=[],
            degraded_mode_capable=True
        )
        
        medium_assessment = DriveHealthAssessment(
            device_path="/dev/sdc1",
            overall_risk=FailureRisk.MEDIUM,
            failure_events=[],
            degraded_mode_capable=True
        )
        
        low_assessment = DriveHealthAssessment(
            device_path="/dev/sdd1",
            overall_risk=FailureRisk.LOW,
            failure_events=[],
            degraded_mode_capable=True
        )
        
        failure_detector._health_assessments = {
            "/dev/sdb1": high_assessment,
            "/dev/sdc1": medium_assessment,
            "/dev/sdd1": low_assessment
        }
        
        degraded_drives = failure_detector.get_degraded_drives()
        assert "/dev/sdb1" in degraded_drives
        assert "/dev/sdc1" in degraded_drives
        assert "/dev/sdd1" not in degraded_drives
    
    def test_can_system_operate_degraded_no_failures(self, failure_detector):
        """Test degraded mode check with no failures."""
        failure_detector._health_assessments = {}
        
        can_operate, reason = failure_detector.can_system_operate_degraded()
        assert can_operate is True
        assert "No failed drives" in reason
    
    def test_can_system_operate_degraded_single_failure(self, failure_detector):
        """Test degraded mode check with single drive failure."""
        # Mock single failed drive
        critical_assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[]
        )
        
        failure_detector._health_assessments = {"/dev/sdb1": critical_assessment}
        
        with patch.object(failure_detector.snapraid_manager, 'get_status') as mock_status:
            mock_status.return_value = Mock()
            can_operate, reason = failure_detector.can_system_operate_degraded()
            assert can_operate is True
            assert "1 data drive failure" in reason
    
    def test_get_recovery_recommendations(self, failure_detector):
        """Test getting recovery recommendations."""
        device_path = "/dev/sdb1"
        
        # Create assessment with failure events
        failure_event = FailureEvent(
            device_path=device_path,
            failure_type=FailureType.SMART_FAILURE,
            risk_level=FailureRisk.CRITICAL,
            timestamp=datetime.now(),
            message="SMART failure detected",
            recommended_actions=["Replace drive immediately", "Backup data"]
        )
        
        assessment = DriveHealthAssessment(
            device_path=device_path,
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[failure_event]
        )
        
        failure_detector._health_assessments = {device_path: assessment}
        
        recommendations = failure_detector.get_recovery_recommendations(device_path)
        assert "Replace drive immediately" in recommendations
        assert "Backup data" in recommendations
        assert "URGENT: Backup all important data immediately" in recommendations
    
    def test_monitoring_lifecycle(self, failure_detector):
        """Test starting and stopping monitoring."""
        assert failure_detector._monitoring_active is False
        
        # Start monitoring
        failure_detector.start_monitoring()
        assert failure_detector._monitoring_active is True
        assert failure_detector._monitor_thread is not None
        
        # Stop monitoring
        failure_detector.stop_monitoring()
        assert failure_detector._monitoring_active is False
    
    def test_to_dict_conversion(self, failure_detector):
        """Test converting assessment to dictionary."""
        failure_event = FailureEvent(
            device_path="/dev/sdb1",
            failure_type=FailureType.SMART_FAILURE,
            risk_level=FailureRisk.CRITICAL,
            timestamp=datetime.now(),
            message="Test failure"
        )
        
        assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[failure_event]
        )
        
        result = failure_detector.to_dict(assessment)
        
        assert result['device_path'] == "/dev/sdb1"
        assert result['overall_risk'] == "critical"
        assert len(result['failure_events']) == 1
        assert result['failure_events'][0]['failure_type'] == "smart_failure"


class TestNotificationManager:
    """Test cases for NotificationManager class."""
    
    @pytest.fixture
    def temp_config_file(self):
        """Create temporary config file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            config_file = f.name
        yield config_file
        os.unlink(config_file)
    
    @pytest.fixture
    def notification_manager(self, temp_config_file):
        """Create NotificationManager instance."""
        return NotificationManager(config_file=temp_config_file)
    
    def test_initialization(self, notification_manager):
        """Test notification manager initialization."""
        assert notification_manager.config is not None
        assert notification_manager.config.enabled is True
        assert NotificationChannel.LOG in notification_manager.config.channels
    
    def test_notify_drive_failure_critical(self, notification_manager):
        """Test notification for critical drive failure."""
        failure_event = FailureEvent(
            device_path="/dev/sdb1",
            failure_type=FailureType.SMART_FAILURE,
            risk_level=FailureRisk.CRITICAL,
            timestamp=datetime.now(),
            message="SMART failure detected"
        )
        
        assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[failure_event]
        )
        
        with patch.object(notification_manager, '_send_notification', return_value=True) as mock_send:
            result = notification_manager.notify_drive_failure(assessment)
            assert result is True
            mock_send.assert_called_once()
            
            # Check notification content
            notification = mock_send.call_args[0][0]
            assert notification.level == NotificationLevel.CRITICAL
            assert "/dev/sdb1" in notification.title
            assert "CRITICAL" in notification.title
    
    def test_notify_drive_failure_rate_limiting(self, notification_manager):
        """Test rate limiting for drive failure notifications."""
        assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[]
        )
        
        # Set short rate limit for testing
        notification_manager.config.rate_limit_minutes = 1
        
        with patch.object(notification_manager, '_send_notification', return_value=True):
            # First notification should succeed
            result1 = notification_manager.notify_drive_failure(assessment)
            assert result1 is True
            
            # Second notification should be rate limited
            result2 = notification_manager.notify_drive_failure(assessment)
            assert result2 is False
    
    def test_notify_system_status(self, notification_manager):
        """Test system status notification."""
        with patch.object(notification_manager, '_send_notification', return_value=True) as mock_send:
            result = notification_manager.notify_system_status(
                "System Status", 
                "All systems operational", 
                NotificationLevel.INFO
            )
            assert result is True
            mock_send.assert_called_once()
    
    def test_notify_recovery_needed(self, notification_manager):
        """Test recovery needed notification."""
        recovery_steps = ["Step 1", "Step 2", "Step 3"]
        
        with patch.object(notification_manager, '_send_notification', return_value=True) as mock_send:
            result = notification_manager.notify_recovery_needed("/dev/sdb1", recovery_steps)
            assert result is True
            mock_send.assert_called_once()
            
            notification = mock_send.call_args[0][0]
            assert notification.level == NotificationLevel.ERROR
            assert notification.recommended_actions == recovery_steps
    
    def test_get_recent_notifications(self, notification_manager):
        """Test getting recent notifications."""
        # Add some test notifications
        old_notification = Notification(
            id="old",
            level=NotificationLevel.INFO,
            title="Old notification",
            message="Old message",
            timestamp=datetime.now() - timedelta(hours=25)  # Older than 24 hours
        )
        
        recent_notification = Notification(
            id="recent",
            level=NotificationLevel.WARNING,
            title="Recent notification",
            message="Recent message",
            timestamp=datetime.now() - timedelta(hours=1)  # Within 24 hours
        )
        
        notification_manager._notification_history = [old_notification, recent_notification]
        
        recent = notification_manager.get_recent_notifications(hours=24)
        assert len(recent) == 1
        assert recent[0].id == "recent"
    
    def test_get_critical_notifications(self, notification_manager):
        """Test getting critical notifications."""
        critical_notification = Notification(
            id="critical",
            level=NotificationLevel.CRITICAL,
            title="Critical issue",
            message="Critical message",
            timestamp=datetime.now()
        )
        
        warning_notification = Notification(
            id="warning",
            level=NotificationLevel.WARNING,
            title="Warning issue",
            message="Warning message",
            timestamp=datetime.now()
        )
        
        notification_manager._notification_history = [critical_notification, warning_notification]
        
        critical = notification_manager.get_critical_notifications()
        assert len(critical) == 1
        assert critical[0].id == "critical"
    
    def test_send_log_notification(self, notification_manager):
        """Test sending log notification."""
        notification = Notification(
            id="test",
            level=NotificationLevel.ERROR,
            title="Test Error",
            message="Test error message",
            timestamp=datetime.now()
        )
        
        with patch('nas.notification_manager.logger') as mock_logger:
            notification_manager._send_log_notification(notification)
            mock_logger.error.assert_called_once()
    
    @patch('smtplib.SMTP')
    def test_send_email_notification(self, mock_smtp, notification_manager):
        """Test sending email notification."""
        # Configure email settings
        notification_manager.config.email_from = "test@example.com"
        notification_manager.config.email_to = ["recipient@example.com"]
        notification_manager.config.email_smtp_server = "smtp.example.com"
        notification_manager.config.email_smtp_port = 587
        
        notification = Notification(
            id="test",
            level=NotificationLevel.ERROR,
            title="Test Error",
            message="Test error message",
            timestamp=datetime.now()
        )
        
        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        result = notification_manager._send_email_notification(notification)
        assert result is True
        mock_server.send_message.assert_called_once()
    
    def test_update_config(self, notification_manager):
        """Test updating configuration."""
        result = notification_manager.update_config(
            enabled=False,
            rate_limit_minutes=30
        )
        
        assert result is True
        assert notification_manager.config.enabled is False
        assert notification_manager.config.rate_limit_minutes == 30
    
    def test_test_notification_log(self, notification_manager):
        """Test sending test notification to log."""
        with patch.object(notification_manager, '_send_log_notification') as mock_log:
            result = notification_manager.test_notification(NotificationChannel.LOG)
            assert result is True
            mock_log.assert_called_once()
    
    def test_risk_to_notification_level_mapping(self, notification_manager):
        """Test risk to notification level mapping."""
        assert notification_manager._risk_to_notification_level(FailureRisk.LOW) == NotificationLevel.INFO
        assert notification_manager._risk_to_notification_level(FailureRisk.MEDIUM) == NotificationLevel.WARNING
        assert notification_manager._risk_to_notification_level(FailureRisk.HIGH) == NotificationLevel.ERROR
        assert notification_manager._risk_to_notification_level(FailureRisk.CRITICAL) == NotificationLevel.CRITICAL
    
    def test_create_failure_title(self, notification_manager):
        """Test creating failure notification title."""
        assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[]
        )
        
        title = notification_manager._create_failure_title(assessment)
        assert "CRITICAL" in title
        assert "/dev/sdb1" in title
    
    def test_create_failure_message(self, notification_manager):
        """Test creating failure notification message."""
        failure_event = FailureEvent(
            device_path="/dev/sdb1",
            failure_type=FailureType.SMART_FAILURE,
            risk_level=FailureRisk.CRITICAL,
            timestamp=datetime.now(),
            message="SMART failure detected"
        )
        
        assessment = DriveHealthAssessment(
            device_path="/dev/sdb1",
            overall_risk=FailureRisk.CRITICAL,
            failure_events=[failure_event],
            degraded_mode_capable=False
        )
        
        message = notification_manager._create_failure_message(assessment)
        assert "/dev/sdb1" in message
        assert "critical failure risk" in message
        assert "SMART failure detected" in message
        assert "degraded mode" in message


if __name__ == "__main__":
    pytest.main([__file__])