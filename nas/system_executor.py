"""Secure system command execution framework."""

import subprocess
import logging
import shlex
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re


logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Supported command types for validation."""
    SNAPRAID = "snapraid"
    SMARTCTL = "smartctl"
    FILESYSTEM = "filesystem"
    MOUNT = "mount"
    BLKID = "blkid"


class SystemCommandExecutor:
    """Secure system command executor with privilege escalation and validation."""
    
    # Allowed commands and their argument patterns
    ALLOWED_COMMANDS = {
        CommandType.SNAPRAID: {
            'binary': 'snapraid',
            'allowed_args': {
                'status', 'sync', 'scrub', 'diff', 'fix', 'check',
                '-c', '--conf', '-v', '--verbose', '-q', '--quiet',
                '-p', '--percentage', '-d', '--filter-disk'
            },
            'requires_sudo': True
        },
        CommandType.SMARTCTL: {
            'binary': 'smartctl',
            'allowed_args': {
                '-H', '--health', '-a', '--all', '-i', '--info',
                '-t', '--test', 'short', 'long', 'conveyance',
                '-l', '--log', 'error', 'selftest', 'selective',
                '-A', '--attributes', '-c', '--capabilities'
            },
            'requires_sudo': True
        },
        CommandType.FILESYSTEM: {
            'binary': 'mkfs.ext4',
            'allowed_args': {
                '-F', '-L', '--label', '-U', '--uuid', '-v', '--verbose'
            },
            'requires_sudo': True
        },
        CommandType.MOUNT: {
            'binary': 'mount',
            'allowed_args': {
                '-t', '--types', '-o', '--options', '-v', '--verbose',
                'umount', '-f', '--force', '-l', '--lazy'
            },
            'requires_sudo': True
        },
        CommandType.BLKID: {
            'binary': 'blkid',
            'allowed_args': {
                '-s', '--match-tag', '-o', '--output', 'value', 'device',
                '-U', '--uuid', '-L', '--label'
            },
            'requires_sudo': False
        }
    }
    
    # Device path validation pattern
    DEVICE_PATH_PATTERN = re.compile(r'^/dev/[a-zA-Z0-9]+[0-9]*$')
    
    # File path validation pattern (for config files, mount points)
    FILE_PATH_PATTERN = re.compile(r'^/[a-zA-Z0-9/_.-]+$')
    
    def __init__(self, dry_run: bool = False):
        """
        Initialize the SystemCommandExecutor.
        
        Args:
            dry_run: If True, commands will be logged but not executed
        """
        self.dry_run = dry_run
        self._command_history: List[Dict] = []
    
    def execute_snapraid_command(self, 
                                operation: str, 
                                config_path: Optional[str] = None,
                                additional_args: Optional[List[str]] = None) -> Tuple[bool, str, str]:
        """
        Execute a SnapRAID command safely.
        
        Args:
            operation: SnapRAID operation (status, sync, scrub, etc.)
            config_path: Path to SnapRAID configuration file
            additional_args: Additional arguments for the command
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        cmd_args = [operation]
        
        if config_path:
            if not self._validate_file_path(config_path):
                raise ValueError(f"Invalid config path: {config_path}")
            cmd_args.extend(['-c', config_path])
        
        if additional_args:
            cmd_args.extend(additional_args)
        
        return self._execute_command(CommandType.SNAPRAID, cmd_args)
    
    def execute_smart_command(self, 
                             device_path: str,
                             operation: str,
                             test_type: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Execute a SMART command safely.
        
        Args:
            device_path: Device path (e.g., '/dev/sdb')
            operation: SMART operation (-H, -a, -t, etc.)
            test_type: Test type for -t operation (short, long, etc.)
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not self._validate_device_path(device_path):
            raise ValueError(f"Invalid device path: {device_path}")
        
        cmd_args = [operation]
        
        if test_type and operation == '-t':
            if test_type not in {'short', 'long', 'conveyance'}:
                raise ValueError(f"Invalid test type: {test_type}")
            cmd_args.append(test_type)
        
        cmd_args.append(device_path)
        
        return self._execute_command(CommandType.SMARTCTL, cmd_args)
    
    def execute_filesystem_command(self, 
                                  device_path: str,
                                  filesystem_type: str = 'ext4',
                                  label: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Execute a filesystem creation command safely.
        
        Args:
            device_path: Device path to format
            filesystem_type: Filesystem type (currently only ext4 supported)
            label: Optional filesystem label
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        if filesystem_type != 'ext4':
            raise ValueError(f"Unsupported filesystem type: {filesystem_type}")
        
        if not self._validate_device_path(device_path):
            raise ValueError(f"Invalid device path: {device_path}")
        
        cmd_args = ['-F']  # Force creation
        
        if label:
            if not self._validate_label(label):
                raise ValueError(f"Invalid label: {label}")
            cmd_args.extend(['-L', label])
        
        cmd_args.append(device_path)
        
        return self._execute_command(CommandType.FILESYSTEM, cmd_args)
    
    def execute_mount_command(self, 
                             device_path: str,
                             mount_point: str,
                             filesystem_type: Optional[str] = None,
                             options: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Execute a mount command safely.
        
        Args:
            device_path: Device path to mount
            mount_point: Mount point directory
            filesystem_type: Filesystem type
            options: Mount options
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not self._validate_device_path(device_path):
            raise ValueError(f"Invalid device path: {device_path}")
        
        if not self._validate_file_path(mount_point):
            raise ValueError(f"Invalid mount point: {mount_point}")
        
        cmd_args = []
        
        if filesystem_type:
            if not self._validate_filesystem_type(filesystem_type):
                raise ValueError(f"Invalid filesystem type: {filesystem_type}")
            cmd_args.extend(['-t', filesystem_type])
        
        if options:
            if not self._validate_mount_options(options):
                raise ValueError(f"Invalid mount options: {options}")
            cmd_args.extend(['-o', options])
        
        cmd_args.extend([device_path, mount_point])
        
        return self._execute_command(CommandType.MOUNT, cmd_args)
    
    def execute_blkid_command(self, 
                             device_path: Optional[str] = None,
                             uuid: Optional[str] = None,
                             output_format: str = 'value') -> Tuple[bool, str, str]:
        """
        Execute a blkid command safely.
        
        Args:
            device_path: Device path to query
            uuid: UUID to search for
            output_format: Output format (value, device)
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        cmd_args = []
        
        if output_format in {'value', 'device'}:
            cmd_args.extend(['-o', output_format])
        
        if uuid:
            if not self._validate_uuid(uuid):
                raise ValueError(f"Invalid UUID format: {uuid}")
            cmd_args.extend(['-U', uuid])
        elif device_path:
            if not self._validate_device_path(device_path):
                raise ValueError(f"Invalid device path: {device_path}")
            cmd_args.append(device_path)
        
        return self._execute_command(CommandType.BLKID, cmd_args)
    
    def _execute_command(self, 
                        command_type: CommandType, 
                        args: List[str]) -> Tuple[bool, str, str]:
        """
        Execute a validated command with proper logging and error handling.
        
        Args:
            command_type: Type of command to execute
            args: Command arguments
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        command_config = self.ALLOWED_COMMANDS[command_type]
        binary = command_config['binary']
        requires_sudo = command_config['requires_sudo']
        
        # Validate all arguments
        self._validate_command_args(command_type, args)
        
        # Build the full command
        if requires_sudo:
            full_command = ['sudo', binary] + args
        else:
            full_command = [binary] + args
        
        # Log the command
        command_str = ' '.join(shlex.quote(arg) for arg in full_command)
        logger.info(f"Executing command: {command_str}")
        
        # Record in history
        self._command_history.append({
            'command': command_str,
            'type': command_type.value,
            'dry_run': self.dry_run
        })
        
        if self.dry_run:
            logger.info("DRY RUN: Command would be executed")
            return True, "DRY RUN", ""
        
        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                check=False
            )
            
            success = result.returncode == 0
            
            if success:
                logger.info(f"Command executed successfully: {command_str}")
            else:
                logger.error(f"Command failed with return code {result.returncode}: {command_str}")
                logger.error(f"Error output: {result.stderr}")
            
            return success, result.stdout, result.stderr
        
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out: {command_str}")
            return False, "", "Command timed out"
        
        except Exception as e:
            logger.error(f"Error executing command {command_str}: {e}")
            return False, "", str(e)
    
    def _validate_command_args(self, command_type: CommandType, args: List[str]) -> None:
        """
        Validate command arguments against allowed patterns.
        
        Args:
            command_type: Type of command
            args: Arguments to validate
            
        Raises:
            ValueError: If any argument is not allowed
        """
        allowed_args = self.ALLOWED_COMMANDS[command_type]['allowed_args']
        
        for arg in args:
            # Skip device paths and file paths - they're validated separately
            if (self.DEVICE_PATH_PATTERN.match(arg) or 
                self.FILE_PATH_PATTERN.match(arg) or
                arg in allowed_args):
                continue
            
            # Check if it's a valid option value (following an option flag)
            if len(args) > 1:
                prev_arg_idx = args.index(arg) - 1
                if prev_arg_idx >= 0:
                    prev_arg = args[prev_arg_idx]
                    if prev_arg in {'-c', '--conf', '-L', '--label', '-t', '--types', '-o', '--options'}:
                        continue
            
            raise ValueError(f"Argument not allowed for {command_type.value}: {arg}")
    
    def _validate_device_path(self, path: str) -> bool:
        """Validate device path format."""
        return bool(self.DEVICE_PATH_PATTERN.match(path))
    
    def _validate_file_path(self, path: str) -> bool:
        """Validate file path format."""
        return bool(self.FILE_PATH_PATTERN.match(path))
    
    def _validate_label(self, label: str) -> bool:
        """Validate filesystem label."""
        # Labels should be alphanumeric with limited special characters
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', label)) and len(label) <= 16
    
    def _validate_filesystem_type(self, fs_type: str) -> bool:
        """Validate filesystem type."""
        allowed_types = {'ext4', 'ext3', 'ext2', 'xfs', 'btrfs', 'ntfs', 'vfat'}
        return fs_type in allowed_types
    
    def _validate_mount_options(self, options: str) -> bool:
        """Validate mount options."""
        # Basic validation for common mount options
        allowed_options = {
            'rw', 'ro', 'defaults', 'noatime', 'relatime', 'user', 'nouser',
            'auto', 'noauto', 'exec', 'noexec', 'suid', 'nosuid'
        }
        
        option_list = options.split(',')
        for option in option_list:
            option = option.strip()
            if option not in allowed_options:
                return False
        
        return True
    
    def _validate_uuid(self, uuid: str) -> bool:
        """Validate UUID format."""
        uuid_pattern = re.compile(
            r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        )
        return bool(uuid_pattern.match(uuid))
    
    def get_command_history(self) -> List[Dict]:
        """Get the history of executed commands."""
        return self._command_history.copy()
    
    def clear_command_history(self) -> None:
        """Clear the command history."""
        self._command_history.clear()
    
    def execute_command(self, command: List[str]) -> Tuple[bool, str, str]:
        """
        Execute a generic command with basic validation.
        
        Args:
            command: List of command parts (binary and arguments)
            
        Returns:
            Tuple of (success, stdout, stderr)
        """
        if not command:
            raise ValueError("Command cannot be empty")
        
        binary = command[0]
        args = command[1:] if len(command) > 1 else []
        
        # Basic validation - only allow known safe binaries
        safe_binaries = {'mergerfs', 'umount', 'mount', 'mkdir', 'rmdir'}
        if binary not in safe_binaries:
            raise ValueError(f"Binary not allowed: {binary}")
        
        # Build the full command with sudo for mount operations
        if binary in {'mergerfs', 'umount', 'mount'}:
            full_command = ['sudo'] + command
        else:
            full_command = command
        
        # Log the command
        command_str = ' '.join(shlex.quote(arg) for arg in full_command)
        logger.info(f"Executing generic command: {command_str}")
        
        # Record in history
        self._command_history.append({
            'command': command_str,
            'type': 'generic',
            'dry_run': self.dry_run
        })
        
        if self.dry_run:
            logger.info("DRY RUN: Command would be executed")
            return True, "DRY RUN", ""
        
        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                check=False
            )
            
            success = result.returncode == 0
            
            if success:
                logger.info(f"Generic command executed successfully: {command_str}")
            else:
                logger.error(f"Generic command failed with return code {result.returncode}: {command_str}")
                logger.error(f"Error output: {result.stderr}")
            
            return success, result.stdout, result.stderr
        
        except subprocess.TimeoutExpired:
            logger.error(f"Generic command timed out: {command_str}")
            return False, "", "Command timed out"
        
        except Exception as e:
            logger.error(f"Error executing generic command {command_str}: {e}")
            return False, "", str(e)