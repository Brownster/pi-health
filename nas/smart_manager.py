"""SMART health monitoring utilities."""

import subprocess
import json
import logging
import re
import os
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class SMARTTestType(Enum):
    """SMART test types."""
    SHORT = "short"
    LONG = "long"
    CONVEYANCE = "conveyance"


class SMARTTestStatus(Enum):
    """SMART test execution status."""
    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class SMARTAttribute:
    """SMART attribute information."""
    id: int
    name: str
    value: int
    worst: int
    threshold: int
    raw_value: str
    when_failed: Optional[str] = None


@dataclass
class SMARTHealthStatus:
    """SMART health status information."""
    device_path: str
    overall_health: str
    temperature: Optional[int] = None
    power_on_hours: Optional[int] = None
    power_cycle_count: Optional[int] = None
    reallocated_sectors: Optional[int] = None
    pending_sectors: Optional[int] = None
    uncorrectable_sectors: Optional[int] = None
    attributes: List[SMARTAttribute] = None
    last_updated: datetime = None
    
    def __post_init__(self):
        if self.attributes is None:
            self.attributes = []
        if self.last_updated is None:
            self.last_updated = datetime.now()


@dataclass
class SMARTTestResult:
    """SMART test result information."""
    device_path: str
    test_type: SMARTTestType
    status: SMARTTestStatus
    progress: Optional[int] = None
    estimated_completion: Optional[datetime] = None
    result_message: Optional[str] = None
    started_at: datetime = None
    completed_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now()


@dataclass
class SMARTHealthHistory:
    """Historical SMART health data for trend analysis."""
    device_path: str
    timestamp: datetime
    overall_health: str
    temperature: Optional[int] = None
    power_on_hours: Optional[int] = None
    power_cycle_count: Optional[int] = None
    reallocated_sectors: Optional[int] = None
    pending_sectors: Optional[int] = None
    uncorrectable_sectors: Optional[int] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class SMARTTrendAnalysis:
    """Trend analysis results for SMART health data."""
    device_path: str
    analysis_period_days: int
    temperature_trend: Optional[str] = None  # "increasing", "decreasing", "stable"
    temperature_avg: Optional[float] = None
    temperature_max: Optional[int] = None
    reallocated_sectors_trend: Optional[str] = None
    pending_sectors_trend: Optional[str] = None
    health_degradation_risk: str = "low"  # "low", "medium", "high"
    recommendations: List[str] = None
    
    def __post_init__(self):
        if self.recommendations is None:
            self.recommendations = []


class SMARTManager:
    """Manages SMART health monitoring and testing."""
    
    def __init__(self, history_file_path: str = "/var/lib/nas/smart_history.json"):
        """Initialize the SMART manager."""
        self._health_cache: Dict[str, SMARTHealthStatus] = {}
        self._test_cache: Dict[str, SMARTTestResult] = {}
        self._history_file_path = history_file_path
        self._health_history: List[SMARTHealthHistory] = []
        self._load_health_history()
    
    def get_health_status(self, device_path: str, use_cache: bool = True) -> Optional[SMARTHealthStatus]:
        """
        Get SMART health status for a device.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            use_cache: Whether to use cached data if available
            
        Returns:
            SMARTHealthStatus if successful, None otherwise
        """
        # Check cache first if requested
        if use_cache and device_path in self._health_cache:
            cached_status = self._health_cache[device_path]
            # Use cache if it's less than 5 minutes old
            if (datetime.now() - cached_status.last_updated).seconds < 300:
                return cached_status
        
        try:
            # Get basic health status
            health_result = self._run_smartctl(['-H', device_path])
            if health_result is None:
                return None
            
            # Get detailed attributes
            attributes_result = self._run_smartctl(['-A', device_path])
            
            # Parse results
            health_status = self._parse_health_status(device_path, health_result, attributes_result)
            
            # Cache the result
            if health_status:
                self._health_cache[device_path] = health_status
            
            return health_status
        
        except Exception as e:
            logger.error(f"Error getting SMART health for {device_path}: {e}")
            return None
    
    def start_test(self, device_path: str, test_type: SMARTTestType) -> bool:
        """
        Start a SMART test on a device.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            test_type: Type of test to run
            
        Returns:
            True if test started successfully, False otherwise
        """
        try:
            # Check if a test is already running
            current_test = self.get_test_status(device_path)
            if current_test and current_test.status == SMARTTestStatus.RUNNING:
                logger.warning(f"SMART test already running on {device_path}")
                return False
            
            # Start the test
            result = self._run_smartctl(['-t', test_type.value, device_path])
            if result is None:
                return False
            
            # Create test result entry
            test_result = SMARTTestResult(
                device_path=device_path,
                test_type=test_type,
                status=SMARTTestStatus.RUNNING,
                progress=0
            )
            
            self._test_cache[device_path] = test_result
            logger.info(f"Started {test_type.value} SMART test on {device_path}")
            return True
        
        except Exception as e:
            logger.error(f"Error starting SMART test on {device_path}: {e}")
            return False
    
    def get_test_status(self, device_path: str) -> Optional[SMARTTestResult]:
        """
        Get the status of a running or completed SMART test.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            
        Returns:
            SMARTTestResult if available, None otherwise
        """
        try:
            # Get test status from smartctl
            result = self._run_smartctl(['-l', 'selftest', device_path])
            if result is None:
                return self._test_cache.get(device_path)
            
            # Parse test status
            test_result = self._parse_test_status(device_path, result)
            
            # Update cache if we have a result
            if test_result:
                self._test_cache[device_path] = test_result
            
            return test_result or self._test_cache.get(device_path)
        
        except Exception as e:
            logger.error(f"Error getting SMART test status for {device_path}: {e}")
            return self._test_cache.get(device_path)
    
    def is_smart_available(self, device_path: str) -> bool:
        """
        Check if SMART is available and enabled on a device.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            
        Returns:
            True if SMART is available, False otherwise
        """
        try:
            result = self._run_smartctl(['-i', device_path])
            if result is None:
                return False
            
            # Check if SMART is supported and enabled
            return 'SMART support is: Available' in result and 'SMART support is: Enabled' in result
        
        except Exception as e:
            logger.debug(f"Error checking SMART availability for {device_path}: {e}")
            return False
    
    def _run_smartctl(self, args: List[str]) -> Optional[str]:
        """
        Run smartctl command with given arguments.
        
        Args:
            args: Command line arguments for smartctl
            
        Returns:
            Command output if successful, None otherwise
        """
        try:
            cmd = ['smartctl'] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # smartctl returns non-zero exit codes for various conditions
            # that are not necessarily errors (e.g., when reporting issues)
            if result.returncode in [0, 1, 2, 4]:  # Common non-error codes
                return result.stdout
            else:
                logger.warning(f"smartctl command failed with code {result.returncode}: {' '.join(cmd)}")
                logger.warning(f"stderr: {result.stderr}")
                return None
        
        except subprocess.TimeoutExpired:
            logger.error(f"smartctl command timed out: {' '.join(args)}")
            return None
        except FileNotFoundError:
            logger.error("smartctl command not found. Please install smartmontools.")
            return None
        except Exception as e:
            logger.error(f"Error running smartctl: {e}")
            return None
    
    def _parse_health_status(self, device_path: str, health_output: str, attributes_output: Optional[str] = None) -> Optional[SMARTHealthStatus]:
        """
        Parse SMART health status from smartctl output.
        
        Args:
            device_path: Device path
            health_output: Output from smartctl -H
            attributes_output: Output from smartctl -A
            
        Returns:
            SMARTHealthStatus if parsing successful, None otherwise
        """
        try:
            # Parse overall health
            overall_health = "UNKNOWN"
            if "SMART overall-health self-assessment test result: PASSED" in health_output:
                overall_health = "PASSED"
            elif "SMART overall-health self-assessment test result: FAILED" in health_output:
                overall_health = "FAILED"
            
            health_status = SMARTHealthStatus(
                device_path=device_path,
                overall_health=overall_health
            )
            
            # Parse attributes if available
            if attributes_output:
                attributes = self._parse_smart_attributes(attributes_output)
                health_status.attributes = attributes
                
                # Extract key metrics
                for attr in attributes:
                    if attr.name.lower() in ['temperature_celsius', 'airflow_temperature_cel']:
                        health_status.temperature = attr.value
                    elif attr.name.lower() == 'power_on_hours':
                        health_status.power_on_hours = int(attr.raw_value.split()[0]) if attr.raw_value else None
                    elif attr.name.lower() == 'power_cycle_count':
                        health_status.power_cycle_count = int(attr.raw_value.split()[0]) if attr.raw_value else None
                    elif attr.name.lower() == 'reallocated_sector_ct':
                        health_status.reallocated_sectors = int(attr.raw_value.split()[0]) if attr.raw_value else None
                    elif attr.name.lower() == 'current_pending_sector':
                        health_status.pending_sectors = int(attr.raw_value.split()[0]) if attr.raw_value else None
                    elif attr.name.lower() == 'offline_uncorrectable':
                        health_status.uncorrectable_sectors = int(attr.raw_value.split()[0]) if attr.raw_value else None
            
            return health_status
        
        except Exception as e:
            logger.error(f"Error parsing SMART health status: {e}")
            return None
    
    def _parse_smart_attributes(self, attributes_output: str) -> List[SMARTAttribute]:
        """
        Parse SMART attributes from smartctl -A output.
        
        Args:
            attributes_output: Output from smartctl -A
            
        Returns:
            List of SMARTAttribute objects
        """
        attributes = []
        
        try:
            lines = attributes_output.split('\n')
            in_attributes_section = False
            
            for line in lines:
                line = line.strip()
                
                # Look for the attributes table header
                if 'ID# ATTRIBUTE_NAME' in line:
                    in_attributes_section = True
                    continue
                
                if not in_attributes_section or not line:
                    continue
                
                # Parse attribute line
                # Format: ID# ATTRIBUTE_NAME FLAG VALUE WORST THRESH TYPE UPDATED WHEN_FAILED RAW_VALUE
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        attr = SMARTAttribute(
                            id=int(parts[0]),
                            name=parts[1],
                            value=int(parts[3]),
                            worst=int(parts[4]),
                            threshold=int(parts[5]),
                            raw_value=' '.join(parts[9:]) if len(parts) > 9 else parts[9] if len(parts) == 9 else '',
                            when_failed=parts[8] if parts[8] != '-' else None
                        )
                        attributes.append(attr)
                    except (ValueError, IndexError):
                        # Skip malformed lines
                        continue
        
        except Exception as e:
            logger.error(f"Error parsing SMART attributes: {e}")
        
        return attributes
    
    def _parse_test_status(self, device_path: str, test_output: str) -> Optional[SMARTTestResult]:
        """
        Parse SMART test status from smartctl -l selftest output.
        
        Args:
            device_path: Device path
            test_output: Output from smartctl -l selftest
            
        Returns:
            SMARTTestResult if parsing successful, None otherwise
        """
        try:
            lines = test_output.split('\n')
            
            # Look for test status information
            for line in lines:
                line = line.strip()
                
                # Check for running test
                if 'Self-test routine in progress' in line:
                    # Extract progress percentage
                    progress_match = re.search(r'(\d+)% of test remaining', line)
                    progress = 100 - int(progress_match.group(1)) if progress_match else 0
                    
                    return SMARTTestResult(
                        device_path=device_path,
                        test_type=SMARTTestType.SHORT,  # Default, could be improved
                        status=SMARTTestStatus.RUNNING,
                        progress=progress
                    )
                
                # Check for completed tests in the test log
                if line.startswith('#') and len(line.split()) >= 3:
                    parts = line.split()
                    if len(parts) >= 4:
                        test_type_str = parts[2].lower()
                        status_str = parts[3].lower()
                        
                        # Map test type
                        test_type = SMARTTestType.SHORT
                        if 'extended' in test_type_str or 'long' in test_type_str:
                            test_type = SMARTTestType.LONG
                        elif 'conveyance' in test_type_str:
                            test_type = SMARTTestType.CONVEYANCE
                        
                        # Map status
                        status = SMARTTestStatus.COMPLETED
                        if 'interrupted' in status_str or 'aborted' in status_str:
                            status = SMARTTestStatus.ABORTED
                        elif 'failed' in status_str:
                            status = SMARTTestStatus.FAILED
                        
                        return SMARTTestResult(
                            device_path=device_path,
                            test_type=test_type,
                            status=status,
                            progress=100 if status == SMARTTestStatus.COMPLETED else 0,
                            result_message=line
                        )
            
            return None
        
        except Exception as e:
            logger.error(f"Error parsing SMART test status: {e}")
            return None
    
    def record_health_status(self, health_status: SMARTHealthStatus) -> None:
        """
        Record health status to history for trend analysis.
        
        Args:
            health_status: SMART health status to record
        """
        try:
            history_entry = SMARTHealthHistory(
                device_path=health_status.device_path,
                timestamp=datetime.now(),
                overall_health=health_status.overall_health,
                temperature=health_status.temperature,
                power_on_hours=health_status.power_on_hours,
                power_cycle_count=health_status.power_cycle_count,
                reallocated_sectors=health_status.reallocated_sectors,
                pending_sectors=health_status.pending_sectors,
                uncorrectable_sectors=health_status.uncorrectable_sectors
            )
            
            self._health_history.append(history_entry)
            
            # Keep only last 30 days of history per device to manage storage
            cutoff_date = datetime.now() - timedelta(days=30)
            self._health_history = [
                entry for entry in self._health_history 
                if entry.timestamp > cutoff_date
            ]
            
            # Save to persistent storage
            self._save_health_history()
            
        except Exception as e:
            logger.error(f"Error recording health status: {e}")
    
    def get_health_history(self, device_path: str, days: int = 7) -> List[SMARTHealthHistory]:
        """
        Get health history for a device.
        
        Args:
            device_path: Device path
            days: Number of days of history to retrieve
            
        Returns:
            List of health history entries
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        return [
            entry for entry in self._health_history
            if entry.device_path == device_path and entry.timestamp > cutoff_date
        ]
    
    def analyze_health_trends(self, device_path: str, days: int = 7) -> Optional[SMARTTrendAnalysis]:
        """
        Analyze health trends for a device.
        
        Args:
            device_path: Device path
            days: Number of days to analyze
            
        Returns:
            SMARTTrendAnalysis if sufficient data available, None otherwise
        """
        try:
            history = self.get_health_history(device_path, days)
            
            if len(history) < 2:
                logger.debug(f"Insufficient data for trend analysis on {device_path}")
                return None
            
            # Sort by timestamp
            history.sort(key=lambda x: x.timestamp)
            
            analysis = SMARTTrendAnalysis(
                device_path=device_path,
                analysis_period_days=days
            )
            
            # Temperature trend analysis
            temps = [entry.temperature for entry in history if entry.temperature is not None]
            if len(temps) >= 2:
                analysis.temperature_avg = sum(temps) / len(temps)
                analysis.temperature_max = max(temps)
                
                # Simple linear trend detection
                if temps[-1] > temps[0] + 5:  # 5°C increase
                    analysis.temperature_trend = "increasing"
                elif temps[-1] < temps[0] - 5:  # 5°C decrease
                    analysis.temperature_trend = "decreasing"
                else:
                    analysis.temperature_trend = "stable"
            
            # Reallocated sectors trend
            realloc_sectors = [entry.reallocated_sectors for entry in history if entry.reallocated_sectors is not None]
            if len(realloc_sectors) >= 2:
                if realloc_sectors[-1] > realloc_sectors[0]:
                    analysis.reallocated_sectors_trend = "increasing"
                elif realloc_sectors[-1] < realloc_sectors[0]:
                    analysis.reallocated_sectors_trend = "decreasing"
                else:
                    analysis.reallocated_sectors_trend = "stable"
            
            # Pending sectors trend
            pending_sectors = [entry.pending_sectors for entry in history if entry.pending_sectors is not None]
            if len(pending_sectors) >= 2:
                if pending_sectors[-1] > pending_sectors[0]:
                    analysis.pending_sectors_trend = "increasing"
                elif pending_sectors[-1] < pending_sectors[0]:
                    analysis.pending_sectors_trend = "decreasing"
                else:
                    analysis.pending_sectors_trend = "stable"
            
            # Risk assessment and recommendations
            analysis.health_degradation_risk = self._assess_health_risk(history, analysis)
            analysis.recommendations = self._generate_recommendations(history, analysis)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing health trends for {device_path}: {e}")
            return None
    
    def _assess_health_risk(self, history: List[SMARTHealthHistory], analysis: SMARTTrendAnalysis) -> str:
        """
        Assess health degradation risk based on trends.
        
        Args:
            history: Health history entries
            analysis: Current trend analysis
            
        Returns:
            Risk level: "low", "medium", "high"
        """
        risk_factors = 0
        
        # Check for increasing temperature
        if analysis.temperature_trend == "increasing" and analysis.temperature_max and analysis.temperature_max > 50:
            risk_factors += 1
        
        # Check for increasing reallocated sectors
        if analysis.reallocated_sectors_trend == "increasing":
            risk_factors += 2  # More serious
        
        # Check for increasing pending sectors
        if analysis.pending_sectors_trend == "increasing":
            risk_factors += 2  # More serious
        
        # Check for failed health status
        recent_failures = [entry for entry in history[-3:] if entry.overall_health == "FAILED"]
        if recent_failures:
            risk_factors += 3  # Very serious
        
        if risk_factors >= 3:
            return "high"
        elif risk_factors >= 1:
            return "medium"
        else:
            return "low"
    
    def _generate_recommendations(self, history: List[SMARTHealthHistory], analysis: SMARTTrendAnalysis) -> List[str]:
        """
        Generate recommendations based on trend analysis.
        
        Args:
            history: Health history entries
            analysis: Current trend analysis
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        if analysis.temperature_trend == "increasing":
            recommendations.append("Monitor drive temperature - consider improving cooling")
        
        if analysis.temperature_max and analysis.temperature_max > 55:
            recommendations.append("Drive temperature is high - check ventilation and cooling")
        
        if analysis.reallocated_sectors_trend == "increasing":
            recommendations.append("Reallocated sectors increasing - consider drive replacement soon")
        
        if analysis.pending_sectors_trend == "increasing":
            recommendations.append("Pending sectors increasing - run extended SMART test")
        
        if analysis.health_degradation_risk == "high":
            recommendations.append("High risk of drive failure - backup data and plan replacement")
        
        # Check for old drives (high power-on hours)
        latest_entry = history[-1] if history else None
        if latest_entry and latest_entry.power_on_hours and latest_entry.power_on_hours > 43800:  # 5 years
            recommendations.append("Drive has high power-on hours - consider proactive replacement")
        
        return recommendations
    
    def _load_health_history(self) -> None:
        """Load health history from persistent storage."""
        try:
            if os.path.exists(self._history_file_path):
                with open(self._history_file_path, 'r') as f:
                    data = json.load(f)
                    
                self._health_history = []
                for entry_data in data.get('health_history', []):
                    # Convert timestamp string back to datetime
                    entry_data['timestamp'] = datetime.fromisoformat(entry_data['timestamp'])
                    self._health_history.append(SMARTHealthHistory(**entry_data))
                
                logger.info(f"Loaded {len(self._health_history)} health history entries")
            else:
                # Create directory if it doesn't exist
                os.makedirs(os.path.dirname(self._history_file_path), exist_ok=True)
                
        except Exception as e:
            logger.error(f"Error loading health history: {e}")
            self._health_history = []
    
    def _save_health_history(self) -> None:
        """Save health history to persistent storage."""
        try:
            # Convert to serializable format
            history_data = []
            for entry in self._health_history:
                entry_dict = asdict(entry)
                # Convert datetime to ISO string
                entry_dict['timestamp'] = entry.timestamp.isoformat()
                history_data.append(entry_dict)
            
            data = {
                'health_history': history_data,
                'last_updated': datetime.now().isoformat()
            }
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self._history_file_path), exist_ok=True)
            
            # Write to temporary file first, then rename for atomic operation
            temp_file = self._history_file_path + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            os.rename(temp_file, self._history_file_path)
            
        except Exception as e:
            logger.error(f"Error saving health history: {e}")
    
    def get_health_status_with_history(self, device_path: str, use_cache: bool = True) -> Optional[SMARTHealthStatus]:
        """
        Get SMART health status and record it to history.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            use_cache: Whether to use cached data if available
            
        Returns:
            SMARTHealthStatus if successful, None otherwise
        """
        health_status = self.get_health_status(device_path, use_cache)
        
        # Record to history if we got fresh data (not from cache)
        if health_status and not use_cache:
            self.record_health_status(health_status)
        
        return health_status