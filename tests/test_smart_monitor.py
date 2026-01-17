"""Tests for the SMART disk health monitoring module."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from smart_monitor import (
    SmartHealth,
    parse_smartctl_json,
    get_smart_data,
    get_all_smart_data,
    format_power_on_hours,
    _parse_nvme_attributes,
    _parse_ata_attributes,
    _calculate_health_status,
)


# ============================================
# Sample smartctl JSON outputs for testing
# ============================================

SAMPLE_HDD_JSON = {
    "device": {"name": "/dev/sda", "type": "scsi"},
    "model_name": "WDC WD80EFAX-68K",
    "serial_number": "ABC123",
    "rotation_rate": 5400,
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "temperature": {"current": 35},
    "power_on_time": {"hours": 12345},
    "ata_smart_attributes": {
        "table": [
            {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "thresh": 10, "raw": {"value": 0}},
            {"id": 9, "name": "Power_On_Hours", "value": 99, "worst": 99, "thresh": 0, "raw": {"value": 12345}},
            {"id": 194, "name": "Temperature_Celsius", "value": 65, "worst": 50, "thresh": 0, "raw": {"value": 35}},
            {"id": 197, "name": "Current_Pending_Sector", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 0}},
            {"id": 198, "name": "Offline_Uncorrectable", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 0}},
        ]
    }
}

SAMPLE_HDD_WITH_WARNINGS_JSON = {
    "device": {"name": "/dev/sdb", "type": "scsi"},
    "model_name": "Seagate ST8000VN",
    "serial_number": "DEF456",
    "rotation_rate": 7200,
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "temperature": {"current": 45},
    "power_on_time": {"hours": 50000},
    "ata_smart_attributes": {
        "table": [
            {"id": 5, "name": "Reallocated_Sector_Ct", "value": 99, "worst": 99, "thresh": 10, "raw": {"value": 8}},
            {"id": 197, "name": "Current_Pending_Sector", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 2}},
            {"id": 198, "name": "Offline_Uncorrectable", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 1}},
        ]
    }
}

SAMPLE_SSD_JSON = {
    "device": {"name": "/dev/sdc", "type": "scsi"},
    "model_name": "Samsung SSD 870 EVO",
    "serial_number": "GHI789",
    "rotation_rate": 0,  # SSD indicator
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "temperature": {"current": 32},
    "power_on_time": {"hours": 5000},
    "ata_smart_attributes": {
        "table": [
            {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "thresh": 10, "raw": {"value": 0}},
            {"id": 177, "name": "Wear_Leveling_Count", "value": 99, "worst": 99, "thresh": 0, "raw": {"value": 1}},
        ]
    }
}

SAMPLE_NVME_JSON = {
    "device": {"name": "/dev/nvme0", "type": "nvme"},
    "model_name": "Samsung SSD 980 PRO",
    "serial_number": "JKL012",
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "nvme_smart_health_information_log": {
        "critical_warning": 0,
        "temperature": 38,
        "available_spare": 100,
        "available_spare_threshold": 10,
        "percentage_used": 2,
        "data_units_read": 12345678,
        "data_units_written": 9876543,
        "host_reads": 123456,
        "host_writes": 98765,
        "controller_busy_time": 100,
        "power_cycles": 50,
        "power_on_hours": 1000,
        "unsafe_shutdowns": 5,
        "media_errors": 0,
        "num_err_log_entries": 0
    },
    "power_on_time": {"hours": 1000}
}

SAMPLE_NVME_WITH_WARNINGS_JSON = {
    "device": {"name": "/dev/nvme1", "type": "nvme"},
    "model_name": "Generic NVMe",
    "serial_number": "MNO345",
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": True},
    "nvme_smart_health_information_log": {
        "temperature": 65,
        "available_spare": 5,
        "percentage_used": 95,
        "media_errors": 3,
        "power_on_hours": 20000
    },
    "power_on_time": {"hours": 20000}
}

SAMPLE_FAILING_DRIVE_JSON = {
    "device": {"name": "/dev/sdd", "type": "scsi"},
    "model_name": "Failing Drive",
    "serial_number": "FAIL001",
    "rotation_rate": 7200,
    "smart_support": {"available": True, "enabled": True},
    "smart_status": {"passed": False},  # SMART self-test failed
    "temperature": {"current": 50},
    "ata_smart_attributes": {"table": []}
}

SAMPLE_NO_SMART_JSON = {
    "device": {"name": "/dev/sde", "type": "scsi"},
    "model_name": "USB Flash Drive",
    "serial_number": "USB001",
    "smart_support": {"available": False, "enabled": False},
}


# ============================================
# Test SmartHealth dataclass
# ============================================

class TestSmartHealthDataclass:
    """Tests for SmartHealth dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        health = SmartHealth(device="/dev/sda")
        assert health.device == "/dev/sda"
        assert health.model == "Unknown"
        assert health.serial == "Unknown"
        assert health.drive_type == "unknown"
        assert health.smart_available is False
        assert health.health_status == "unknown"
        assert health.attributes == []

    def test_to_dict(self):
        """Test conversion to dictionary."""
        health = SmartHealth(
            device="/dev/sda",
            model="Test Drive",
            temperature_c=35
        )
        d = health.to_dict()
        assert isinstance(d, dict)
        assert d['device'] == "/dev/sda"
        assert d['model'] == "Test Drive"
        assert d['temperature_c'] == 35


# ============================================
# Test parse_smartctl_json function
# ============================================

class TestParseSmartctlJson:
    """Tests for parsing smartctl JSON output."""

    def test_parse_healthy_hdd(self):
        """Test parsing a healthy HDD."""
        health = parse_smartctl_json(SAMPLE_HDD_JSON)

        assert health.device == "/dev/sda"
        assert health.model == "WDC WD80EFAX-68K"
        assert health.serial == "ABC123"
        assert health.drive_type == "hdd"
        assert health.smart_available is True
        assert health.smart_enabled is True
        assert health.health_status == "healthy"
        assert health.temperature_c == 35
        assert health.power_on_hours == 12345
        assert health.reallocated_sectors == 0
        assert health.pending_sectors == 0

    def test_parse_hdd_with_warnings(self):
        """Test parsing an HDD with warning conditions."""
        health = parse_smartctl_json(SAMPLE_HDD_WITH_WARNINGS_JSON)

        assert health.health_status == "warning"
        assert health.reallocated_sectors == 8
        assert health.pending_sectors == 2
        assert health.uncorrectable_errors == 1
        assert "Reallocated sectors" in health.error_message
        assert "Pending sectors" in health.error_message

    def test_parse_ssd(self):
        """Test parsing an SSD."""
        health = parse_smartctl_json(SAMPLE_SSD_JSON)

        assert health.drive_type == "ssd"
        assert health.health_status == "healthy"
        assert health.temperature_c == 32

    def test_parse_nvme(self):
        """Test parsing an NVMe drive."""
        health = parse_smartctl_json(SAMPLE_NVME_JSON)

        assert health.drive_type == "nvme"
        assert health.health_status == "healthy"
        assert health.temperature_c == 38
        assert health.percentage_used == 2
        assert health.available_spare == 100
        assert health.media_errors == 0
        assert len(health.attributes) > 0

    def test_parse_nvme_with_warnings(self):
        """Test parsing NVMe drive with warning conditions."""
        health = parse_smartctl_json(SAMPLE_NVME_WITH_WARNINGS_JSON)

        assert health.health_status == "warning"
        assert "percentage used" in health.error_message.lower()
        assert "available spare" in health.error_message.lower()
        assert "media errors" in health.error_message.lower()

    def test_parse_failing_drive(self):
        """Test parsing a drive that failed SMART self-test."""
        health = parse_smartctl_json(SAMPLE_FAILING_DRIVE_JSON)

        assert health.health_status == "failing"

    def test_parse_no_smart_support(self):
        """Test parsing a drive without SMART support."""
        health = parse_smartctl_json(SAMPLE_NO_SMART_JSON)

        assert health.smart_available is False
        assert health.health_status == "unknown"

    def test_parse_empty_data(self):
        """Test parsing empty/minimal JSON."""
        health = parse_smartctl_json({})

        assert health.device == "unknown"
        assert health.model == "Unknown"

    def test_parse_missing_fields(self):
        """Test parsing JSON with missing optional fields."""
        minimal_json = {
            "device": {"name": "/dev/sdx"},
            "model_name": "Test",
            "smart_support": {"available": True, "enabled": True},
            "smart_status": {"passed": True}
        }
        health = parse_smartctl_json(minimal_json)

        assert health.device == "/dev/sdx"
        assert health.temperature_c is None
        assert health.power_on_hours is None


# ============================================
# Test _calculate_health_status function
# ============================================

class TestCalculateHealthStatus:
    """Tests for health status calculation."""

    def test_already_failing_not_overwritten(self):
        """Test that failing status is not overwritten."""
        health = SmartHealth(device="/dev/sda", health_status="failing")
        _calculate_health_status(health)
        assert health.health_status == "failing"

    def test_reallocated_sectors_warning(self):
        """Test warning for reallocated sectors."""
        health = SmartHealth(device="/dev/sda", reallocated_sectors=5, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"

    def test_pending_sectors_warning(self):
        """Test warning for pending sectors."""
        health = SmartHealth(device="/dev/sda", pending_sectors=1, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"

    def test_high_temperature_warning(self):
        """Test warning for high temperature."""
        health = SmartHealth(device="/dev/sda", temperature_c=60, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"
        assert "temperature" in health.error_message.lower()

    def test_nvme_high_percentage_used_warning(self):
        """Test warning for NVMe high percentage used."""
        health = SmartHealth(device="/dev/nvme0", percentage_used=95, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"

    def test_nvme_low_spare_warning(self):
        """Test warning for NVMe low available spare."""
        health = SmartHealth(device="/dev/nvme0", available_spare=5, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"

    def test_nvme_media_errors_warning(self):
        """Test warning for NVMe media errors."""
        health = SmartHealth(device="/dev/nvme0", media_errors=1, smart_available=True)
        _calculate_health_status(health)
        assert health.health_status == "warning"

    def test_healthy_when_no_issues(self):
        """Test healthy status when no issues found."""
        health = SmartHealth(
            device="/dev/sda",
            smart_available=True,
            reallocated_sectors=0,
            pending_sectors=0,
            temperature_c=35
        )
        _calculate_health_status(health)
        assert health.health_status == "healthy"

    def test_multiple_warnings_combined(self):
        """Test multiple warning conditions are combined."""
        health = SmartHealth(
            device="/dev/sda",
            smart_available=True,
            reallocated_sectors=5,
            pending_sectors=2,
            temperature_c=60
        )
        _calculate_health_status(health)
        assert health.health_status == "warning"
        assert "Reallocated" in health.error_message
        assert "Pending" in health.error_message
        assert "temperature" in health.error_message.lower()


# ============================================
# Test get_smart_data function
# ============================================

class TestGetSmartData:
    """Tests for getting SMART data from a device."""

    @patch('smart_monitor.subprocess.run')
    def test_successful_query(self, mock_run):
        """Test successful smartctl query."""
        import json
        mock_run.return_value = MagicMock(
            stdout=json.dumps(SAMPLE_HDD_JSON),
            stderr="",
            returncode=0
        )

        health = get_smart_data("/dev/sda")

        assert health.device == "/dev/sda"
        assert health.model == "WDC WD80EFAX-68K"
        mock_run.assert_called_once()

    @patch('smart_monitor.subprocess.run')
    def test_retry_with_sat_on_usb(self, mock_run):
        """Test retry with -d sat for USB drives."""
        import json
        # First call fails (no output), second with SAT succeeds
        mock_run.side_effect = [
            MagicMock(stdout="", stderr="can't read device", returncode=1),
            MagicMock(stdout=json.dumps(SAMPLE_HDD_JSON), stderr="", returncode=0)
        ]

        health = get_smart_data("/dev/sda")

        assert health.model == "WDC WD80EFAX-68K"
        assert mock_run.call_count == 2

    @patch('smart_monitor.subprocess.run')
    def test_timeout_handling(self, mock_run):
        """Test timeout is handled gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="smartctl", timeout=30)

        health = get_smart_data("/dev/sda")

        assert health.error_message == "Timeout reading SMART data"

    @patch('smart_monitor.subprocess.run')
    def test_smartctl_not_installed(self, mock_run):
        """Test handling when smartctl is not installed."""
        mock_run.side_effect = FileNotFoundError()

        health = get_smart_data("/dev/sda")

        assert health.error_message == "smartctl not installed"

    @patch('smart_monitor.subprocess.run')
    def test_invalid_json_output(self, mock_run):
        """Test handling of invalid JSON output."""
        mock_run.return_value = MagicMock(
            stdout="not valid json",
            stderr="",
            returncode=0
        )

        health = get_smart_data("/dev/sda")

        assert "Failed to parse" in health.error_message

    @patch('smart_monitor.subprocess.run')
    def test_use_sat_flag(self, mock_run):
        """Test -d sat flag is passed when requested."""
        import json
        mock_run.return_value = MagicMock(
            stdout=json.dumps(SAMPLE_HDD_JSON),
            stderr="",
            returncode=0
        )

        get_smart_data("/dev/sda", use_sat=True)

        call_args = mock_run.call_args[0][0]
        assert '-d' in call_args
        assert 'sat' in call_args


# ============================================
# Test get_all_smart_data function
# ============================================

class TestGetAllSmartData:
    """Tests for getting SMART data from all devices."""

    @patch('smart_monitor.get_smart_data')
    @patch('smart_monitor.subprocess.run')
    def test_discovers_multiple_disks(self, mock_run, mock_get_smart):
        """Test discovery of multiple disks."""
        mock_run.return_value = MagicMock(
            stdout="sda disk\nsdb disk\nnvme0n1 disk\n",
            stderr="",
            returncode=0
        )
        mock_get_smart.return_value = SmartHealth(device="/dev/test")

        results = get_all_smart_data()

        assert len(results) == 3
        assert mock_get_smart.call_count == 3

    @patch('smart_monitor.subprocess.run')
    def test_filters_non_disk_devices(self, mock_run):
        """Test that non-disk devices are filtered out."""
        mock_run.return_value = MagicMock(
            stdout="sda disk\nsda1 part\nsr0 rom\n",
            stderr="",
            returncode=0
        )

        with patch('smart_monitor.get_smart_data') as mock_get:
            mock_get.return_value = SmartHealth(device="/dev/sda")
            results = get_all_smart_data()

            # Only sda should be queried (disk type)
            assert mock_get.call_count == 1

    @patch('smart_monitor.subprocess.run')
    def test_handles_lsblk_error(self, mock_run):
        """Test handling of lsblk errors."""
        mock_run.side_effect = Exception("lsblk failed")

        results = get_all_smart_data()

        assert results == []


# ============================================
# Test format_power_on_hours function
# ============================================

class TestFormatPowerOnHours:
    """Tests for power-on hours formatting."""

    def test_format_none(self):
        """Test formatting None value."""
        assert format_power_on_hours(None) == "Unknown"

    def test_format_hours_only(self):
        """Test formatting hours less than a day."""
        assert format_power_on_hours(10) == "10h"
        assert format_power_on_hours(23) == "23h"

    def test_format_days(self):
        """Test formatting days."""
        assert format_power_on_hours(48) == "2d"
        assert format_power_on_hours(100) == "4d"

    def test_format_years_and_days(self):
        """Test formatting years and days."""
        hours = (365 * 24) + (30 * 24)  # 1 year + 30 days
        assert format_power_on_hours(hours) == "1y 30d"

    def test_format_multiple_years(self):
        """Test formatting multiple years."""
        hours = (3 * 365 * 24) + (100 * 24)  # 3 years + 100 days
        assert format_power_on_hours(hours) == "3y 100d"


# ============================================
# Test ATA attribute parsing
# ============================================

class TestParseAtaAttributes:
    """Tests for ATA SMART attribute parsing."""

    def test_extracts_critical_attributes(self):
        """Test extraction of critical SMART attributes."""
        json_data = {
            "ata_smart_attributes": {
                "table": [
                    {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "thresh": 10, "raw": {"value": 5}},
                    {"id": 197, "name": "Current_Pending_Sector", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 2}},
                ]
            }
        }
        health = SmartHealth(device="/dev/sda")
        _parse_ata_attributes(json_data, health)

        assert health.reallocated_sectors == 5
        assert health.pending_sectors == 2
        assert len(health.attributes) == 2

    def test_marks_critical_attributes(self):
        """Test that critical attributes are marked."""
        json_data = {
            "ata_smart_attributes": {
                "table": [
                    {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "thresh": 10, "raw": {"value": 0}},
                    {"id": 1, "name": "Raw_Read_Error_Rate", "value": 100, "worst": 100, "thresh": 0, "raw": {"value": 0}},
                ]
            }
        }
        health = SmartHealth(device="/dev/sda")
        _parse_ata_attributes(json_data, health)

        # ID 5 is critical, ID 1 is not
        critical_attr = next(a for a in health.attributes if a['id'] == 5)
        non_critical_attr = next(a for a in health.attributes if a['id'] == 1)

        assert critical_attr['critical'] is True
        assert non_critical_attr['critical'] is False


# ============================================
# Test NVMe attribute parsing
# ============================================

class TestParseNvmeAttributes:
    """Tests for NVMe SMART attribute parsing."""

    def test_extracts_nvme_attributes(self):
        """Test extraction of NVMe SMART attributes."""
        json_data = {
            "nvme_smart_health_information_log": {
                "percentage_used": 5,
                "available_spare": 100,
                "media_errors": 0,
                "temperature": 40
            }
        }
        health = SmartHealth(device="/dev/nvme0")
        _parse_nvme_attributes(json_data, health)

        assert health.percentage_used == 5
        assert health.available_spare == 100
        assert health.media_errors == 0
        assert health.temperature_c == 40

    def test_builds_attributes_list(self):
        """Test that attributes list is built for NVMe."""
        json_data = {
            "nvme_smart_health_information_log": {
                "percentage_used": 5,
                "power_cycles": 100
            }
        }
        health = SmartHealth(device="/dev/nvme0")
        _parse_nvme_attributes(json_data, health)

        assert len(health.attributes) == 2
        names = [a['name'] for a in health.attributes]
        assert "Percentage Used" in names
