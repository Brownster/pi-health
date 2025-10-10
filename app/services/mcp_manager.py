"""
MCP Service Manager - Dynamic service discovery and lifecycle management.

This module provides a pluggable architecture for MCP services, allowing users to:
1. Auto-discover MCP services from plugins directory
2. Start/stop services on-demand
3. Monitor service health and resource usage
4. Add custom MCP services easily
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import threading
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from enum import Enum

import requests


class MCPServiceStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class MCPServiceInfo:
    """Information about an MCP service."""
    id: str
    name: str
    description: str
    port: int
    url: str
    status: MCPServiceStatus
    pid: Optional[int] = None
    last_started: Optional[float] = None
    last_used: Optional[float] = None
    auto_start: bool = True
    config_required: List[str] = None
    health_endpoint: str = "/health"

    def __post_init__(self):
        if self.config_required is None:
            self.config_required = []


class MCPServiceManager:
    """Manages MCP service lifecycle and discovery."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.services: Dict[str, MCPServiceInfo] = {}
        self.processes: Dict[str, subprocess.Popen] = {}
        self.shutdown_timers: Dict[str, threading.Timer] = {}
        self.auto_shutdown_delay = 1800  # 30 minutes

        # Discover and register services
        self._discover_services()

    def _discover_services(self):
        """Auto-discover MCP services from various sources."""

        # Built-in services
        self._register_builtin_services()

        # Docker Compose services
        self._discover_docker_services()

        # User plugins
        self._discover_plugin_services()

        # Configuration-based services
        self._discover_config_services()

    def _register_builtin_services(self):
        """Register built-in MCP services."""
        builtin_services = [
            MCPServiceInfo(
                id="docker",
                name="Docker MCP",
                description="Docker container management and monitoring",
                port=8001,
                url="http://localhost:8001",
                status=MCPServiceStatus.STOPPED,
                config_required=["DOCKER_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="sonarr",
                name="Sonarr MCP",
                description="Sonarr TV series management",
                port=8002,
                url="http://localhost:8002",
                status=MCPServiceStatus.STOPPED,
                config_required=["SONARR_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="radarr",
                name="Radarr MCP",
                description="Radarr movie management",
                port=8003,
                url="http://localhost:8003",
                status=MCPServiceStatus.STOPPED,
                config_required=["RADARR_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="lidarr",
                name="Lidarr MCP",
                description="Lidarr music management",
                port=8004,
                url="http://localhost:8004",
                status=MCPServiceStatus.STOPPED,
                config_required=["LIDARR_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="sabnzbd",
                name="SABnzbd MCP",
                description="SABnzbd download management",
                port=8005,
                url="http://localhost:8005",
                status=MCPServiceStatus.STOPPED,
                config_required=["SABNZBD_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="jellyfin",
                name="Jellyfin MCP",
                description="Jellyfin media server management",
                port=8006,
                url="http://localhost:8006",
                status=MCPServiceStatus.STOPPED,
                config_required=["JELLYFIN_MCP_BASE_URL"]
            ),
            MCPServiceInfo(
                id="jellyseerr",
                name="Jellyseerr MCP",
                description="Jellyseerr media requests",
                port=8007,
                url="http://localhost:8007",
                status=MCPServiceStatus.STOPPED,
                config_required=["JELLYSEERR_MCP_BASE_URL"]
            ),
        ]

        for service in builtin_services:
            self.services[service.id] = service

    def _discover_plugin_services(self):
        """Discover user-defined MCP services from plugins directory."""
        plugins_dir = Path("mcp_plugins")
        if not plugins_dir.exists():
            return

        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir() or plugin_dir.name.startswith('.'):
                continue

            # Look for service definition
            service_file = plugin_dir / "service.py"
            if service_file.exists():
                try:
                    service_info = self._load_plugin_service(plugin_dir)
                    if service_info:
                        self.services[service_info.id] = service_info
                except Exception as e:
                    print(f"Failed to load plugin {plugin_dir.name}: {e}")

    def _load_plugin_service(self, plugin_dir: Path) -> Optional[MCPServiceInfo]:
        """Load service definition from plugin directory."""
        try:
            # Import the service module
            spec = importlib.util.spec_from_file_location(
                f"plugin_{plugin_dir.name}", plugin_dir / "service.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Get service info from module
            if hasattr(module, 'get_service_info'):
                return module.get_service_info()

        except Exception as e:
            print(f"Error loading plugin {plugin_dir.name}: {e}")
            return None

    def _discover_docker_services(self):
        """Auto-discover services from Docker Compose configuration."""
        compose_file = Path("docker-compose.yml")
        if not compose_file.exists():
            return

        try:
            with open(compose_file) as f:
                compose_config = yaml.safe_load(f)

            services = compose_config.get('services', {})

            # Map of service names to MCP configurations
            docker_service_map = {
                'sonarr': {'port': 8989, 'desc': 'TV series management via Docker'},
                'radarr': {'port': 7878, 'desc': 'Movie management via Docker'},
                'lidarr': {'port': 8686, 'desc': 'Music management via Docker'},
                'sabnzbd': {'port': 8080, 'desc': 'Usenet downloader via Docker'},
                'jellyfin': {'port': 8096, 'desc': 'Media server via Docker'},
                'jellyseerr': {'port': 5055, 'desc': 'Media requests via Docker'},
            }

            for service_name, service_config in services.items():
                if service_name in docker_service_map:
                    config = docker_service_map[service_name]

                    # Extract port from Docker Compose if different
                    ports = service_config.get('ports', [])
                    if ports:
                        # Get first port mapping (assumes format "8989:8989")
                        port_mapping = str(ports[0]).split(':')[0]
                        if port_mapping.isdigit():
                            config['port'] = int(port_mapping)

                    # Create MCP service info
                    mcp_service = MCPServiceInfo(
                        id=f"{service_name}-docker",
                        name=f"{service_name.title()} (Docker)",
                        description=config['desc'],
                        port=config['port'],
                        url=f"http://localhost:{config['port']}",
                        status=MCPServiceStatus.UNKNOWN,
                        auto_start=False,  # Don't auto-manage Docker services
                        config_required=[f"{service_name.upper()}_MCP_BASE_URL"]
                    )

                    self.services[mcp_service.id] = mcp_service

        except Exception as e:
            print(f"Error reading Docker Compose configuration: {e}")

    def _discover_config_services(self):
        """Update service configuration from environment/config."""
        for service_id, service in self.services.items():
            # Check if required config is available
            service.status = MCPServiceStatus.STOPPED

            # For builtin services, check if they're configured
            config_available = True
            for req_config in service.config_required:
                if not self.config.get(req_config):
                    config_available = False
                    break

            if not config_available:
                service.status = MCPServiceStatus.UNKNOWN

    def get_all_services(self) -> List[MCPServiceInfo]:
        """Get list of all discovered services."""
        # Update status before returning
        for service in self.services.values():
            self._update_service_status(service)

        return list(self.services.values())

    def get_service(self, service_id: str) -> Optional[MCPServiceInfo]:
        """Get specific service by ID."""
        service = self.services.get(service_id)
        if service:
            self._update_service_status(service)
        return service

    def start_service(self, service_id: str) -> Dict[str, Any]:
        """Start an MCP service."""
        service = self.services.get(service_id)
        if not service:
            return {"success": False, "error": "Service not found"}

        if service.status == MCPServiceStatus.RUNNING:
            return {"success": True, "message": "Service already running"}

        # Handle Docker-managed services differently
        if service_id.endswith('-docker'):
            return self._manage_docker_service(service_id, 'start')

        # Cancel any shutdown timer
        self._cancel_shutdown_timer(service_id)

        try:
            # Check if it's a builtin service
            if service_id in ["docker", "sonarr", "radarr", "lidarr", "sabnzbd", "jellyfin", "jellyseerr"]:
                success = self._start_builtin_service(service)
            else:
                # Plugin service
                success = self._start_plugin_service(service)

            if success:
                service.status = MCPServiceStatus.RUNNING
                service.last_started = time.time()
                service.last_used = time.time()
                return {"success": True, "message": f"Started {service.name}"}
            else:
                service.status = MCPServiceStatus.ERROR
                return {"success": False, "error": f"Failed to start {service.name}"}

        except Exception as e:
            service.status = MCPServiceStatus.ERROR
            return {"success": False, "error": str(e)}

    def stop_service(self, service_id: str) -> Dict[str, Any]:
        """Stop an MCP service."""
        service = self.services.get(service_id)
        if not service:
            return {"success": False, "error": "Service not found"}

        if service.status == MCPServiceStatus.STOPPED:
            return {"success": True, "message": "Service already stopped"}

        # Handle Docker-managed services
        if service_id.endswith('-docker'):
            return self._manage_docker_service(service_id, 'stop')

        # Cancel shutdown timer
        self._cancel_shutdown_timer(service_id)

        try:
            process = self.processes.get(service_id)
            if process:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

                del self.processes[service_id]

            service.status = MCPServiceStatus.STOPPED
            service.pid = None

            return {"success": True, "message": f"Stopped {service.name}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def restart_service(self, service_id: str) -> Dict[str, Any]:
        """Restart an MCP service."""
        # Handle Docker services with direct restart
        if service_id.endswith('-docker'):
            return self._manage_docker_service(service_id, 'restart')

        stop_result = self.stop_service(service_id)
        if not stop_result["success"]:
            return stop_result

        time.sleep(2)  # Brief pause
        return self.start_service(service_id)

    def schedule_auto_shutdown(self, service_id: str):
        """Schedule auto-shutdown of a service after inactivity."""
        service = self.services.get(service_id)
        if not service or not service.auto_start:
            return

        # Cancel existing timer
        self._cancel_shutdown_timer(service_id)

        # Schedule new shutdown
        timer = threading.Timer(
            self.auto_shutdown_delay,
            lambda: self._auto_shutdown_service(service_id)
        )
        timer.start()
        self.shutdown_timers[service_id] = timer

    def mark_service_used(self, service_id: str):
        """Mark service as recently used (resets auto-shutdown timer)."""
        service = self.services.get(service_id)
        if service:
            service.last_used = time.time()
            # Reschedule shutdown
            if service.status == MCPServiceStatus.RUNNING:
                self.schedule_auto_shutdown(service_id)

    def _start_builtin_service(self, service: MCPServiceInfo) -> bool:
        """Start a builtin MCP service."""
        service_dir = f"mcp/{service.id}"
        main_file = f"{service_dir}/main.py"

        if not os.path.exists(main_file):
            return False

        try:
            # Start the service process using the same Python interpreter
            process = subprocess.Popen([
                sys.executable, main_file, "--port", str(service.port)
            ], cwd=".", env=os.environ.copy())

            self.processes[service.id] = process
            service.pid = process.pid

            # Wait a bit and check if it started successfully
            time.sleep(3)
            return self._check_service_health(service)

        except Exception as e:
            print(f"Error starting {service.name}: {e}")
            return False

    def _start_plugin_service(self, service: MCPServiceInfo) -> bool:
        """Start a plugin MCP service."""
        plugin_dir = Path("mcp_plugins") / service.id
        main_file = plugin_dir / "main.py"

        if not main_file.exists():
            return False

        try:
            process = subprocess.Popen([
                sys.executable, str(main_file), "--port", str(service.port)
            ], cwd=str(plugin_dir), env=os.environ.copy())

            self.processes[service.id] = process
            service.pid = process.pid

            time.sleep(3)
            return self._check_service_health(service)

        except Exception as e:
            print(f"Error starting plugin {service.name}: {e}")
            return False

    def _check_service_health(self, service: MCPServiceInfo) -> bool:
        """Check if service is healthy via HTTP health check."""
        try:
            response = requests.get(
                f"{service.url}{service.health_endpoint}",
                timeout=5
            )
            return response.status_code == 200
        except:
            return False

    def _update_service_status(self, service: MCPServiceInfo):
        """Update service status by checking health."""
        if service.pid:
            # Check if process is still running
            process = self.processes.get(service.id)
            if process and process.poll() is None:
                # Process running, check health
                if self._check_service_health(service):
                    service.status = MCPServiceStatus.RUNNING
                else:
                    service.status = MCPServiceStatus.ERROR
            else:
                # Process died
                service.status = MCPServiceStatus.STOPPED
                service.pid = None
                if service.id in self.processes:
                    del self.processes[service.id]

    def _cancel_shutdown_timer(self, service_id: str):
        """Cancel auto-shutdown timer for a service."""
        timer = self.shutdown_timers.get(service_id)
        if timer:
            timer.cancel()
            del self.shutdown_timers[service_id]

    def _auto_shutdown_service(self, service_id: str):
        """Auto-shutdown a service due to inactivity."""
        service = self.services.get(service_id)
        if not service:
            return

        # Check if service was used recently
        if service.last_used and (time.time() - service.last_used) < self.auto_shutdown_delay:
            # Still being used, reschedule
            self.schedule_auto_shutdown(service_id)
            return

        # Shutdown the service
        print(f"Auto-stopping {service.name} due to inactivity")
        self.stop_service(service_id)

    def _manage_docker_service(self, service_id: str, action: str) -> Dict[str, Any]:
        """Manage Docker Compose services."""
        service_name = service_id.replace('-docker', '')

        try:
            if action == 'start':
                result = subprocess.run(
                    ['docker-compose', 'up', '-d', service_name],
                    capture_output=True, text=True, timeout=60
                )
            elif action == 'stop':
                result = subprocess.run(
                    ['docker-compose', 'stop', service_name],
                    capture_output=True, text=True, timeout=30
                )
            elif action == 'restart':
                result = subprocess.run(
                    ['docker-compose', 'restart', service_name],
                    capture_output=True, text=True, timeout=60
                )
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

            if result.returncode == 0:
                return {"success": True, "message": f"Docker service {service_name} {action} successful"}
            else:
                return {"success": False, "error": f"Docker command failed: {result.stderr}"}

        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Docker {action} command timed out"}
        except FileNotFoundError:
            return {"success": False, "error": "docker-compose command not found"}
        except Exception as e:
            return {"success": False, "error": f"Docker {action} failed: {str(e)}"}

    def get_resource_usage(self) -> Dict[str, Any]:
        """Get resource usage statistics for all running services."""
        running_services = []
        total_memory = 0

        for service in self.services.values():
            if service.status == MCPServiceStatus.RUNNING and service.pid:
                try:
                    import psutil
                    process = psutil.Process(service.pid)
                    memory_mb = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent()

                    running_services.append({
                        "id": service.id,
                        "name": service.name,
                        "memory_mb": round(memory_mb, 1),
                        "cpu_percent": round(cpu_percent, 1)
                    })
                    total_memory += memory_mb
                except:
                    pass

        return {
            "running_services": running_services,
            "total_services": len(self.services),
            "active_services": len(running_services),
            "total_memory_mb": round(total_memory, 1)
        }

    def cleanup(self):
        """Cleanup all running services and timers."""
        # Cancel all shutdown timers
        for timer in self.shutdown_timers.values():
            timer.cancel()
        self.shutdown_timers.clear()

        # Stop all running services
        for service_id in list(self.processes.keys()):
            self.stop_service(service_id)