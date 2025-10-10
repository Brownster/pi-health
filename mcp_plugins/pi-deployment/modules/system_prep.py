"""
System Prep Module
System preparation and validation for Pi deployment.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class SystemPrep:
    """System preparation and validation for Pi deployment."""

    def __init__(self):
        self.required_packages = [
            'curl', 'wget', 'git', 'htop', 'vim', 'unzip',
            'apt-transport-https', 'ca-certificates', 'gnupg', 'lsb-release'
        ]

    async def prepare_system(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare Pi system for deployment."""
        logger.info("Starting system preparation...")

        preparation_result = {
            'steps_completed': [],
            'steps_failed': [],
            'system_updated': False,
            'packages_installed': [],
            'docker_installed': False,
            'permissions_set': False
        }

        try:
            # Step 1: Update system packages
            if config.get('update_system', True):
                update_result = await self._update_system_packages()
                if update_result['success']:
                    preparation_result['system_updated'] = True
                    preparation_result['steps_completed'].append('system_update')
                else:
                    preparation_result['steps_failed'].append({
                        'step': 'system_update',
                        'error': update_result['error']
                    })

            # Step 2: Install essential packages
            if config.get('install_packages', True):
                packages_result = await self._install_essential_packages()
                if packages_result['success']:
                    preparation_result['packages_installed'] = packages_result['installed_packages']
                    preparation_result['steps_completed'].append('package_installation')
                else:
                    preparation_result['steps_failed'].append({
                        'step': 'package_installation',
                        'error': packages_result['error']
                    })

            # Step 3: Install Docker if not present
            if config.get('install_docker', True):
                docker_result = await self._ensure_docker_installed()
                if docker_result['success']:
                    preparation_result['docker_installed'] = True
                    preparation_result['steps_completed'].append('docker_installation')
                else:
                    preparation_result['steps_failed'].append({
                        'step': 'docker_installation',
                        'error': docker_result['error']
                    })

            # Step 4: Setup user permissions
            permissions_result = await self._setup_user_permissions()
            if permissions_result['success']:
                preparation_result['permissions_set'] = True
                preparation_result['steps_completed'].append('permissions_setup')
            else:
                preparation_result['steps_failed'].append({
                    'step': 'permissions_setup',
                    'error': permissions_result['error']
                })

            # Step 5: Create directory structure
            directories_result = await self._create_directory_structure(config)
            if directories_result['success']:
                preparation_result['directories_created'] = directories_result['directories']
                preparation_result['steps_completed'].append('directory_creation')
            else:
                preparation_result['steps_failed'].append({
                    'step': 'directory_creation',
                    'error': directories_result['error']
                })

            # Step 6: Configure system limits
            limits_result = await self._configure_system_limits()
            if limits_result['success']:
                preparation_result['steps_completed'].append('system_limits')
            else:
                preparation_result['steps_failed'].append({
                    'step': 'system_limits',
                    'error': limits_result['error']
                })

            return {'success': len(preparation_result['steps_failed']) == 0, 'result': preparation_result}

        except Exception as e:
            logger.error(f"System preparation failed: {e}")
            return {'success': False, 'error': str(e), 'result': preparation_result}

    async def get_system_info(self) -> Dict[str, Any]:
        """Get comprehensive Pi system information."""
        try:
            system_info = {}

            # Hardware information
            system_info['hardware'] = await self._get_hardware_info()

            # Operating system information
            system_info['os'] = await self._get_os_info()

            # Resource information
            system_info['resources'] = await self._get_resource_info()

            # Network information
            system_info['network'] = await self._get_network_info()

            # Storage information
            system_info['storage'] = await self._get_storage_info()

            # Software information
            system_info['software'] = await self._get_software_info()

            return system_info

        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return {'error': str(e)}

    async def _update_system_packages(self) -> Dict[str, Any]:
        """Update system packages."""
        try:
            logger.info("Updating system packages...")

            # Update package lists
            update_result = await self._run_command(['apt', 'update'])
            if not update_result['success']:
                return {'success': False, 'error': f"Failed to update package lists: {update_result['stderr']}"}

            # Upgrade packages
            upgrade_result = await self._run_command(['apt', 'upgrade', '-y'])
            if not upgrade_result['success']:
                return {'success': False, 'error': f"Failed to upgrade packages: {upgrade_result['stderr']}"}

            return {'success': True, 'message': 'System packages updated successfully'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _install_essential_packages(self) -> Dict[str, Any]:
        """Install essential packages for Pi Health deployment."""
        try:
            logger.info("Installing essential packages...")

            installed_packages = []

            for package in self.required_packages:
                # Check if package is already installed
                check_result = await self._run_command(['dpkg', '-l', package], ignore_errors=True)

                if not check_result['success'] or 'no packages found' in check_result['stderr']:
                    # Install package
                    install_result = await self._run_command(['apt', 'install', '-y', package])
                    if install_result['success']:
                        installed_packages.append(package)
                        logger.info(f"Installed package: {package}")
                    else:
                        logger.warning(f"Failed to install package {package}: {install_result['stderr']}")

            return {'success': True, 'installed_packages': installed_packages}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _ensure_docker_installed(self) -> Dict[str, Any]:
        """Ensure Docker is installed and configured."""
        try:
            # Check if Docker is already installed
            docker_check = await self._run_command(['docker', '--version'], ignore_errors=True)
            if docker_check['success']:
                # Docker is installed, check if it's running
                docker_status = await self._run_command(['systemctl', 'is-active', 'docker'], ignore_errors=True)
                if docker_status['success'] and 'active' in docker_status['stdout']:
                    return {'success': True, 'message': 'Docker is already installed and running'}

            logger.info("Installing Docker...")

            # Install Docker using the official installation script
            docker_install = await self._run_command([
                'sh', '-c',
                'curl -fsSL https://get.docker.com | sh'
            ])

            if not docker_install['success']:
                return {'success': False, 'error': f"Docker installation failed: {docker_install['stderr']}"}

            # Start and enable Docker service
            await self._run_command(['systemctl', 'start', 'docker'])
            await self._run_command(['systemctl', 'enable', 'docker'])

            # Install Docker Compose if not present
            compose_check = await self._run_command(['docker-compose', '--version'], ignore_errors=True)
            if not compose_check['success']:
                compose_install = await self._run_command(['pip3', 'install', 'docker-compose'])
                if not compose_install['success']:
                    logger.warning("Failed to install docker-compose via pip")

            return {'success': True, 'message': 'Docker installed and configured successfully'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _setup_user_permissions(self) -> Dict[str, Any]:
        """Setup user permissions for Docker and system access."""
        try:
            current_user = os.getenv('USER', 'pi')

            # Add user to docker group
            usermod_result = await self._run_command(['usermod', '-aG', 'docker', current_user])
            if not usermod_result['success']:
                return {'success': False, 'error': f"Failed to add user to docker group: {usermod_result['stderr']}"}

            # Set up sudo permissions for specific commands
            sudoers_content = f"""# Pi-Health deployment permissions
{current_user} ALL=(ALL) NOPASSWD: /usr/bin/systemctl
{current_user} ALL=(ALL) NOPASSWD: /bin/mount
{current_user} ALL=(ALL) NOPASSWD: /bin/umount
{current_user} ALL=(ALL) NOPASSWD: /usr/sbin/usermod
"""

            sudoers_file = Path(f'/etc/sudoers.d/pi-health-{current_user}')
            try:
                with open(sudoers_file, 'w') as f:
                    f.write(sudoers_content)
                sudoers_file.chmod(0o440)
            except PermissionError:
                logger.warning("Could not create sudoers file - may need manual configuration")

            return {'success': True, 'message': 'User permissions configured'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _create_directory_structure(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create necessary directory structure."""
        try:
            directories_to_create = [
                '/home/pi/docker',
                '/home/pi/docker-deployments',
                '/var/log/pi-health',
                '/etc/pi-health'
            ]

            # Add custom directories from config
            custom_dirs = config.get('additional_directories', [])
            directories_to_create.extend(custom_dirs)

            created_directories = []

            for directory in directories_to_create:
                dir_path = Path(directory)
                try:
                    dir_path.mkdir(parents=True, exist_ok=True, mode=0o755)
                    created_directories.append(str(dir_path))

                    # Set ownership to current user
                    current_user = os.getenv('USER', 'pi')
                    chown_result = await self._run_command(['chown', f'{current_user}:{current_user}', str(dir_path)], ignore_errors=True)

                except Exception as e:
                    logger.warning(f"Could not create directory {directory}: {e}")

            return {'success': True, 'directories': created_directories}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _configure_system_limits(self) -> Dict[str, Any]:
        """Configure system limits for containerized applications."""
        try:
            # Configure limits for containers and file handles
            limits_content = """# Pi-Health system limits
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768

# Docker-specific limits
root soft nofile 65536
root hard nofile 65536
"""

            limits_file = Path('/etc/security/limits.d/99-pi-health.conf')
            try:
                with open(limits_file, 'w') as f:
                    f.write(limits_content)
            except PermissionError:
                logger.warning("Could not create limits file - may need manual configuration")

            # Configure sysctl for container workloads
            sysctl_content = """# Pi-Health sysctl optimizations
fs.file-max = 65536
vm.max_map_count = 262144
net.core.somaxconn = 65535
"""

            sysctl_file = Path('/etc/sysctl.d/99-pi-health.conf')
            try:
                with open(sysctl_file, 'w') as f:
                    f.write(sysctl_content)

                # Apply sysctl settings immediately
                await self._run_command(['sysctl', '-p', str(sysctl_file)], ignore_errors=True)

            except PermissionError:
                logger.warning("Could not create sysctl file - may need manual configuration")

            return {'success': True, 'message': 'System limits configured'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _get_hardware_info(self) -> Dict[str, Any]:
        """Get hardware information."""
        hardware_info = {}

        try:
            # CPU information
            cpuinfo_result = await self._run_command(['cat', '/proc/cpuinfo'])
            if cpuinfo_result['success']:
                cpuinfo = cpuinfo_result['stdout']

                model_match = re.search(r'Model\s*:\s*(.+)', cpuinfo)
                if model_match:
                    hardware_info['model'] = model_match.group(1).strip()

                revision_match = re.search(r'Revision\s*:\s*(\w+)', cpuinfo)
                if revision_match:
                    hardware_info['revision'] = revision_match.group(1).strip()

                serial_match = re.search(r'Serial\s*:\s*(\w+)', cpuinfo)
                if serial_match:
                    hardware_info['serial'] = serial_match.group(1).strip()

                processor_count = len(re.findall(r'processor\s*:', cpuinfo))
                hardware_info['cpu_cores'] = processor_count

            # Memory information
            meminfo_result = await self._run_command(['cat', '/proc/meminfo'])
            if meminfo_result['success']:
                mem_match = re.search(r'MemTotal:\s*(\d+)\s*kB', meminfo_result['stdout'])
                if mem_match:
                    hardware_info['memory_kb'] = int(mem_match.group(1))
                    hardware_info['memory_gb'] = round(int(mem_match.group(1)) / 1024 / 1024, 1)

            # Temperature
            temp_result = await self._run_command(['vcgencmd', 'measure_temp'], ignore_errors=True)
            if temp_result['success']:
                temp_match = re.search(r'temp=([0-9.]+)', temp_result['stdout'])
                if temp_match:
                    hardware_info['temperature'] = float(temp_match.group(1))

            # CPU frequency
            freq_result = await self._run_command(['vcgencmd', 'measure_clock', 'arm'], ignore_errors=True)
            if freq_result['success']:
                freq_match = re.search(r'frequency\(48\)=(\d+)', freq_result['stdout'])
                if freq_match:
                    hardware_info['cpu_frequency_mhz'] = int(freq_match.group(1)) // 1000000

        except Exception as e:
            hardware_info['error'] = str(e)

        return hardware_info

    async def _get_os_info(self) -> Dict[str, Any]:
        """Get operating system information."""
        os_info = {}

        try:
            # OS release information
            release_result = await self._run_command(['cat', '/etc/os-release'])
            if release_result['success']:
                for line in release_result['stdout'].split('\n'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        os_info[key.lower()] = value.strip('"')

            # Kernel information
            uname_result = await self._run_command(['uname', '-a'])
            if uname_result['success']:
                os_info['kernel'] = uname_result['stdout']

            # Uptime
            uptime_result = await self._run_command(['uptime', '-p'])
            if uptime_result['success']:
                os_info['uptime'] = uptime_result['stdout']

        except Exception as e:
            os_info['error'] = str(e)

        return os_info

    async def _get_resource_info(self) -> Dict[str, Any]:
        """Get current resource usage information."""
        resource_info = {}

        try:
            # CPU usage
            top_result = await self._run_command(['top', '-bn1'], ignore_errors=True)
            if top_result['success']:
                cpu_line = None
                for line in top_result['stdout'].split('\n'):
                    if '%Cpu' in line:
                        cpu_line = line
                        break
                if cpu_line:
                    resource_info['cpu_usage'] = cpu_line

            # Memory usage
            free_result = await self._run_command(['free', '-h'])
            if free_result['success']:
                resource_info['memory_usage'] = free_result['stdout']

            # Load average
            load_result = await self._run_command(['cat', '/proc/loadavg'])
            if load_result['success']:
                load_avg = load_result['stdout'].split()[:3]
                resource_info['load_average'] = {
                    '1min': float(load_avg[0]),
                    '5min': float(load_avg[1]),
                    '15min': float(load_avg[2])
                }

        except Exception as e:
            resource_info['error'] = str(e)

        return resource_info

    async def _get_network_info(self) -> Dict[str, Any]:
        """Get network interface information."""
        network_info = {}

        try:
            # Network interfaces
            ip_result = await self._run_command(['ip', 'addr', 'show'])
            if ip_result['success']:
                network_info['interfaces'] = ip_result['stdout']

            # Default route
            route_result = await self._run_command(['ip', 'route', 'show', 'default'])
            if route_result['success']:
                network_info['default_route'] = route_result['stdout']

            # DNS configuration
            resolv_result = await self._run_command(['cat', '/etc/resolv.conf'])
            if resolv_result['success']:
                network_info['dns_config'] = resolv_result['stdout']

        except Exception as e:
            network_info['error'] = str(e)

        return network_info

    async def _get_storage_info(self) -> Dict[str, Any]:
        """Get storage and filesystem information."""
        storage_info = {}

        try:
            # Disk usage
            df_result = await self._run_command(['df', '-h'])
            if df_result['success']:
                storage_info['disk_usage'] = df_result['stdout']

            # Block devices
            lsblk_result = await self._run_command(['lsblk'])
            if lsblk_result['success']:
                storage_info['block_devices'] = lsblk_result['stdout']

            # Mount points
            mount_result = await self._run_command(['mount'])
            if mount_result['success']:
                storage_info['mount_points'] = mount_result['stdout']

        except Exception as e:
            storage_info['error'] = str(e)

        return storage_info

    async def _get_software_info(self) -> Dict[str, Any]:
        """Get installed software information."""
        software_info = {}

        try:
            # Docker version
            docker_result = await self._run_command(['docker', '--version'], ignore_errors=True)
            if docker_result['success']:
                software_info['docker'] = docker_result['stdout']

            # Docker Compose version
            compose_result = await self._run_command(['docker-compose', '--version'], ignore_errors=True)
            if compose_result['success']:
                software_info['docker_compose'] = compose_result['stdout']

            # Python version
            python_result = await self._run_command(['python3', '--version'])
            if python_result['success']:
                software_info['python'] = python_result['stdout']

            # Git version
            git_result = await self._run_command(['git', '--version'])
            if git_result['success']:
                software_info['git'] = git_result['stdout']

        except Exception as e:
            software_info['error'] = str(e)

        return software_info

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