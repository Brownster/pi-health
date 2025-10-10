"""
Pi Optimizer Module
Intelligent Pi system optimization for performance, stability, and workload-specific tuning.
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
import subprocess

logger = logging.getLogger(__name__)


class PiOptimizer:
    """Intelligent Pi system optimizer for performance and stability."""

    def __init__(self):
        self.config_backup_dir = Path("/etc/pi-health-backups")
        self.config_backup_dir.mkdir(exist_ok=True, mode=0o755)

        # Pi model detection
        self.pi_model = None
        self.pi_memory = None
        self.pi_revision = None

        # Optimization profiles
        self.optimization_profiles = {
            'media_server': {
                'name': 'Media Server Optimization',
                'description': 'Optimized for media streaming and transcoding',
                'optimizations': [
                    'gpu_memory_split_256',
                    'increase_swap',
                    'network_optimization',
                    'storage_optimization',
                    'cpu_governor_ondemand',
                    'disable_unnecessary_services'
                ]
            },
            'low_power': {
                'name': 'Low Power Optimization',
                'description': 'Optimized for minimal power consumption',
                'optimizations': [
                    'cpu_governor_powersave',
                    'disable_hdmi',
                    'disable_wifi_power_save',
                    'reduce_gpu_memory',
                    'disable_unnecessary_services'
                ]
            },
            'performance': {
                'name': 'Maximum Performance',
                'description': 'Optimized for maximum computational performance',
                'optimizations': [
                    'overclock_modest',
                    'cpu_governor_performance',
                    'increase_gpu_memory',
                    'network_optimization',
                    'storage_optimization',
                    'increase_swap'
                ]
            },
            'development': {
                'name': 'Development Environment',
                'description': 'Optimized for development work and compilation',
                'optimizations': [
                    'increase_swap',
                    'cpu_governor_ondemand',
                    'network_optimization',
                    'storage_optimization',
                    'development_tools'
                ]
            },
            'server': {
                'name': 'Server Optimization',
                'description': 'Optimized for headless server operation',
                'optimizations': [
                    'disable_unnecessary_services',
                    'network_optimization',
                    'storage_optimization',
                    'security_hardening',
                    'log_optimization'
                ]
            }
        }

    async def optimize_system(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize Pi system based on configuration and workload."""
        logger.info("Starting Pi system optimization...")

        optimization_result = {
            'profile': config.get('profile', 'auto'),
            'applied_optimizations': [],
            'failed_optimizations': [],
            'warnings': [],
            'system_info': {}
        }

        try:
            # Detect Pi model and capabilities
            system_info = await self._detect_pi_system()
            optimization_result['system_info'] = system_info

            # Determine optimization profile
            if config.get('profile') == 'auto':
                profile = await self._determine_optimal_profile(config, system_info)
            else:
                profile = config.get('profile', 'media_server')

            if profile not in self.optimization_profiles:
                return {"success": False, "error": f"Unknown optimization profile: {profile}"}

            optimization_result['profile'] = profile
            profile_config = self.optimization_profiles[profile]

            # Create system backup before optimization
            backup_result = await self._create_system_backup()
            if not backup_result['success']:
                optimization_result['warnings'].append("Could not create system backup")

            # Apply optimizations
            for optimization in profile_config['optimizations']:
                try:
                    result = await self._apply_optimization(optimization, config, system_info)
                    if result['success']:
                        optimization_result['applied_optimizations'].append({
                            'optimization': optimization,
                            'description': result.get('description', ''),
                            'changes': result.get('changes', [])
                        })
                    else:
                        optimization_result['failed_optimizations'].append({
                            'optimization': optimization,
                            'error': result.get('error', 'Unknown error')
                        })

                except Exception as e:
                    logger.error(f"Failed to apply optimization {optimization}: {e}")
                    optimization_result['failed_optimizations'].append({
                        'optimization': optimization,
                        'error': str(e)
                    })

            # Apply custom optimizations if specified
            custom_optimizations = config.get('custom_optimizations', [])
            for custom_opt in custom_optimizations:
                try:
                    result = await self._apply_custom_optimization(custom_opt, system_info)
                    if result['success']:
                        optimization_result['applied_optimizations'].append(result)
                    else:
                        optimization_result['failed_optimizations'].append(result)
                except Exception as e:
                    optimization_result['failed_optimizations'].append({
                        'optimization': custom_opt,
                        'error': str(e)
                    })

            # Post-optimization validation
            validation_result = await self._validate_optimizations()
            optimization_result['validation'] = validation_result

            success = len(optimization_result['failed_optimizations']) == 0
            return {"success": success, "result": optimization_result}

        except Exception as e:
            logger.error(f"System optimization failed: {e}")
            return {"success": False, "error": str(e), "result": optimization_result}

    async def _detect_pi_system(self) -> Dict[str, Any]:
        """Detect Pi model, revision, and capabilities."""
        try:
            system_info = {
                'model': 'unknown',
                'revision': 'unknown',
                'memory': 0,
                'cpu_count': 1,
                'architecture': 'unknown',
                'gpio_available': False,
                'camera_available': False,
                'hardware_acceleration': []
            }

            # Read /proc/cpuinfo for Pi information
            cpuinfo_result = await self._run_command(['cat', '/proc/cpuinfo'])
            if cpuinfo_result['success']:
                cpuinfo = cpuinfo_result['stdout']

                # Extract model information
                model_match = re.search(r'Model\s*:\s*(.+)', cpuinfo)
                if model_match:
                    system_info['model'] = model_match.group(1).strip()

                # Extract revision
                revision_match = re.search(r'Revision\s*:\s*(\w+)', cpuinfo)
                if revision_match:
                    system_info['revision'] = revision_match.group(1).strip()

                # Count CPU cores
                processor_count = len(re.findall(r'processor\s*:', cpuinfo))
                system_info['cpu_count'] = processor_count

                # Get architecture
                arch_result = await self._run_command(['uname', '-m'])
                if arch_result['success']:
                    system_info['architecture'] = arch_result['stdout'].strip()

            # Get memory information
            meminfo_result = await self._run_command(['cat', '/proc/meminfo'])
            if meminfo_result['success']:
                mem_match = re.search(r'MemTotal:\s*(\d+)\s*kB', meminfo_result['stdout'])
                if mem_match:
                    system_info['memory'] = int(mem_match.group(1)) * 1024  # Convert to bytes

            # Check for GPU memory split
            gpu_mem_result = await self._run_command(['vcgencmd', 'get_mem', 'gpu'], ignore_errors=True)
            if gpu_mem_result['success']:
                gpu_mem_match = re.search(r'gpu=(\d+)M', gpu_mem_result['stdout'])
                if gpu_mem_match:
                    system_info['gpu_memory'] = int(gpu_mem_match.group(1))

            # Check for hardware acceleration capabilities
            if 'Pi 4' in system_info['model']:
                system_info['hardware_acceleration'] = ['h264', 'hevc', 'vc1']
            elif 'Pi 3' in system_info['model']:
                system_info['hardware_acceleration'] = ['h264']

            # Check GPIO availability
            gpio_result = await self._run_command(['ls', '/dev/gpiomem'], ignore_errors=True)
            system_info['gpio_available'] = gpio_result['success']

            # Check camera availability
            camera_result = await self._run_command(['vcgencmd', 'get_camera'], ignore_errors=True)
            if camera_result['success'] and 'detected=1' in camera_result['stdout']:
                system_info['camera_available'] = True

            logger.info(f"Detected Pi system: {system_info['model']}")
            return system_info

        except Exception as e:
            logger.error(f"Pi system detection failed: {e}")
            return {'model': 'unknown', 'error': str(e)}

    async def _determine_optimal_profile(self, config: Dict[str, Any], system_info: Dict[str, Any]) -> str:
        """Automatically determine optimal optimization profile."""
        try:
            # Check for specific workload indicators
            workload_hints = config.get('workload_hints', [])

            if any(hint in workload_hints for hint in ['media', 'plex', 'jellyfin', 'streaming']):
                return 'media_server'

            if any(hint in workload_hints for hint in ['development', 'compile', 'build', 'code']):
                return 'development'

            if any(hint in workload_hints for hint in ['server', 'headless', 'daemon', 'service']):
                return 'server'

            if any(hint in workload_hints for hint in ['battery', 'low_power', 'efficiency']):
                return 'low_power'

            if any(hint in workload_hints for hint in ['performance', 'gaming', 'compute']):
                return 'performance'

            # Default based on Pi model and memory
            memory_gb = system_info.get('memory', 0) // (1024**3)

            if 'Pi 4' in system_info.get('model', '') and memory_gb >= 4:
                return 'media_server'  # Pi 4 with 4GB+ is good for media
            elif memory_gb >= 2:
                return 'server'  # 2GB+ is good for server workloads
            else:
                return 'low_power'  # Lower memory models should conserve resources

        except Exception as e:
            logger.error(f"Could not determine optimal profile: {e}")
            return 'media_server'  # Safe default

    async def _create_system_backup(self) -> Dict[str, Any]:
        """Create backup of system configuration files."""
        try:
            import shutil
            import time

            backup_timestamp = int(time.time())
            backup_dir = self.config_backup_dir / f"backup_{backup_timestamp}"
            backup_dir.mkdir(exist_ok=True)

            # Files to backup
            backup_files = [
                '/boot/config.txt',
                '/boot/cmdline.txt',
                '/etc/fstab',
                '/etc/sysctl.conf',
                '/etc/systemd/system.conf'
            ]

            backed_up_files = []

            for file_path in backup_files:
                src_path = Path(file_path)
                if src_path.exists():
                    dest_path = backup_dir / src_path.name
                    shutil.copy2(src_path, dest_path)
                    backed_up_files.append(file_path)

            return {
                'success': True,
                'backup_dir': str(backup_dir),
                'backed_up_files': backed_up_files
            }

        except Exception as e:
            logger.error(f"System backup failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _apply_optimization(self, optimization: str, config: Dict[str, Any], system_info: Dict[str, Any]) -> Dict[str, Any]:
        """Apply specific optimization."""
        try:
            if optimization == 'gpu_memory_split_256':
                return await self._optimize_gpu_memory_split(256, system_info)

            elif optimization == 'increase_swap':
                return await self._optimize_swap_size(config.get('swap_size', 2048))

            elif optimization == 'network_optimization':
                return await self._optimize_network_performance()

            elif optimization == 'storage_optimization':
                return await self._optimize_storage_performance()

            elif optimization == 'cpu_governor_ondemand':
                return await self._set_cpu_governor('ondemand')

            elif optimization == 'cpu_governor_performance':
                return await self._set_cpu_governor('performance')

            elif optimization == 'cpu_governor_powersave':
                return await self._set_cpu_governor('powersave')

            elif optimization == 'disable_unnecessary_services':
                return await self._disable_unnecessary_services()

            elif optimization == 'disable_hdmi':
                return await self._disable_hdmi_output()

            elif optimization == 'disable_wifi_power_save':
                return await self._disable_wifi_power_save()

            elif optimization == 'reduce_gpu_memory':
                return await self._optimize_gpu_memory_split(16, system_info)

            elif optimization == 'increase_gpu_memory':
                return await self._optimize_gpu_memory_split(512, system_info)

            elif optimization == 'overclock_modest':
                return await self._apply_modest_overclock(system_info)

            elif optimization == 'security_hardening':
                return await self._apply_security_hardening()

            elif optimization == 'log_optimization':
                return await self._optimize_logging()

            elif optimization == 'development_tools':
                return await self._setup_development_tools()

            else:
                return {'success': False, 'error': f'Unknown optimization: {optimization}'}

        except Exception as e:
            logger.error(f"Optimization {optimization} failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _optimize_gpu_memory_split(self, gpu_memory: int, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize GPU memory split."""
        try:
            config_txt = Path('/boot/config.txt')
            if not config_txt.exists():
                return {'success': False, 'error': '/boot/config.txt not found'}

            # Read current config
            content = config_txt.read_text()

            # Update or add gpu_mem setting
            if re.search(r'^gpu_mem=', content, re.MULTILINE):
                content = re.sub(r'^gpu_mem=.*$', f'gpu_mem={gpu_memory}', content, flags=re.MULTILINE)
            else:
                content += f'\n# Pi-Health GPU memory optimization\ngpu_mem={gpu_memory}\n'

            # Write updated config
            config_txt.write_text(content)

            return {
                'success': True,
                'description': f'Set GPU memory split to {gpu_memory}MB',
                'changes': [f'gpu_mem={gpu_memory}'],
                'reboot_required': True
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _optimize_swap_size(self, swap_size_mb: int) -> Dict[str, Any]:
        """Optimize swap file size."""
        try:
            changes = []

            # Stop swap
            await self._run_command(['swapoff', '/swapfile'], ignore_errors=True)

            # Create new swap file
            swap_result = await self._run_command([
                'dd', 'if=/dev/zero', 'of=/swapfile',
                f'bs=1M', f'count={swap_size_mb}'
            ])

            if not swap_result['success']:
                return {'success': False, 'error': f'Failed to create swap file: {swap_result["stderr"]}'}

            # Set permissions
            await self._run_command(['chmod', '600', '/swapfile'])

            # Make swap
            mkswap_result = await self._run_command(['mkswap', '/swapfile'])
            if not mkswap_result['success']:
                return {'success': False, 'error': f'Failed to make swap: {mkswap_result["stderr"]}'}

            # Enable swap
            swapon_result = await self._run_command(['swapon', '/swapfile'])
            if not swapon_result['success']:
                return {'success': False, 'error': f'Failed to enable swap: {swapon_result["stderr"]}'}

            changes.append(f'Created {swap_size_mb}MB swap file')

            # Update fstab to make permanent
            fstab = Path('/etc/fstab')
            fstab_content = fstab.read_text()

            if '/swapfile' not in fstab_content:
                fstab_content += '\n/swapfile none swap sw 0 0\n'
                fstab.write_text(fstab_content)
                changes.append('Added swap to /etc/fstab')

            return {
                'success': True,
                'description': f'Optimized swap size to {swap_size_mb}MB',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _optimize_network_performance(self) -> Dict[str, Any]:
        """Optimize network performance settings."""
        try:
            changes = []

            # Network optimization settings
            sysctl_settings = {
                'net.core.rmem_max': '134217728',
                'net.core.wmem_max': '134217728',
                'net.ipv4.tcp_rmem': '4096 87380 134217728',
                'net.ipv4.tcp_wmem': '4096 65536 134217728',
                'net.core.netdev_max_backlog': '30000',
                'net.ipv4.tcp_congestion_control': 'bbr',
                'net.ipv4.tcp_slow_start_after_idle': '0'
            }

            # Apply settings immediately
            for setting, value in sysctl_settings.items():
                result = await self._run_command(['sysctl', '-w', f'{setting}={value}'], ignore_errors=True)
                if result['success']:
                    changes.append(f'Set {setting}={value}')

            # Make settings persistent
            sysctl_conf = Path('/etc/sysctl.d/99-pi-health-network.conf')
            with open(sysctl_conf, 'w') as f:
                f.write('# Pi-Health Network Optimizations\n')
                for setting, value in sysctl_settings.items():
                    f.write(f'{setting} = {value}\n')

            changes.append('Created persistent network configuration')

            return {
                'success': True,
                'description': 'Optimized network performance settings',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _optimize_storage_performance(self) -> Dict[str, Any]:
        """Optimize storage performance."""
        try:
            changes = []

            # Mount options optimization
            fstab = Path('/etc/fstab')
            fstab_content = fstab.read_text()

            # Add noatime to root filesystem if not present
            if 'noatime' not in fstab_content:
                # This is a simplified approach - in production, you'd parse fstab properly
                fstab_content = re.sub(
                    r'(\S+\s+/\s+ext4\s+)defaults',
                    r'\1defaults,noatime',
                    fstab_content
                )
                fstab.write_text(fstab_content)
                changes.append('Added noatime to root filesystem mount options')

            # I/O scheduler optimization
            schedulers = ['mq-deadline', 'kyber', 'none']
            for device in ['/sys/block/mmcblk0/queue/scheduler', '/sys/block/sda/queue/scheduler']:
                device_path = Path(device)
                if device_path.exists():
                    try:
                        current_scheduler = device_path.read_text().strip()
                        for scheduler in schedulers:
                            if scheduler in current_scheduler:
                                device_path.write_text(scheduler)
                                changes.append(f'Set I/O scheduler to {scheduler} for {device_path.parent.parent.name}')
                                break
                    except Exception:
                        continue

            # VM settings for better I/O performance
            vm_settings = {
                'vm.dirty_ratio': '15',
                'vm.dirty_background_ratio': '5',
                'vm.dirty_writeback_centisecs': '500',
                'vm.dirty_expire_centisecs': '3000'
            }

            for setting, value in vm_settings.items():
                result = await self._run_command(['sysctl', '-w', f'{setting}={value}'], ignore_errors=True)
                if result['success']:
                    changes.append(f'Set {setting}={value}')

            return {
                'success': True,
                'description': 'Optimized storage performance',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _set_cpu_governor(self, governor: str) -> Dict[str, Any]:
        """Set CPU frequency governor."""
        try:
            changes = []

            # Set governor for all CPUs
            cpu_dirs = Path('/sys/devices/system/cpu').glob('cpu[0-9]*')

            for cpu_dir in cpu_dirs:
                governor_file = cpu_dir / 'cpufreq' / 'scaling_governor'
                if governor_file.exists():
                    try:
                        governor_file.write_text(governor)
                        changes.append(f'Set {cpu_dir.name} governor to {governor}')
                    except Exception as e:
                        logger.warning(f'Could not set governor for {cpu_dir.name}: {e}')

            # Make persistent via systemd service
            service_content = f"""[Unit]
Description=Set CPU Governor to {governor}
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo {governor} | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

            service_file = Path(f'/etc/systemd/system/pi-health-governor-{governor}.service')
            service_file.write_text(service_content)

            # Enable service
            await self._run_command(['systemctl', 'daemon-reload'])
            await self._run_command(['systemctl', 'enable', f'pi-health-governor-{governor}.service'])

            changes.append(f'Created systemd service for {governor} governor persistence')

            return {
                'success': True,
                'description': f'Set CPU governor to {governor}',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _disable_unnecessary_services(self) -> Dict[str, Any]:
        """Disable unnecessary system services for headless operation."""
        try:
            changes = []

            # Services to disable for headless/server operation
            services_to_disable = [
                'bluetooth.service',
                'hciuart.service',
                'bluealsa.service',
                'triggerhappy.service',
                'avahi-daemon.service'
            ]

            for service in services_to_disable:
                try:
                    # Check if service exists and is enabled
                    status_result = await self._run_command(['systemctl', 'is-enabled', service], ignore_errors=True)

                    if status_result['success'] and 'enabled' in status_result['stdout']:
                        disable_result = await self._run_command(['systemctl', 'disable', service])
                        if disable_result['success']:
                            changes.append(f'Disabled {service}')

                        stop_result = await self._run_command(['systemctl', 'stop', service], ignore_errors=True)
                        if stop_result['success']:
                            changes.append(f'Stopped {service}')

                except Exception as e:
                    logger.warning(f'Could not process service {service}: {e}')

            return {
                'success': True,
                'description': 'Disabled unnecessary system services',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _disable_hdmi_output(self) -> Dict[str, Any]:
        """Disable HDMI output for power saving."""
        try:
            # Add HDMI disable to boot config
            config_txt = Path('/boot/config.txt')
            content = config_txt.read_text()

            hdmi_settings = [
                '# Pi-Health HDMI power saving',
                'hdmi_blanking=1',
                'hdmi_force_hotplug=0'
            ]

            for setting in hdmi_settings:
                if setting not in content:
                    content += f'\n{setting}'

            config_txt.write_text(content)

            return {
                'success': True,
                'description': 'Disabled HDMI output for power saving',
                'changes': hdmi_settings,
                'reboot_required': True
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _disable_wifi_power_save(self) -> Dict[str, Any]:
        """Disable Wi-Fi power saving for better performance."""
        try:
            # Create systemd service to disable WiFi power management
            service_content = """[Unit]
Description=Disable WiFi Power Management
After=network.target

[Service]
Type=oneshot
ExecStart=/sbin/iwconfig wlan0 power off
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""

            service_file = Path('/etc/systemd/system/wifi-power-management-off.service')
            service_file.write_text(service_content)

            await self._run_command(['systemctl', 'daemon-reload'])
            await self._run_command(['systemctl', 'enable', 'wifi-power-management-off.service'])

            # Apply immediately if WiFi is available
            iwconfig_result = await self._run_command(['iwconfig', 'wlan0', 'power', 'off'], ignore_errors=True)

            return {
                'success': True,
                'description': 'Disabled WiFi power saving',
                'changes': ['Created WiFi power management service', 'Disabled power saving immediately'],
                'immediate_effect': iwconfig_result['success']
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _apply_modest_overclock(self, system_info: Dict[str, Any]) -> Dict[str, Any]:
        """Apply modest overclocking settings."""
        try:
            # Only apply to Pi 4 for safety
            if 'Pi 4' not in system_info.get('model', ''):
                return {'success': False, 'error': 'Overclocking only supported on Pi 4'}

            config_txt = Path('/boot/config.txt')
            content = config_txt.read_text()

            # Modest Pi 4 overclock settings
            overclock_settings = [
                '# Pi-Health modest overclock settings',
                'arm_freq=1750',
                'gpu_freq=600',
                'over_voltage=4',
                'temp_limit=80'
            ]

            for setting in overclock_settings:
                if not setting.startswith('#'):
                    setting_name = setting.split('=')[0]
                    if re.search(f'^{setting_name}=', content, re.MULTILINE):
                        content = re.sub(f'^{setting_name}=.*$', setting, content, flags=re.MULTILINE)
                    else:
                        content += f'\n{setting}'
                else:
                    content += f'\n{setting}'

            config_txt.write_text(content)

            return {
                'success': True,
                'description': 'Applied modest overclock settings',
                'changes': overclock_settings,
                'reboot_required': True,
                'warning': 'Monitor temperatures after reboot'
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _apply_security_hardening(self) -> Dict[str, Any]:
        """Apply basic security hardening."""
        try:
            changes = []

            # Disable unused network protocols
            security_settings = {
                'net.ipv4.conf.all.send_redirects': '0',
                'net.ipv4.conf.default.send_redirects': '0',
                'net.ipv4.conf.all.accept_redirects': '0',
                'net.ipv4.conf.default.accept_redirects': '0',
                'net.ipv4.conf.all.secure_redirects': '0',
                'net.ipv4.conf.default.secure_redirects': '0',
                'net.ipv4.ip_forward': '0'
            }

            for setting, value in security_settings.items():
                result = await self._run_command(['sysctl', '-w', f'{setting}={value}'], ignore_errors=True)
                if result['success']:
                    changes.append(f'Set {setting}={value}')

            return {
                'success': True,
                'description': 'Applied basic security hardening',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _optimize_logging(self) -> Dict[str, Any]:
        """Optimize system logging for storage and performance."""
        try:
            changes = []

            # Configure journald for log rotation
            journald_conf = Path('/etc/systemd/journald.conf')
            journald_settings = [
                'SystemMaxUse=100M',
                'SystemMaxFileSize=10M',
                'RuntimeMaxUse=50M',
                'RuntimeMaxFileSize=5M'
            ]

            if journald_conf.exists():
                content = journald_conf.read_text()
                for setting in journald_settings:
                    setting_name = setting.split('=')[0]
                    if f'{setting_name}=' in content:
                        content = re.sub(f'^#{setting_name}=.*$', setting, content, flags=re.MULTILINE)
                        content = re.sub(f'^{setting_name}=.*$', setting, content, flags=re.MULTILINE)
                    else:
                        content += f'\n{setting}'

                journald_conf.write_text(content)
                changes.extend(journald_settings)

            return {
                'success': True,
                'description': 'Optimized system logging',
                'changes': changes,
                'service_restart_required': ['systemd-journald']
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _setup_development_tools(self) -> Dict[str, Any]:
        """Setup development tools and optimizations."""
        try:
            changes = []

            # Install essential development packages
            dev_packages = ['build-essential', 'git', 'curl', 'wget', 'vim', 'htop', 'tmux']

            install_result = await self._run_command(['apt', 'update'], ignore_errors=True)
            if install_result['success']:
                for package in dev_packages:
                    package_result = await self._run_command(['apt', 'install', '-y', package], ignore_errors=True)
                    if package_result['success']:
                        changes.append(f'Installed {package}')

            # Configure Git with safe defaults
            git_configs = [
                ['git', 'config', '--global', 'init.defaultBranch', 'main'],
                ['git', 'config', '--global', 'pull.rebase', 'false']
            ]

            for git_cmd in git_configs:
                result = await self._run_command(git_cmd, ignore_errors=True)
                if result['success']:
                    changes.append(f'Configured git: {" ".join(git_cmd[3:])}')

            return {
                'success': True,
                'description': 'Setup development tools',
                'changes': changes
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _apply_custom_optimization(self, custom_opt: Dict[str, Any], system_info: Dict[str, Any]) -> Dict[str, Any]:
        """Apply custom optimization specified by user."""
        try:
            opt_type = custom_opt.get('type')

            if opt_type == 'sysctl':
                setting = custom_opt.get('setting')
                value = custom_opt.get('value')
                result = await self._run_command(['sysctl', '-w', f'{setting}={value}'])
                return {
                    'success': result['success'],
                    'optimization': f'sysctl_{setting}',
                    'description': f'Set {setting}={value}'
                }

            elif opt_type == 'boot_config':
                setting = custom_opt.get('setting')
                value = custom_opt.get('value')
                return await self._modify_boot_config(setting, value)

            elif opt_type == 'service':
                service = custom_opt.get('service')
                action = custom_opt.get('action', 'disable')
                result = await self._run_command(['systemctl', action, service])
                return {
                    'success': result['success'],
                    'optimization': f'service_{service}',
                    'description': f'{action.title()} service {service}'
                }

            else:
                return {'success': False, 'error': f'Unknown custom optimization type: {opt_type}'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _modify_boot_config(self, setting: str, value: str) -> Dict[str, Any]:
        """Modify boot configuration setting."""
        try:
            config_txt = Path('/boot/config.txt')
            content = config_txt.read_text()

            if re.search(f'^{setting}=', content, re.MULTILINE):
                content = re.sub(f'^{setting}=.*$', f'{setting}={value}', content, flags=re.MULTILINE)
            else:
                content += f'\n{setting}={value}'

            config_txt.write_text(content)

            return {
                'success': True,
                'optimization': f'boot_config_{setting}',
                'description': f'Set boot config {setting}={value}',
                'reboot_required': True
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _validate_optimizations(self) -> Dict[str, Any]:
        """Validate applied optimizations."""
        try:
            validation_results = {}

            # Check if system is stable
            uptime_result = await self._run_command(['uptime'])
            validation_results['system_stable'] = uptime_result['success']

            # Check memory usage
            free_result = await self._run_command(['free', '-h'])
            validation_results['memory_info'] = free_result['stdout'] if free_result['success'] else 'unavailable'

            # Check CPU temperature
            temp_result = await self._run_command(['vcgencmd', 'measure_temp'], ignore_errors=True)
            if temp_result['success']:
                temp_match = re.search(r'temp=([0-9.]+)', temp_result['stdout'])
                if temp_match:
                    temp = float(temp_match.group(1))
                    validation_results['cpu_temperature'] = temp
                    validation_results['temperature_safe'] = temp < 75.0

            return {
                'success': True,
                'validation_results': validation_results
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def get_recommendations(self) -> Dict[str, Any]:
        """Get AI-driven optimization recommendations based on current system state."""
        try:
            # Detect current system
            system_info = await self._detect_pi_system()

            # Analyze current performance
            performance_info = await self._analyze_system_performance()

            # Generate recommendations
            recommendations = []

            # Memory-based recommendations
            memory_gb = system_info.get('memory', 0) // (1024**3)
            if memory_gb < 2:
                recommendations.append({
                    'category': 'memory',
                    'priority': 'high',
                    'title': 'Increase swap space',
                    'description': 'Your Pi has limited RAM. Increasing swap can prevent out-of-memory issues.',
                    'optimization': 'increase_swap'
                })

            # Temperature recommendations
            if performance_info.get('cpu_temperature', 0) > 70:
                recommendations.append({
                    'category': 'thermal',
                    'priority': 'high',
                    'title': 'Improve cooling',
                    'description': 'CPU temperature is high. Consider adding cooling or reducing overclock.',
                    'optimization': 'thermal_management'
                })

            # Storage recommendations
            if performance_info.get('disk_usage_percent', 0) > 80:
                recommendations.append({
                    'category': 'storage',
                    'priority': 'medium',
                    'title': 'Free up disk space',
                    'description': 'Disk usage is high. This can impact performance.',
                    'optimization': 'storage_cleanup'
                })

            # Network recommendations
            if performance_info.get('network_load', 0) > 0.7:
                recommendations.append({
                    'category': 'network',
                    'priority': 'medium',
                    'title': 'Optimize network settings',
                    'description': 'High network utilization detected. Network optimization could help.',
                    'optimization': 'network_optimization'
                })

            return {
                'success': True,
                'system_info': system_info,
                'performance_info': performance_info,
                'recommendations': recommendations
            }

        except Exception as e:
            logger.error(f"Failed to generate recommendations: {e}")
            return {'success': False, 'error': str(e)}

    async def _analyze_system_performance(self) -> Dict[str, Any]:
        """Analyze current system performance metrics."""
        try:
            performance = {}

            # CPU temperature
            temp_result = await self._run_command(['vcgencmd', 'measure_temp'], ignore_errors=True)
            if temp_result['success']:
                temp_match = re.search(r'temp=([0-9.]+)', temp_result['stdout'])
                if temp_match:
                    performance['cpu_temperature'] = float(temp_match.group(1))

            # CPU frequency
            freq_result = await self._run_command(['vcgencmd', 'measure_clock', 'arm'], ignore_errors=True)
            if freq_result['success']:
                freq_match = re.search(r'frequency\(48\)=(\d+)', freq_result['stdout'])
                if freq_match:
                    performance['cpu_frequency'] = int(freq_match.group(1)) // 1000000  # Convert to MHz

            # Memory usage
            free_result = await self._run_command(['free', '-b'])
            if free_result['success']:
                free_lines = free_result['stdout'].split('\n')
                if len(free_lines) > 1:
                    mem_line = free_lines[1].split()
                    if len(mem_line) >= 3:
                        total_mem = int(mem_line[1])
                        used_mem = int(mem_line[2])
                        performance['memory_usage_percent'] = (used_mem / total_mem) * 100

            # Disk usage
            df_result = await self._run_command(['df', '/'])
            if df_result['success']:
                df_lines = df_result['stdout'].split('\n')
                if len(df_lines) > 1:
                    disk_line = df_lines[1].split()
                    if len(disk_line) >= 5:
                        usage_str = disk_line[4].replace('%', '')
                        if usage_str.isdigit():
                            performance['disk_usage_percent'] = int(usage_str)

            # Load average
            uptime_result = await self._run_command(['uptime'])
            if uptime_result['success']:
                load_match = re.search(r'load average:\s*([0-9.]+)', uptime_result['stdout'])
                if load_match:
                    performance['load_average'] = float(load_match.group(1))

            return performance

        except Exception as e:
            logger.error(f"Performance analysis failed: {e}")
            return {}

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