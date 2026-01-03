"""
Pi-specific hardware monitoring module.
Provides throttling detection, CPU frequency/voltage, and WiFi signal metrics.
"""
import subprocess
import os
import re


def run_vcgencmd(command):
    """Run a vcgencmd command and return output, or None if not available."""
    try:
        result = subprocess.run(
            ['/usr/bin/vcgencmd', command],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def get_throttling_status():
    """
    Get throttling status from vcgencmd get_throttled.

    Returns dict with:
    - raw: hex value from vcgencmd
    - under_voltage_now: bool - currently under-voltage
    - freq_capped_now: bool - frequency currently capped
    - throttled_now: bool - currently throttled
    - soft_temp_limit_now: bool - soft temperature limit active
    - under_voltage_occurred: bool - under-voltage has occurred
    - freq_capped_occurred: bool - frequency capping has occurred
    - throttled_occurred: bool - throttling has occurred
    - soft_temp_limit_occurred: bool - soft temperature limit has occurred
    - has_issues: bool - any current issues
    - has_historical_issues: bool - any historical issues
    """
    output = run_vcgencmd('get_throttled')
    if not output:
        return None

    # Parse "throttled=0x0" format
    match = re.search(r'throttled=(0x[0-9a-fA-F]+)', output)
    if not match:
        return None

    hex_val = int(match.group(1), 16)

    # Bit flags (from Raspberry Pi documentation)
    # Bit 0: Under-voltage detected
    # Bit 1: Arm frequency capped
    # Bit 2: Currently throttled
    # Bit 3: Soft temperature limit active
    # Bit 16: Under-voltage has occurred
    # Bit 17: Arm frequency capping has occurred
    # Bit 18: Throttling has occurred
    # Bit 19: Soft temperature limit has occurred

    result = {
        'raw': match.group(1),
        'under_voltage_now': bool(hex_val & (1 << 0)),
        'freq_capped_now': bool(hex_val & (1 << 1)),
        'throttled_now': bool(hex_val & (1 << 2)),
        'soft_temp_limit_now': bool(hex_val & (1 << 3)),
        'under_voltage_occurred': bool(hex_val & (1 << 16)),
        'freq_capped_occurred': bool(hex_val & (1 << 17)),
        'throttled_occurred': bool(hex_val & (1 << 18)),
        'soft_temp_limit_occurred': bool(hex_val & (1 << 19)),
    }

    result['has_issues'] = any([
        result['under_voltage_now'],
        result['freq_capped_now'],
        result['throttled_now'],
        result['soft_temp_limit_now']
    ])

    result['has_historical_issues'] = any([
        result['under_voltage_occurred'],
        result['freq_capped_occurred'],
        result['throttled_occurred'],
        result['soft_temp_limit_occurred']
    ])

    return result


def get_cpu_frequency():
    """
    Get current CPU frequency in MHz.
    Returns int or None if not available.
    """
    output = run_vcgencmd('measure_clock arm')
    if not output:
        return None

    # Parse "frequency(48)=1500000000" format
    match = re.search(r'frequency\(\d+\)=(\d+)', output)
    if match:
        freq_hz = int(match.group(1))
        return freq_hz // 1_000_000  # Convert to MHz

    return None


def get_cpu_voltage():
    """
    Get current CPU core voltage.
    Returns float (volts) or None if not available.
    """
    output = run_vcgencmd('measure_volts core')
    if not output:
        return None

    # Parse "volt=1.2000V" format
    match = re.search(r'volt=([0-9.]+)V', output)
    if match:
        return float(match.group(1))

    return None


def get_wifi_signal_from_iwconfig():
    """
    Get WiFi signal strength using iwconfig command.
    Fallback when /proc/net/wireless is not available.

    Returns dict with same structure as get_wifi_signal or None.
    """
    try:
        # Try to find iwconfig in common locations
        iwconfig_paths = ['/sbin/iwconfig', '/usr/sbin/iwconfig', 'iwconfig']
        iwconfig_cmd = None

        for path in iwconfig_paths:
            try:
                result = subprocess.run(
                    [path, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                iwconfig_cmd = path
                break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        if not iwconfig_cmd:
            return None

        # Run iwconfig to get all interfaces
        result = subprocess.run(
            [iwconfig_cmd],
            capture_output=True,
            text=True,
            timeout=5
        )

        # iwconfig returns info on stderr for some systems, stdout for others
        output = result.stdout + result.stderr

        # Find wireless interface with signal info
        # Example: wlan0     IEEE 802.11  ... Link Quality=57/70  Signal level=-53 dBm
        interface_pattern = r'^(\w+)\s+IEEE'
        quality_pattern = r'Link Quality[=:](\d+)/(\d+)'
        signal_pattern = r'Signal level[=:](-?\d+)\s*dBm'

        current_interface = None
        for line in output.split('\n'):
            # Check for interface line
            iface_match = re.match(interface_pattern, line)
            if iface_match:
                current_interface = iface_match.group(1)

            # Check for signal info
            quality_match = re.search(quality_pattern, line)
            signal_match = re.search(signal_pattern, line)

            if quality_match and signal_match and current_interface:
                link_quality = int(quality_match.group(1))
                link_max = int(quality_match.group(2))
                signal_level = int(signal_match.group(1))

                # Calculate percentage from link quality (more accurate than dBm conversion)
                signal_percent = int((link_quality / link_max) * 100) if link_max > 0 else 0

                return {
                    'interface': current_interface,
                    'link_quality': link_quality,
                    'signal_level': signal_level,
                    'noise_level': 0,  # Not available from iwconfig
                    'signal_percent': signal_percent
                }

    except (subprocess.TimeoutExpired, Exception):
        pass

    return None


def get_wifi_signal():
    """
    Get WiFi signal strength from /proc/net/wireless or iwconfig fallback.

    Returns dict with:
    - interface: str - interface name (e.g., 'wlan0')
    - link_quality: int - link quality (0-70 typically)
    - signal_level: int - signal level in dBm
    - noise_level: int - noise level in dBm
    - signal_percent: int - approximate signal percentage (0-100)

    Returns None if no WiFi interface or not connected.
    """
    # Try /proc/net/wireless first (faster, no subprocess)
    try:
        with open('/proc/net/wireless', 'r') as f:
            lines = f.readlines()

        # Skip header lines, parse interface data
        for line in lines[2:]:  # First two lines are headers
            parts = line.split()
            if len(parts) >= 4:
                interface = parts[0].rstrip(':')

                # Parse values (may have trailing '.')
                try:
                    link_quality = int(float(parts[2].rstrip('.')))
                    signal_level = int(float(parts[3].rstrip('.')))
                    noise_level = int(float(parts[4].rstrip('.'))) if len(parts) > 4 else 0
                except (ValueError, IndexError):
                    continue

                # Convert signal to approximate percentage
                # dBm typically ranges from -100 (weak) to -30 (strong)
                if signal_level <= -100:
                    signal_percent = 0
                elif signal_level >= -30:
                    signal_percent = 100
                else:
                    signal_percent = int(2 * (signal_level + 100))

                return {
                    'interface': interface,
                    'link_quality': link_quality,
                    'signal_level': signal_level,
                    'noise_level': noise_level,
                    'signal_percent': signal_percent
                }
    except (FileNotFoundError, PermissionError):
        pass

    # Fallback to iwconfig
    return get_wifi_signal_from_iwconfig()


def get_pi_metrics():
    """
    Get all Pi-specific metrics in a single call.

    Returns dict with:
    - throttling: throttling status dict or None
    - cpu_freq_mhz: CPU frequency in MHz or None
    - cpu_voltage: CPU voltage in V or None
    - wifi_signal: WiFi signal dict or None
    - is_raspberry_pi: bool - whether vcgencmd is available
    """
    throttling = get_throttling_status()
    cpu_freq = get_cpu_frequency()
    cpu_voltage = get_cpu_voltage()
    wifi = get_wifi_signal()

    return {
        'throttling': throttling,
        'cpu_freq_mhz': cpu_freq,
        'cpu_voltage': cpu_voltage,
        'wifi_signal': wifi,
        'is_raspberry_pi': throttling is not None or cpu_freq is not None
    }
