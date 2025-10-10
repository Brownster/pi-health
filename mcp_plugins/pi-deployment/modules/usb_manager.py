"""
USB Manager Module
Intelligent USB device detection, mounting, and management for Pi systems.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)


class USBDevice:
    """Represents a USB storage device."""

    def __init__(self, device_path: str, info: Dict[str, Any]):
        self.device_path = device_path
        self.label = info.get('label', '')
        self.uuid = info.get('uuid', '')
        self.fstype = info.get('fstype', 'unknown')
        self.size = info.get('size', 0)
        self.model = info.get('model', '')
        self.vendor = info.get('vendor', '')
        self.is_mounted = info.get('is_mounted', False)
        self.mount_point = info.get('mount_point', '')
        self.is_system = info.get('is_system', False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'device_path': self.device_path,
            'label': self.label,
            'uuid': self.uuid,
            'fstype': self.fstype,
            'size': self.size,
            'model': self.model,
            'vendor': self.vendor,
            'is_mounted': self.is_mounted,
            'mount_point': self.mount_point,
            'is_system': self.is_system
        }


class USBManager:
    """Intelligent USB device manager for Pi systems."""

    def __init__(self):
        self.mount_base = Path("/mnt")
        self.auto_mount_base = Path("/mnt/usb-auto")
        self.fstab_backup = Path("/etc/fstab.pi-health-backup")

        # Create auto-mount directory
        self.auto_mount_base.mkdir(exist_ok=True, mode=0o755)

    async def detect_devices(self) -> List[Dict[str, Any]]:
        """Detect all USB storage devices."""
        logger.info("Detecting USB storage devices...")

        devices = []

        try:
            # Use lsblk to get detailed device information
            result = await self._run_command([
                'lsblk', '-J', '-o',
                'NAME,KNAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINT,MODEL,VENDOR,TYPE,HOTPLUG'
            ])

            if result['success']:
                lsblk_data = json.loads(result['stdout'])

                for device in lsblk_data.get('blockdevices', []):
                    await self._process_device(device, devices)

        except Exception as e:
            logger.error(f"Error detecting USB devices: {e}")

        logger.info(f"Found {len(devices)} USB storage devices")
        return devices

    async def _process_device(self, device: Dict[str, Any], devices: List[Dict[str, Any]]) -> None:
        """Process a single device from lsblk output."""
        # Only process USB devices (hotplug = True) that are disks or parts
        if not device.get('hotplug') or device.get('type') not in ['disk', 'part']:
            return

        # Skip if it's likely a system device
        name = device.get('name', '')
        if any(skip in name for skip in ['loop', 'ram', 'sr', 'mmcblk0']):
            return

        device_path = f"/dev/{device.get('kname', name)}"

        # Get additional device info
        device_info = await self._get_device_details(device_path)

        usb_device = USBDevice(device_path, {
            'label': device.get('label', ''),
            'uuid': device.get('uuid', ''),
            'fstype': device.get('fstype', 'unknown'),
            'size': self._parse_size(device.get('size', '0')),
            'model': device.get('model', '').strip(),
            'vendor': device.get('vendor', '').strip(),
            'is_mounted': bool(device.get('mountpoint')),
            'mount_point': device.get('mountpoint', ''),
            'is_system': await self._is_system_device(device_path),
            **device_info
        })

        devices.append(usb_device.to_dict())

        # Process children (partitions)
        for child in device.get('children', []):
            await self._process_device(child, devices)

    async def _get_device_details(self, device_path: str) -> Dict[str, Any]:
        """Get additional device details using various tools."""
        details = {}

        try:
            # Get filesystem details with blkid
            result = await self._run_command(['blkid', '-p', device_path])
            if result['success']:
                blkid_info = self._parse_blkid_output(result['stdout'])
                details.update(blkid_info)

        except Exception as e:
            logger.debug(f"Could not get blkid info for {device_path}: {e}")

        return details

    def _parse_blkid_output(self, output: str) -> Dict[str, Any]:
        """Parse blkid output for device information."""
        info = {}

        # Parse blkid output (format: KEY="VALUE")
        for match in re.finditer(r'(\w+)="([^"]*)"', output):
            key, value = match.groups()
            if key.lower() == 'type':
                info['fstype'] = value
            elif key.lower() == 'uuid':
                info['uuid'] = value
            elif key.lower() == 'label':
                info['label'] = value

        return info

    def _parse_size(self, size_str: str) -> int:
        """Parse size string to bytes."""
        if not size_str:
            return 0

        # Convert size strings like "1.2T", "500G", "1024M" to bytes
        size_str = size_str.upper().strip()

        multipliers = {
            'B': 1,
            'K': 1024,
            'M': 1024**2,
            'G': 1024**3,
            'T': 1024**4
        }

        for suffix, multiplier in multipliers.items():
            if size_str.endswith(suffix):
                try:
                    number = float(size_str[:-1])
                    return int(number * multiplier)
                except ValueError:
                    pass

        try:
            return int(size_str)
        except ValueError:
            return 0

    async def _is_system_device(self, device_path: str) -> bool:
        """Check if device is likely a system device."""
        # Check if device contains critical system files
        try:
            result = await self._run_command(['mount', device_path, '/tmp/pi-health-check'], ignore_errors=True)
            if result['success']:
                # Check for system directories
                system_paths = ['/tmp/pi-health-check/boot', '/tmp/pi-health-check/etc', '/tmp/pi-health-check/usr']
                is_system = any(Path(p).exists() for p in system_paths)

                # Unmount
                await self._run_command(['umount', '/tmp/pi-health-check'], ignore_errors=True)
                return is_system

        except Exception:
            pass

        return False

    async def smart_mount(self, device: str, mount_point: str = None, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Intelligently mount a USB device with optimal settings."""
        logger.info(f"Smart mounting device: {device}")

        if options is None:
            options = {}

        try:
            # Get device info
            devices = await self.detect_devices()
            device_info = next((d for d in devices if d['device_path'] == device), None)

            if not device_info:
                return {"success": False, "error": f"Device {device} not found"}

            if device_info['is_mounted']:
                return {
                    "success": True,
                    "message": f"Device already mounted at {device_info['mount_point']}",
                    "mount_point": device_info['mount_point']
                }

            # Determine optimal mount point
            if not mount_point:
                mount_point = await self._determine_mount_point(device_info)

            # Create mount point
            mount_path = Path(mount_point)
            mount_path.mkdir(parents=True, exist_ok=True)

            # Determine optimal mount options
            mount_options = await self._get_optimal_mount_options(device_info, options)

            # Mount the device
            mount_cmd = ['mount']
            if mount_options:
                mount_cmd.extend(['-o', mount_options])
            mount_cmd.extend([device, mount_point])

            result = await self._run_command(mount_cmd)

            if result['success']:
                # Set appropriate permissions
                await self._set_mount_permissions(mount_point, device_info)

                # Add to persistent mounts if requested
                if options.get('persistent', False):
                    await self._add_to_fstab(device, mount_point, device_info['fstype'], mount_options)

                logger.info(f"Successfully mounted {device} at {mount_point}")
                return {
                    "success": True,
                    "mount_point": mount_point,
                    "options": mount_options,
                    "device_info": device_info
                }
            else:
                return {"success": False, "error": f"Mount failed: {result['stderr']}"}

        except Exception as e:
            logger.error(f"Smart mount failed for {device}: {e}")
            return {"success": False, "error": str(e)}

    async def _determine_mount_point(self, device_info: Dict[str, Any]) -> str:
        """Determine optimal mount point for device."""
        # Prefer label-based naming
        if device_info.get('label'):
            safe_label = re.sub(r'[^a-zA-Z0-9_-]', '_', device_info['label'])
            mount_point = self.auto_mount_base / safe_label
        elif device_info.get('uuid'):
            # Use UUID if no label
            mount_point = self.auto_mount_base / device_info['uuid'][:8]
        else:
            # Fallback to device name
            device_name = Path(device_info['device_path']).name
            mount_point = self.auto_mount_base / device_name

        # Ensure uniqueness
        counter = 1
        original_mount_point = mount_point
        while mount_point.exists() and any(mount_point.iterdir()):
            mount_point = Path(f"{original_mount_point}_{counter}")
            counter += 1

        return str(mount_point)

    async def _get_optimal_mount_options(self, device_info: Dict[str, Any], user_options: Dict[str, Any]) -> str:
        """Get optimal mount options based on filesystem type and usage."""
        fstype = device_info.get('fstype', 'auto')
        options = []

        # Base options for all filesystems
        options.extend(['rw', 'noatime'])

        # Filesystem-specific optimizations
        if fstype in ['ext4', 'ext3', 'ext2']:
            options.extend(['data=writeback', 'nobarrier'])
            if user_options.get('optimize_for_media', True):
                options.append('commit=60')  # Reduce commit frequency for media
        elif fstype in ['vfat', 'fat32']:
            options.extend(['utf8', 'umask=000'])
        elif fstype == 'ntfs':
            options.extend(['utf8', 'umask=000', 'nls=utf8'])
        elif fstype in ['exfat']:
            options.extend(['utf8', 'umask=000'])

        # Add user-specified options
        if user_options.get('read_only', False):
            options = [opt for opt in options if opt != 'rw'] + ['ro']

        if user_options.get('no_exec', False):
            options.append('noexec')

        if user_options.get('additional_options'):
            options.extend(user_options['additional_options'])

        return ','.join(options)

    async def _set_mount_permissions(self, mount_point: str, device_info: Dict[str, Any]) -> None:
        """Set appropriate permissions on mounted filesystem."""
        try:
            # For media servers, we want wide access
            if device_info.get('fstype') in ['ext4', 'ext3', 'ext2']:
                # Create standard media directories with proper permissions
                media_dirs = ['Movies', 'TV', 'Music', 'Books', 'Downloads']
                for media_dir in media_dirs:
                    media_path = Path(mount_point) / media_dir
                    media_path.mkdir(exist_ok=True)
                    await self._run_command(['chmod', '755', str(media_path)], ignore_errors=True)

            # Set ownership to current user if possible
            current_user = os.getenv('USER', 'pi')
            await self._run_command(['chown', '-R', f'{current_user}:{current_user}', mount_point], ignore_errors=True)

        except Exception as e:
            logger.warning(f"Could not set permissions on {mount_point}: {e}")

    async def _add_to_fstab(self, device: str, mount_point: str, fstype: str, options: str) -> None:
        """Add mount to /etc/fstab for persistence."""
        try:
            # Backup fstab if not already done
            if not self.fstab_backup.exists():
                await self._run_command(['cp', '/etc/fstab', str(self.fstab_backup)])

            # Get device UUID for more reliable mounting
            result = await self._run_command(['blkid', '-s', 'UUID', '-o', 'value', device])
            if result['success'] and result['stdout'].strip():
                device_identifier = f"UUID={result['stdout'].strip()}"
            else:
                device_identifier = device

            # Add entry to fstab
            fstab_entry = f"{device_identifier} {mount_point} {fstype} {options} 0 2\n"

            with open('/etc/fstab', 'a') as f:
                f.write(f"# Pi-Health auto-added mount\n")
                f.write(fstab_entry)

            logger.info(f"Added {device} to fstab for persistent mounting")

        except Exception as e:
            logger.error(f"Could not add {device} to fstab: {e}")

    async def auto_setup(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Automatically setup USB storage based on configuration."""
        logger.info("Starting automatic USB setup...")

        results = {
            "mounted_devices": [],
            "failed_devices": [],
            "setup_actions": []
        }

        try:
            devices = await self.detect_devices()

            # Filter devices based on config
            target_devices = []

            if config.get('auto_mount_all', False):
                target_devices = [d for d in devices if not d['is_mounted'] and not d['is_system']]
            elif config.get('device_filters'):
                target_devices = await self._filter_devices(devices, config['device_filters'])
            elif config.get('specific_devices'):
                target_devices = [d for d in devices if d['device_path'] in config['specific_devices']]

            # Mount each target device
            for device in target_devices:
                mount_options = config.get('mount_options', {})
                mount_result = await self.smart_mount(device['device_path'], options=mount_options)

                if mount_result['success']:
                    results["mounted_devices"].append({
                        "device": device['device_path'],
                        "mount_point": mount_result['mount_point'],
                        "device_info": device
                    })
                    results["setup_actions"].append(f"Mounted {device['device_path']} at {mount_result['mount_point']}")
                else:
                    results["failed_devices"].append({
                        "device": device['device_path'],
                        "error": mount_result['error']
                    })

            # Create symbolic links if requested
            if config.get('create_media_links', False):
                await self._create_media_links(results["mounted_devices"])
                results["setup_actions"].append("Created media directory symbolic links")

            return {"success": True, "results": results}

        except Exception as e:
            logger.error(f"Auto USB setup failed: {e}")
            return {"success": False, "error": str(e), "results": results}

    async def _filter_devices(self, devices: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filter devices based on criteria."""
        filtered = []

        for device in devices:
            if device['is_mounted'] or device['is_system']:
                continue

            # Size filters
            if 'min_size' in filters and device['size'] < self._parse_size(filters['min_size']):
                continue
            if 'max_size' in filters and device['size'] > self._parse_size(filters['max_size']):
                continue

            # Filesystem filters
            if 'allowed_filesystems' in filters and device['fstype'] not in filters['allowed_filesystems']:
                continue

            # Label filters
            if 'label_patterns' in filters:
                if not any(re.search(pattern, device.get('label', ''), re.IGNORECASE)
                          for pattern in filters['label_patterns']):
                    continue

            filtered.append(device)

        return filtered

    async def _create_media_links(self, mounted_devices: List[Dict[str, Any]]) -> None:
        """Create convenient symbolic links to media directories."""
        try:
            media_base = Path('/media')
            media_base.mkdir(exist_ok=True)

            for mount_info in mounted_devices:
                mount_point = Path(mount_info['mount_point'])
                device_info = mount_info['device_info']

                # Create link name
                link_name = device_info.get('label', Path(device_info['device_path']).name)
                link_path = media_base / link_name

                # Remove existing link if present
                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()

                # Create new link
                link_path.symlink_to(mount_point)

                logger.info(f"Created media link: {link_path} -> {mount_point}")

        except Exception as e:
            logger.error(f"Could not create media links: {e}")

    async def get_mount_status(self) -> Dict[str, Any]:
        """Get comprehensive status of all mounted USB devices."""
        try:
            devices = await self.detect_devices()
            mounted_devices = [d for d in devices if d['is_mounted']]

            # Get disk usage for mounted devices
            for device in mounted_devices:
                if device['mount_point']:
                    usage = await self._get_disk_usage(device['mount_point'])
                    device['disk_usage'] = usage

            return {
                "success": True,
                "total_devices": len(devices),
                "mounted_devices": len(mounted_devices),
                "devices": mounted_devices,
                "mount_points": [d['mount_point'] for d in mounted_devices]
            }

        except Exception as e:
            logger.error(f"Error getting mount status: {e}")
            return {"success": False, "error": str(e)}

    async def _get_disk_usage(self, path: str) -> Dict[str, Any]:
        """Get disk usage statistics for a path."""
        try:
            result = await self._run_command(['df', '-h', path])
            if result['success']:
                lines = result['stdout'].strip().split('\n')
                if len(lines) >= 2:
                    fields = lines[1].split()
                    return {
                        "total": fields[1],
                        "used": fields[2],
                        "available": fields[3],
                        "use_percent": fields[4]
                    }
        except Exception:
            pass

        return {"total": "Unknown", "used": "Unknown", "available": "Unknown", "use_percent": "Unknown"}

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