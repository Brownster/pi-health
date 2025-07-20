#!/usr/bin/env python3
"""
Integration tests for Docker stack integration with pooled storage.
Tests the enhanced installer's Docker integration functionality.
"""

import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDockerStackIntegration(unittest.TestCase):
    """Test cases for Docker stack integration with pooled storage."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_docker_compose_volume_mappings(self):
        """Test that Docker Compose volume mappings are correctly configured for pooled storage."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for pooled storage volume mappings
        volume_mappings = [
            '${STORAGE_MOUNT}/${TVSHOWS_FOLDER}:/tv',
            '${STORAGE_MOUNT}/${MOVIES_FOLDER}:/movies',
            '${DOWNLOADS}:/downloads',
            '${STORAGE_MOUNT}:/media'
        ]
        
        for mapping in volume_mappings:
            self.assertIn(mapping, content, f"Volume mapping {mapping} not found in Docker Compose")
    
    def test_systemd_service_dependencies(self):
        """Test that systemd services have proper dependencies for Docker integration."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for proper service dependencies
        dependencies = [
            'Before=docker.service',
            'After=local-fs.target',
            'After=mergerfs-mount.service',
            'Requires=mergerfs-mount.service'
        ]
        
        for dependency in dependencies:
            self.assertIn(dependency, content, f"Service dependency {dependency} not found")
    
    def test_mount_validation_before_docker_start(self):
        """Test that mount validation occurs before Docker containers start."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for mount validation logic
        validation_elements = [
            'mountpoint -q /mnt/storage',
            'for i in {1..30}',
            'TimeoutStartSec=60',
            'if mountpoint -q'
        ]
        
        for element in validation_elements:
            self.assertIn(element, content, f"Mount validation element {element} not found")
    
    def test_docker_network_configuration(self):
        """Test that Docker network configuration is properly set up."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for Docker network setup
        network_elements = [
            'setup_docker_network',
            'CONTAINER_NETWORK',
            'docker network create',
            'networks:',
            '${CONTAINER_NETWORK}:'
        ]
        
        for element in network_elements:
            self.assertIn(element, content, f"Docker network element {element} not found")
    
    def test_container_startup_order(self):
        """Test that containers have proper startup order dependencies."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for container startup dependencies
        startup_elements = [
            'healthcheck:',
            'restart: unless-stopped',
            'depends_on:',
            'network_mode: "service:'
        ]
        
        # At least some of these should be present for proper container orchestration
        found_elements = sum(1 for element in startup_elements if element in content)
        self.assertGreater(found_elements, 2, "Insufficient container startup orchestration elements found")


class TestPoolingStorageConfiguration(unittest.TestCase):
    """Test cases for pooling storage configuration in Docker context."""
    
    def setUp(self):
        """Set up test environment."""
        self.installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
    
    def test_storage_mount_environment_variables(self):
        """Test that storage mount points are properly configured as environment variables."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for storage environment variables
        env_vars = [
            'STORAGE_MOUNT="/mnt/storage"',
            'DOWNLOADS="/mnt/storage/downloads"',
            'MOVIES_FOLDER="Movies"',
            'TVSHOWS_FOLDER="TVShows"'
        ]
        
        for env_var in env_vars:
            self.assertIn(env_var, content, f"Environment variable {env_var} not found")
    
    def test_media_directory_creation(self):
        """Test that media directories are created in the pooled storage."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for media directory creation
        directory_elements = [
            'MOVIES_DIR="$STORAGE_MOUNT/Movies"',
            'TVSHOWS_DIR="$STORAGE_MOUNT/TVShows"',
            'DOWNLOADS_DIR="$STORAGE_MOUNT/downloads"',
            'sudo mkdir -p "$MOVIES_DIR" "$TVSHOWS_DIR" "$DOWNLOADS_DIR"'
        ]
        
        for element in directory_elements:
            self.assertIn(element, content, f"Directory creation element {element} not found")
    
    def test_permissions_configuration(self):
        """Test that proper permissions are set for pooled storage."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for permission settings
        permission_elements = [
            'sudo chown -R "$USER:$USER" "$STORAGE_MOUNT"',
            'sudo chmod -R 775 "$STORAGE_MOUNT"',
            'sudo chown -R "$USER:$USER"',
            'sudo chmod -R 775'
        ]
        
        for element in permission_elements:
            self.assertIn(element, content, f"Permission element {element} not found")


class TestSystemdIntegration(unittest.TestCase):
    """Test cases for systemd integration with pooled storage."""
    
    def setUp(self):
        """Set up test environment."""
        self.installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
    
    def test_systemd_service_creation(self):
        """Test that all required systemd services are created."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for systemd service files creation patterns
        service_patterns = [
            'mergerfs-mount.service',
            'snapraid-health.service',
            'snapraid-health.timer',
            'snapraid-sync.service',
            'snapraid-sync.timer',
            'sudo mv /tmp/',
            '/etc/systemd/system/'
        ]
        
        for pattern in service_patterns:
            self.assertIn(pattern, content, f"Systemd service pattern {pattern} not found")
    
    def test_systemd_service_enablement(self):
        """Test that systemd services are properly enabled."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for service enablement commands
        enablement_commands = [
            'sudo systemctl daemon-reload',
            'sudo systemctl enable mergerfs-mount.service',
            'sudo systemctl enable snapraid-health.timer',
            'sudo systemctl start snapraid-health.timer',
            'sudo systemctl enable snapraid-sync.timer'
        ]
        
        for command in enablement_commands:
            self.assertIn(command, content, f"Service enablement command {command} not found")
    
    def test_timer_configuration(self):
        """Test that systemd timers are properly configured."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for timer configuration
        timer_elements = [
            'OnCalendar=daily',
            'OnCalendar=weekly',
            'Persistent=true',
            'WantedBy=timers.target'
        ]
        
        for element in timer_elements:
            self.assertIn(element, content, f"Timer configuration element {element} not found")


class TestErrorHandlingAndRecovery(unittest.TestCase):
    """Test cases for error handling and recovery in Docker integration."""
    
    def setUp(self):
        """Set up test environment."""
        self.installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
    
    def test_mount_failure_handling(self):
        """Test that mount failures are properly handled."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for mount failure handling
        error_handling = [
            'if [[ $? -ne 0 ]]; then',
            'echo "Error: Failed to mount',
            'exit 1',
            'Please check the drive'
        ]
        
        for pattern in error_handling:
            self.assertIn(pattern, content, f"Mount error handling pattern {pattern} not found")
    
    def test_installation_verification(self):
        """Test that installation verification is implemented."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for installation verification
        verification_patterns = [
            'if command -v mergerfs',
            'if command -v snapraid',
            'installation failed',
            'installed successfully'
        ]
        
        for pattern in verification_patterns:
            self.assertIn(pattern, content, f"Installation verification pattern {pattern} not found")
    
    def test_dependency_resolution(self):
        """Test that dependency resolution and fallback mechanisms are implemented."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for dependency resolution
        resolution_patterns = [
            'apt-cache show',
            'install_mergerfs_from_github',
            'install_snapraid_from_source',
            'Attempting to install from',
            'sudo apt-get install -f -y'
        ]
        
        for pattern in resolution_patterns:
            self.assertIn(pattern, content, f"Dependency resolution pattern {pattern} not found")


class TestConfigurationPersistence(unittest.TestCase):
    """Test cases for configuration persistence across reboots."""
    
    def setUp(self):
        """Set up test environment."""
        self.installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
    
    def test_fstab_configuration(self):
        """Test that fstab is properly configured for persistent mounting."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for fstab configuration
        fstab_elements = [
            'update_fstab',
            '/etc/fstab',
            'UUID=',
            'fuse.mergerfs',
            'defaults,allow_other,use_ino'
        ]
        
        for element in fstab_elements:
            self.assertIn(element, content, f"fstab configuration element {element} not found")
    
    def test_configuration_file_generation(self):
        """Test that configuration files are generated and persisted."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for configuration file generation
        config_elements = [
            '/etc/mergerfs/mergerfs.conf',
            '/etc/snapraid/snapraid.conf',
            'generate_mergerfs_config',
            'generate_snapraid_config',
            'sudo mv /tmp/'
        ]
        
        for element in config_elements:
            self.assertIn(element, content, f"Configuration file element {element} not found")
    
    def test_service_persistence(self):
        """Test that services are configured to persist across reboots."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for service persistence
        persistence_elements = [
            'WantedBy=multi-user.target',
            'WantedBy=timers.target',
            'RemainAfterExit=yes',
            'Persistent=true'
        ]
        
        for element in persistence_elements:
            self.assertIn(element, content, f"Service persistence element {element} not found")


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_classes = [
        TestDockerStackIntegration,
        TestPoolingStorageConfiguration,
        TestSystemdIntegration,
        TestErrorHandlingAndRecovery,
        TestConfigurationPersistence
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)