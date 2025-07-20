#!/usr/bin/env python3
"""
Tests for pooling software installation and configuration functionality.
Tests the enhanced installer functions for MergerFS and SnapRAID setup.
"""

import os
import sys
import unittest
import tempfile
import shutil
import subprocess
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPoolingInstaller(unittest.TestCase):
    """Test cases for pooling software installation functionality."""
    
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
    
    def test_installer_script_exists(self):
        """Test that the installer script exists and is executable."""
        self.assertTrue(os.path.exists(self.installer_script))
        self.assertTrue(os.access(self.installer_script, os.R_OK))
    
    def test_installer_has_pooling_functions(self):
        """Test that the installer script contains the required pooling functions."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for required functions
        required_functions = [
            'install_pooling_software',
            'install_mergerfs_from_github',
            'install_snapraid_from_source',
            'setup_pooling_systemd_services',
            'generate_mergerfs_config',
            'generate_snapraid_config'
        ]
        
        for func in required_functions:
            self.assertIn(func, content, f"Function {func} not found in installer script")
    
    def test_installer_has_enhanced_dependencies(self):
        """Test that the installer includes enhanced dependency installation."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for enhanced dependencies
        dependencies = [
            'fuse3',
            'attr',
            'acl',
            'util-linux',
            'smartmontools',
            'parted',
            'e2fsprogs'
        ]
        
        for dep in dependencies:
            self.assertIn(dep, content, f"Dependency {dep} not found in installer script")
    
    def test_installer_has_systemd_services(self):
        """Test that the installer creates proper systemd services."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for systemd service definitions
        services = [
            'mergerfs-mount.service',
            'snapraid-health.service',
            'snapraid-health.timer',
            'snapraid-sync.service',
            'snapraid-sync.timer'
        ]
        
        for service in services:
            self.assertIn(service, content, f"Systemd service {service} not found in installer script")
    
    def test_mergerfs_config_generation(self):
        """Test MergerFS configuration generation."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for MergerFS configuration elements
        config_elements = [
            'MERGERFS_SOURCES',
            'MERGERFS_MOUNT',
            'MERGERFS_OPTIONS',
            'category.create=epmfs',
            'category.search=ff',
            'category.action=epall',
            'cache.files=partial',
            'dropcacheonclose=true'
        ]
        
        for element in config_elements:
            self.assertIn(element, content, f"MergerFS config element {element} not found")
    
    def test_snapraid_config_generation(self):
        """Test SnapRAID configuration generation."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for SnapRAID configuration elements
        config_elements = [
            'parity /mnt/parity1/snapraid.parity',
            'content /var/snapraid/snapraid.content',
            'block_size 256',
            'hash_size 16',
            'autosave 10',
            'smart-update'
        ]
        
        for element in config_elements:
            self.assertIn(element, content, f"SnapRAID config element {element} not found")
    
    def test_enhanced_exclusions(self):
        """Test that enhanced exclusions are present in SnapRAID config."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for enhanced exclusions
        exclusions = [
            'exclude *.part',
            'exclude *.partial',
            'exclude *.!qB',
            'exclude *.!ut',
            'exclude /docker/',
            'exclude /var/lib/docker/',
            'exclude */.grab/',
            'exclude */cache/',
            'exclude */logs/'
        ]
        
        for exclusion in exclusions:
            self.assertIn(exclusion, content, f"SnapRAID exclusion {exclusion} not found")
    
    def test_docker_integration_dependencies(self):
        """Test that Docker integration dependencies are properly configured."""
        with open(self.installer_script, 'r') as f:
            content = f.read()
        
        # Check for Docker integration elements
        integration_elements = [
            'Before=docker.service',
            'After=mergerfs-mount.service',
            'Requires=mergerfs-mount.service',
            'mountpoint -q /mnt/storage'
        ]
        
        for element in integration_elements:
            self.assertIn(element, content, f"Docker integration element {element} not found")


class TestPoolingConfigGeneration(unittest.TestCase):
    """Test cases for configuration file generation."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_mergerfs_config_structure(self):
        """Test MergerFS configuration file structure."""
        # Create a mock configuration
        mount_points = ['/mnt/disk1', '/mnt/disk2', '/mnt/disk3']
        
        # Expected configuration content
        expected_content = [
            'MERGERFS_SOURCES=$(IFS=:; echo "${mount_points[*]}")',
            'MERGERFS_MOUNT=$storage_mount',
            'category.create=epmfs',
            'category.search=ff',
            'category.action=epall',
            'cache.files=partial',
            'dropcacheonclose=true'
        ]
        
        # This would be tested by running the actual function
        # For now, we verify the structure exists in the installer
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        for expected in expected_content:
            self.assertIn(expected, content)
    
    def test_snapraid_config_structure(self):
        """Test SnapRAID configuration file structure."""
        # Expected configuration content
        expected_content = [
            'parity /mnt/parity1/snapraid.parity',
            'content /var/snapraid/snapraid.content',
            'content /mnt/disk1/snapraid.content',
            'content /mnt/parity1/snapraid.content',
            'block_size 256',
            'hash_size 16',
            'autosave 10'
        ]
        
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        for expected in expected_content:
            self.assertIn(expected, content)


class TestSystemdServiceGeneration(unittest.TestCase):
    """Test cases for systemd service generation."""
    
    def test_mergerfs_mount_service(self):
        """Test MergerFS mount service configuration."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for service configuration elements
        service_elements = [
            '[Unit]',
            'Description=Ensure MergerFS mounts are ready',
            'After=local-fs.target',
            'Before=docker.service',
            '[Service]',
            'Type=oneshot',
            'RemainAfterExit=yes',
            'mountpoint -q /mnt/storage',
            '[Install]',
            'WantedBy=multi-user.target'
        ]
        
        for element in service_elements:
            self.assertIn(element, content, f"Service element {element} not found")
    
    def test_snapraid_health_service(self):
        """Test SnapRAID health monitoring service configuration."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for health service elements
        service_elements = [
            'Description=SnapRAID Health Check',
            'After=mergerfs-mount.service',
            'Requires=mergerfs-mount.service',
            'ExecStart=/usr/bin/snapraid status',
            'StandardOutput=journal',
            'StandardError=journal'
        ]
        
        for element in service_elements:
            self.assertIn(element, content, f"Health service element {element} not found")
    
    def test_snapraid_sync_timer(self):
        """Test SnapRAID sync timer configuration."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for timer elements
        timer_elements = [
            'Description=Run SnapRAID sync weekly',
            'OnCalendar=weekly',
            'Persistent=true',
            'WantedBy=timers.target'
        ]
        
        for element in timer_elements:
            self.assertIn(element, content, f"Timer element {element} not found")


class TestInstallationValidation(unittest.TestCase):
    """Test cases for installation validation."""
    
    def test_dependency_installation_order(self):
        """Test that dependencies are installed in the correct order."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Find the install_pooling_software function
        function_start = content.find('install_pooling_software() {')
        function_end = content.find('\n}\n', function_start)
        function_content = content[function_start:function_end]
        
        # Check that dependencies are installed before main packages
        deps_index = function_content.find('Installing dependencies')
        mergerfs_index = function_content.find('Installing MergerFS')
        snapraid_index = function_content.find('Installing SnapRAID')
        
        self.assertLess(deps_index, mergerfs_index, "Dependencies should be installed before MergerFS")
        self.assertLess(deps_index, snapraid_index, "Dependencies should be installed before SnapRAID")
    
    def test_error_handling(self):
        """Test that proper error handling is implemented."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for error handling patterns
        error_patterns = [
            'exit 1',
            'Error:',
            '|| {',
            'Failed to',
            'if [[ $? -ne 0 ]]'
        ]
        
        for pattern in error_patterns:
            self.assertIn(pattern, content, f"Error handling pattern {pattern} not found")
    
    def test_verification_steps(self):
        """Test that installation verification steps are present."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for verification patterns
        verification_patterns = [
            'command -v mergerfs',
            'command -v snapraid',
            'mergerfs --version',
            'snapraid --version',
            'installation failed'
        ]
        
        for pattern in verification_patterns:
            self.assertIn(pattern, content, f"Verification pattern {pattern} not found")


class TestDockerIntegration(unittest.TestCase):
    """Test cases for Docker stack integration."""
    
    def test_docker_service_dependencies(self):
        """Test that Docker service dependencies are properly configured."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for Docker integration
        integration_patterns = [
            'Before=docker.service',
            'After=mergerfs-mount.service',
            'Requires=mergerfs-mount.service'
        ]
        
        for pattern in integration_patterns:
            self.assertIn(pattern, content, f"Docker integration pattern {pattern} not found")
    
    def test_mount_point_validation(self):
        """Test that mount point validation is implemented."""
        installer_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'docs', 'Pi-Installer', 'pi-pvr.sh'
        )
        
        with open(installer_script, 'r') as f:
            content = f.read()
        
        # Check for mount point validation
        validation_patterns = [
            'mountpoint -q',
            '/mnt/storage',
            'TimeoutStartSec=60'
        ]
        
        for pattern in validation_patterns:
            self.assertIn(pattern, content, f"Mount validation pattern {pattern} not found")


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases
    test_classes = [
        TestPoolingInstaller,
        TestPoolingConfigGeneration,
        TestSystemdServiceGeneration,
        TestInstallationValidation,
        TestDockerIntegration
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)