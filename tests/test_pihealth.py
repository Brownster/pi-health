#!/usr/bin/env python3
"""
Tests for pihealth module
"""
import sys
import os
from unittest.mock import patch, mock_open, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pihealth


class TestCpuUsage:
    def test_calculate_cpu_usage(self):
        start = ["cpu", "10", "0", "10", "80", "0", "0", "0", "0"]
        end = ["cpu", "20", "0", "10", "90", "0", "0", "0", "0"]
        usage = pihealth.calculate_cpu_usage(start, end)
        assert round(usage, 2) == 50.0

    def test_get_cpu_usage_reads_twice(self):
        import io
        open_mock = MagicMock(
            side_effect=[
                io.StringIO("cpu 10 0 10 80 0 0 0 0\n"),
                io.StringIO("cpu 20 0 10 90 0 0 0 0\n"),
            ]
        )
        with patch("builtins.open", open_mock):
            with patch("time.sleep", return_value=None):
                value = pihealth.get_cpu_usage()
        assert value is not None


class TestTemperature:
    def test_get_temperature_missing(self):
        with patch("os.path.exists", return_value=False):
            assert pihealth.get_temperature() is None

    def test_get_temperature_parses(self):
        with patch("os.path.exists", return_value=True):
            popen = MagicMock()
            popen.readline.return_value = "temp=55.5'C\n"
            with patch("os.popen", return_value=popen):
                assert pihealth.get_temperature() == 55.5


class TestSystemStats:
    @patch("pihealth.psutil.net_io_counters")
    @patch("pihealth.psutil.disk_usage")
    @patch("pihealth.psutil.virtual_memory")
    def test_get_system_stats(self, mock_mem, mock_disk, mock_net):
        mock_mem.return_value = MagicMock(total=1, used=2, available=3, percent=4)
        mock_disk.return_value = MagicMock(total=5, used=6, free=7, percent=8)
        mock_net.return_value = MagicMock(bytes_sent=9, bytes_recv=10)

        with patch("pihealth.get_cpu_usage", return_value=12.3):
            with patch("pihealth.get_temperature", return_value=42.0):
                stats = pihealth.get_system_stats()

        assert stats["cpu_usage_percent"] == 12.3
        assert stats["temperature_celsius"] == 42.0
