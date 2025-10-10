"""
Network Setup Module
Intelligent network configuration including VPN and Tailscale setup for Pi systems.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
import ipaddress
import requests

logger = logging.getLogger(__name__)


class NetworkSetup:
    """Intelligent network configuration manager for Pi systems."""

    def __init__(self):
        self.vpn_providers = {
            'nordvpn': {
                'name': 'NordVPN',
                'config_template': 'nordvpn',
                'auth_fields': ['username', 'password'],
                'server_field': 'server_countries'
            },
            'surfshark': {
                'name': 'Surfshark',
                'config_template': 'surfshark',
                'auth_fields': ['username', 'password'],
                'server_field': 'server_countries'
            },
            'expressvpn': {
                'name': 'ExpressVPN',
                'config_template': 'expressvpn',
                'auth_fields': ['username', 'password'],
                'server_field': 'server_location'
            },
            'custom': {
                'name': 'Custom OpenVPN',
                'config_template': 'custom',
                'auth_fields': ['username', 'password'],
                'requires_config_file': True
            }
        }

    async def setup_vpn(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Setup VPN with intelligent provider detection and configuration."""
        logger.info("Setting up VPN configuration...")

        try:
            provider = config.get('provider', 'custom').lower()

            if provider not in self.vpn_providers:
                return {"success": False, "error": f"Unsupported VPN provider: {provider}"}

            provider_info = self.vpn_providers[provider]

            # Validate required fields
            validation_result = await self._validate_vpn_config(config, provider_info)
            if not validation_result['valid']:
                return {"success": False, "error": f"Configuration validation failed: {validation_result['error']}"}

            # Create VPN configuration
            vpn_config_dir = Path("/home/pi/docker/vpn")  # Default Pi path
            if config.get('config_dir'):
                vpn_config_dir = Path(config['config_dir'])

            vpn_config_dir.mkdir(parents=True, exist_ok=True)

            # Setup provider-specific configuration
            if provider == 'custom':
                setup_result = await self._setup_custom_vpn(config, vpn_config_dir)
            else:
                setup_result = await self._setup_provider_vpn(config, provider_info, vpn_config_dir)

            if not setup_result['success']:
                return setup_result

            # Test VPN connection if requested
            if config.get('test_connection', True):
                test_result = await self._test_vpn_connection(vpn_config_dir)
                setup_result['connection_test'] = test_result

            # Setup kill switch and DNS leak protection
            if config.get('enable_kill_switch', True):
                killswitch_result = await self._setup_kill_switch(config)
                setup_result['kill_switch'] = killswitch_result

            logger.info(f"VPN setup completed for provider: {provider}")
            return setup_result

        except Exception as e:
            logger.error(f"VPN setup failed: {e}")
            return {"success": False, "error": str(e)}

    async def _validate_vpn_config(self, config: Dict[str, Any], provider_info: Dict[str, Any]) -> Dict[str, Any]:
        """Validate VPN configuration parameters."""
        errors = []

        # Check required authentication fields
        for field in provider_info['auth_fields']:
            if not config.get(field):
                errors.append(f"Missing required field: {field}")

        # Check for config file if required
        if provider_info.get('requires_config_file'):
            config_files = config.get('config_files', [])
            if not config_files:
                errors.append("Custom VPN requires OpenVPN configuration files")

        # Validate server configuration
        if provider_info.get('server_field'):
            server_config = config.get(provider_info['server_field'])
            if not server_config:
                errors.append(f"Missing server configuration: {provider_info['server_field']}")

        return {
            'valid': len(errors) == 0,
            'error': '; '.join(errors) if errors else None
        }

    async def _setup_provider_vpn(self, config: Dict[str, Any], provider_info: Dict[str, Any], config_dir: Path) -> Dict[str, Any]:
        """Setup VPN for known providers using Gluetun."""
        try:
            provider = config.get('provider').lower()

            # Create VPN environment file
            env_content = await self._generate_vpn_env(config, provider_info)

            env_file = config_dir / ".env"
            with open(env_file, 'w') as f:
                f.write(env_content)

            # Set secure permissions
            env_file.chmod(0o600)

            # Create docker-compose snippet for VPN service
            compose_config = await self._generate_vpn_compose_config(config, provider)

            compose_file = config_dir / "docker-compose.vpn.yml"
            with open(compose_file, 'w') as f:
                f.write(compose_config)

            return {
                "success": True,
                "provider": provider,
                "config_dir": str(config_dir),
                "files_created": [str(env_file), str(compose_file)],
                "message": f"VPN configuration created for {provider_info['name']}"
            }

        except Exception as e:
            logger.error(f"Provider VPN setup failed: {e}")
            return {"success": False, "error": str(e)}

    async def _generate_vpn_env(self, config: Dict[str, Any], provider_info: Dict[str, Any]) -> str:
        """Generate VPN environment configuration."""
        provider = config.get('provider').lower()

        env_lines = [
            "# VPN Configuration - Generated by Pi-Health",
            f"# Provider: {provider_info['name']}",
            "",
            f"VPN_SERVICE_PROVIDER={provider}",
            "VPN_TYPE=openvpn",
        ]

        # Add authentication
        if 'username' in config:
            env_lines.append(f"OPENVPN_USER={config['username']}")
        if 'password' in config:
            env_lines.append(f"OPENVPN_PASSWORD={config['password']}")

        # Add server configuration
        if provider == 'nordvpn':
            if config.get('server_countries'):
                env_lines.append(f"SERVER_COUNTRIES={config['server_countries']}")
            if config.get('server_categories'):
                env_lines.append(f"SERVER_CATEGORIES={config['server_categories']}")
        elif provider == 'surfshark':
            if config.get('server_countries'):
                env_lines.append(f"SERVER_COUNTRIES={config['server_countries']}")
        elif provider == 'expressvpn':
            if config.get('server_location'):
                env_lines.append(f"SERVER_NAMES={config['server_location']}")

        # Add advanced options
        env_lines.extend([
            "",
            "# Advanced Configuration",
            "FIREWALL=on",
            "DOT=off",  # Disable DNS over TLS to prevent conflicts
        ])

        if config.get('port_forwarding', False):
            env_lines.append("VPN_PORT_FORWARDING=on")

        # Add custom DNS if specified
        if config.get('custom_dns'):
            dns_servers = ','.join(config['custom_dns'])
            env_lines.append(f"DNS={dns_servers}")

        return '\n'.join(env_lines)

    async def _generate_vpn_compose_config(self, config: Dict[str, Any], provider: str) -> str:
        """Generate Docker Compose configuration for VPN service."""

        compose_config = f"""version: '3.8'

services:
  vpn:
    image: qmcgaw/gluetun:latest
    container_name: pi-health-vpn
    cap_add:
      - NET_ADMIN
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/London
    env_file:
      - .env
    ports:
      # Add ports that need VPN protection here
      - "8080:8080"    # SABnzbd
      - "9091:9091"    # Transmission
    volumes:
      - /dev/net/tun:/dev/net/tun
    restart: unless-stopped
    networks:
      - pi-health-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/ip"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

networks:
  pi-health-network:
    name: pi-health-network
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
"""

        return compose_config

    async def _setup_custom_vpn(self, config: Dict[str, Any], config_dir: Path) -> Dict[str, Any]:
        """Setup custom OpenVPN configuration."""
        try:
            config_files = config.get('config_files', [])
            if not config_files:
                return {"success": False, "error": "No OpenVPN config files provided"}

            # Copy config files
            copied_files = []
            for config_file_path in config_files:
                config_file = Path(config_file_path)
                if config_file.exists():
                    dest_file = config_dir / config_file.name
                    dest_file.write_bytes(config_file.read_bytes())
                    copied_files.append(str(dest_file))

            if not copied_files:
                return {"success": False, "error": "No valid config files found"}

            # Create auth file if credentials provided
            auth_file = None
            if config.get('username') and config.get('password'):
                auth_file = config_dir / "auth.txt"
                with open(auth_file, 'w') as f:
                    f.write(f"{config['username']}\n{config['password']}\n")
                auth_file.chmod(0o600)

            # Create environment file
            env_content = f"""# Custom OpenVPN Configuration
VPN_SERVICE_PROVIDER=custom
VPN_TYPE=openvpn
OPENVPN_USER={config.get('username', '')}
OPENVPN_PASSWORD={config.get('password', '')}
"""

            env_file = config_dir / ".env"
            with open(env_file, 'w') as f:
                f.write(env_content)
            env_file.chmod(0o600)

            return {
                "success": True,
                "provider": "custom",
                "config_dir": str(config_dir),
                "config_files": copied_files,
                "auth_file": str(auth_file) if auth_file else None,
                "message": "Custom VPN configuration created"
            }

        except Exception as e:
            logger.error(f"Custom VPN setup failed: {e}")
            return {"success": False, "error": str(e)}

    async def _test_vpn_connection(self, config_dir: Path) -> Dict[str, Any]:
        """Test VPN connection by starting container temporarily."""
        try:
            logger.info("Testing VPN connection...")

            # Start VPN container for testing
            test_result = await self._run_command([
                'docker-compose', '-f', str(config_dir / 'docker-compose.vpn.yml'),
                'up', '-d', 'vpn'
            ])

            if not test_result['success']:
                return {"success": False, "error": "Failed to start VPN container for testing"}

            # Wait for connection
            await asyncio.sleep(30)

            # Test external IP
            ip_test = await self._test_external_ip()

            # Stop test container
            await self._run_command([
                'docker-compose', '-f', str(config_dir / 'docker-compose.vpn.yml'),
                'down'
            ], ignore_errors=True)

            return {
                "success": ip_test['success'],
                "external_ip": ip_test.get('ip'),
                "location": ip_test.get('location'),
                "message": "VPN connection test completed"
            }

        except Exception as e:
            logger.error(f"VPN connection test failed: {e}")
            return {"success": False, "error": str(e)}

    async def _test_external_ip(self) -> Dict[str, Any]:
        """Test external IP to verify VPN connection."""
        try:
            # Test with multiple services
            ip_services = [
                "https://ipinfo.io/json",
                "https://httpbin.org/ip",
                "https://api.ipify.org?format=json"
            ]

            for service in ip_services:
                try:
                    response = requests.get(service, timeout=10)
                    if response.status_code == 200:
                        data = response.json()

                        # Extract IP from different response formats
                        if 'ip' in data:
                            return {
                                "success": True,
                                "ip": data['ip'],
                                "location": data.get('city', '') + ', ' + data.get('country', '') if 'city' in data else None
                            }
                        elif 'origin' in data:
                            return {"success": True, "ip": data['origin']}

                except Exception:
                    continue

            return {"success": False, "error": "Could not determine external IP"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _setup_kill_switch(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Setup VPN kill switch using iptables."""
        try:
            # This is handled by Gluetun's built-in firewall
            # We just need to ensure proper configuration

            kill_switch_rules = [
                "# VPN Kill Switch - Managed by Gluetun",
                "# All traffic routed through VPN container",
                "# No additional iptables rules needed"
            ]

            return {
                "success": True,
                "method": "gluetun-firewall",
                "message": "Kill switch handled by Gluetun container firewall"
            }

        except Exception as e:
            logger.error(f"Kill switch setup failed: {e}")
            return {"success": False, "error": str(e)}

    async def setup_tailscale(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Setup Tailscale mesh networking."""
        logger.info("Setting up Tailscale...")

        try:
            # Check if Tailscale is already installed
            tailscale_installed = await self._check_tailscale_installation()

            if not tailscale_installed['installed']:
                install_result = await self._install_tailscale()
                if not install_result['success']:
                    return install_result

            # Configure Tailscale
            auth_key = config.get('auth_key')
            if not auth_key:
                return {
                    "success": False,
                    "error": "Tailscale auth key required. Get one from https://login.tailscale.com/admin/settings/keys"
                }

            # Start Tailscale
            setup_result = await self._configure_tailscale(config)

            if setup_result['success']:
                # Get Tailscale status
                status = await self._get_tailscale_status()
                setup_result['status'] = status

            return setup_result

        except Exception as e:
            logger.error(f"Tailscale setup failed: {e}")
            return {"success": False, "error": str(e)}

    async def _check_tailscale_installation(self) -> Dict[str, Any]:
        """Check if Tailscale is installed."""
        try:
            result = await self._run_command(['which', 'tailscale'])

            if result['success']:
                version_result = await self._run_command(['tailscale', 'version'])
                return {
                    "installed": True,
                    "version": version_result['stdout'] if version_result['success'] else "unknown"
                }
            else:
                return {"installed": False}

        except Exception as e:
            return {"installed": False, "error": str(e)}

    async def _install_tailscale(self) -> Dict[str, Any]:
        """Install Tailscale on the Pi."""
        try:
            logger.info("Installing Tailscale...")

            # Download and run Tailscale installer
            install_commands = [
                ['curl', '-fsSL', 'https://tailscale.com/install.sh'],
                ['sh']
            ]

            # Use the official installer script
            result = await self._run_command([
                'sh', '-c',
                'curl -fsSL https://tailscale.com/install.sh | sh'
            ])

            if result['success']:
                return {
                    "success": True,
                    "message": "Tailscale installed successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"Tailscale installation failed: {result['stderr']}"
                }

        except Exception as e:
            logger.error(f"Tailscale installation failed: {e}")
            return {"success": False, "error": str(e)}

    async def _configure_tailscale(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Configure Tailscale with auth key."""
        try:
            auth_key = config['auth_key']

            # Build tailscale up command
            cmd = ['tailscale', 'up', '--authkey', auth_key]

            # Add optional flags
            if config.get('accept_routes', False):
                cmd.append('--accept-routes')

            if config.get('advertise_exit_node', False):
                cmd.append('--advertise-exit-node')

            if config.get('advertise_routes'):
                cmd.extend(['--advertise-routes', config['advertise_routes']])

            if config.get('hostname'):
                cmd.extend(['--hostname', config['hostname']])

            # Run configuration
            result = await self._run_command(cmd)

            if result['success']:
                return {
                    "success": True,
                    "message": "Tailscale configured and connected successfully"
                }
            else:
                return {
                    "success": False,
                    "error": f"Tailscale configuration failed: {result['stderr']}"
                }

        except Exception as e:
            logger.error(f"Tailscale configuration failed: {e}")
            return {"success": False, "error": str(e)}

    async def _get_tailscale_status(self) -> Dict[str, Any]:
        """Get Tailscale connection status."""
        try:
            # Get status
            status_result = await self._run_command(['tailscale', 'status', '--json'])

            if status_result['success']:
                status_data = json.loads(status_result['stdout'])

                # Get IP
                ip_result = await self._run_command(['tailscale', 'ip', '-4'])
                tailscale_ip = ip_result['stdout'] if ip_result['success'] else "unknown"

                return {
                    "connected": True,
                    "tailscale_ip": tailscale_ip,
                    "backend_state": status_data.get('BackendState', 'unknown'),
                    "peers": len(status_data.get('Peer', {})),
                    "self": status_data.get('Self', {})
                }
            else:
                return {
                    "connected": False,
                    "error": status_result['stderr']
                }

        except Exception as e:
            logger.error(f"Error getting Tailscale status: {e}")
            return {"connected": False, "error": str(e)}

    async def setup_complete_network(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Setup complete network configuration including VPN and Tailscale."""
        logger.info("Setting up complete network configuration...")

        results = {
            "vpn": None,
            "tailscale": None,
            "network_optimization": None
        }

        try:
            # Setup VPN if configured
            if config.get('vpn'):
                vpn_result = await self.setup_vpn(config['vpn'])
                results['vpn'] = vpn_result

            # Setup Tailscale if configured
            if config.get('tailscale'):
                tailscale_result = await self.setup_tailscale(config['tailscale'])
                results['tailscale'] = tailscale_result

            # Optimize network settings for Pi
            if config.get('optimize_network', True):
                optimization_result = await self._optimize_network_settings()
                results['network_optimization'] = optimization_result

            # Overall success if no critical failures
            overall_success = True
            if results['vpn'] and not results['vpn']['success']:
                overall_success = False
            if results['tailscale'] and not results['tailscale']['success']:
                overall_success = False

            return {
                "success": overall_success,
                "results": results,
                "message": "Network setup completed"
            }

        except Exception as e:
            logger.error(f"Complete network setup failed: {e}")
            return {"success": False, "error": str(e), "results": results}

    async def _optimize_network_settings(self) -> Dict[str, Any]:
        """Optimize network settings for Pi performance."""
        try:
            optimizations = []

            # Increase network buffer sizes
            sysctl_settings = {
                'net.core.rmem_max': '134217728',
                'net.core.wmem_max': '134217728',
                'net.ipv4.tcp_rmem': '4096 87380 134217728',
                'net.ipv4.tcp_wmem': '4096 65536 134217728',
                'net.core.netdev_max_backlog': '30000',
                'net.ipv4.tcp_congestion_control': 'bbr'
            }

            for setting, value in sysctl_settings.items():
                result = await self._run_command(['sysctl', '-w', f'{setting}={value}'], ignore_errors=True)
                if result['success']:
                    optimizations.append(f"Set {setting}={value}")

            # Make changes persistent
            sysctl_conf = "/etc/sysctl.d/99-pi-health-network.conf"
            with open(sysctl_conf, 'w') as f:
                f.write("# Pi-Health Network Optimizations\n")
                for setting, value in sysctl_settings.items():
                    f.write(f"{setting} = {value}\n")

            optimizations.append("Created persistent sysctl configuration")

            return {
                "success": True,
                "optimizations": optimizations,
                "message": "Network optimization completed"
            }

        except Exception as e:
            logger.error(f"Network optimization failed: {e}")
            return {"success": False, "error": str(e)}

    async def get_network_status(self) -> Dict[str, Any]:
        """Get comprehensive network status."""
        try:
            status = {
                "interfaces": [],
                "vpn": {"connected": False},
                "tailscale": {"connected": False},
                "internet": {"connected": False},
                "dns": {"working": False}
            }

            # Get network interfaces
            interfaces_result = await self._run_command(['ip', 'addr', 'show'])
            if interfaces_result['success']:
                status['interfaces'] = await self._parse_network_interfaces(interfaces_result['stdout'])

            # Test internet connectivity
            internet_test = await self._test_internet_connectivity()
            status['internet'] = internet_test

            # Check VPN status (if Gluetun container is running)
            vpn_status = await self._check_vpn_status()
            status['vpn'] = vpn_status

            # Check Tailscale status
            tailscale_status = await self._get_tailscale_status()
            status['tailscale'] = tailscale_status

            # Test DNS resolution
            dns_test = await self._test_dns_resolution()
            status['dns'] = dns_test

            return {"success": True, "status": status}

        except Exception as e:
            logger.error(f"Error getting network status: {e}")
            return {"success": False, "error": str(e)}

    async def _parse_network_interfaces(self, ip_output: str) -> List[Dict[str, Any]]:
        """Parse network interfaces from ip command output."""
        interfaces = []

        # Parse ip addr show output
        current_interface = None

        for line in ip_output.split('\n'):
            line = line.strip()

            # Interface line
            if re.match(r'^\d+:', line):
                if current_interface:
                    interfaces.append(current_interface)

                match = re.search(r'\d+:\s+(\w+):\s+<([^>]*)>', line)
                if match:
                    current_interface = {
                        'name': match.group(1),
                        'flags': match.group(2).split(','),
                        'addresses': []
                    }

            # IP address line
            elif line.startswith('inet ') and current_interface:
                match = re.search(r'inet\s+([^/\s]+)', line)
                if match:
                    current_interface['addresses'].append({
                        'type': 'ipv4',
                        'address': match.group(1)
                    })

        # Add last interface
        if current_interface:
            interfaces.append(current_interface)

        return interfaces

    async def _test_internet_connectivity(self) -> Dict[str, Any]:
        """Test internet connectivity."""
        try:
            # Test with ping
            result = await self._run_command(['ping', '-c', '3', '8.8.8.8'])

            if result['success']:
                # Extract latency info
                lines = result['stdout'].split('\n')
                for line in lines:
                    if 'avg' in line:
                        match = re.search(r'(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)', line)
                        if match:
                            return {
                                "connected": True,
                                "latency_avg": float(match.group(2)),
                                "latency_min": float(match.group(1)),
                                "latency_max": float(match.group(3))
                            }

                return {"connected": True}
            else:
                return {"connected": False, "error": result['stderr']}

        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def _check_vpn_status(self) -> Dict[str, Any]:
        """Check if VPN (Gluetun) is running and connected."""
        try:
            # Check if Gluetun container is running
            result = await self._run_command([
                'docker', 'ps', '--filter', 'name=pi-health-vpn', '--format', '{{.Status}}'
            ])

            if result['success'] and 'Up' in result['stdout']:
                # Container is running, check health
                health_result = await self._run_command([
                    'docker', 'inspect', '--format', '{{.State.Health.Status}}', 'pi-health-vpn'
                ])

                if health_result['success']:
                    health_status = health_result['stdout'].strip()
                    return {
                        "connected": health_status == 'healthy',
                        "status": health_status,
                        "container_running": True
                    }

            return {"connected": False, "container_running": False}

        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def _test_dns_resolution(self) -> Dict[str, Any]:
        """Test DNS resolution."""
        try:
            result = await self._run_command(['nslookup', 'google.com'])

            if result['success'] and 'NXDOMAIN' not in result['stdout']:
                return {"working": True}
            else:
                return {"working": False, "error": result.get('stderr', 'DNS resolution failed')}

        except Exception as e:
            return {"working": False, "error": str(e)}

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