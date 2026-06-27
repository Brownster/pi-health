#!/usr/bin/env python3
"""Tests for app.py system-stats helpers (CPU delta, temperature, disk guard)."""
import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app


def _temp(current):
    return types.SimpleNamespace(current=current, label='', high=None, critical=None)


class TestCpuDelta:
    def test_percent_from_delta_basic(self):
        # 50 busy jiffies, 50 idle jiffies -> 50%
        start = [0, 0, 0, 0, 0, 0, 0, 0]
        end = [50, 0, 0, 50, 0, 0, 0, 0]
        assert app._cpu_percent_from_delta(start, end) == 50.0

    def test_percent_from_delta_fully_busy(self):
        start = [0, 0, 0, 100, 0, 0, 0, 0]
        end = [100, 0, 0, 100, 0, 0, 0, 0]  # all new jiffies are user (busy)
        assert app._cpu_percent_from_delta(start, end) == 100.0

    def test_percent_from_delta_no_movement_returns_none(self):
        snap = [10, 0, 5, 80, 0, 0, 0, 0]
        assert app._cpu_percent_from_delta(snap, snap) is None

    def test_get_cpu_usage_delta_aggregate_and_per_core(self):
        first = {'cpu': [0, 0, 0, 0, 0, 0, 0, 0], 'cpu0': [0, 0, 0, 0, 0, 0, 0, 0]}
        second = {'cpu': [75, 0, 0, 25, 0, 0, 0, 0], 'cpu0': [50, 0, 0, 50, 0, 0, 0, 0]}
        with patch.object(app, '_read_proc_stat_cpu', side_effect=[first, second]):
            with patch.object(app.time, 'sleep', return_value=None):
                aggregate, per_core = app.get_cpu_usage_delta()
        assert aggregate == 75.0
        assert {c['core']: c['usage_percent'] for c in per_core} == {'cpu0': 50.0}

    def test_get_cpu_usage_delta_handles_unreadable(self):
        with patch.object(app, '_read_proc_stat_cpu', side_effect=FileNotFoundError):
            aggregate, per_core = app.get_cpu_usage_delta()
        assert aggregate is None
        assert per_core == []


class TestTemperatureFallback:
    def test_prefers_cpu_sensor_over_chipset(self):
        sensors = {'acpitz': [_temp(25.0)], 'coretemp': [_temp(84.0)]}
        with patch.object(app.psutil, 'sensors_temperatures', return_value=sensors):
            assert app.get_temperature_fallback() == 84.0

    def test_falls_back_to_any_sensor(self):
        sensors = {'acpitz': [_temp(40.0)]}
        with patch.object(app.psutil, 'sensors_temperatures', return_value=sensors):
            assert app.get_temperature_fallback() == 40.0

    def test_none_when_no_sensors(self):
        with patch.object(app.psutil, 'sensors_temperatures', return_value={}):
            assert app.get_temperature_fallback() is None


class TestSafeDiskUsage:
    def test_missing_path_returns_none(self):
        assert app._safe_disk_usage('/definitely/not/a/real/mount/xyz') is None

    def test_valid_path_returns_dict(self):
        usage = app._safe_disk_usage('/')
        assert usage is not None
        assert set(usage) == {'total', 'used', 'free', 'percent'}


class TestGetSystemStatsResilience:
    def test_missing_second_disk_does_not_crash(self, monkeypatch):
        monkeypatch.setenv('DISK_PATH_2', '/definitely/not/a/real/mount/xyz')
        stats = app.get_system_stats()
        assert stats['disk_usage_2'] is None        # guarded, not a 500
        assert stats['disk_usage'] is not None       # first disk ('/') still works
        assert 'cpu_usage_percent' in stats
