"""Unit tests for the FailureDetector class."""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from nas.failure_detector import FailureDetector, FailureRisk, FailureType
from nas.models import DriveHealthState

class TestFailureDetector(unittest.TestCase):
    """Test suite for the FailureDetector class."""

    def setUp(self):
        """Set up the test environment."""
        self.drive_manager = MagicMock()
        self.snapraid_manager = MagicMock()
        self.smart_manager = MagicMock()
        self.failure_detector = FailureDetector(self.drive_manager, self.snapraid_manager, self.smart_manager)

    @patch('nas.failure_detector.os.path.exists')
    @patch('nas.failure_detector.os.access')
    def test_assess_drive_health_healthy(self, mock_access, mock_exists):
        """Test drive health assessment for a healthy drive."""
        # Arrange
        device_path = "/dev/sda"
        smart_status = MagicMock()
        smart_status.overall_health = "PASSED"
        smart_status.temperature = 40
        smart_status.reallocated_sectors = 0
        smart_status.pending_sectors = 0
        self.smart_manager.get_health_status.return_value = smart_status
        self.smart_manager.analyze_health_trends.return_value = None
        self.drive_manager.get_drive_by_device.return_value = MagicMock()
        mock_exists.return_value = True
        mock_access.return_value = True

        # Act
        assessment = self.failure_detector.assess_drive_health(device_path)

        # Assert
        self.assertEqual(assessment.overall_risk, FailureRisk.LOW)
        self.assertEqual(len(assessment.failure_events), 0)

    @patch('nas.failure_detector.os.path.exists')
    @patch('nas.failure_detector.os.access')
    def test_assess_drive_health_smart_failure(self, mock_access, mock_exists):
        """Test drive health assessment for a drive with a SMART failure."""
        # Arrange
        device_path = "/dev/sda"
        smart_status = MagicMock()
        smart_status.overall_health = "FAILED"
        smart_status.temperature = 40
        smart_status.reallocated_sectors = 0
        smart_status.pending_sectors = 0
        self.smart_manager.get_health_status.return_value = smart_status
        self.smart_manager.analyze_health_trends.return_value = None
        self.drive_manager.get_drive_by_device.return_value = MagicMock()
        mock_exists.return_value = True
        mock_access.return_value = True

        # Act
        assessment = self.failure_detector.assess_drive_health(device_path)

        # Assert
        self.assertEqual(assessment.overall_risk, FailureRisk.CRITICAL)
        self.assertEqual(len(assessment.failure_events), 1)
        self.assertEqual(assessment.failure_events[0].failure_type, FailureType.SMART_FAILURE)

    @patch('nas.failure_detector.os.path.exists')
    @patch('nas.failure_detector.os.access')
    def test_assess_drive_health_high_temperature(self, mock_access, mock_exists):
        """Test drive health assessment for a drive with high temperature."""
        # Arrange
        device_path = "/dev/sda"
        smart_status = MagicMock()
        smart_status.overall_health = "PASSED"
        smart_status.temperature = 65
        smart_status.reallocated_sectors = 0
        smart_status.pending_sectors = 0
        self.smart_manager.get_health_status.return_value = smart_status
        self.smart_manager.analyze_health_trends.return_value = None
        self.drive_manager.get_drive_by_device.return_value = MagicMock()
        mock_exists.return_value = True
        mock_access.return_value = True

        # Act
        assessment = self.failure_detector.assess_drive_health(device_path)

        # Assert
        self.assertEqual(assessment.overall_risk, FailureRisk.HIGH)
        self.assertEqual(len(assessment.failure_events), 1)
        self.assertEqual(assessment.failure_events[0].failure_type, FailureType.TEMPERATURE_CRITICAL)

    def test_get_failed_drives(self):
        """Test getting a list of failed drives."""
        # Arrange
        assessment1 = MagicMock()
        assessment1.overall_risk = FailureRisk.LOW
        assessment2 = MagicMock()
        assessment2.overall_risk = FailureRisk.CRITICAL
        self.failure_detector._health_assessments = {
            "/dev/sda": assessment1,
            "/dev/sdb": assessment2,
        }

        # Act
        failed_drives = self.failure_detector.get_failed_drives()

        # Assert
        self.assertEqual(len(failed_drives), 1)
        self.assertEqual(failed_drives[0], "/dev/sdb")

if __name__ == "__main__":
    unittest.main()
