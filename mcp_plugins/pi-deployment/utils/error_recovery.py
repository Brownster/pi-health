"""
Error Recovery Module
Intelligent error recovery and rollback capabilities for Pi deployments.
"""

import asyncio
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import sqlite3

logger = logging.getLogger(__name__)


class RecoverySnapshot:
    """Represents a system recovery snapshot."""

    def __init__(self, snapshot_id: str, snapshot_type: str, data: Dict[str, Any]):
        self.snapshot_id = snapshot_id
        self.snapshot_type = snapshot_type
        self.created_at = time.time()
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            'snapshot_id': self.snapshot_id,
            'snapshot_type': self.snapshot_type,
            'created_at': self.created_at,
            'data': self.data
        }


class ErrorRecovery:
    """Intelligent error recovery and rollback system."""

    def __init__(self):
        self.recovery_dir = Path("/var/lib/pi-health/recovery")
        self.recovery_dir.mkdir(parents=True, exist_ok=True)

        self.snapshots_dir = self.recovery_dir / "snapshots"
        self.snapshots_dir.mkdir(exist_ok=True)

        self.db_path = self.recovery_dir / "recovery.db"
        self._init_database()

        # Recovery strategies
        self.recovery_strategies = {
            'docker_deployment_failed': self._recover_docker_deployment,
            'service_start_failed': self._recover_service_start,
            'network_configuration_failed': self._recover_network_config,
            'storage_mount_failed': self._recover_storage_mount,
            'system_optimization_failed': self._recover_system_optimization,
            'workflow_interrupted': self._recover_workflow_interruption
        }

    def _init_database(self):
        """Initialize recovery database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Snapshots table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS snapshots (
                        id TEXT PRIMARY KEY,
                        snapshot_type TEXT NOT NULL,
                        deployment_id TEXT,
                        created_at REAL NOT NULL,
                        data TEXT NOT NULL,
                        file_path TEXT,
                        description TEXT
                    )
                """)

                # Recovery actions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS recovery_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        deployment_id TEXT NOT NULL,
                        error_type TEXT NOT NULL,
                        recovery_strategy TEXT NOT NULL,
                        status TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        end_time REAL,
                        result TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to initialize recovery database: {e}")

    async def create_snapshot(self, snapshot_type: str, data: Dict[str, Any], deployment_id: str = None) -> str:
        """Create a recovery snapshot."""
        try:
            snapshot_id = f"{snapshot_type}_{int(time.time())}"

            # Create snapshot object
            snapshot = RecoverySnapshot(snapshot_id, snapshot_type, data)

            # Save snapshot files if needed
            snapshot_dir = self.snapshots_dir / snapshot_id
            snapshot_dir.mkdir(exist_ok=True)

            file_paths = []

            # Handle different snapshot types
            if snapshot_type == 'config_files':
                file_paths = await self._backup_config_files(data, snapshot_dir)
            elif snapshot_type == 'docker_state':
                file_paths = await self._backup_docker_state(data, snapshot_dir)
            elif snapshot_type == 'system_state':
                file_paths = await self._backup_system_state(data, snapshot_dir)

            # Save snapshot metadata to database
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO snapshots (id, snapshot_type, deployment_id, created_at, data, file_path, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    snapshot_id,
                    snapshot_type,
                    deployment_id,
                    snapshot.created_at,
                    json.dumps(snapshot.data),
                    json.dumps(file_paths) if file_paths else None,
                    data.get('description', f'{snapshot_type} snapshot')
                ))
                conn.commit()

            logger.info(f"Created snapshot: {snapshot_id}")
            return snapshot_id

        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            return ""

    async def _backup_config_files(self, data: Dict[str, Any], snapshot_dir: Path) -> List[str]:
        """Backup configuration files."""
        backed_up_files = []

        try:
            config_files = data.get('config_files', [])

            for config_file in config_files:
                src_path = Path(config_file)
                if src_path.exists():
                    dest_path = snapshot_dir / src_path.name
                    shutil.copy2(src_path, dest_path)
                    backed_up_files.append(str(dest_path))

            return backed_up_files

        except Exception as e:
            logger.error(f"Config files backup failed: {e}")
            return []

    async def _backup_docker_state(self, data: Dict[str, Any], snapshot_dir: Path) -> List[str]:
        """Backup Docker deployment state."""
        backed_up_files = []

        try:
            deployment_dir = data.get('deployment_dir')
            if deployment_dir and Path(deployment_dir).exists():
                # Save docker-compose.yml and .env
                compose_file = Path(deployment_dir) / 'docker-compose.yml'
                env_file = Path(deployment_dir) / '.env'

                if compose_file.exists():
                    shutil.copy2(compose_file, snapshot_dir / 'docker-compose.yml')
                    backed_up_files.append(str(snapshot_dir / 'docker-compose.yml'))

                if env_file.exists():
                    shutil.copy2(env_file, snapshot_dir / '.env')
                    backed_up_files.append(str(snapshot_dir / '.env'))

            # Save running containers info
            containers_info = await self._get_running_containers()
            if containers_info:
                containers_file = snapshot_dir / 'containers_state.json'
                with open(containers_file, 'w') as f:
                    json.dump(containers_info, f, indent=2)
                backed_up_files.append(str(containers_file))

            return backed_up_files

        except Exception as e:
            logger.error(f"Docker state backup failed: {e}")
            return []

    async def _backup_system_state(self, data: Dict[str, Any], snapshot_dir: Path) -> List[str]:
        """Backup system configuration state."""
        backed_up_files = []

        try:
            # System files to backup
            system_files = [
                '/boot/config.txt',
                '/etc/fstab',
                '/etc/sysctl.conf',
                '/etc/systemd/system.conf'
            ]

            for system_file in system_files:
                src_path = Path(system_file)
                if src_path.exists():
                    dest_path = snapshot_dir / src_path.name
                    try:
                        shutil.copy2(src_path, dest_path)
                        backed_up_files.append(str(dest_path))
                    except PermissionError:
                        logger.warning(f"Cannot backup {system_file}: Permission denied")

            # Save system info
            system_info = await self._get_system_info_snapshot()
            if system_info:
                info_file = snapshot_dir / 'system_info.json'
                with open(info_file, 'w') as f:
                    json.dump(system_info, f, indent=2)
                backed_up_files.append(str(info_file))

            return backed_up_files

        except Exception as e:
            logger.error(f"System state backup failed: {e}")
            return []

    async def handle_workflow_failure(self, workflow_id: str, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Handle workflow failure with intelligent recovery."""
        try:
            logger.info(f"Handling workflow failure: {workflow_id}")

            failure_step = workflow_status.get('current_step')
            error_message = workflow_status.get('error', 'Unknown error')

            # Determine recovery strategy based on failure point
            recovery_strategy = await self._determine_recovery_strategy(failure_step, error_message)

            recovery_result = {
                'workflow_id': workflow_id,
                'failure_step': failure_step,
                'error_message': error_message,
                'recovery_strategy': recovery_strategy,
                'actions_taken': [],
                'success': False
            }

            # Execute recovery strategy
            if recovery_strategy in self.recovery_strategies:
                strategy_result = await self.recovery_strategies[recovery_strategy](workflow_status)
                recovery_result.update(strategy_result)
            else:
                # Generic recovery
                generic_result = await self._generic_recovery(workflow_status)
                recovery_result.update(generic_result)

            # Log recovery attempt
            await self._log_recovery_action(workflow_id, failure_step, recovery_strategy, recovery_result)

            return recovery_result

        except Exception as e:
            logger.error(f"Workflow failure handling failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _determine_recovery_strategy(self, failure_step: str, error_message: str) -> str:
        """Determine appropriate recovery strategy based on failure details."""
        try:
            # Analyze error patterns
            error_lower = error_message.lower()

            if 'docker' in error_lower or 'container' in error_lower:
                return 'docker_deployment_failed'
            elif 'network' in error_lower or 'connection' in error_lower:
                return 'network_configuration_failed'
            elif 'mount' in error_lower or 'storage' in error_lower:
                return 'storage_mount_failed'
            elif 'service' in error_lower:
                return 'service_start_failed'
            elif 'system' in error_lower or 'optimization' in error_lower:
                return 'system_optimization_failed'
            elif failure_step:
                return 'workflow_interrupted'
            else:
                return 'generic_recovery'

        except Exception as e:
            logger.error(f"Failed to determine recovery strategy: {e}")
            return 'generic_recovery'

    async def _recover_docker_deployment(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from Docker deployment failures."""
        try:
            actions_taken = []
            success = False

            deployment_dir = workflow_status.get('deployment_dir')
            if deployment_dir:
                # Stop any running containers
                stop_result = await self._run_command([
                    'docker-compose', '-f', f'{deployment_dir}/docker-compose.yml', 'down'
                ], ignore_errors=True)

                if stop_result['success']:
                    actions_taken.append('Stopped failed containers')

                # Clean up volumes if needed
                cleanup_result = await self._run_command([
                    'docker-compose', '-f', f'{deployment_dir}/docker-compose.yml', 'down', '-v'
                ], ignore_errors=True)

                if cleanup_result['success']:
                    actions_taken.append('Cleaned up volumes')

                # Remove deployment directory
                try:
                    shutil.rmtree(deployment_dir)
                    actions_taken.append('Removed deployment directory')
                    success = True
                except Exception as e:
                    actions_taken.append(f'Failed to remove deployment directory: {e}')

            return {
                'success': success,
                'actions_taken': actions_taken,
                'recovery_type': 'docker_cleanup'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'docker_cleanup'
            }

    async def _recover_service_start(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from service start failures."""
        try:
            actions_taken = []

            # Restart Docker daemon
            restart_result = await self._run_command(['systemctl', 'restart', 'docker'], ignore_errors=True)
            if restart_result['success']:
                actions_taken.append('Restarted Docker daemon')

            # Clear Docker cache
            prune_result = await self._run_command(['docker', 'system', 'prune', '-f'], ignore_errors=True)
            if prune_result['success']:
                actions_taken.append('Pruned Docker system')

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'service_recovery'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'service_recovery'
            }

    async def _recover_network_config(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from network configuration failures."""
        try:
            actions_taken = []

            # Reset network interface
            reset_result = await self._run_command(['systemctl', 'restart', 'networking'], ignore_errors=True)
            if reset_result['success']:
                actions_taken.append('Reset network interfaces')

            # Flush DNS
            dns_result = await self._run_command(['systemctl', 'restart', 'systemd-resolved'], ignore_errors=True)
            if dns_result['success']:
                actions_taken.append('Restarted DNS resolver')

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'network_recovery'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'network_recovery'
            }

    async def _recover_storage_mount(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from storage mounting failures."""
        try:
            actions_taken = []

            # Unmount any problematic mounts
            mount_result = await self._run_command(['mount'], ignore_errors=True)
            if mount_result['success']:
                # Look for pi-health related mounts and unmount them
                for line in mount_result['stdout'].split('\n'):
                    if 'pi-health' in line or '/mnt/usb-auto' in line:
                        mount_point = line.split()[2]
                        umount_result = await self._run_command(['umount', mount_point], ignore_errors=True)
                        if umount_result['success']:
                            actions_taken.append(f'Unmounted {mount_point}')

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'storage_recovery'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'storage_recovery'
            }

    async def _recover_system_optimization(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from system optimization failures."""
        try:
            actions_taken = []

            # Restore from snapshot if available
            snapshots = await self.get_snapshots()
            system_snapshots = [s for s in snapshots.get('snapshots', []) if s['snapshot_type'] == 'system_state']

            if system_snapshots:
                latest_snapshot = max(system_snapshots, key=lambda x: x['created_at'])
                restore_result = await self.restore_snapshot(latest_snapshot['id'])
                if restore_result['success']:
                    actions_taken.append(f"Restored system from snapshot {latest_snapshot['id']}")

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'system_recovery'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'system_recovery'
            }

    async def _recover_workflow_interruption(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Recover from workflow interruption."""
        try:
            actions_taken = []

            # Clean up partial deployment
            deployment_dir = workflow_status.get('deployment_dir')
            if deployment_dir and Path(deployment_dir).exists():
                try:
                    shutil.rmtree(deployment_dir)
                    actions_taken.append('Cleaned up partial deployment')
                except Exception as e:
                    actions_taken.append(f'Failed to clean up partial deployment: {e}')

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'workflow_cleanup'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'workflow_cleanup'
            }

    async def _generic_recovery(self, workflow_status: Dict[str, Any]) -> Dict[str, Any]:
        """Generic recovery actions."""
        try:
            actions_taken = []

            # Basic cleanup actions
            cleanup_actions = [
                (['docker', 'system', 'prune', '-f'], 'Pruned Docker system'),
                (['systemctl', 'restart', 'docker'], 'Restarted Docker'),
            ]

            for cmd, description in cleanup_actions:
                result = await self._run_command(cmd, ignore_errors=True)
                if result['success']:
                    actions_taken.append(description)

            return {
                'success': len(actions_taken) > 0,
                'actions_taken': actions_taken,
                'recovery_type': 'generic_cleanup'
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'recovery_type': 'generic_cleanup'
            }

    async def rollback(self, deployment_id: str) -> Dict[str, Any]:
        """Rollback a specific deployment."""
        try:
            logger.info(f"Rolling back deployment: {deployment_id}")

            # Find snapshots for this deployment
            snapshots = await self.get_snapshots()
            deployment_snapshots = [
                s for s in snapshots.get('snapshots', [])
                if s.get('deployment_id') == deployment_id
            ]

            if not deployment_snapshots:
                return {'success': False, 'error': 'No snapshots found for deployment'}

            rollback_actions = []
            success = True

            # Restore from most recent snapshot
            latest_snapshot = max(deployment_snapshots, key=lambda x: x['created_at'])
            restore_result = await self.restore_snapshot(latest_snapshot['id'])

            if restore_result['success']:
                rollback_actions.extend(restore_result.get('actions', []))
            else:
                success = False

            # Additional cleanup
            cleanup_result = await self._cleanup_deployment_artifacts(deployment_id)
            rollback_actions.extend(cleanup_result.get('actions', []))

            return {
                'success': success,
                'deployment_id': deployment_id,
                'actions_taken': rollback_actions,
                'snapshot_used': latest_snapshot['id']
            }

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return {'success': False, 'error': str(e)}

    async def restore_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore from a specific snapshot."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM snapshots WHERE id = ?", (snapshot_id,))
                row = cursor.fetchone()

                if not row:
                    return {'success': False, 'error': 'Snapshot not found'}

                columns = ['id', 'snapshot_type', 'deployment_id', 'created_at', 'data', 'file_path', 'description']
                snapshot_data = dict(zip(columns, row))

            # Parse snapshot data
            data = json.loads(snapshot_data['data'])
            file_paths = json.loads(snapshot_data['file_path']) if snapshot_data['file_path'] else []

            restore_actions = []

            # Restore files
            snapshot_dir = self.snapshots_dir / snapshot_id
            if snapshot_dir.exists():
                for file_path in file_paths:
                    src_path = Path(file_path)
                    if src_path.exists():
                        # Determine destination based on file type
                        dest_path = await self._determine_restore_destination(src_path, data)
                        if dest_path:
                            try:
                                shutil.copy2(src_path, dest_path)
                                restore_actions.append(f'Restored {dest_path}')
                            except PermissionError:
                                restore_actions.append(f'Cannot restore {dest_path}: Permission denied')

            return {
                'success': len(restore_actions) > 0,
                'snapshot_id': snapshot_id,
                'actions': restore_actions
            }

        except Exception as e:
            logger.error(f"Snapshot restore failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _determine_restore_destination(self, src_path: Path, snapshot_data: Dict[str, Any]) -> Optional[Path]:
        """Determine where to restore a file based on its type."""
        filename = src_path.name

        if filename == 'docker-compose.yml':
            deployment_dir = snapshot_data.get('deployment_dir')
            return Path(deployment_dir) / 'docker-compose.yml' if deployment_dir else None

        elif filename == '.env':
            deployment_dir = snapshot_data.get('deployment_dir')
            return Path(deployment_dir) / '.env' if deployment_dir else None

        elif filename == 'config.txt':
            return Path('/boot/config.txt')

        elif filename == 'fstab':
            return Path('/etc/fstab')

        # Add more file type mappings as needed
        return None

    async def get_snapshots(self) -> Dict[str, Any]:
        """Get list of available recovery snapshots."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, snapshot_type, deployment_id, created_at, description
                    FROM snapshots
                    ORDER BY created_at DESC
                """)

                rows = cursor.fetchall()
                columns = ['id', 'snapshot_type', 'deployment_id', 'created_at', 'description']

                snapshots = []
                for row in rows:
                    snapshot = dict(zip(columns, row))
                    snapshot['created_at_human'] = datetime.fromtimestamp(snapshot['created_at']).strftime('%Y-%m-%d %H:%M:%S')
                    snapshots.append(snapshot)

                return {
                    'success': True,
                    'snapshots': snapshots,
                    'total_snapshots': len(snapshots)
                }

        except Exception as e:
            logger.error(f"Failed to get snapshots: {e}")
            return {'success': False, 'error': str(e)}

    async def _cleanup_deployment_artifacts(self, deployment_id: str) -> Dict[str, Any]:
        """Clean up artifacts from a failed deployment."""
        actions = []

        try:
            # Remove deployment directory if it exists
            deployment_base = Path("/home/pi/docker-deployments")
            deployment_dirs = list(deployment_base.glob(f"*{deployment_id}*"))

            for deployment_dir in deployment_dirs:
                if deployment_dir.exists():
                    shutil.rmtree(deployment_dir)
                    actions.append(f'Removed deployment directory {deployment_dir}')

            return {'success': True, 'actions': actions}

        except Exception as e:
            logger.error(f"Artifact cleanup failed: {e}")
            return {'success': False, 'error': str(e), 'actions': actions}

    async def _get_running_containers(self) -> Dict[str, Any]:
        """Get information about running containers."""
        try:
            result = await self._run_command(['docker', 'ps', '--format', 'json'])
            if result['success']:
                containers = []
                for line in result['stdout'].split('\n'):
                    if line.strip():
                        try:
                            containers.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                return {'containers': containers}
        except Exception as e:
            logger.error(f"Failed to get running containers: {e}")

        return {}

    async def _get_system_info_snapshot(self) -> Dict[str, Any]:
        """Get system information for snapshot."""
        try:
            info = {}

            # System info commands
            info_commands = [
                (['uptime'], 'uptime'),
                (['free', '-h'], 'memory'),
                (['df', '-h'], 'disk'),
                (['systemctl', 'list-units', '--failed'], 'failed_services')
            ]

            for cmd, key in info_commands:
                result = await self._run_command(cmd, ignore_errors=True)
                if result['success']:
                    info[key] = result['stdout']

            return info

        except Exception as e:
            logger.error(f"Failed to get system info snapshot: {e}")
            return {}

    async def _log_recovery_action(self, deployment_id: str, error_type: str, recovery_strategy: str, result: Dict[str, Any]) -> None:
        """Log a recovery action to the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO recovery_actions (deployment_id, error_type, recovery_strategy, status, start_time, end_time, result)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    deployment_id,
                    error_type,
                    recovery_strategy,
                    'success' if result.get('success') else 'failed',
                    result.get('start_time', time.time()),
                    result.get('end_time', time.time()),
                    json.dumps(result)
                ))
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to log recovery action: {e}")

    async def _run_command(self, cmd: List[str], ignore_errors: bool = False) -> Dict[str, Any]:
        """Run a system command asynchronously."""
        try:
            logger.debug(f"Running command: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            result = {
                "success": process.returncode == 0 or ignore_errors,
                "returncode": process.returncode,
                "stdout": stdout.decode('utf-8', errors='ignore').strip(),
                "stderr": stderr.decode('utf-8', errors='ignore').strip()
            }

            if not result["success"] and not ignore_errors:
                logger.error(f"Command failed: {' '.join(cmd)}, Error: {result['stderr']}")

            return result

        except Exception as e:
            logger.error(f"Exception running command {' '.join(cmd)}: {e}")
            return {"success": False, "error": str(e), "stdout": "", "stderr": ""}