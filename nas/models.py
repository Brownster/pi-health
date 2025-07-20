"""Data models for NAS management."""

from dataclasses import dataclass
from typing import Optional
from enum import Enum


class DriveRole(Enum):
    """Drive role in the NAS system."""
    DATA = "data"
    PARITY = "parity"
    UNKNOWN = "unknown"


class HealthStatus(Enum):
    """Drive health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DriveHealthState(Enum):
    """Detailed drive health state for failure detection."""
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"


@dataclass
class DriveConfig:
    """Configuration and status information for a drive."""
    device_path: str
    uuid: str
    mount_point: str
    filesystem: str
    role: DriveRole
    size_bytes: int
    used_bytes: int
    health_status: HealthStatus
    label: Optional[str] = None
    
    @property
    def free_bytes(self) -> int:
        """Calculate free space in bytes."""
        return max(0, self.size_bytes - self.used_bytes)
    
    @property
    def usage_percent(self) -> float:
        """Calculate usage percentage."""
        if self.size_bytes == 0:
            return 0.0
        return (self.used_bytes / self.size_bytes) * 100