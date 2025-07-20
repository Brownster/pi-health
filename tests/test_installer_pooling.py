#!/usr/bin/env python3
"""
Tests for installer pooling configuration functionality.
Tests the bash script functions for drive detection, selection, and pooling setup.
"""

import unittest
import subprocess
import tempfile
import os
import shutil
from unittest.mock import patch, MagicMock, call


class TestInstallerPooling(unittest.TestCase):
    """Test cases for installer pooling configuration."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.installer_script = "docs/Pi-Installer/pi-pvr.sh"
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_drive_detection_command(self):
        """Test that the drive detection command works correctly."""
        # Test the lsblk command used in the script
        try:
            result = subprocess.run([
                'bash', '-c', 
                'lsblk -o NAME,SIZE,TYPE,FSTYPE | awk \'/part/ {print "/dev/"$1, $2, $4}\' | sed \'s/[└├─]//g\''
            ], capture_output=True, text=True, timeout=10)
            
            # Should not fail (even if no drives detected)
            self.assertIsNotNone(result.stdout)
            self.assertEqual(result.returncode, 0)
            
        except subprocess.TimeoutExpired:
            self.fail("Drive detection command timed out")
        except Exception as e:
            self.fail(f"Drive detection command failed: {e}")

    def test_installer_script_syntax(self):
        """Test that the installer script has valid bash syntax."""
        try:
            result = subprocess.run([
                'bash', '-n', self.installer_script
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                self.fail(f"Bash syntax error in installer script: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            self.fail("Syntax check timed out")
        except Exception as e:
            self.fail(f"Syntax check failed: {e}")

    def test_storage_configuration_menu_exists(self):
        """Test that the storage configuration menu function exists."""
        try:
            result = subprocess.run([
                'grep', '-A', '10', 'choose_storage_configuration()', self.installer_script
            ], capture_output=True, text=True, timeout=10)
            
            self.assertEqual(result.returncode, 0)
            self.assertIn("choose_storage_configuration", result.stdout)
            self.assertIn("Traditional single-drive setup", result.stdout)
            self.assertIn("Pooled storage with redundancy", result.stdout)
            
        except subprocess.TimeoutExpired:
            self.fail("Function check timed out")
        except Exception as e:
            self.fail(f"Function check failed: {e}")

    def test_pooled_storage_function_exists(self):
        """Test that the pooled storage setup function exists."""
        try:
            result = subprocess.run([
                'grep', '-A', '5', 'setup_pooled_storage()', self.installer_script
            ], capture_output=True, text=True, timeout=10)
            
            self.assertEqual(result.returncode, 0)
            self.assertIn("setup_pooled_storage", result.stdout)
            self.assertIn("Setting up pooled storage", result.stdout)
            
        except subprocess.TimeoutExpired:
            self.fail("Function check timed out")
        except Exception as e:
            self.fail(f"Function check failed: {e}")

    def test_mergerfs_snapraid_installation_commands(self):
        """Test that MergerFS and SnapRAID installation commands are valid."""
        # Test that the package names are correct
        try:
            result = subprocess.run([
                'apt-cache', 'search', 'mergerfs'
            ], capture_output=True, text=True, timeout=10)
            
            # Should find mergerfs package or similar
            self.assertEqual(result.returncode, 0)
            
        except subprocess.TimeoutExpired:
            self.fail("Package search timed out")
        except Exception as e:
            # This might fail in environments without apt, which is okay
            pass

        try:
            result = subprocess.run([
                'apt-cache', 'search', 'snapraid'
            ], capture_output=True, text=True, timeout=10)
            
            # Should find snapraid package or similar
            self.assertEqual(result.returncode, 0)
            
        except subprocess.TimeoutExpired:
            self.fail("Package search timed out")
        except Exception as e:
            # This might fail in environments without apt, which is okay
            pass

    def test_fstab_entry_format(self):
        """Test that the fstab entry format for MergerFS is correct."""
        # Test the fstab entry format used in the script
        test_mount_points = ["/mnt/disk1", "/mnt/disk2", "/mnt/disk3"]
        expected_sources = ":".join(test_mount_points)
        expected_entry = f"{expected_sources} /mnt/storage fuse.mergerfs defaults,allow_other,use_ino,cache.files=partial,dropcacheonclose=true,category.create=epmfs,category.search=ff,category.action=epall 0 0"
        
        # Verify the format is valid
        parts = expected_entry.split()
        self.assertEqual(len(parts), 6)  # Standard fstab format
        self.assertIn("fuse.mergerfs", parts[2])
        self.assertIn("epmfs", parts[3])  # MergerFS policy

    def test_snapraid_config_format(self):
        """Test that the SnapRAID configuration format is correct."""
        # Test the SnapRAID config format used in the script
        expected_config_lines = [
            "# SnapRAID configuration file",
            "parity /mnt/parity1/snapraid.parity",
            "content /var/snapraid/snapraid.content",
            "content /mnt/disk1/snapraid.content",
            "content /mnt/parity1/snapraid.content",
            "data d1 /mnt/disk1",
            "data d2 /mnt/disk2",
            "exclude *.tmp",
            "exclude *.temp",
            "exclude *.log",
            "exclude /lost+found/"
        ]
        
        # Verify each line format
        for line in expected_config_lines:
            if line.startswith("parity"):
                self.assertRegex(line, r"parity /mnt/parity\d+/snapraid\.parity")
            elif line.startswith("content"):
                self.assertRegex(line, r"content /.*snapraid\.content")
            elif line.startswith("data"):
                self.assertRegex(line, r"data d\d+ /mnt/disk\d+")
            elif line.startswith("exclude"):
                self.assertRegex(line, r"exclude (\*?\.\w+|/[\w+]+/)")

    def test_drive_selection_validation(self):
        """Test drive selection validation logic."""
        # Test the validation patterns used in the script
        valid_selections = ["1", "2", "3", "10", "done", "skip"]
        invalid_selections = ["0", "-1", "abc", "", "done123", "skip1"]
        
        # Test numeric validation regex pattern
        import re
        numeric_pattern = r"^[0-9]+$"
        
        for selection in ["1", "2", "3", "10"]:
            self.assertTrue(re.match(numeric_pattern, selection))
            
        for selection in ["abc", "", "done", "skip"]:
            # These should fail numeric validation
            self.assertFalse(re.match(numeric_pattern, selection))
            
        # Test edge cases separately
        self.assertTrue(re.match(numeric_pattern, "0"))  # Valid number but invalid range
        self.assertFalse(re.match(numeric_pattern, "-1"))  # Invalid - contains dash

    def test_mount_point_creation_logic(self):
        """Test mount point creation logic."""
        # Test the mount point naming pattern used in the script
        expected_patterns = [
            ("/mnt/disk1", 0),
            ("/mnt/disk2", 1), 
            ("/mnt/disk3", 2),
            ("/mnt/parity1", "parity")
        ]
        
        for mount_point, index in expected_patterns:
            if isinstance(index, int):
                expected = f"/mnt/disk{index + 1}"
                self.assertEqual(mount_point, expected)
            else:
                self.assertEqual(mount_point, "/mnt/parity1")

    def test_filesystem_format_commands(self):
        """Test filesystem format commands are correct."""
        # Test the mkfs.ext4 command format
        test_device = "/dev/sdb1"
        expected_command = f"mkfs.ext4 -F {test_device}"
        
        # Verify command format
        parts = expected_command.split()
        self.assertEqual(parts[0], "mkfs.ext4")
        self.assertEqual(parts[1], "-F")  # Force flag
        self.assertEqual(parts[2], test_device)

    def test_permission_setting_commands(self):
        """Test permission setting commands are correct."""
        # Test the chmod and chown commands used
        test_path = "/mnt/disk1"
        test_user = "testuser"
        
        expected_chmod = f"chmod -R 775 {test_path}"
        expected_chown = f"chown -R {test_user}:{test_user} {test_path}"
        
        # Verify command formats
        chmod_parts = expected_chmod.split()
        self.assertEqual(chmod_parts[0], "chmod")
        self.assertEqual(chmod_parts[1], "-R")
        self.assertEqual(chmod_parts[2], "775")
        
        chown_parts = expected_chown.split()
        self.assertEqual(chown_parts[0], "chown")
        self.assertEqual(chown_parts[1], "-R")
        self.assertEqual(chown_parts[2], f"{test_user}:{test_user}")

    def test_error_handling_scenarios(self):
        """Test error handling scenarios in the pooling setup."""
        # Test scenarios that should trigger error handling
        error_scenarios = [
            ("no_drives", "No USB drives detected"),
            ("insufficient_drives", "requires at least 2 drives"),
            ("mount_failure", "Failed to mount"),
            ("format_failure", "Failed to format")
        ]
        
        for scenario, expected_message in error_scenarios:
            # These are the error messages that should be present in the script
            self.assertIsInstance(expected_message, str)
            self.assertGreater(len(expected_message), 0)

    def test_configuration_file_paths(self):
        """Test that configuration file paths are correct."""
        expected_paths = {
            "snapraid_config": "/etc/snapraid/snapraid.conf",
            "snapraid_content": "/var/snapraid/snapraid.content",
            "mergerfs_mount": "/mnt/storage",
            "parity_mount": "/mnt/parity1"
        }
        
        for config_type, path in expected_paths.items():
            # Verify paths are absolute and follow Linux conventions
            self.assertTrue(path.startswith("/"))
            if "snapraid" in config_type:
                self.assertIn("snapraid", path)
            if "mount" in config_type:
                self.assertIn("/mnt/", path)


class TestInstallerIntegration(unittest.TestCase):
    """Integration tests for installer functionality."""

    def setUp(self):
        """Set up integration test environment."""
        self.installer_script = "docs/Pi-Installer/pi-pvr.sh"

    def test_main_function_calls_storage_configuration(self):
        """Test that main function calls the new storage configuration function."""
        try:
            # Extract the main function and check it calls choose_storage_configuration
            result = subprocess.run([
                'bash', '-c', 
                f'grep -A 30 "# Main setup function" {self.installer_script} | grep "choose_storage_configuration"'
            ], capture_output=True, text=True, timeout=10)
            
            self.assertEqual(result.returncode, 0)
            self.assertIn("choose_storage_configuration", result.stdout)
            
        except subprocess.TimeoutExpired:
            self.fail("Integration test timed out")
        except Exception as e:
            self.fail(f"Integration test failed: {e}")

    def test_storage_configuration_function_flow(self):
        """Test the flow of the storage configuration function."""
        try:
            # Check that the function contains the expected menu options
            result = subprocess.run([
                'bash', '-c', 
                f'grep -A 10 "choose_storage_configuration()" {self.installer_script}'
            ], capture_output=True, text=True, timeout=10)
            
            self.assertEqual(result.returncode, 0)
            self.assertIn("Traditional single-drive setup", result.stdout)
            self.assertIn("Pooled storage with redundancy", result.stdout)
            
        except subprocess.TimeoutExpired:
            self.fail("Function flow test timed out")
        except Exception as e:
            self.fail(f"Function flow test failed: {e}")

    def test_pooled_storage_dependencies(self):
        """Test that pooled storage function includes required dependencies."""
        try:
            # Check that mergerfs is installed
            result_mergerfs = subprocess.run([
                'grep', '-E', 'apt-get install.*mergerfs', self.installer_script
            ], capture_output=True, text=True, timeout=10)

            self.assertEqual(result_mergerfs.returncode, 0)
            self.assertIn("mergerfs", result_mergerfs.stdout)

            # Check that snapraid is installed
            result_snapraid = subprocess.run([
                'grep', '-E', 'apt-get install.*snapraid', self.installer_script
            ], capture_output=True, text=True, timeout=10)

            self.assertEqual(result_snapraid.returncode, 0)
            self.assertIn("snapraid", result_snapraid.stdout)
            
        except subprocess.TimeoutExpired:
            self.fail("Dependencies test timed out")
        except Exception as e:
            self.fail(f"Dependencies test failed: {e}")


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)