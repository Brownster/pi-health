"""
SMART disk health monitoring module.
Parses smartctl output and provides health status for drives.
"""

import json
import subprocess
import re
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class SmartHealth:
    """SMART health data for a drive."""
    device: str
    model: str = "Unknown"
    serial: str = "Unknown"
    drive_type: str = "unknown"  # hdd, ssd, nvme, usb
    smart_available: bool = False
    smart_enabled: bool = False
    health_status: str = "unknown"  # healthy, warning, failing, unknown
    temperature_c: Optional[int] = None
    power_on_hours: Optional[int] = None

    # HDD/SSD specific (SATA)
    reallocated_sectors: Optional[int] = None
    pending_sectors: Optional[int] = None
    uncorrectable_errors: Optional[int] = None

    # NVMe specific
    percentage_used: Optional[int] = None
    available_spare: Optional[int] = None
    media_errors: Optional[int] = None

    # Raw attributes for detailed view
    attributes: list = field(default_factory=list)

    # Error info
    error_message: Optional[str] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


# SMART attribute IDs that indicate problems
CRITICAL_ATTRIBUTES = {
    5: 'Reallocated_Sector_Ct',
    10: 'Spin_Retry_Count',
    184: 'End-to-End_Error',
    187: 'Reported_Uncorrect',
    188: 'Command_Timeout',
    196: 'Reallocated_Event_Count',
    197: 'Current_Pending_Sector',
    198: 'Offline_Uncorrectable',
    201: 'Soft_Read_Error_Rate',
}

# Thresholds for warning (non-zero is usually bad for these)
WARNING_IF_NONZERO = {5, 10, 184, 187, 196, 197, 198, 201}


def parse_smartctl_json(json_data: dict) -> SmartHealth:
    """
    Parse smartctl JSON output into SmartHealth object.

    Args:
        json_data: Parsed JSON from smartctl -j output

    Returns:
        SmartHealth object with parsed data
    """
    device = json_data.get('device', {}).get('name', 'unknown')
    health = SmartHealth(device=device)

    # Basic device info
    health.model = json_data.get('model_name', 'Unknown')
    health.serial = json_data.get('serial_number', 'Unknown')

    # Determine drive type
    device_type = json_data.get('device', {}).get('type', '')
    if 'nvme' in device_type.lower():
        health.drive_type = 'nvme'
    elif json_data.get('rotation_rate', 0) == 0:
        health.drive_type = 'ssd'
    elif json_data.get('rotation_rate', 0) > 0:
        health.drive_type = 'hdd'
    else:
        health.drive_type = 'unknown'

    # SMART availability
    smart_status = json_data.get('smart_status', {})
    health.smart_available = json_data.get('smart_support', {}).get('available', False)
    health.smart_enabled = json_data.get('smart_support', {}).get('enabled', False)

    # Overall health from smartctl
    if smart_status.get('passed') is True:
        health.health_status = 'healthy'
    elif smart_status.get('passed') is False:
        health.health_status = 'failing'

    # Temperature
    temp_data = json_data.get('temperature', {})
    if 'current' in temp_data:
        health.temperature_c = temp_data['current']

    # Power on hours
    health.power_on_hours = json_data.get('power_on_time', {}).get('hours')

    # Parse based on drive type
    if health.drive_type == 'nvme':
        _parse_nvme_attributes(json_data, health)
    else:
        _parse_ata_attributes(json_data, health)

    # Determine final health status based on attributes
    _calculate_health_status(health)

    return health


def _parse_nvme_attributes(json_data: dict, health: SmartHealth):
    """Parse NVMe specific SMART attributes."""
    nvme_health = json_data.get('nvme_smart_health_information_log', {})

    health.percentage_used = nvme_health.get('percentage_used')
    health.available_spare = nvme_health.get('available_spare')
    health.media_errors = nvme_health.get('media_errors')

    # Temperature might be in NVMe section
    if health.temperature_c is None:
        health.temperature_c = nvme_health.get('temperature')

    # Build attributes list for detailed view
    for key, value in nvme_health.items():
        if isinstance(value, (int, float)):
            health.attributes.append({
                'name': key.replace('_', ' ').title(),
                'value': value,
                'raw': value
            })


def _parse_ata_attributes(json_data: dict, health: SmartHealth):
    """Parse ATA (SATA HDD/SSD) SMART attributes."""
    ata_attrs = json_data.get('ata_smart_attributes', {}).get('table', [])

    for attr in ata_attrs:
        attr_id = attr.get('id')
        attr_name = attr.get('name', '')
        raw_value = attr.get('raw', {}).get('value', 0)
        current = attr.get('value', 0)
        worst = attr.get('worst', 0)
        thresh = attr.get('thresh', 0)

        # Extract key metrics
        if attr_id == 5:  # Reallocated Sector Count
            health.reallocated_sectors = raw_value
        elif attr_id == 197:  # Current Pending Sector
            health.pending_sectors = raw_value
        elif attr_id == 198:  # Offline Uncorrectable
            health.uncorrectable_errors = raw_value
        elif attr_id == 194 and health.temperature_c is None:  # Temperature
            health.temperature_c = raw_value
        elif attr_id == 9:  # Power On Hours
            if health.power_on_hours is None:
                health.power_on_hours = raw_value

        # Add to attributes list
        health.attributes.append({
            'id': attr_id,
            'name': attr_name,
            'value': current,
            'worst': worst,
            'thresh': thresh,
            'raw': raw_value,
            'critical': attr_id in CRITICAL_ATTRIBUTES
        })


def _calculate_health_status(health: SmartHealth):
    """
    Calculate overall health status based on attributes.
    Updates health.health_status if issues are found.
    """
    if health.health_status == 'failing':
        return  # Already marked as failing by SMART self-assessment

    warnings = []

    # Check HDD/SSD attributes
    if health.reallocated_sectors and health.reallocated_sectors > 0:
        warnings.append(f"Reallocated sectors: {health.reallocated_sectors}")

    if health.pending_sectors and health.pending_sectors > 0:
        warnings.append(f"Pending sectors: {health.pending_sectors}")

    if health.uncorrectable_errors and health.uncorrectable_errors > 0:
        warnings.append(f"Uncorrectable errors: {health.uncorrectable_errors}")

    # Check NVMe attributes
    if health.percentage_used is not None and health.percentage_used > 90:
        warnings.append(f"NVMe percentage used: {health.percentage_used}%")

    if health.available_spare is not None and health.available_spare < 10:
        warnings.append(f"NVMe available spare low: {health.available_spare}%")

    if health.media_errors and health.media_errors > 0:
        warnings.append(f"NVMe media errors: {health.media_errors}")

    # Check temperature (common threshold)
    if health.temperature_c is not None and health.temperature_c > 55:
        warnings.append(f"High temperature: {health.temperature_c}°C")

    # Set status based on warnings
    if warnings:
        health.health_status = 'warning'
        health.error_message = "; ".join(warnings)
    elif health.smart_available and health.health_status == 'unknown':
        health.health_status = 'healthy'


def get_smart_data(device: str, use_sat: bool = False) -> SmartHealth:
    """
    Get SMART data for a device by running smartctl.

    Args:
        device: Device path (e.g., /dev/sda)
        use_sat: Use SAT passthrough for USB drives (-d sat)

    Returns:
        SmartHealth object
    """
    health = SmartHealth(device=device)

    cmd = ['smartctl', '-j', '-a']
    if use_sat:
        cmd.extend(['-d', 'sat'])
    cmd.append(device)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # smartctl returns non-zero for various reasons, try to parse anyway
        if result.stdout:
            try:
                json_data = json.loads(result.stdout)
                return parse_smartctl_json(json_data)
            except json.JSONDecodeError:
                health.error_message = "Failed to parse smartctl output"
                return health

        # If no output and not using SAT, try with SAT for USB drives
        if not use_sat and 'No such device' not in result.stderr:
            return get_smart_data(device, use_sat=True)

        health.error_message = result.stderr or "No SMART data available"

    except subprocess.TimeoutExpired:
        health.error_message = "Timeout reading SMART data"
    except FileNotFoundError:
        health.error_message = "smartctl not installed"
    except Exception as e:
        health.error_message = str(e)

    return health


def get_all_smart_data() -> list:
    """
    Get SMART data for all block devices.

    Returns:
        List of SmartHealth objects
    """
    results = []

    try:
        # Get list of block devices
        lsblk = subprocess.run(
            ['lsblk', '-d', '-n', '-o', 'NAME,TYPE'],
            capture_output=True,
            text=True,
            timeout=10
        )

        for line in lsblk.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == 'disk':
                device = f"/dev/{parts[0]}"
                health = get_smart_data(device)
                results.append(health)

    except Exception as e:
        # Return empty list on error
        pass

    return results


def format_power_on_hours(hours: Optional[int]) -> str:
    """Format power-on hours into human readable string."""
    if hours is None:
        return "Unknown"

    days = hours // 24
    years = days // 365
    remaining_days = days % 365

    if years > 0:
        return f"{years}y {remaining_days}d"
    elif days > 0:
        return f"{days}d"
    else:
        return f"{hours}h"
