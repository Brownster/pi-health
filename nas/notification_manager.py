"""Notification system for drive failures and system alerts."""

import logging
import smtplib
import json
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum

from .failure_detector import FailureEvent, DriveHealthAssessment, FailureRisk

logger = logging.getLogger(__name__)


class NotificationLevel(Enum):
    """Notification severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(Enum):
    """Available notification channels."""
    EMAIL = "email"
    LOG = "log"
    WEBHOOK = "webhook"


@dataclass
class NotificationConfig:
    """Configuration for notifications."""
    enabled: bool = True
    channels: List[NotificationChannel] = None
    email_smtp_server: str = ""
    email_smtp_port: int = 587
    email_username: str = ""
    email_password: str = ""
    email_from: str = ""
    email_to: List[str] = None
    webhook_url: str = ""
    min_level: NotificationLevel = NotificationLevel.WARNING
    rate_limit_minutes: int = 60  # Minimum time between similar notifications
    
    def __post_init__(self):
        if self.channels is None:
            self.channels = [NotificationChannel.LOG]
        if self.email_to is None:
            self.email_to = []


@dataclass
class Notification:
    """A notification message."""
    id: str
    level: NotificationLevel
    title: str
    message: str
    timestamp: datetime
    device_path: Optional[str] = None
    failure_events: List[FailureEvent] = None
    recommended_actions: List[str] = None
    sent_channels: List[NotificationChannel] = None
    
    def __post_init__(self):
        if self.failure_events is None:
            self.failure_events = []
        if self.recommended_actions is None:
            self.recommended_actions = []
        if self.sent_channels is None:
            self.sent_channels = []


class NotificationManager:
    """Manages notifications for drive failures and system alerts."""
    
    def __init__(self, config_file: str = "/etc/nas/notifications.json"):
        """
        Initialize notification manager.
        
        Args:
            config_file: Path to notification configuration file
        """
        self.config_file = config_file
        self.config = self._load_config()
        self._notification_history: List[Notification] = []
        self._last_notification_times: Dict[str, datetime] = {}
    
    def notify_drive_failure(self, assessment: DriveHealthAssessment) -> bool:
        """
        Send notification for drive failure or health issues.
        
        Args:
            assessment: Drive health assessment
            
        Returns:
            True if notification was sent successfully
        """
        try:
            # Determine notification level based on risk
            level = self._risk_to_notification_level(assessment.overall_risk)
            
            # Check if we should send notification (rate limiting)
            notification_key = f"drive_failure_{assessment.device_path}_{level.value}"
            if not self._should_send_notification(notification_key, level):
                return False
            
            # Create notification
            title = self._create_failure_title(assessment)
            message = self._create_failure_message(assessment)
            recommended_actions = self._get_failure_recommendations(assessment)
            
            notification = Notification(
                id=f"drive_failure_{assessment.device_path}_{datetime.now().timestamp()}",
                level=level,
                title=title,
                message=message,
                timestamp=datetime.now(),
                device_path=assessment.device_path,
                failure_events=assessment.failure_events,
                recommended_actions=recommended_actions
            )
            
            # Send notification through configured channels
            success = self._send_notification(notification)
            
            if success:
                self._last_notification_times[notification_key] = datetime.now()
                self._notification_history.append(notification)
                
                # Keep only recent notifications (last 30 days)
                cutoff_date = datetime.now() - timedelta(days=30)
                self._notification_history = [
                    n for n in self._notification_history
                    if n.timestamp > cutoff_date
                ]
            
            return success
        
        except Exception as e:
            logger.error(f"Error sending drive failure notification: {e}")
            return False
    
    def notify_system_status(self, title: str, message: str, level: NotificationLevel = NotificationLevel.INFO) -> bool:
        """
        Send general system status notification.
        
        Args:
            title: Notification title
            message: Notification message
            level: Notification level
            
        Returns:
            True if notification was sent successfully
        """
        try:
            # Check rate limiting
            notification_key = f"system_status_{level.value}"
            if not self._should_send_notification(notification_key, level):
                return False
            
            notification = Notification(
                id=f"system_status_{datetime.now().timestamp()}",
                level=level,
                title=title,
                message=message,
                timestamp=datetime.now()
            )
            
            success = self._send_notification(notification)
            
            if success:
                self._last_notification_times[notification_key] = datetime.now()
                self._notification_history.append(notification)
            
            return success
        
        except Exception as e:
            logger.error(f"Error sending system status notification: {e}")
            return False
    
    def notify_recovery_needed(self, device_path: str, recovery_steps: List[str]) -> bool:
        """
        Send notification about required recovery actions.
        
        Args:
            device_path: Device that needs recovery
            recovery_steps: List of recovery steps
            
        Returns:
            True if notification was sent successfully
        """
        title = f"Recovery Required: {device_path}"
        message = f"Drive {device_path} requires recovery actions to restore full functionality."
        
        notification = Notification(
            id=f"recovery_needed_{device_path}_{datetime.now().timestamp()}",
            level=NotificationLevel.ERROR,
            title=title,
            message=message,
            timestamp=datetime.now(),
            device_path=device_path,
            recommended_actions=recovery_steps
        )
        
        return self._send_notification(notification)
    
    def get_recent_notifications(self, hours: int = 24) -> List[Notification]:
        """
        Get recent notifications.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of recent notifications
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [
            notification for notification in self._notification_history
            if notification.timestamp > cutoff_time
        ]
    
    def get_critical_notifications(self) -> List[Notification]:
        """Get all critical notifications that haven't been resolved."""
        return [
            notification for notification in self._notification_history
            if notification.level == NotificationLevel.CRITICAL
        ]
    
    def _load_config(self) -> NotificationConfig:
        """Load notification configuration from file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                
                # Convert channel strings to enums
                if 'channels' in data:
                    data['channels'] = [NotificationChannel(ch) for ch in data['channels']]
                
                # Convert min_level string to enum
                if 'min_level' in data:
                    data['min_level'] = NotificationLevel(data['min_level'])
                
                return NotificationConfig(**data)
            else:
                # Create default config
                config = NotificationConfig()
                self._save_config(config)
                return config
        
        except Exception as e:
            logger.error(f"Error loading notification config: {e}")
            return NotificationConfig()
    
    def _save_config(self, config: NotificationConfig) -> None:
        """Save notification configuration to file."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            # Convert to serializable format
            data = asdict(config)
            data['channels'] = [ch.value for ch in config.channels]
            data['min_level'] = config.min_level.value
            
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Error saving notification config: {e}")
    
    def _should_send_notification(self, notification_key: str, level: NotificationLevel) -> bool:
        """Check if notification should be sent based on rate limiting and level."""
        # Check if notifications are enabled
        if not self.config.enabled:
            return False
        
        # Check minimum level
        level_priority = {
            NotificationLevel.INFO: 0,
            NotificationLevel.WARNING: 1,
            NotificationLevel.ERROR: 2,
            NotificationLevel.CRITICAL: 3
        }
        
        if level_priority[level] < level_priority[self.config.min_level]:
            return False
        
        # Check rate limiting
        if notification_key in self._last_notification_times:
            last_sent = self._last_notification_times[notification_key]
            time_since_last = datetime.now() - last_sent
            
            if time_since_last.total_seconds() < (self.config.rate_limit_minutes * 60):
                return False
        
        return True
    
    def _send_notification(self, notification: Notification) -> bool:
        """Send notification through configured channels."""
        success = True
        
        for channel in self.config.channels:
            try:
                if channel == NotificationChannel.LOG:
                    self._send_log_notification(notification)
                    notification.sent_channels.append(channel)
                elif channel == NotificationChannel.EMAIL:
                    if self._send_email_notification(notification):
                        notification.sent_channels.append(channel)
                    else:
                        success = False
                elif channel == NotificationChannel.WEBHOOK:
                    if self._send_webhook_notification(notification):
                        notification.sent_channels.append(channel)
                    else:
                        success = False
            
            except Exception as e:
                logger.error(f"Error sending notification via {channel.value}: {e}")
                success = False
        
        return success
    
    def _send_log_notification(self, notification: Notification) -> None:
        """Send notification to log."""
        log_message = f"[{notification.level.value.upper()}] {notification.title}: {notification.message}"
        
        if notification.level == NotificationLevel.CRITICAL:
            logger.critical(log_message)
        elif notification.level == NotificationLevel.ERROR:
            logger.error(log_message)
        elif notification.level == NotificationLevel.WARNING:
            logger.warning(log_message)
        else:
            logger.info(log_message)
        
        if notification.recommended_actions:
            logger.info(f"Recommended actions: {', '.join(notification.recommended_actions)}")
    
    def _send_email_notification(self, notification: Notification) -> bool:
        """Send notification via email."""
        try:
            if not self.config.email_to or not self.config.email_from:
                logger.warning("Email notification configured but missing recipients or sender")
                return False
            
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.config.email_from
            msg['To'] = ', '.join(self.config.email_to)
            msg['Subject'] = f"[NAS Alert] {notification.title}"
            
            # Create email body
            body = self._create_email_body(notification)
            msg.attach(MIMEText(body, 'html'))
            
            # Send email
            with smtplib.SMTP(self.config.email_smtp_server, self.config.email_smtp_port) as server:
                if self.config.email_username and self.config.email_password:
                    server.starttls()
                    server.login(self.config.email_username, self.config.email_password)
                
                server.send_message(msg)
            
            logger.info(f"Email notification sent: {notification.title}")
            return True
        
        except Exception as e:
            logger.error(f"Error sending email notification: {e}")
            return False
    
    def _send_webhook_notification(self, notification: Notification) -> bool:
        """Send notification via webhook."""
        try:
            if not self.config.webhook_url:
                return False
            
            import requests
            
            payload = {
                'id': notification.id,
                'level': notification.level.value,
                'title': notification.title,
                'message': notification.message,
                'timestamp': notification.timestamp.isoformat(),
                'device_path': notification.device_path,
                'recommended_actions': notification.recommended_actions
            }
            
            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Webhook notification sent: {notification.title}")
                return True
            else:
                logger.error(f"Webhook notification failed with status {response.status_code}")
                return False
        
        except Exception as e:
            logger.error(f"Error sending webhook notification: {e}")
            return False
    
    def _create_email_body(self, notification: Notification) -> str:
        """Create HTML email body for notification."""
        level_colors = {
            NotificationLevel.INFO: "#17a2b8",
            NotificationLevel.WARNING: "#ffc107",
            NotificationLevel.ERROR: "#dc3545",
            NotificationLevel.CRITICAL: "#721c24"
        }
        
        color = level_colors.get(notification.level, "#6c757d")
        
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
            <div style="border-left: 4px solid {color}; padding-left: 20px;">
                <h2 style="color: {color}; margin-top: 0;">
                    {notification.title}
                </h2>
                <p><strong>Level:</strong> {notification.level.value.upper()}</p>
                <p><strong>Time:</strong> {notification.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
                {f'<p><strong>Device:</strong> {notification.device_path}</p>' if notification.device_path else ''}
                
                <h3>Details</h3>
                <p>{notification.message}</p>
        """
        
        if notification.failure_events:
            html += "<h3>Failure Events</h3><ul>"
            for event in notification.failure_events:
                html += f"<li><strong>{event.failure_type.value}:</strong> {event.message}</li>"
            html += "</ul>"
        
        if notification.recommended_actions:
            html += "<h3>Recommended Actions</h3><ol>"
            for action in notification.recommended_actions:
                html += f"<li>{action}</li>"
            html += "</ol>"
        
        html += """
            </div>
            <hr style="margin-top: 30px;">
            <p style="color: #6c757d; font-size: 12px;">
                This is an automated notification from your NAS system.
            </p>
        </body>
        </html>
        """
        
        return html
    
    def _risk_to_notification_level(self, risk: FailureRisk) -> NotificationLevel:
        """Convert failure risk to notification level."""
        risk_mapping = {
            FailureRisk.LOW: NotificationLevel.INFO,
            FailureRisk.MEDIUM: NotificationLevel.WARNING,
            FailureRisk.HIGH: NotificationLevel.ERROR,
            FailureRisk.CRITICAL: NotificationLevel.CRITICAL
        }
        return risk_mapping.get(risk, NotificationLevel.WARNING)
    
    def _create_failure_title(self, assessment: DriveHealthAssessment) -> str:
        """Create notification title for drive failure."""
        risk_titles = {
            FailureRisk.LOW: "Drive Health Check",
            FailureRisk.MEDIUM: "Drive Health Warning",
            FailureRisk.HIGH: "Drive Health Alert",
            FailureRisk.CRITICAL: "CRITICAL: Drive Failure"
        }
        
        base_title = risk_titles.get(assessment.overall_risk, "Drive Health Issue")
        return f"{base_title}: {assessment.device_path}"
    
    def _create_failure_message(self, assessment: DriveHealthAssessment) -> str:
        """Create detailed message for drive failure notification."""
        message_parts = [
            f"Drive {assessment.device_path} has been assessed with {assessment.overall_risk.value} failure risk."
        ]
        
        if assessment.failure_events:
            message_parts.append(f"Detected {len(assessment.failure_events)} issue(s):")
            for event in assessment.failure_events[:3]:  # Show first 3 events
                message_parts.append(f"- {event.failure_type.value}: {event.message}")
            
            if len(assessment.failure_events) > 3:
                message_parts.append(f"... and {len(assessment.failure_events) - 3} more issue(s)")
        
        if not assessment.degraded_mode_capable:
            message_parts.append("WARNING: System may not be able to operate in degraded mode without this drive.")
        
        return " ".join(message_parts)
    
    def _get_failure_recommendations(self, assessment: DriveHealthAssessment) -> List[str]:
        """Get recommended actions for drive failure."""
        recommendations = []
        
        # Collect recommendations from failure events
        for event in assessment.failure_events:
            recommendations.extend(event.recommended_actions)
        
        # Add general recommendations based on risk level
        if assessment.overall_risk == FailureRisk.CRITICAL:
            recommendations.extend([
                "Stop using this drive for new data immediately",
                "Backup all important data from this drive",
                "Replace drive as soon as possible"
            ])
        elif assessment.overall_risk == FailureRisk.HIGH:
            recommendations.extend([
                "Plan drive replacement within the next few days",
                "Increase backup frequency for this drive",
                "Monitor drive health closely"
            ])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_recommendations = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique_recommendations.append(rec)
        
        return unique_recommendations
    
    def update_config(self, **kwargs) -> bool:
        """
        Update notification configuration.
        
        Args:
            **kwargs: Configuration parameters to update
            
        Returns:
            True if configuration was updated successfully
        """
        try:
            # Update configuration
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
            
            # Save updated configuration
            self._save_config(self.config)
            return True
        
        except Exception as e:
            logger.error(f"Error updating notification config: {e}")
            return False
    
    def test_notification(self, channel: NotificationChannel) -> bool:
        """
        Send a test notification through specified channel.
        
        Args:
            channel: Channel to test
            
        Returns:
            True if test notification was sent successfully
        """
        test_notification = Notification(
            id=f"test_{datetime.now().timestamp()}",
            level=NotificationLevel.INFO,
            title="Test Notification",
            message="This is a test notification to verify the notification system is working correctly.",
            timestamp=datetime.now(),
            recommended_actions=["No action required - this is a test"]
        )
        
        try:
            if channel == NotificationChannel.LOG:
                self._send_log_notification(test_notification)
                return True
            elif channel == NotificationChannel.EMAIL:
                return self._send_email_notification(test_notification)
            elif channel == NotificationChannel.WEBHOOK:
                return self._send_webhook_notification(test_notification)
            else:
                return False
        
        except Exception as e:
            logger.error(f"Error sending test notification: {e}")
            return False