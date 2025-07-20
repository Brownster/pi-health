"""Tests for SMART health history and trend analysis functionality."""

import unittest
from unittest.mock import Mock, patch, mock_open
import json
import tempfile
import os
from datetime import datetime, timedelta
import sys

# Add the parent directory to the path so we can import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nas.smart_manager import (
    SMARTManager, SMARTHealthStatus, SMARTHealthHistory, 
    SMARTTrendAnalysis, SMARTAttribute
)


class TestSMARTHealthHistory(unittest.TestCase):
    """Test cases for SMART health history and trend analysis."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Use a temporary file for testing
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()
        self.smart_manager = SMARTManager(history_file_path=self.temp_file.name)
    
    def tearDown(self):
        """Clean up test fixtures."""
        try:
            os.unlink(self.temp_file.name)
        except FileNotFoundError:
            pass
    
    def test_record_health_status(self):
        """Test recording health status to history."""
        # Create a mock health status
        health_status = SMARTHealthStatus(
            device_path='/dev/sdb',
            overall_health='PASSED',
            temperature=45,
            power_on_hours=1000,
            reallocated_sectors=0,
            pending_sectors=0
        )
        
        # Record the health status
        self.smart_manager.record_health_status(health_status)
        
        # Check that it was recorded
        history = self.smart_manager.get_health_history('/dev/sdb', days=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].device_path, '/dev/sdb')
        self.assertEqual(history[0].overall_health, 'PASSED')
        self.assertEqual(history[0].temperature, 45)
    
    def test_get_health_history_filtering(self):
        """Test health history filtering by device and date."""
        # Create health status entries for different devices and dates
        now = datetime.now()
        
        # Recent entry for device A
        health_a_recent = SMARTHealthStatus(
            device_path='/dev/sdb',
            overall_health='PASSED',
            temperature=45
        )
        
        # Old entry for device A
        health_a_old = SMARTHealthStatus(
            device_path='/dev/sdb',
            overall_health='PASSED',
            temperature=40
        )
        
        # Recent entry for device B
        health_b_recent = SMARTHealthStatus(
            device_path='/dev/sdc',
            overall_health='PASSED',
            temperature=50
        )
        
        # Manually create history entries with specific timestamps
        history_a_recent = SMARTHealthHistory(
            device_path='/dev/sdb',
            timestamp=now,
            overall_health='PASSED',
            temperature=45
        )
        
        history_a_old = SMARTHealthHistory(
            device_path='/dev/sdb',
            timestamp=now - timedelta(days=10),
            overall_health='PASSED',
            temperature=40
        )
        
        history_b_recent = SMARTHealthHistory(
            device_path='/dev/sdc',
            timestamp=now,
            overall_health='PASSED',
            temperature=50
        )
        
        # Add to manager's history
        self.smart_manager._health_history = [history_a_recent, history_a_old, history_b_recent]
        
        # Test filtering by device and recent days
        history_a = self.smart_manager.get_health_history('/dev/sdb', days=7)
        self.assertEqual(len(history_a), 1)  # Only recent entry
        self.assertEqual(history_a[0].temperature, 45)
        
        # Test filtering by device with longer period
        history_a_long = self.smart_manager.get_health_history('/dev/sdb', days=15)
        self.assertEqual(len(history_a_long), 2)  # Both entries
        
        # Test filtering by different device
        history_b = self.smart_manager.get_health_history('/dev/sdc', days=7)
        self.assertEqual(len(history_b), 1)
        self.assertEqual(history_b[0].temperature, 50)
    
    def test_analyze_health_trends_insufficient_data(self):
        """Test trend analysis with insufficient data."""
        # No history data
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        self.assertIsNone(analysis)
        
        # Only one data point
        history_entry = SMARTHealthHistory(
            device_path='/dev/sdb',
            timestamp=datetime.now(),
            overall_health='PASSED',
            temperature=45
        )
        self.smart_manager._health_history = [history_entry]
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        self.assertIsNone(analysis)
    
    def test_analyze_health_trends_temperature(self):
        """Test temperature trend analysis."""
        now = datetime.now()
        
        # Create history with increasing temperature trend
        history_entries = [
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=6),
                overall_health='PASSED',
                temperature=40
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=3),
                overall_health='PASSED',
                temperature=45
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now,
                overall_health='PASSED',
                temperature=50
            )
        ]
        
        self.smart_manager._health_history = history_entries
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.device_path, '/dev/sdb')
        self.assertEqual(analysis.temperature_trend, 'increasing')
        self.assertEqual(analysis.temperature_max, 50)
        self.assertAlmostEqual(analysis.temperature_avg, 45.0, places=1)
    
    def test_analyze_health_trends_reallocated_sectors(self):
        """Test reallocated sectors trend analysis."""
        now = datetime.now()
        
        # Create history with increasing reallocated sectors
        history_entries = [
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=3),
                overall_health='PASSED',
                reallocated_sectors=0
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now,
                overall_health='PASSED',
                reallocated_sectors=2
            )
        ]
        
        self.smart_manager._health_history = history_entries
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.reallocated_sectors_trend, 'increasing')
    
    def test_assess_health_risk_low(self):
        """Test health risk assessment - low risk."""
        now = datetime.now()
        
        # Create stable, healthy history
        history_entries = [
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=3),
                overall_health='PASSED',
                temperature=40,
                reallocated_sectors=0,
                pending_sectors=0
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now,
                overall_health='PASSED',
                temperature=42,
                reallocated_sectors=0,
                pending_sectors=0
            )
        ]
        
        self.smart_manager._health_history = history_entries
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        
        self.assertEqual(analysis.health_degradation_risk, 'low')
    
    def test_assess_health_risk_high(self):
        """Test health risk assessment - high risk."""
        now = datetime.now()
        
        # Create problematic history
        history_entries = [
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=3),
                overall_health='PASSED',
                temperature=45,
                reallocated_sectors=0,
                pending_sectors=0
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now,
                overall_health='FAILED',  # Failed health
                temperature=60,  # High temperature
                reallocated_sectors=5,  # Increasing reallocated sectors
                pending_sectors=2  # Increasing pending sectors
            )
        ]
        
        self.smart_manager._health_history = history_entries
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        
        self.assertEqual(analysis.health_degradation_risk, 'high')
        self.assertTrue(any('high risk' in rec.lower() for rec in analysis.recommendations))
    
    def test_generate_recommendations(self):
        """Test recommendation generation."""
        now = datetime.now()
        
        # Create history that should trigger multiple recommendations
        history_entries = [
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now - timedelta(days=3),
                overall_health='PASSED',
                temperature=45,
                power_on_hours=40000,  # High power-on hours
                reallocated_sectors=0,
                pending_sectors=0
            ),
            SMARTHealthHistory(
                device_path='/dev/sdb',
                timestamp=now,
                overall_health='PASSED',
                temperature=58,  # High temperature
                power_on_hours=40100,
                reallocated_sectors=2,  # Increasing reallocated sectors
                pending_sectors=1  # Increasing pending sectors
            )
        ]
        
        self.smart_manager._health_history = history_entries
        
        analysis = self.smart_manager.analyze_health_trends('/dev/sdb', days=7)
        
        # Check that appropriate recommendations are generated
        recommendations = analysis.recommendations
        self.assertTrue(any('temperature' in rec.lower() for rec in recommendations))
        self.assertTrue(any('reallocated sectors' in rec.lower() for rec in recommendations))
        self.assertTrue(any('pending sectors' in rec.lower() for rec in recommendations))
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    @patch('os.makedirs')
    def test_save_and_load_health_history(self, mock_makedirs, mock_exists, mock_file):
        """Test saving and loading health history to/from file."""
        mock_exists.return_value = False
        
        # Create some health history
        now = datetime.now()
        history_entry = SMARTHealthHistory(
            device_path='/dev/sdb',
            timestamp=now,
            overall_health='PASSED',
            temperature=45
        )
        
        self.smart_manager._health_history = [history_entry]
        
        # Test saving
        self.smart_manager._save_health_history()
        
        # Verify file operations
        mock_makedirs.assert_called()
        mock_file.assert_called()
        
        # Check that JSON data was written
        written_data = ''.join(call.args[0] for call in mock_file().write.call_args_list)
        self.assertIn('health_history', written_data)
        self.assertIn('/dev/sdb', written_data)
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('os.path.exists')
    def test_load_health_history_file_not_exists(self, mock_exists, mock_file):
        """Test loading health history when file doesn't exist."""
        mock_exists.return_value = False
        
        # Create new manager (triggers load)
        manager = SMARTManager(history_file_path='/nonexistent/file.json')
        
        # Should have empty history
        self.assertEqual(len(manager._health_history), 0)
    
    def test_health_status_with_history_integration(self):
        """Test the integrated method that gets health status and records to history."""
        # Mock the base get_health_status method
        mock_health_status = SMARTHealthStatus(
            device_path='/dev/sdb',
            overall_health='PASSED',
            temperature=45
        )
        
        with patch.object(self.smart_manager, 'get_health_status', return_value=mock_health_status):
            # Call the integrated method
            result = self.smart_manager.get_health_status_with_history('/dev/sdb', use_cache=False)
            
            # Should return the health status
            self.assertEqual(result.device_path, '/dev/sdb')
            self.assertEqual(result.overall_health, 'PASSED')
            
            # Should have recorded to history
            history = self.smart_manager.get_health_history('/dev/sdb', days=1)
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0].device_path, '/dev/sdb')


if __name__ == '__main__':
    unittest.main()