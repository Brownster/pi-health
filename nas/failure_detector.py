"""Drive failure detection and handling system."""

import logging
import threading
import time
import os
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

from .smart_manager import SMARTManager, SMARTHealthStatus, SMARTTrendAnalysis
from .drive_manager import DriveManager
from .snapraid_manager import SnapRAIDManager
from .models import DriveConfig, HealthStatus

logger = logging.getLogger(__name__)


class FailureRisk(Enum):
    """Drive failure risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FailureType(Enum):
    """Types of drive failures."""
    SMART_FAILURE = "smart_failure"
    MOUNT_FAILURE = "mount_failure"
    IO_ERROR = "io_error"
    TEMPERATURE_CRITICAL = "temperature_critical"
    REALLOCATED_SECTORS = "reallocated_sectors"
    PENDING_SECTORS = "pending_sectors"
    COMMUNICATION_ERROR = "communication_error"


@dataclass
class FailureEvent:
    """Information about a drive failure event."""
    device_path: str
    failure_type: FailureType
    risk_level: FailureRisk
    timestamp: datetime
    message: str
    smart_data: Optional[Dict[str, Any]] = None
    recommended_actions: List[str] = None
    is_critical: bool = False
    
    def __post_init__(self):
        if self.recommended_actions is None:
            self.recommended_actions = []


@dataclass
class DriveHealthAssessment:
    """Comprehensive drive health assessment."""
    device_path: str
    overall_risk: FailureRisk
    failure_events: List[FailureEvent]
    smart_status: Optional[SMARTHealthStatus] = None
    trend_analysis: Optional[SMARTTrendAnalysis] = None
    last_assessment: datetime = None
    degraded_mode_capable: bool = True
    
    def __post_init__(self):
        if self.last_assessment is None:
            self.last_assessment = datetime.now()


class FailureDetector:
    """Detects and handles drive failures through comprehensive monitoring."""
    
    def __init__(self, drive_manager: DriveManager, snapraid_manager: SnapRAIDManager, smart_manager: SMARTManager):
        """
        Initialize the failure detector.
        
        Args:
            drive_manager: Drive manager instance
            snapraid_manager: SnapRAID manager instance
            smart_manager: SMART manager instance
        """
        self.drive_manager = drive_manager
        self.snapraid_manager = snapraid_manager
        self.smart_manager = smart_manager
        
        # Failure tracking
        self._failure_events: Dict[str, List[FailureEvent]] = {}
        self._health_assessments: Dict[str, DriveHealthAssessment] = {}
        self._monitoring_active = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Configuration
        self.check_interval = 300  # 5 minutes
        self.temperature_critical_threshold = 60  # Celsius
        self.temperature_warning_threshold = 55  # Celsius
        self.reallocated_sectors_threshold = 5
        self.pending_sectors_threshold = 1
        
    def start_monitoring(self) -> None:
        """Start continuous drive failure monitoring."""
        if self._monitoring_active:
            logger.warning("Drive failure monitoring is already active")
            return
        
        self._monitoring_active = True
        self._stop_event.clear()
        
        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="FailureDetector"
        )
        self._monitor_thread.start()
        
        logger.info("Drive failure monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop continuous drive failure monitoring."""
        if not self._monitoring_active:
            return
        
        self._monitoring_active = False
        self._stop_event.set()
        
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=10)
        
        logger.info("Drive failure monitoring stopped")
    
    def assess_drive_health(self, device_path: str) -> DriveHealthAssessment:
        """
        Perform comprehensive health assessment for a drive.
        
        Args:
            device_path: Device path to assess
            
        Returns:
            DriveHealthAssessment with current status and risks
        """
        failure_events = []
        overall_risk = FailureRisk.LOW
        
        try:
            # Get SMART health status
            smart_status = self.smart_manager.get_health_status(device_path, use_cache=False)
            
            # Get trend analysis
            trend_analysis = self.smart_manager.analyze_health_trends(device_path, days=7)
            
            # Check for SMART failures
            if smart_status:
                smart_events = self._check_smart_health(device_path, smart_status)
                failure_events.extend(smart_events)
            
            # Check for trend-based risks
            if trend_analysis:
                trend_events = self._check_health_trends(device_path, trend_analysis)
                failure_events.extend(trend_events)
            
            # Check mount and I/O status
            io_events = self._check_io_health(device_path)
            failure_events.extend(io_events)
            
            # Determine overall risk level
            if failure_events:
                risk_levels = [event.risk_level for event in failure_events]
                if FailureRisk.CRITICAL in risk_levels:
                    overall_risk = FailureRisk.CRITICAL
                elif FailureRisk.HIGH in risk_levels:
                    overall_risk = FailureRisk.HIGH
                elif FailureRisk.MEDIUM in risk_levels:
                    overall_risk = FailureRisk.MEDIUM
            
            # Create assessment
            assessment = DriveHealthAssessment(
                device_path=device_path,
                overall_risk=overall_risk,
                failure_events=failure_events,
                smart_status=smart_status,
                trend_analysis=trend_analysis,
                degraded_mode_capable=self._can_operate_degraded(device_path)
            )
            
            # Cache the assessment
            self._health_assessments[device_path] = assessment
            
            # Store failure events
            if failure_events:
                if device_path not in self._failure_events:
                    self._failure_events[device_path] = []
                self._failure_events[device_path].extend(failure_events)
                
                # Keep only recent events (last 30 days)
                cutoff_date = datetime.now() - timedelta(days=30)
                self._failure_events[device_path] = [
                    event for event in self._failure_events[device_path]
                    if event.timestamp > cutoff_date
                ]
            
            return assessment
        
        except Exception as e:
            logger.error(f"Error assessing drive health for {device_path}: {e}")
            
            # Return minimal assessment with error
            return DriveHealthAssessment(
                device_path=device_path,
                overall_risk=FailureRisk.HIGH,
                failure_events=[FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.COMMUNICATION_ERROR,
                    risk_level=FailureRisk.HIGH,
                    timestamp=datetime.now(),
                    message=f"Error assessing drive health: {e}",
                    recommended_actions=["Check drive connection", "Verify drive is accessible"]
                )],
                degraded_mode_capable=False
            )
    
    def get_failed_drives(self) -> List[str]:
        """
        Get list of drives that have failed or are at critical risk.
        
        Returns:
            List of device paths for failed drives
        """
        failed_drives = []
        
        for device_path, assessment in self._health_assessments.items():
            if assessment.overall_risk == FailureRisk.CRITICAL:
                failed_drives.append(device_path)
            elif any(event.is_critical for event in assessment.failure_events):
                failed_drives.append(device_path)
        
        return failed_drives
    
    def get_degraded_drives(self) -> List[str]:
        """
        Get list of drives that are degraded but still operational.
        
        Returns:
            List of device paths for degraded drives
        """
        degraded_drives = []
        
        for device_path, assessment in self._health_assessments.items():
            if assessment.overall_risk in [FailureRisk.MEDIUM, FailureRisk.HIGH]:
                if assessment.degraded_mode_capable:
                    degraded_drives.append(device_path)
        
        return degraded_drives
    
    def can_system_operate_degraded(self) -> Tuple[bool, str]:
        """
        Check if the system can operate in degraded mode with current failures.
        
        Returns:
            Tuple of (can_operate, reason)
        """
        try:
            failed_drives = self.get_failed_drives()
            
            if not failed_drives:
                return True, "No failed drives detected"
            
            # Check SnapRAID status to see if we can recover
            snapraid_status = self.snapraid_manager.get_status(use_cache=False)
            if not snapraid_status:
                return False, "Cannot determine SnapRAID status"
            
            # Count data drive failures
            data_drive_failures = 0
            parity_drive_failures = 0
            
            for failed_drive in failed_drives:
                # Check if this is a data drive or parity drive
                # This is a simplified check - in practice you'd need to map device paths
                # to SnapRAID configuration
                if 'parity' in failed_drive.lower():
                    parity_drive_failures += 1
                else:
                    data_drive_failures += 1
            
            # SnapRAID can handle single data drive failure with parity
            if data_drive_failures <= 1 and parity_drive_failures == 0:
                return True, f"System can operate with {data_drive_failures} data drive failure(s)"
            elif data_drive_failures == 0 and parity_drive_failures > 0:
                return True, "System can operate without parity protection (no data loss)"
            else:
                return False, f"Too many drive failures: {data_drive_failures} data, {parity_drive_failures} parity"
        
        except Exception as e:
            logger.error(f"Error checking degraded mode capability: {e}")
            return False, f"Error checking system status: {e}"
    
    def get_recovery_recommendations(self, device_path: str) -> List[str]:
        """
        Get recovery recommendations for a specific drive.
        
        Args:
            device_path: Device path to get recommendations for
            
        Returns:
            List of recommended recovery actions
        """
        assessment = self._health_assessments.get(device_path)
        if not assessment:
            return ["Run drive health assessment first"]
        
        recommendations = []
        
        # Collect recommendations from all failure events
        for event in assessment.failure_events:
            recommendations.extend(event.recommended_actions)
        
        # Add general recommendations based on risk level
        if assessment.overall_risk == FailureRisk.CRITICAL:
            recommendations.extend([
                "URGENT: Backup all important data immediately",
                "Replace drive as soon as possible",
                "Do not rely on this drive for critical operations"
            ])
        elif assessment.overall_risk == FailureRisk.HIGH:
            recommendations.extend([
                "Plan drive replacement soon",
                "Increase backup frequency",
                "Monitor drive closely"
            ])
        elif assessment.overall_risk == FailureRisk.MEDIUM:
            recommendations.extend([
                "Monitor drive health regularly",
                "Consider running extended SMART tests",
                "Ensure good cooling and ventilation"
            ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        return unique_recommendations
    
    def _monitoring_loop(self) -> None:
        """Main monitoring loop that runs in background thread."""
        logger.info("Drive failure monitoring loop started")
        
        while not self._stop_event.is_set():
            try:
                # Discover current drives
                drives = self.drive_manager.discover_drives()
                
                # Assess health of each drive
                for drive in drives:
                    if self._stop_event.is_set():
                        break
                    
                    try:
                        assessment = self.assess_drive_health(drive.device_path)
                        
                        # Log critical issues
                        if assessment.overall_risk == FailureRisk.CRITICAL:
                            logger.critical(f"CRITICAL: Drive {drive.device_path} has critical health issues")
                        elif assessment.overall_risk == FailureRisk.HIGH:
                            logger.warning(f"WARNING: Drive {drive.device_path} has high failure risk")
                        
                    except Exception as e:
                        logger.error(f"Error assessing drive {drive.device_path}: {e}")
                
                # Wait for next check interval
                self._stop_event.wait(self.check_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                self._stop_event.wait(60)  # Wait 1 minute before retrying
        
        logger.info("Drive failure monitoring loop stopped")
    
    def _check_smart_health(self, device_path: str, smart_status: SMARTHealthStatus) -> List[FailureEvent]:
        """Check SMART health status for failure indicators."""
        events = []
        
        # Check overall SMART health
        if smart_status.overall_health == "FAILED":
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.SMART_FAILURE,
                risk_level=FailureRisk.CRITICAL,
                timestamp=datetime.now(),
                message="SMART overall health assessment failed",
                smart_data={"overall_health": smart_status.overall_health},
                recommended_actions=[
                    "Replace drive immediately",
                    "Backup all data",
                    "Do not use drive for new data"
                ],
                is_critical=True
            ))
        
        # Check temperature
        if smart_status.temperature:
            if smart_status.temperature >= self.temperature_critical_threshold:
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.TEMPERATURE_CRITICAL,
                    risk_level=FailureRisk.HIGH,
                    timestamp=datetime.now(),
                    message=f"Drive temperature critical: {smart_status.temperature}°C",
                    smart_data={"temperature": smart_status.temperature},
                    recommended_actions=[
                        "Improve cooling immediately",
                        "Check ventilation",
                        "Consider drive replacement if temperature persists"
                    ]
                ))
            elif smart_status.temperature >= self.temperature_warning_threshold:
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.TEMPERATURE_CRITICAL,
                    risk_level=FailureRisk.MEDIUM,
                    timestamp=datetime.now(),
                    message=f"Drive temperature elevated: {smart_status.temperature}°C",
                    smart_data={"temperature": smart_status.temperature},
                    recommended_actions=[
                        "Monitor temperature closely",
                        "Improve cooling if possible"
                    ]
                ))
        
        # Check reallocated sectors
        if smart_status.reallocated_sectors and smart_status.reallocated_sectors > self.reallocated_sectors_threshold:
            risk_level = FailureRisk.HIGH if smart_status.reallocated_sectors > 10 else FailureRisk.MEDIUM
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.REALLOCATED_SECTORS,
                risk_level=risk_level,
                timestamp=datetime.now(),
                message=f"High reallocated sectors count: {smart_status.reallocated_sectors}",
                smart_data={"reallocated_sectors": smart_status.reallocated_sectors},
                recommended_actions=[
                    "Plan drive replacement",
                    "Run extended SMART test",
                    "Backup important data"
                ]
            ))
        
        # Check pending sectors
        if smart_status.pending_sectors and smart_status.pending_sectors > self.pending_sectors_threshold:
            risk_level = FailureRisk.HIGH if smart_status.pending_sectors > 5 else FailureRisk.MEDIUM
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.PENDING_SECTORS,
                risk_level=risk_level,
                timestamp=datetime.now(),
                message=f"Pending sectors detected: {smart_status.pending_sectors}",
                smart_data={"pending_sectors": smart_status.pending_sectors},
                recommended_actions=[
                    "Run extended SMART test immediately",
                    "Monitor closely",
                    "Consider drive replacement if sectors don't clear"
                ]
            ))
        
        return events
    
    def _check_health_trends(self, device_path: str, trend_analysis: SMARTTrendAnalysis) -> List[FailureEvent]:
        """Check health trends for failure indicators."""
        events = []
        
        # Check for increasing reallocated sectors
        if trend_analysis.reallocated_sectors_trend == "increasing":
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.REALLOCATED_SECTORS,
                risk_level=FailureRisk.MEDIUM,
                timestamp=datetime.now(),
                message="Reallocated sectors count is increasing",
                recommended_actions=[
                    "Monitor drive closely",
                    "Plan proactive replacement",
                    "Increase backup frequency"
                ]
            ))
        
        # Check for increasing pending sectors
        if trend_analysis.pending_sectors_trend == "increasing":
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.PENDING_SECTORS,
                risk_level=FailureRisk.MEDIUM,
                timestamp=datetime.now(),
                message="Pending sectors count is increasing",
                recommended_actions=[
                    "Run SMART tests regularly",
                    "Monitor for further increases",
                    "Consider drive replacement if trend continues"
                ]
            ))
        
        # Check for temperature trends
        if trend_analysis.temperature_trend == "increasing" and trend_analysis.temperature_max:
            if trend_analysis.temperature_max > self.temperature_warning_threshold:
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.TEMPERATURE_CRITICAL,
                    risk_level=FailureRisk.MEDIUM,
                    timestamp=datetime.now(),
                    message=f"Drive temperature trending upward (max: {trend_analysis.temperature_max}°C)",
                    recommended_actions=[
                        "Improve cooling",
                        "Check for dust buildup",
                        "Monitor temperature closely"
                    ]
                ))
        
        return events
    
    def _check_io_health(self, device_path: str) -> List[FailureEvent]:
        """Check I/O and mount health."""
        events = []
        
        try:
            # Get drive config to check mount status
            drive = self.drive_manager.get_drive_by_device(device_path)
            if not drive:
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.MOUNT_FAILURE,
                    risk_level=FailureRisk.HIGH,
                    timestamp=datetime.now(),
                    message="Drive not found in system",
                    recommended_actions=[
                        "Check physical connections",
                        "Verify drive is powered on",
                        "Check system logs for errors"
                    ]
                ))
                return events
            
            # Check if mount point is accessible
            import os
            if not os.path.exists(drive.mount_point):
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.MOUNT_FAILURE,
                    risk_level=FailureRisk.HIGH,
                    timestamp=datetime.now(),
                    message=f"Mount point not accessible: {drive.mount_point}",
                    recommended_actions=[
                        "Check mount status",
                        "Attempt to remount drive",
                        "Check filesystem integrity"
                    ]
                ))
            elif not os.access(drive.mount_point, os.R_OK | os.W_OK):
                events.append(FailureEvent(
                    device_path=device_path,
                    failure_type=FailureType.IO_ERROR,
                    risk_level=FailureRisk.MEDIUM,
                    timestamp=datetime.now(),
                    message=f"Drive not readable/writable: {drive.mount_point}",
                    recommended_actions=[
                        "Check filesystem permissions",
                        "Run filesystem check",
                        "Check for I/O errors in system logs"
                    ]
                ))
        
        except Exception as e:
            events.append(FailureEvent(
                device_path=device_path,
                failure_type=FailureType.COMMUNICATION_ERROR,
                risk_level=FailureRisk.MEDIUM,
                timestamp=datetime.now(),
                message=f"Error checking I/O health: {e}",
                recommended_actions=[
                    "Check system logs",
                    "Verify drive connectivity"
                ]
            ))
        
        return events
    
    def _can_operate_degraded(self, device_path: str) -> bool:
        """Check if system can operate in degraded mode without this drive."""
        try:
            # This is a simplified check - in practice you'd need to check
            # SnapRAID configuration and parity status
            failed_drives = self.get_failed_drives()
            
            # If this would be the only failed drive, system can likely operate degraded
            if device_path not in failed_drives:
                return len(failed_drives) == 0  # No other failures
            else:
                return len(failed_drives) <= 1  # Only this drive failed
        
        except Exception:
            return False
    
    def get_all_assessments(self) -> Dict[str, DriveHealthAssessment]:
        """Get all cached health assessments."""
        return self._health_assessments.copy()
    
    def get_failure_history(self, device_path: str, days: int = 30) -> List[FailureEvent]:
        """
        Get failure event history for a drive.
        
        Args:
            device_path: Device path
            days: Number of days of history to retrieve
            
        Returns:
            List of failure events
        """
        if device_path not in self._failure_events:
            return []
        
        cutoff_date = datetime.now() - timedelta(days=days)
        return [
            event for event in self._failure_events[device_path]
            if event.timestamp > cutoff_date
        ]
    
    def to_dict(self, assessment: DriveHealthAssessment) -> Dict[str, Any]:
        """Convert DriveHealthAssessment to dictionary for JSON serialization."""
        result = asdict(assessment)
        
        # Convert enums to strings
        result['overall_risk'] = assessment.overall_risk.value
        
        # Convert failure events
        result['failure_events'] = []
        for event in assessment.failure_events:
            event_dict = asdict(event)
            event_dict['failure_type'] = event.failure_type.value
            event_dict['risk_level'] = event.risk_level.value
            event_dict['timestamp'] = event.timestamp.isoformat()
            result['failure_events'].append(event_dict)
        
        # Convert timestamps
        result['last_assessment'] = assessment.last_assessment.isoformat()
        
        return result