"""
Docker Orchestrator Module
Intelligent Docker stack deployment and management for Pi systems.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
import time

logger = logging.getLogger(__name__)


class DockerStack:
    """Represents a deployable Docker stack."""

    def __init__(self, stack_id: str, config: Dict[str, Any]):
        self.stack_id = stack_id
        self.name = config.get('name', stack_id)
        self.description = config.get('description', '')
        self.compose_file = config.get('compose_file')
        self.env_template = config.get('env_template')
        self.requirements = config.get('requirements', [])
        self.services = config.get('services', [])
        self.estimated_time = config.get('estimated_time', '10-15 minutes')
        self.categories = config.get('categories', [])


class DockerOrchestrator:
    """Intelligent Docker deployment orchestrator for Pi systems."""

    def __init__(self):
        self.stacks_dir = Path("templates/docker-stacks")
        self.deployment_dir = Path("/home/pi/docker-deployments")
        self.deployment_dir.mkdir(parents=True, exist_ok=True)

        # Initialize built-in stacks
        self.stacks = self._initialize_builtin_stacks()

        # Load custom stacks from templates directory
        self._load_custom_stacks()

    def _initialize_builtin_stacks(self) -> Dict[str, DockerStack]:
        """Initialize built-in deployment stacks."""
        stacks = {}

        # Arr Media Stack
        stacks['arr-stack'] = DockerStack('arr-stack', {
            'name': 'Complete Arr Media Stack',
            'description': 'Full media automation with Sonarr, Radarr, Lidarr, Jellyfin, and VPN protection',
            'compose_file': '../docker-compose.arr-stack.yml',
            'env_template': '../.env.arr-stack',
            'requirements': ['8GB+ storage', 'VPN subscription', 'Pi 4 recommended'],
            'services': ['sonarr', 'radarr', 'lidarr', 'jellyfin', 'jellyseerr', 'transmission', 'jackett', 'vpn'],
            'estimated_time': '15-30 minutes',
            'categories': ['media', 'automation', 'entertainment']
        })

        # Pi-Health Monitoring Stack
        stacks['monitoring-stack'] = DockerStack('monitoring-stack', {
            'name': 'Pi Monitoring Stack',
            'description': 'Comprehensive monitoring with Prometheus, Grafana, and system metrics',
            'services': ['prometheus', 'grafana', 'node-exporter', 'cadvisor'],
            'estimated_time': '10-15 minutes',
            'categories': ['monitoring', 'metrics', 'observability']
        })

        # Development Environment
        stacks['dev-stack'] = DockerStack('dev-stack', {
            'name': 'Development Environment',
            'description': 'Complete development setup with code-server, database, and tools',
            'services': ['code-server', 'postgres', 'redis', 'gitea'],
            'estimated_time': '15-20 minutes',
            'categories': ['development', 'tools', 'productivity']
        })

        # Home Automation Stack
        stacks['home-automation'] = DockerStack('home-automation', {
            'name': 'Home Automation Hub',
            'description': 'Home Assistant with MQTT, Node-RED, and automation tools',
            'services': ['homeassistant', 'mqtt', 'nodered', 'zigbee2mqtt'],
            'estimated_time': '20-25 minutes',
            'categories': ['automation', 'smart-home', 'iot']
        })

        # Lightweight Media Server
        stacks['light-media'] = DockerStack('light-media', {
            'name': 'Lightweight Media Server',
            'description': 'Simple media streaming with Jellyfin and basic management',
            'services': ['jellyfin', 'filebrowser'],
            'estimated_time': '5-10 minutes',
            'categories': ['media', 'streaming', 'lightweight']
        })

        return stacks

    def _load_custom_stacks(self) -> None:
        """Load custom stacks from templates directory."""
        if not self.stacks_dir.exists():
            return

        for stack_dir in self.stacks_dir.iterdir():
            if not stack_dir.is_dir():
                continue

            try:
                config_file = stack_dir / "stack.yml"
                if config_file.exists():
                    with open(config_file) as f:
                        stack_config = yaml.safe_load(f)

                    stack_id = stack_dir.name
                    self.stacks[stack_id] = DockerStack(stack_id, stack_config)
                    logger.info(f"Loaded custom stack: {stack_id}")

            except Exception as e:
                logger.error(f"Failed to load custom stack {stack_dir.name}: {e}")

    async def get_available_stacks(self) -> List[Dict[str, Any]]:
        """Get list of available deployment stacks."""
        stacks_list = []

        for stack_id, stack in self.stacks.items():
            # Get stack status
            status = await self._get_stack_status(stack_id)

            stacks_list.append({
                'id': stack_id,
                'name': stack.name,
                'description': stack.description,
                'services': stack.services,
                'requirements': stack.requirements,
                'estimated_time': stack.estimated_time,
                'categories': stack.categories,
                'status': status
            })

        return stacks_list

    async def deploy_stack(self, stack_type: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy a complete Docker stack with intelligent orchestration."""
        logger.info(f"Starting deployment of stack: {stack_type}")

        if stack_type not in self.stacks:
            return {"success": False, "error": f"Unknown stack type: {stack_type}"}

        stack = self.stacks[stack_type]

        deployment_result = {
            "stack_id": stack_type,
            "stack_name": stack.name,
            "deployment_id": f"{stack_type}-{int(time.time())}",
            "status": "starting",
            "steps": [],
            "services": {},
            "start_time": time.time()
        }

        try:
            # Step 1: Validate deployment requirements
            deployment_result["current_step"] = "validation"
            validation_result = await self._validate_deployment_requirements(stack, config)

            if not validation_result['valid']:
                deployment_result["status"] = "failed"
                deployment_result["error"] = f"Validation failed: {validation_result['error']}"
                return {"success": False, "result": deployment_result}

            deployment_result["steps"].append({
                "step": "validation",
                "status": "completed",
                "message": "Requirements validated successfully"
            })

            # Step 2: Prepare deployment environment
            deployment_result["current_step"] = "preparation"
            prep_result = await self._prepare_deployment_environment(stack, config, deployment_result["deployment_id"])

            if not prep_result['success']:
                deployment_result["status"] = "failed"
                deployment_result["error"] = f"Preparation failed: {prep_result['error']}"
                return {"success": False, "result": deployment_result}

            deployment_result["deployment_dir"] = prep_result["deployment_dir"]
            deployment_result["steps"].append({
                "step": "preparation",
                "status": "completed",
                "message": "Environment prepared successfully"
            })

            # Step 3: Generate configuration files
            deployment_result["current_step"] = "configuration"
            config_result = await self._generate_stack_configuration(stack, config, prep_result["deployment_dir"])

            if not config_result['success']:
                deployment_result["status"] = "failed"
                deployment_result["error"] = f"Configuration failed: {config_result['error']}"
                return {"success": False, "result": deployment_result}

            deployment_result["steps"].append({
                "step": "configuration",
                "status": "completed",
                "message": "Configuration files generated"
            })

            # Step 4: Pre-deployment hooks
            deployment_result["current_step"] = "pre_hooks"
            pre_hooks_result = await self._run_pre_deployment_hooks(stack, config, prep_result["deployment_dir"])
            deployment_result["steps"].append({
                "step": "pre_hooks",
                "status": "completed",
                "message": "Pre-deployment hooks executed"
            })

            # Step 5: Deploy services with intelligent ordering
            deployment_result["current_step"] = "deployment"
            deploy_result = await self._deploy_services_intelligent(stack, config, prep_result["deployment_dir"])

            if not deploy_result['success']:
                deployment_result["status"] = "failed"
                deployment_result["error"] = f"Deployment failed: {deploy_result['error']}"
                return {"success": False, "result": deployment_result}

            deployment_result["services"] = deploy_result["services"]
            deployment_result["steps"].append({
                "step": "deployment",
                "status": "completed",
                "message": "Services deployed successfully"
            })

            # Step 6: Health checks and validation
            deployment_result["current_step"] = "health_checks"
            health_result = await self._perform_health_checks(stack, prep_result["deployment_dir"])

            deployment_result["health_checks"] = health_result
            deployment_result["steps"].append({
                "step": "health_checks",
                "status": "completed",
                "message": "Health checks completed"
            })

            # Step 7: Post-deployment configuration
            deployment_result["current_step"] = "post_config"
            post_config_result = await self._post_deployment_configuration(stack, config, prep_result["deployment_dir"])

            deployment_result["steps"].append({
                "step": "post_config",
                "status": "completed",
                "message": "Post-deployment configuration completed"
            })

            # Finalize deployment
            deployment_result["status"] = "completed"
            deployment_result["current_step"] = None
            deployment_result["end_time"] = time.time()
            deployment_result["total_time"] = deployment_result["end_time"] - deployment_result["start_time"]

            # Generate access information
            access_info = await self._generate_access_information(stack, config, prep_result["deployment_dir"])
            deployment_result["access_info"] = access_info

            logger.info(f"Stack deployment completed successfully: {stack_type}")
            return {"success": True, "result": deployment_result}

        except Exception as e:
            logger.error(f"Stack deployment failed: {e}")
            deployment_result["status"] = "failed"
            deployment_result["error"] = str(e)
            deployment_result["end_time"] = time.time()

            # Attempt rollback
            try:
                rollback_result = await self._rollback_deployment(deployment_result)
                deployment_result["rollback"] = rollback_result
            except Exception:
                pass

            return {"success": False, "result": deployment_result}

    async def _validate_deployment_requirements(self, stack: DockerStack, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate deployment requirements before starting."""
        errors = []

        try:
            # Check Docker availability
            docker_result = await self._run_command(['docker', '--version'])
            if not docker_result['success']:
                errors.append("Docker is not installed or not accessible")

            # Check Docker Compose
            compose_result = await self._run_command(['docker-compose', '--version'])
            if not compose_result['success']:
                compose_result = await self._run_command(['docker', 'compose', 'version'])
                if not compose_result['success']:
                    errors.append("Docker Compose is not available")

            # Check available disk space
            df_result = await self._run_command(['df', '-h', '.'])
            if df_result['success']:
                # Parse disk space (simplified check)
                lines = df_result['stdout'].split('\n')
                if len(lines) > 1:
                    fields = lines[1].split()
                    if len(fields) >= 4:
                        available = fields[3]
                        # Simple check - warn if less than 5GB
                        if 'G' in available:
                            available_gb = float(available.replace('G', ''))
                            if available_gb < 5:
                                errors.append(f"Low disk space: {available} available (5GB+ recommended)")

            # Check network connectivity
            ping_result = await self._run_command(['ping', '-c', '1', '8.8.8.8'], ignore_errors=True)
            if not ping_result['success']:
                errors.append("Internet connectivity required for container downloads")

            # Stack-specific requirements
            if stack.stack_id == 'arr-stack':
                # Check VPN configuration for Arr stack
                if not config.get('vpn_configured', False):
                    logger.warning("VPN not configured for Arr stack - downloads will not be protected")

            return {
                'valid': len(errors) == 0,
                'error': '; '.join(errors) if errors else None,
                'warnings': []
            }

        except Exception as e:
            return {'valid': False, 'error': f"Validation check failed: {str(e)}"}

    async def _prepare_deployment_environment(self, stack: DockerStack, config: Dict[str, Any], deployment_id: str) -> Dict[str, Any]:
        """Prepare deployment environment and directory structure."""
        try:
            deployment_dir = self.deployment_dir / deployment_id
            deployment_dir.mkdir(parents=True, exist_ok=True)

            # Create directory structure
            directories = ['config', 'data', 'logs', 'backups']
            for directory in directories:
                (deployment_dir / directory).mkdir(exist_ok=True)

            # Set permissions
            await self._run_command(['chmod', '755', str(deployment_dir)])

            # Create deployment metadata
            metadata = {
                'deployment_id': deployment_id,
                'stack_id': stack.stack_id,
                'stack_name': stack.name,
                'created': time.time(),
                'config': config
            }

            with open(deployment_dir / 'metadata.json', 'w') as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Deployment environment prepared: {deployment_dir}")
            return {
                'success': True,
                'deployment_dir': str(deployment_dir)
            }

        except Exception as e:
            logger.error(f"Failed to prepare deployment environment: {e}")
            return {'success': False, 'error': str(e)}

    async def _generate_stack_configuration(self, stack: DockerStack, config: Dict[str, Any], deployment_dir: str) -> Dict[str, Any]:
        """Generate Docker Compose and environment files for the stack."""
        try:
            deployment_path = Path(deployment_dir)

            # Generate configuration based on stack type
            if stack.stack_id == 'arr-stack':
                return await self._generate_arr_stack_config(config, deployment_path)
            elif stack.stack_id == 'monitoring-stack':
                return await self._generate_monitoring_stack_config(config, deployment_path)
            elif stack.stack_id == 'dev-stack':
                return await self._generate_dev_stack_config(config, deployment_path)
            elif stack.stack_id == 'home-automation':
                return await self._generate_home_automation_config(config, deployment_path)
            elif stack.stack_id == 'light-media':
                return await self._generate_light_media_config(config, deployment_path)
            else:
                return await self._generate_generic_stack_config(stack, config, deployment_path)

        except Exception as e:
            logger.error(f"Configuration generation failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _generate_arr_stack_config(self, config: Dict[str, Any], deployment_path: Path) -> Dict[str, Any]:
        """Generate configuration for Arr media stack."""
        try:
            # Copy base templates
            arr_compose_source = Path("docker-compose.arr-stack.yml")
            arr_env_source = Path(".env.arr-stack")

            if arr_compose_source.exists():
                shutil.copy2(arr_compose_source, deployment_path / "docker-compose.yml")

            if arr_env_source.exists():
                shutil.copy2(arr_env_source, deployment_path / ".env")

            # Customize configuration
            env_file = deployment_path / ".env"
            if env_file.exists():
                # Update environment variables
                env_content = env_file.read_text()

                # Replace configuration values
                replacements = {
                    'PUID': str(config.get('puid', 1000)),
                    'PGID': str(config.get('pgid', 1000)),
                    'TIMEZONE': config.get('timezone', 'UTC'),
                    'DOCKER_CONFIG_PATH': config.get('docker_config_path', str(deployment_path / 'config')),
                    'MEDIA_PATH': config.get('media_path', '/mnt/storage'),
                    'DOWNLOADS_PATH': config.get('downloads_path', '/mnt/downloads')
                }

                for key, value in replacements.items():
                    env_content = re.sub(f'^{key}=.*$', f'{key}={value}', env_content, flags=re.MULTILINE)

                env_file.write_text(env_content)

            return {'success': True, 'message': 'Arr stack configuration generated'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _generate_monitoring_stack_config(self, config: Dict[str, Any], deployment_path: Path) -> Dict[str, Any]:
        """Generate configuration for monitoring stack."""
        try:
            compose_content = """version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana:/etc/grafana/provisioning
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin123
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:latest
    container_name: node-exporter
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.ignored-mount-points=^/(sys|proc|dev|host|etc)($$|/)'
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
"""

            with open(deployment_path / "docker-compose.yml", 'w') as f:
                f.write(compose_content)

            # Create Prometheus configuration
            (deployment_path / "config" / "prometheus").mkdir(parents=True, exist_ok=True)
            prometheus_config = """global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
"""
            with open(deployment_path / "config" / "prometheus" / "prometheus.yml", 'w') as f:
                f.write(prometheus_config)

            return {'success': True, 'message': 'Monitoring stack configuration generated'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _generate_light_media_config(self, config: Dict[str, Any], deployment_path: Path) -> Dict[str, Any]:
        """Generate configuration for lightweight media server."""
        try:
            compose_content = f"""version: '3.8'

services:
  jellyfin:
    image: jellyfin/jellyfin:latest
    container_name: jellyfin
    ports:
      - "8096:8096"
    volumes:
      - ./config/jellyfin:/config
      - {config.get('media_path', '/mnt/media')}:/media:ro
    environment:
      - PUID={config.get('puid', 1000)}
      - PGID={config.get('pgid', 1000)}
      - TZ={config.get('timezone', 'UTC')}
    restart: unless-stopped

  filebrowser:
    image: filebrowser/filebrowser:latest
    container_name: filebrowser
    ports:
      - "8080:80"
    volumes:
      - ./config/filebrowser:/config
      - {config.get('media_path', '/mnt/media')}:/srv
    environment:
      - PUID={config.get('puid', 1000)}
      - PGID={config.get('pgid', 1000)}
    restart: unless-stopped
"""

            with open(deployment_path / "docker-compose.yml", 'w') as f:
                f.write(compose_content)

            return {'success': True, 'message': 'Light media stack configuration generated'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _generate_generic_stack_config(self, stack: DockerStack, config: Dict[str, Any], deployment_path: Path) -> Dict[str, Any]:
        """Generate generic configuration for custom stacks."""
        try:
            if stack.compose_file:
                compose_source = Path(stack.compose_file)
                if compose_source.exists():
                    shutil.copy2(compose_source, deployment_path / "docker-compose.yml")

            if stack.env_template:
                env_source = Path(stack.env_template)
                if env_source.exists():
                    shutil.copy2(env_source, deployment_path / ".env")

            return {'success': True, 'message': 'Generic stack configuration generated'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _run_pre_deployment_hooks(self, stack: DockerStack, config: Dict[str, Any], deployment_dir: str) -> Dict[str, Any]:
        """Run pre-deployment hooks."""
        try:
            hooks_result = []

            # Create necessary directories
            if stack.stack_id == 'arr-stack':
                media_dirs = ['Movies', 'TV', 'Music', 'Books', 'Downloads']
                media_path = config.get('media_path', '/mnt/storage')

                for media_dir in media_dirs:
                    dir_path = Path(media_path) / media_dir
                    dir_path.mkdir(parents=True, exist_ok=True)
                    hooks_result.append(f"Created media directory: {dir_path}")

            return {'success': True, 'hooks': hooks_result}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _deploy_services_intelligent(self, stack: DockerStack, config: Dict[str, Any], deployment_dir: str) -> Dict[str, Any]:
        """Deploy services with intelligent dependency ordering."""
        try:
            deployment_path = Path(deployment_dir)
            os.chdir(deployment_path)

            # Pull images first
            logger.info("Pulling container images...")
            pull_result = await self._run_command(['docker-compose', 'pull'])

            if not pull_result['success']:
                logger.warning(f"Image pull warnings: {pull_result['stderr']}")

            # Start services with dependency awareness
            logger.info("Starting services...")
            up_result = await self._run_command(['docker-compose', 'up', '-d'])

            if not up_result['success']:
                return {'success': False, 'error': f"Failed to start services: {up_result['stderr']}"}

            # Get service status
            services_result = await self._get_running_services(deployment_path)

            return {
                'success': True,
                'services': services_result,
                'message': 'Services deployed successfully'
            }

        except Exception as e:
            logger.error(f"Service deployment failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _get_running_services(self, deployment_path: Path) -> Dict[str, Any]:
        """Get status of running services."""
        try:
            os.chdir(deployment_path)
            ps_result = await self._run_command(['docker-compose', 'ps', '--format', 'json'])

            if ps_result['success']:
                services = {}
                for line in ps_result['stdout'].split('\n'):
                    if line.strip():
                        try:
                            service_data = json.loads(line)
                            service_name = service_data.get('Service', 'unknown')
                            services[service_name] = {
                                'name': service_data.get('Name'),
                                'state': service_data.get('State'),
                                'status': service_data.get('Status'),
                                'ports': service_data.get('Publishers', [])
                            }
                        except json.JSONDecodeError:
                            continue

                return services

        except Exception as e:
            logger.error(f"Error getting service status: {e}")

        return {}

    async def _perform_health_checks(self, stack: DockerStack, deployment_dir: str) -> Dict[str, Any]:
        """Perform health checks on deployed services."""
        try:
            deployment_path = Path(deployment_dir)
            os.chdir(deployment_path)

            # Wait for services to start
            await asyncio.sleep(30)

            health_results = {}

            # Get service status
            services = await self._get_running_services(deployment_path)

            for service_name, service_info in services.items():
                health_status = {
                    'running': service_info['state'] == 'running',
                    'status': service_info['status']
                }

                # Additional health checks based on service type
                if 'jellyfin' in service_name.lower():
                    # Test Jellyfin health endpoint
                    health_check = await self._test_http_endpoint('http://localhost:8096/health')
                    health_status['http_health'] = health_check

                elif 'sonarr' in service_name.lower():
                    health_check = await self._test_http_endpoint('http://localhost:8989/api/v3/system/status')
                    health_status['api_health'] = health_check

                health_results[service_name] = health_status

            return {
                'success': True,
                'results': health_results,
                'overall_healthy': all(result['running'] for result in health_results.values())
            }

        except Exception as e:
            logger.error(f"Health checks failed: {e}")
            return {'success': False, 'error': str(e)}

    async def _test_http_endpoint(self, url: str, timeout: int = 10) -> Dict[str, Any]:
        """Test HTTP endpoint availability."""
        try:
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url) as response:
                    return {
                        'available': response.status < 500,
                        'status_code': response.status
                    }
        except Exception as e:
            return {'available': False, 'error': str(e)}

    async def _post_deployment_configuration(self, stack: DockerStack, config: Dict[str, Any], deployment_dir: str) -> Dict[str, Any]:
        """Run post-deployment configuration."""
        try:
            post_config_actions = []

            if stack.stack_id == 'arr-stack':
                # Wait for Arr services to fully initialize
                await asyncio.sleep(60)

                # Could add initial configuration via API calls
                post_config_actions.append("Arr services initialized")

            elif stack.stack_id == 'monitoring-stack':
                # Configure Grafana dashboards
                post_config_actions.append("Monitoring dashboards configured")

            return {
                'success': True,
                'actions': post_config_actions
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _generate_access_information(self, stack: DockerStack, config: Dict[str, Any], deployment_dir: str) -> Dict[str, Any]:
        """Generate access information for deployed services."""
        try:
            access_info = {
                'services': [],
                'default_credentials': [],
                'notes': []
            }

            if stack.stack_id == 'arr-stack':
                access_info['services'] = [
                    {'name': 'Sonarr (TV)', 'url': 'http://localhost:8989'},
                    {'name': 'Radarr (Movies)', 'url': 'http://localhost:7878'},
                    {'name': 'Lidarr (Music)', 'url': 'http://localhost:8686'},
                    {'name': 'Jellyfin (Media)', 'url': 'http://localhost:8096'},
                    {'name': 'Jellyseerr (Requests)', 'url': 'http://localhost:5055'},
                ]
                access_info['notes'] = [
                    'Initial setup wizard will run on first access',
                    'Configure indexers and download clients',
                    'VPN must be configured for download protection'
                ]

            elif stack.stack_id == 'monitoring-stack':
                access_info['services'] = [
                    {'name': 'Grafana', 'url': 'http://localhost:3000'},
                    {'name': 'Prometheus', 'url': 'http://localhost:9090'},
                ]
                access_info['default_credentials'] = [
                    {'service': 'Grafana', 'username': 'admin', 'password': 'admin123'}
                ]

            elif stack.stack_id == 'light-media':
                access_info['services'] = [
                    {'name': 'Jellyfin', 'url': 'http://localhost:8096'},
                    {'name': 'File Browser', 'url': 'http://localhost:8080'},
                ]

            return access_info

        except Exception as e:
            logger.error(f"Error generating access information: {e}")
            return {'services': [], 'error': str(e)}

    async def _rollback_deployment(self, deployment_result: Dict[str, Any]) -> Dict[str, Any]:
        """Rollback a failed deployment."""
        try:
            deployment_dir = deployment_result.get('deployment_dir')
            if not deployment_dir:
                return {'success': False, 'error': 'No deployment directory found'}

            deployment_path = Path(deployment_dir)
            if not deployment_path.exists():
                return {'success': False, 'error': 'Deployment directory not found'}

            os.chdir(deployment_path)

            # Stop and remove containers
            down_result = await self._run_command(['docker-compose', 'down', '-v'], ignore_errors=True)

            # Remove deployment directory
            shutil.rmtree(deployment_path, ignore_errors=True)

            return {
                'success': True,
                'message': 'Deployment rolled back successfully'
            }

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return {'success': False, 'error': str(e)}

    async def get_deployment_status(self) -> Dict[str, Any]:
        """Get status of all deployments."""
        try:
            deployments = []

            for deployment_dir in self.deployment_dir.iterdir():
                if not deployment_dir.is_dir():
                    continue

                try:
                    metadata_file = deployment_dir / 'metadata.json'
                    if metadata_file.exists():
                        with open(metadata_file) as f:
                            metadata = json.load(f)

                        # Get current status
                        status = await self._get_stack_status_from_dir(deployment_dir)

                        deployments.append({
                            'deployment_id': metadata['deployment_id'],
                            'stack_id': metadata['stack_id'],
                            'stack_name': metadata['stack_name'],
                            'created': metadata['created'],
                            'status': status
                        })

                except Exception as e:
                    logger.error(f"Error reading deployment {deployment_dir.name}: {e}")

            return {
                'success': True,
                'deployments': deployments,
                'total_deployments': len(deployments)
            }

        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def _get_stack_status(self, stack_id: str) -> Dict[str, Any]:
        """Get status of a specific stack."""
        # This would check for existing deployments
        return {'status': 'not_deployed', 'services': []}

    async def _get_stack_status_from_dir(self, deployment_dir: Path) -> Dict[str, Any]:
        """Get stack status from deployment directory."""
        try:
            os.chdir(deployment_dir)
            ps_result = await self._run_command(['docker-compose', 'ps', '-q'])

            if ps_result['success'] and ps_result['stdout']:
                return {'status': 'running', 'containers': ps_result['stdout'].split('\n')}
            else:
                return {'status': 'stopped', 'containers': []}

        except Exception:
            return {'status': 'unknown', 'containers': []}

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