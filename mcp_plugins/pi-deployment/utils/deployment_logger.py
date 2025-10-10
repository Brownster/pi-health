"""
Deployment Logger
Comprehensive logging and monitoring for Pi deployment operations.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import sqlite3

logger = logging.getLogger(__name__)


class DeploymentLogger:
    """Comprehensive deployment logging and monitoring system."""

    def __init__(self):
        self.log_dir = Path("/var/log/pi-health")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # SQLite database for structured logging
        self.db_path = self.log_dir / "deployments.db"
        self._init_database()

        # File-based logging
        self.log_file = self.log_dir / "deployment.log"
        self._setup_file_logging()

    def _init_database(self):
        """Initialize SQLite database for deployment logging."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Deployments table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS deployments (
                        id TEXT PRIMARY KEY,
                        stack_id TEXT NOT NULL,
                        stack_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        end_time REAL,
                        config TEXT,
                        result TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Actions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        deployment_id TEXT,
                        action_type TEXT NOT NULL,
                        action_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        end_time REAL,
                        result TEXT,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (deployment_id) REFERENCES deployments (id)
                    )
                """)

                # System events table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        event_data TEXT,
                        timestamp REAL NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def _setup_file_logging(self):
        """Setup file-based logging."""
        try:
            # Configure file handler for deployment logs
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setLevel(logging.INFO)

            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)

            # Add handler to deployment logger
            deployment_logger = logging.getLogger('pi-deployment')
            deployment_logger.addHandler(file_handler)
            deployment_logger.setLevel(logging.INFO)

        except Exception as e:
            logger.error(f"Failed to setup file logging: {e}")

    async def log_deployment_start(self, deployment_id: str, stack_id: str, stack_name: str, config: Dict[str, Any]) -> None:
        """Log the start of a deployment."""
        try:
            start_time = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO deployments (id, stack_id, stack_name, status, start_time, config)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (deployment_id, stack_id, stack_name, 'starting', start_time, json.dumps(config)))
                conn.commit()

            logger.info(f"Deployment started: {deployment_id} ({stack_name})")

        except Exception as e:
            logger.error(f"Failed to log deployment start: {e}")

    async def log_deployment_end(self, deployment_id: str, status: str, result: Dict[str, Any]) -> None:
        """Log the completion of a deployment."""
        try:
            end_time = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE deployments
                    SET status = ?, end_time = ?, result = ?
                    WHERE id = ?
                """, (status, end_time, json.dumps(result), deployment_id))
                conn.commit()

            logger.info(f"Deployment completed: {deployment_id} - Status: {status}")

        except Exception as e:
            logger.error(f"Failed to log deployment end: {e}")

    async def log_action(self, action_type: str, action_data: Dict[str, Any], deployment_id: str = None) -> str:
        """Log a deployment action."""
        try:
            action_id = f"{action_type}_{int(time.time())}"
            start_time = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO actions (deployment_id, action_type, action_name, status, start_time, result)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    deployment_id,
                    action_type,
                    action_data.get('name', action_type),
                    'in_progress',
                    start_time,
                    json.dumps(action_data)
                ))
                action_db_id = cursor.lastrowid
                conn.commit()

            logger.info(f"Action logged: {action_type} - {action_data.get('name', '')}")
            return str(action_db_id)

        except Exception as e:
            logger.error(f"Failed to log action: {e}")
            return ""

    async def update_action(self, action_db_id: str, status: str, result: Dict[str, Any] = None, error: str = None) -> None:
        """Update an action's status and result."""
        try:
            end_time = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE actions
                    SET status = ?, end_time = ?, result = ?, error_message = ?
                    WHERE id = ?
                """, (status, end_time, json.dumps(result) if result else None, error, int(action_db_id)))
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to update action: {e}")

    async def log_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]) -> None:
        """Log a complete workflow execution."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Check if deployment record exists, create if not
                cursor.execute("SELECT id FROM deployments WHERE id = ?", (workflow_id,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO deployments (id, stack_id, stack_name, status, start_time, result)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        workflow_id,
                        'workflow',
                        workflow_data.get('workflow_type', 'unknown'),
                        workflow_data.get('status', 'unknown'),
                        workflow_data.get('start_time', time.time()),
                        json.dumps(workflow_data)
                    ))
                else:
                    cursor.execute("""
                        UPDATE deployments
                        SET status = ?, result = ?, end_time = ?
                        WHERE id = ?
                    """, (
                        workflow_data.get('status', 'unknown'),
                        json.dumps(workflow_data),
                        workflow_data.get('end_time', time.time()),
                        workflow_id
                    ))

                conn.commit()

            logger.info(f"Workflow logged: {workflow_id}")

        except Exception as e:
            logger.error(f"Failed to log workflow: {e}")

    async def log_system_event(self, event_type: str, event_data: Dict[str, Any]) -> None:
        """Log a system event."""
        try:
            timestamp = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO system_events (event_type, event_data, timestamp)
                    VALUES (?, ?, ?)
                """, (event_type, json.dumps(event_data), timestamp))
                conn.commit()

            logger.info(f"System event logged: {event_type}")

        except Exception as e:
            logger.error(f"Failed to log system event: {e}")

    async def get_logs(self, deployment_id: str) -> Dict[str, Any]:
        """Get logs for a specific deployment."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get deployment info
                cursor.execute("""
                    SELECT * FROM deployments WHERE id = ?
                """, (deployment_id,))
                deployment_row = cursor.fetchone()

                if not deployment_row:
                    return {'error': 'Deployment not found'}

                deployment_columns = ['id', 'stack_id', 'stack_name', 'status', 'start_time', 'end_time', 'config', 'result', 'created_at']
                deployment = dict(zip(deployment_columns, deployment_row))

                # Parse JSON fields
                try:
                    deployment['config'] = json.loads(deployment['config']) if deployment['config'] else {}
                    deployment['result'] = json.loads(deployment['result']) if deployment['result'] else {}
                except json.JSONDecodeError:
                    pass

                # Get actions
                cursor.execute("""
                    SELECT * FROM actions WHERE deployment_id = ?
                    ORDER BY start_time ASC
                """, (deployment_id,))

                action_rows = cursor.fetchall()
                action_columns = ['id', 'deployment_id', 'action_type', 'action_name', 'status', 'start_time', 'end_time', 'result', 'error_message', 'created_at']

                actions = []
                for row in action_rows:
                    action = dict(zip(action_columns, row))
                    try:
                        action['result'] = json.loads(action['result']) if action['result'] else {}
                    except json.JSONDecodeError:
                        pass
                    actions.append(action)

                return {
                    'deployment': deployment,
                    'actions': actions,
                    'total_actions': len(actions)
                }

        except Exception as e:
            logger.error(f"Failed to get logs for {deployment_id}: {e}")
            return {'error': str(e)}

    async def get_recent_logs(self, limit: int = 50) -> Dict[str, Any]:
        """Get recent deployment activity."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Get recent deployments
                cursor.execute("""
                    SELECT id, stack_id, stack_name, status, start_time, end_time, created_at
                    FROM deployments
                    ORDER BY start_time DESC
                    LIMIT ?
                """, (limit,))

                deployment_rows = cursor.fetchall()
                deployment_columns = ['id', 'stack_id', 'stack_name', 'status', 'start_time', 'end_time', 'created_at']

                deployments = []
                for row in deployment_rows:
                    deployment = dict(zip(deployment_columns, row))
                    deployments.append(deployment)

                # Get recent actions
                cursor.execute("""
                    SELECT action_type, action_name, status, start_time, end_time, deployment_id, created_at
                    FROM actions
                    ORDER BY start_time DESC
                    LIMIT ?
                """, (limit,))

                action_rows = cursor.fetchall()
                action_columns = ['action_type', 'action_name', 'status', 'start_time', 'end_time', 'deployment_id', 'created_at']

                actions = []
                for row in action_rows:
                    action = dict(zip(action_columns, row))
                    actions.append(action)

                # Get recent system events
                cursor.execute("""
                    SELECT event_type, event_data, timestamp, created_at
                    FROM system_events
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit // 2,))

                event_rows = cursor.fetchall()
                event_columns = ['event_type', 'event_data', 'timestamp', 'created_at']

                events = []
                for row in event_rows:
                    event = dict(zip(event_columns, row))
                    try:
                        event['event_data'] = json.loads(event['event_data']) if event['event_data'] else {}
                    except json.JSONDecodeError:
                        pass
                    events.append(event)

                return {
                    'recent_deployments': deployments,
                    'recent_actions': actions,
                    'recent_events': events
                }

        except Exception as e:
            logger.error(f"Failed to get recent logs: {e}")
            return {'error': str(e)}

    async def get_deployment_statistics(self) -> Dict[str, Any]:
        """Get deployment statistics and analytics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                stats = {}

                # Total deployments
                cursor.execute("SELECT COUNT(*) FROM deployments")
                stats['total_deployments'] = cursor.fetchone()[0]

                # Deployments by status
                cursor.execute("""
                    SELECT status, COUNT(*)
                    FROM deployments
                    GROUP BY status
                """)
                stats['deployments_by_status'] = dict(cursor.fetchall())

                # Most popular stacks
                cursor.execute("""
                    SELECT stack_id, COUNT(*) as count
                    FROM deployments
                    GROUP BY stack_id
                    ORDER BY count DESC
                    LIMIT 10
                """)
                stats['popular_stacks'] = [{'stack_id': row[0], 'count': row[1]} for row in cursor.fetchall()]

                # Recent deployment success rate (last 30 days)
                thirty_days_ago = time.time() - (30 * 24 * 60 * 60)
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
                    FROM deployments
                    WHERE start_time > ?
                """, (thirty_days_ago,))

                row = cursor.fetchone()
                if row[0] > 0:
                    stats['success_rate_30_days'] = (row[1] / row[0]) * 100
                else:
                    stats['success_rate_30_days'] = 0

                # Average deployment time
                cursor.execute("""
                    SELECT AVG(end_time - start_time) as avg_duration
                    FROM deployments
                    WHERE end_time IS NOT NULL AND status = 'completed'
                """)
                avg_duration = cursor.fetchone()[0]
                stats['average_deployment_time_seconds'] = avg_duration if avg_duration else 0

                # Failed deployments with errors
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM deployments
                    WHERE status IN ('failed', 'error')
                """)
                stats['failed_deployments'] = cursor.fetchone()[0]

                return stats

        except Exception as e:
            logger.error(f"Failed to get deployment statistics: {e}")
            return {'error': str(e)}

    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get status of a specific workflow."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT status, result, start_time, end_time
                    FROM deployments
                    WHERE id = ?
                """, (workflow_id,))

                row = cursor.fetchone()
                if not row:
                    return {'status': 'not_found'}

                status, result, start_time, end_time = row

                workflow_status = {
                    'workflow_id': workflow_id,
                    'status': status,
                    'start_time': start_time,
                    'end_time': end_time
                }

                if result:
                    try:
                        workflow_status['result'] = json.loads(result)
                    except json.JSONDecodeError:
                        workflow_status['result'] = {'raw': result}

                return workflow_status

        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            return {'error': str(e)}

    async def cleanup_old_logs(self, days_to_keep: int = 90) -> Dict[str, Any]:
        """Clean up old log entries."""
        try:
            cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Delete old deployments and their actions
                cursor.execute("SELECT COUNT(*) FROM deployments WHERE start_time < ?", (cutoff_time,))
                old_deployments = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM actions WHERE start_time < ?", (cutoff_time,))
                old_actions = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM system_events WHERE timestamp < ?", (cutoff_time,))
                old_events = cursor.fetchone()[0]

                # Delete old records
                cursor.execute("DELETE FROM actions WHERE start_time < ?", (cutoff_time,))
                cursor.execute("DELETE FROM deployments WHERE start_time < ?", (cutoff_time,))
                cursor.execute("DELETE FROM system_events WHERE timestamp < ?", (cutoff_time,))

                conn.commit()

                # Vacuum database to reclaim space
                cursor.execute("VACUUM")

                return {
                    'success': True,
                    'cleaned_deployments': old_deployments,
                    'cleaned_actions': old_actions,
                    'cleaned_events': old_events,
                    'cutoff_date': datetime.fromtimestamp(cutoff_time).isoformat()
                }

        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return {'success': False, 'error': str(e)}

    async def export_logs(self, output_format: str = 'json', deployment_id: str = None) -> Dict[str, Any]:
        """Export logs in various formats."""
        try:
            if deployment_id:
                data = await self.get_logs(deployment_id)
            else:
                data = await self.get_recent_logs(limit=1000)

            if output_format.lower() == 'json':
                export_data = json.dumps(data, indent=2, default=str)
                filename = f"pi-health-logs-{int(time.time())}.json"
            elif output_format.lower() == 'csv':
                # Simplified CSV export (would need pandas for full implementation)
                export_data = "Export format CSV not implemented yet"
                filename = f"pi-health-logs-{int(time.time())}.csv"
            else:
                return {'success': False, 'error': f'Unsupported format: {output_format}'}

            # Write to file
            export_path = self.log_dir / filename
            with open(export_path, 'w') as f:
                f.write(export_data)

            return {
                'success': True,
                'export_path': str(export_path),
                'format': output_format,
                'size_bytes': len(export_data)
            }

        except Exception as e:
            logger.error(f"Failed to export logs: {e}")
            return {'success': False, 'error': str(e)}