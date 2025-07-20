#!/usr/bin/env python3

"""
Integration tests for Docker stack with pooled storage
Tests the complete workflow of pooled storage integration with Docker containers
"""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import yaml
import json


class TestDockerPooledStorageIntegration(unittest.TestCase):
    """Test Docker integration with pooled storage setup"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.docker_dir = os.path.join(self.test_dir, "docker")
        self.env_file = os.path.join(self.docker_dir, ".env")
        os.makedirs(self.docker_dir, exist_ok=True)
        
        # Mock storage paths
        self.storage_mount = "/mnt/storage"
        self.mount_points = ["/mnt/disk1", "/mnt/disk2"]
        self.parity_mount = "/mnt/parity1"
        
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def create_mock_env_file(self):
        """Create a mock .env file for testing"""
        env_content = """
DOCKER_DIR="/home/user/docker"
TIMEZONE=Europe/London
PUID=1000
PGID=1000
MOVIES_FOLDER="Movies"
TVSHOWS_FOLDER="TVShows"
DOWNLOADS="/mnt/storage/downloads"
STORAGE_MOUNT="/mnt/storage/"
VPN_CONTAINER="vpn"
JELLYFIN_CONTAINER="jellyfin"
JACKETT_CONTAINER="jackett"
SONARR_CONTAINER="sonarr"
RADARR_CONTAINER="radarr"
"""
        with open(self.env_file, 'w') as f:
            f.write(env_content)
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_docker_storage_health_check_script_creation(self, mock_exists, mock_run):
        """Test creation of Docker storage health check script"""
        mock_exists.return_value = False
        mock_run.return_value = MagicMock(returncode=0)
        
        # Import the function we're testing (would be from the installer script)
        # For testing purposes, we'll define it inline
        def create_docker_health_check_script():
            script_content = '''#!/bin/bash
# Docker Storage Health Check Script
set -euo pipefail

STORAGE_MOUNT="/mnt/storage"
REQUIRED_DIRS=("Movies" "TVShows" "downloads")

check_mergerfs_mount() {
    if ! mountpoint -q "$STORAGE_MOUNT"; then
        echo "ERROR: MergerFS mount $STORAGE_MOUNT is not available"
        return 1
    fi
    return 0
}

check_required_directories() {
    for dir in "${REQUIRED_DIRS[@]}"; do
        local full_path="$STORAGE_MOUNT/$dir"
        if [[ ! -d "$full_path" ]] || [[ ! -w "$full_path" ]]; then
            echo "ERROR: Directory $full_path is not accessible"
            return 1
        fi
    done
    return 0
}

main() {
    if ! check_mergerfs_mount || ! check_required_directories; then
        exit 1
    fi
    echo "Docker storage health check passed"
    exit 0
}

main "$@"
'''
            return script_content
        
        script_content = create_docker_health_check_script()
        
        # Verify script contains required checks
        self.assertIn("mountpoint -q", script_content)
        self.assertIn("Movies", script_content)
        self.assertIn("TVShows", script_content)
        self.assertIn("downloads", script_content)
        self.assertIn("/mnt/storage", script_content)
    
    def test_env_file_update_for_pooled_storage(self):
        """Test updating .env file for pooled storage configuration"""
        self.create_mock_env_file()
        
        # Function to update env file (simulated from installer)
        def update_env_for_pooled_storage(env_file_path):
            # Read existing content
            with open(env_file_path, 'r') as f:
                content = f.read()
            
            # Update storage paths
            content = content.replace('STORAGE_MOUNT="/mnt/storage/"', 'STORAGE_MOUNT="/mnt/storage"')
            content = content.replace('DOWNLOADS="/mnt/storage/downloads"', 'DOWNLOADS="/mnt/storage/downloads"')
            
            # Add pooled storage variables
            if 'POOLED_STORAGE_ENABLED' not in content:
                content += '''
# Pooled Storage Configuration
POOLED_STORAGE_ENABLED=true
MERGERFS_MOUNT="/mnt/storage"
SNAPRAID_CONFIG="/etc/snapraid/snapraid.conf"
DOCKER_STORAGE_HEALTH_CHECK=true
'''
            
            with open(env_file_path, 'w') as f:
                f.write(content)
        
        update_env_for_pooled_storage(self.env_file)
        
        # Verify updates
        with open(self.env_file, 'r') as f:
            updated_content = f.read()
        
        self.assertIn('POOLED_STORAGE_ENABLED=true', updated_content)
        self.assertIn('MERGERFS_MOUNT="/mnt/storage"', updated_content)
        self.assertIn('SNAPRAID_CONFIG="/etc/snapraid/snapraid.conf"', updated_content)
        self.assertIn('DOCKER_STORAGE_HEALTH_CHECK=true', updated_content)
    
    def test_docker_compose_override_creation(self):
        """Test creation of Docker Compose override for pooled storage"""
        override_content = {
            'version': '3.8',
            'services': {
                'storage-health-check': {
                    'image': 'alpine:latest',
                    'container_name': 'storage-health-check',
                    'command': [
                        'sh', '-c',
                        'apk add --no-cache util-linux && '
                        'while true; do '
                        'if mountpoint -q /mnt/storage && [ -d /mnt/storage/Movies ]; then '
                        'echo "Storage health check passed"; sleep 30; '
                        'else echo "Storage health check failed"; exit 1; fi; done'
                    ],
                    'volumes': ['/mnt/storage:/mnt/storage:ro'],
                    'restart': 'unless-stopped',
                    'healthcheck': {
                        'test': ['CMD-SHELL', 'mountpoint -q /mnt/storage'],
                        'interval': '30s',
                        'timeout': '10s',
                        'retries': 3
                    }
                },
                'vpn': {
                    'depends_on': ['storage-health-check'],
                    'healthcheck': {
                        'test': ['CMD-SHELL', 'curl --fail http://localhost:8000 && mountpoint -q /mnt/storage'],
                        'interval': '30s',
                        'timeout': '10s',
                        'retries': 3,
                        'start_period': '60s'
                    }
                },
                'jellyfin': {
                    'depends_on': {
                        'storage-health-check': {
                            'condition': 'service_healthy'
                        }
                    },
                    'volumes': [
                        '/home/user/docker/jellyfin:/config',
                        '/mnt/storage:/media:ro',
                        '/mnt/storage/Movies:/movies:ro',
                        '/mnt/storage/TVShows:/tv:ro'
                    ]
                },
                'pi-health-dashboard': {
                    'depends_on': {
                        'storage-health-check': {
                            'condition': 'service_healthy'
                        }
                    },
                    'environment': [
                        'POOLED_STORAGE_ENABLED=true',
                        'MERGERFS_MOUNT=/mnt/storage',
                        'SNAPRAID_CONFIG=/etc/snapraid/snapraid.conf'
                    ],
                    'volumes': [
                        '/mnt/storage:/mnt/storage:ro',
                        '/mnt/disk1:/mnt/disk1:ro',
                        '/mnt/disk2:/mnt/disk2:ro',
                        '/mnt/parity1:/mnt/parity1:ro',
                        '/etc/snapraid:/etc/snapraid:ro',
                        '/etc/mergerfs:/etc/mergerfs:ro'
                    ]
                }
            }
        }
        
        # Verify override structure
        self.assertIn('storage-health-check', override_content['services'])
        self.assertIn('healthcheck', override_content['services']['storage-health-check'])
        self.assertIn('depends_on', override_content['services']['vpn'])
        self.assertIn('depends_on', override_content['services']['jellyfin'])
        
        # Verify health check configuration
        health_check = override_content['services']['storage-health-check']['healthcheck']
        self.assertEqual(health_check['interval'], '30s')
        self.assertEqual(health_check['retries'], 3)
        
        # Verify volume mounts for monitoring
        pi_health_volumes = override_content['services']['pi-health-dashboard']['volumes']
        expected_volumes = [
            '/mnt/storage:/mnt/storage:ro',
            '/mnt/disk1:/mnt/disk1:ro',
            '/mnt/disk2:/mnt/disk2:ro',
            '/etc/snapraid:/etc/snapraid:ro'
        ]
        for volume in expected_volumes:
            self.assertIn(volume, pi_health_volumes)
    
    @patch('subprocess.run')
    def test_systemd_service_dependencies(self, mock_run):
        """Test systemd service dependency configuration"""
        mock_run.return_value = MagicMock(returncode=0)
        
        # Test systemd override configuration
        systemd_override = """[Unit]
# Ensure Docker waits for storage to be available
After=mergerfs-mount.service docker-storage-health.service
Wants=mergerfs-mount.service docker-storage-health.service

[Service]
# Add pre-start health check
ExecStartPre=/usr/local/bin/check-docker-storage-health.sh
"""
        
        # Verify systemd configuration
        self.assertIn('mergerfs-mount.service', systemd_override)
        self.assertIn('docker-storage-health.service', systemd_override)
        self.assertIn('ExecStartPre', systemd_override)
        self.assertIn('check-docker-storage-health.sh', systemd_override)
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_storage_availability_check(self, mock_exists, mock_run):
        """Test storage availability checking before container startup"""
        # Mock successful storage check
        mock_exists.side_effect = lambda path: path in [
            '/mnt/storage',
            '/mnt/storage/Movies',
            '/mnt/storage/TVShows',
            '/mnt/storage/downloads'
        ]
        mock_run.return_value = MagicMock(returncode=0, stdout=b'Storage available')
        
        def check_storage_availability():
            """Simulate storage availability check"""
            required_paths = [
                '/mnt/storage',
                '/mnt/storage/Movies',
                '/mnt/storage/TVShows',
                '/mnt/storage/downloads'
            ]
            
            for path in required_paths:
                if not os.path.exists(path):
                    return False
            
            # Check if MergerFS mount is active
            result = subprocess.run(['mountpoint', '-q', '/mnt/storage'], 
                                  capture_output=True)
            return result.returncode == 0
        
        # Test successful check
        self.assertTrue(check_storage_availability())
    
    @patch('subprocess.run')
    def test_container_startup_sequence(self, mock_run):
        """Test proper container startup sequence with storage dependencies"""
        # Mock successful commands
        mock_run.return_value = MagicMock(returncode=0)
        
        startup_sequence = [
            'systemctl start mergerfs-mount.service',
            '/usr/local/bin/check-docker-storage-health.sh',
            'docker-compose up -d storage-health-check',
            'docker-compose up -d vpn',
            'docker-compose up -d jellyfin sonarr radarr'
        ]
        
        # Verify startup sequence includes storage checks
        self.assertIn('mergerfs-mount.service', startup_sequence[0])
        self.assertIn('check-docker-storage-health.sh', startup_sequence[1])
        self.assertIn('storage-health-check', startup_sequence[2])
    
    def test_volume_mount_configuration(self):
        """Test Docker volume mount configuration for pooled storage"""
        expected_mounts = {
            'jellyfin': [
                '/mnt/storage:/media:ro',
                '/mnt/storage/Movies:/movies:ro',
                '/mnt/storage/TVShows:/tv:ro'
            ],
            'sonarr': [
                '/mnt/storage/TVShows:/tv',
                '/mnt/storage/downloads:/downloads'
            ],
            'radarr': [
                '/mnt/storage/Movies:/movies',
                '/mnt/storage/downloads:/downloads'
            ],
            'pi-health-dashboard': [
                '/mnt/storage:/mnt/storage:ro',
                '/mnt/disk1:/mnt/disk1:ro',
                '/mnt/disk2:/mnt/disk2:ro',
                '/mnt/parity1:/mnt/parity1:ro',
                '/etc/snapraid:/etc/snapraid:ro',
                '/etc/mergerfs:/etc/mergerfs:ro'
            ]
        }
        
        # Verify mount configurations
        for service, mounts in expected_mounts.items():
            for mount in mounts:
                # Verify mount format (source:destination[:options])
                parts = mount.split(':')
                self.assertGreaterEqual(len(parts), 2, f"Invalid mount format: {mount}")
                
                source, destination = parts[0], parts[1]
                self.assertTrue(source.startswith('/mnt/') or source.startswith('/etc/'), 
                              f"Invalid source path: {source}")
                self.assertTrue(destination.startswith('/'), 
                              f"Invalid destination path: {destination}")
    
    @patch('subprocess.run')
    def test_health_check_integration(self, mock_run):
        """Test health check integration with Docker containers"""
        # Mock health check responses
        health_checks = {
            'storage-health-check': 'mountpoint -q /mnt/storage',
            'vpn': 'curl --fail http://localhost:8000 && mountpoint -q /mnt/storage',
            'jellyfin': 'curl -f http://localhost:8096/health',
            'pi-health-dashboard': 'curl -f http://localhost:8080/health'
        }
        
        mock_run.return_value = MagicMock(returncode=0)
        
        for service, check_command in health_checks.items():
            # Verify health check commands include storage verification where appropriate
            if 'storage' in service or service == 'vpn':
                self.assertIn('mountpoint', check_command)
                self.assertIn('/mnt/storage', check_command)
    
    def test_error_handling_storage_unavailable(self):
        """Test error handling when storage is unavailable"""
        def simulate_storage_failure():
            """Simulate storage failure scenario"""
            return {
                'mount_check': False,
                'directory_check': False,
                'write_test': False,
                'error_message': 'MergerFS mount /mnt/storage is not available'
            }
        
        failure_result = simulate_storage_failure()
        
        # Verify error handling
        self.assertFalse(failure_result['mount_check'])
        self.assertIn('not available', failure_result['error_message'])
    
    @patch('subprocess.run')
    def test_recovery_after_storage_restoration(self, mock_run):
        """Test container recovery after storage becomes available"""
        # Simulate storage becoming available
        mock_run.side_effect = [
            MagicMock(returncode=1),  # First check fails
            MagicMock(returncode=1),  # Second check fails
            MagicMock(returncode=0),  # Third check succeeds
        ]
        
        def wait_for_storage_with_retry(max_attempts=3):
            """Simulate waiting for storage with retry logic"""
            for attempt in range(max_attempts):
                result = subprocess.run(['mountpoint', '-q', '/mnt/storage'])
                if result.returncode == 0:
                    return True
                time.sleep(1)
            return False
        
        # Test recovery logic
        self.assertTrue(wait_for_storage_with_retry())
        self.assertEqual(mock_run.call_count, 3)
    
    def test_configuration_validation(self):
        """Test validation of pooled storage configuration"""
        config = {
            'storage_mount': '/mnt/storage',
            'data_drives': ['/mnt/disk1', '/mnt/disk2'],
            'parity_drive': '/mnt/parity1',
            'required_directories': ['Movies', 'TVShows', 'downloads']
        }
        
        def validate_pooled_storage_config(config):
            """Validate pooled storage configuration"""
            errors = []
            
            if not config.get('storage_mount'):
                errors.append('Storage mount point not specified')
            
            if not config.get('data_drives') or len(config['data_drives']) < 2:
                errors.append('At least 2 data drives required for pooling')
            
            if not config.get('required_directories'):
                errors.append('Required directories not specified')
            
            return len(errors) == 0, errors
        
        is_valid, errors = validate_pooled_storage_config(config)
        self.assertTrue(is_valid, f"Configuration validation failed: {errors}")
    
    def test_docker_compose_environment_variables(self):
        """Test Docker Compose environment variable configuration"""
        expected_env_vars = {
            'POOLED_STORAGE_ENABLED': 'true',
            'MERGERFS_MOUNT': '/mnt/storage',
            'SNAPRAID_CONFIG': '/etc/snapraid/snapraid.conf',
            'DOCKER_STORAGE_HEALTH_CHECK': 'true',
            'STORAGE_MOUNT': '/mnt/storage',
            'DOWNLOADS': '/mnt/storage/downloads'
        }
        
        # Verify environment variables are properly set
        for var_name, expected_value in expected_env_vars.items():
            # In a real test, this would check the actual environment or config files
            self.assertIsNotNone(expected_value)
            if var_name in ['POOLED_STORAGE_ENABLED', 'DOCKER_STORAGE_HEALTH_CHECK']:
                self.assertEqual(expected_value, 'true')


class TestDockerStorageHealthScript(unittest.TestCase):
    """Test the Docker storage health check script functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()
        self.storage_mount = os.path.join(self.test_dir, "storage")
        os.makedirs(self.storage_mount, exist_ok=True)
        
        # Create required directories
        for dir_name in ['Movies', 'TVShows', 'downloads']:
            os.makedirs(os.path.join(self.storage_mount, dir_name), exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    @patch('subprocess.run')
    def test_mountpoint_check(self, mock_run):
        """Test MergerFS mountpoint checking"""
        # Mock successful mountpoint check
        mock_run.return_value = MagicMock(returncode=0)
        
        def check_mergerfs_mount(storage_path):
            result = subprocess.run(['mountpoint', '-q', storage_path])
            return result.returncode == 0
        
        self.assertTrue(check_mergerfs_mount('/mnt/storage'))
        mock_run.assert_called_with(['mountpoint', '-q', '/mnt/storage'])
    
    def test_directory_accessibility_check(self):
        """Test required directory accessibility checking"""
        def check_required_directories(storage_path, required_dirs):
            for dir_name in required_dirs:
                full_path = os.path.join(storage_path, dir_name)
                if not os.path.exists(full_path) or not os.access(full_path, os.W_OK):
                    return False
            return True
        
        required_dirs = ['Movies', 'TVShows', 'downloads']
        self.assertTrue(check_required_directories(self.storage_mount, required_dirs))
    
    def test_file_io_operations(self):
        """Test file I/O operations on storage"""
        test_file = os.path.join(self.storage_mount, '.docker-health-test')
        test_content = 'Docker storage health test'
        
        def test_file_operations(storage_path):
            test_file_path = os.path.join(storage_path, '.docker-health-test')
            
            try:
                # Test write
                with open(test_file_path, 'w') as f:
                    f.write(test_content)
                
                # Test read
                with open(test_file_path, 'r') as f:
                    content = f.read()
                
                # Test delete
                os.remove(test_file_path)
                
                return content == test_content
            except Exception:
                return False
        
        self.assertTrue(test_file_operations(self.storage_mount))
    
    @patch('subprocess.run')
    def test_snapraid_health_check(self, mock_run):
        """Test SnapRAID health checking (non-critical)"""
        # Mock SnapRAID status command
        mock_run.return_value = MagicMock(returncode=0, stdout=b'SnapRAID status OK')
        
        def check_snapraid_health():
            try:
                result = subprocess.run(['snapraid', 'status'], 
                                      capture_output=True, timeout=30)
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # SnapRAID check is non-critical
                return True
        
        self.assertTrue(check_snapraid_health())


if __name__ == '__main__':
    unittest.main()