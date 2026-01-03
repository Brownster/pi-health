#!/usr/bin/env python3
"""
Tests for Pi Monitor module
"""
import pytest
import sys
import os
from unittest.mock import patch, mock_open, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pi_monitor import (
    get_throttling_status,
    get_cpu_frequency,
    get_cpu_voltage,
    get_wifi_signal,
    get_wifi_signal_from_iwconfig,
    get_pi_metrics,
    run_vcgencmd
)


class TestRunVcgencmd:
    """Test vcgencmd helper function."""

    @patch('subprocess.run')
    def test_run_vcgencmd_success(self, mock_run):
        """Test successful vcgencmd call."""
        mock_run.return_value = MagicMock(returncode=0, stdout='output\n')
        result = run_vcgencmd('get_throttled')
        assert result == 'output'
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_run_vcgencmd_not_found(self, mock_run):
        """Test vcgencmd not available."""
        mock_run.side_effect = FileNotFoundError()
        result = run_vcgencmd('get_throttled')
        assert result is None

    @patch('subprocess.run')
    def test_run_vcgencmd_failure(self, mock_run):
        """Test vcgencmd returns non-zero."""
        mock_run.return_value = MagicMock(returncode=1, stdout='error')
        result = run_vcgencmd('get_throttled')
        assert result is None


class TestGetThrottlingStatus:
    """Test throttling status parsing."""

    @patch('pi_monitor.run_vcgencmd')
    def test_no_throttling(self, mock_vcgencmd):
        """Test when no throttling occurs."""
        mock_vcgencmd.return_value = 'throttled=0x0'
        result = get_throttling_status()

        assert result is not None
        assert result['raw'] == '0x0'
        assert result['under_voltage_now'] is False
        assert result['throttled_now'] is False
        assert result['has_issues'] is False
        assert result['has_historical_issues'] is False

    @patch('pi_monitor.run_vcgencmd')
    def test_under_voltage_now(self, mock_vcgencmd):
        """Test current under-voltage detection."""
        mock_vcgencmd.return_value = 'throttled=0x1'
        result = get_throttling_status()

        assert result['under_voltage_now'] is True
        assert result['has_issues'] is True

    @patch('pi_monitor.run_vcgencmd')
    def test_throttled_now(self, mock_vcgencmd):
        """Test current throttling detection."""
        mock_vcgencmd.return_value = 'throttled=0x4'
        result = get_throttling_status()

        assert result['throttled_now'] is True
        assert result['has_issues'] is True

    @patch('pi_monitor.run_vcgencmd')
    def test_historical_under_voltage(self, mock_vcgencmd):
        """Test historical under-voltage detection."""
        mock_vcgencmd.return_value = 'throttled=0x10000'
        result = get_throttling_status()

        assert result['under_voltage_occurred'] is True
        assert result['has_issues'] is False
        assert result['has_historical_issues'] is True

    @patch('pi_monitor.run_vcgencmd')
    def test_multiple_flags(self, mock_vcgencmd):
        """Test multiple throttling flags set."""
        # 0x50005 = under_voltage_now + throttled_now + under_voltage_occurred + throttled_occurred
        mock_vcgencmd.return_value = 'throttled=0x50005'
        result = get_throttling_status()

        assert result['under_voltage_now'] is True
        assert result['throttled_now'] is True
        assert result['under_voltage_occurred'] is True
        assert result['throttled_occurred'] is True
        assert result['has_issues'] is True
        assert result['has_historical_issues'] is True

    @patch('pi_monitor.run_vcgencmd')
    def test_vcgencmd_not_available(self, mock_vcgencmd):
        """Test when vcgencmd not available."""
        mock_vcgencmd.return_value = None
        result = get_throttling_status()
        assert result is None

    @patch('pi_monitor.run_vcgencmd')
    def test_invalid_output_format(self, mock_vcgencmd):
        """Test handling of invalid output."""
        mock_vcgencmd.return_value = 'unexpected output'
        result = get_throttling_status()
        assert result is None


class TestGetCpuFrequency:
    """Test CPU frequency parsing."""

    @patch('pi_monitor.run_vcgencmd')
    def test_frequency_success(self, mock_vcgencmd):
        """Test successful frequency reading."""
        mock_vcgencmd.return_value = 'frequency(48)=1500000000'
        result = get_cpu_frequency()
        assert result == 1500  # MHz

    @patch('pi_monitor.run_vcgencmd')
    def test_frequency_lower(self, mock_vcgencmd):
        """Test lower frequency (throttled)."""
        mock_vcgencmd.return_value = 'frequency(48)=600000000'
        result = get_cpu_frequency()
        assert result == 600

    @patch('pi_monitor.run_vcgencmd')
    def test_frequency_not_available(self, mock_vcgencmd):
        """Test when frequency not available."""
        mock_vcgencmd.return_value = None
        result = get_cpu_frequency()
        assert result is None

    @patch('pi_monitor.run_vcgencmd')
    def test_frequency_invalid_format(self, mock_vcgencmd):
        """Test handling of invalid format."""
        mock_vcgencmd.return_value = 'invalid'
        result = get_cpu_frequency()
        assert result is None


class TestGetCpuVoltage:
    """Test CPU voltage parsing."""

    @patch('pi_monitor.run_vcgencmd')
    def test_voltage_success(self, mock_vcgencmd):
        """Test successful voltage reading."""
        mock_vcgencmd.return_value = 'volt=1.2000V'
        result = get_cpu_voltage()
        assert result == 1.2

    @patch('pi_monitor.run_vcgencmd')
    def test_voltage_lower(self, mock_vcgencmd):
        """Test lower voltage reading."""
        mock_vcgencmd.return_value = 'volt=0.8500V'
        result = get_cpu_voltage()
        assert result == 0.85

    @patch('pi_monitor.run_vcgencmd')
    def test_voltage_not_available(self, mock_vcgencmd):
        """Test when voltage not available."""
        mock_vcgencmd.return_value = None
        result = get_cpu_voltage()
        assert result is None


class TestGetWifiSignal:
    """Test WiFi signal parsing."""

    def test_wifi_signal_success(self):
        """Test successful WiFi signal reading."""
        mock_content = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   70.  -40.  -256        0      0      0      0      0        0
"""
        with patch('builtins.open', mock_open(read_data=mock_content)):
            result = get_wifi_signal()

        assert result is not None
        assert result['interface'] == 'wlan0'
        assert result['link_quality'] == 70
        assert result['signal_level'] == -40
        assert result['signal_percent'] > 0

    def test_wifi_signal_weak(self):
        """Test weak WiFi signal."""
        mock_content = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   20.  -85.  -256        0      0      0      0      0        0
"""
        with patch('builtins.open', mock_open(read_data=mock_content)):
            result = get_wifi_signal()

        assert result is not None
        assert result['signal_level'] == -85
        assert result['signal_percent'] == 30  # 2 * (-85 + 100) = 30

    def test_wifi_no_file(self):
        """Test when /proc/net/wireless doesn't exist."""
        with patch('builtins.open', side_effect=FileNotFoundError()):
            result = get_wifi_signal()
        assert result is None

    def test_wifi_no_interface(self):
        """Test when no WiFi interface connected."""
        mock_content = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
"""
        with patch('builtins.open', mock_open(read_data=mock_content)):
            result = get_wifi_signal()
        assert result is None

    @patch('pi_monitor.get_wifi_signal_from_iwconfig')
    def test_wifi_fallback_to_iwconfig(self, mock_iwconfig):
        """Test fallback to iwconfig when /proc/net/wireless fails."""
        mock_iwconfig.return_value = {
            'interface': 'wlan0',
            'link_quality': 50,
            'signal_level': -60,
            'noise_level': 0,
            'signal_percent': 71
        }
        with patch('builtins.open', side_effect=FileNotFoundError()):
            result = get_wifi_signal()

        assert result is not None
        assert result['interface'] == 'wlan0'
        mock_iwconfig.assert_called_once()


class TestGetWifiSignalFromIwconfig:
    """Test iwconfig fallback for WiFi signal."""

    @patch('subprocess.run')
    def test_iwconfig_success(self, mock_run):
        """Test successful iwconfig parsing."""
        # First call for version check, second for actual iwconfig
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout='iwconfig 30'),
            MagicMock(returncode=0, stdout="""wlan0     IEEE 802.11  ESSID:"MyNetwork"
          Mode:Managed  Frequency:5.18 GHz  Access Point: AA:BB:CC:DD:EE:FF
          Bit Rate=72.2 Mb/s   Tx-Power=20 dBm
          Retry short limit:7   RTS thr:off   Fragment thr:off
          Power Management:on
          Link Quality=57/70  Signal level=-53 dBm
          Rx invalid nwid:0  Rx invalid crypt:0  Rx invalid frag:0
          Tx excessive retries:0  Invalid misc:0   Missed beacon:0

eth0      no wireless extensions.

lo        no wireless extensions.
""", stderr='')
        ]
        result = get_wifi_signal_from_iwconfig()

        assert result is not None
        assert result['interface'] == 'wlan0'
        assert result['link_quality'] == 57
        assert result['signal_level'] == -53
        assert result['signal_percent'] == 81  # 57/70 * 100

    @patch('subprocess.run')
    def test_iwconfig_weak_signal(self, mock_run):
        """Test iwconfig with weak signal."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=''),
            MagicMock(returncode=0, stdout="""wlan0     IEEE 802.11  ESSID:"WeakNetwork"
          Link Quality=15/70  Signal level=-85 dBm
""", stderr='')
        ]
        result = get_wifi_signal_from_iwconfig()

        assert result is not None
        assert result['link_quality'] == 15
        assert result['signal_level'] == -85
        assert result['signal_percent'] == 21  # 15/70 * 100

    @patch('subprocess.run')
    def test_iwconfig_not_found(self, mock_run):
        """Test when iwconfig is not installed."""
        mock_run.side_effect = FileNotFoundError()
        result = get_wifi_signal_from_iwconfig()
        assert result is None

    @patch('subprocess.run')
    def test_iwconfig_no_wireless(self, mock_run):
        """Test when no wireless interfaces."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=''),
            MagicMock(returncode=0, stdout="""eth0      no wireless extensions.
lo        no wireless extensions.
""", stderr='')
        ]
        result = get_wifi_signal_from_iwconfig()
        assert result is None


class TestGetPiMetrics:
    """Test combined Pi metrics function."""

    @patch('pi_monitor.get_throttling_status')
    @patch('pi_monitor.get_cpu_frequency')
    @patch('pi_monitor.get_cpu_voltage')
    @patch('pi_monitor.get_wifi_signal')
    def test_pi_metrics_full(self, mock_wifi, mock_voltage, mock_freq, mock_throttle):
        """Test getting all Pi metrics."""
        mock_throttle.return_value = {'raw': '0x0', 'has_issues': False}
        mock_freq.return_value = 1500
        mock_voltage.return_value = 1.2
        mock_wifi.return_value = {'interface': 'wlan0', 'signal_percent': 80}

        result = get_pi_metrics()

        assert result['throttling'] is not None
        assert result['cpu_freq_mhz'] == 1500
        assert result['cpu_voltage'] == 1.2
        assert result['wifi_signal'] is not None
        assert result['is_raspberry_pi'] is True

    @patch('pi_monitor.get_throttling_status')
    @patch('pi_monitor.get_cpu_frequency')
    @patch('pi_monitor.get_cpu_voltage')
    @patch('pi_monitor.get_wifi_signal')
    def test_pi_metrics_not_pi(self, mock_wifi, mock_voltage, mock_freq, mock_throttle):
        """Test when not on Raspberry Pi."""
        mock_throttle.return_value = None
        mock_freq.return_value = None
        mock_voltage.return_value = None
        mock_wifi.return_value = None

        result = get_pi_metrics()

        assert result['is_raspberry_pi'] is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
