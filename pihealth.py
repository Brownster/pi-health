# Step 2: Backend - System Metrics Collection

import psutil
import os

def get_system_stats():
    """Gather system statistics from the host."""
    with open('/host_proc/stat', 'r') as f:
        # Parse CPU usage from host /proc/stat (simplified example)
        cpu_line = f.readline().split()
        cpu_usage_percent = calculate_cpu_usage(cpu_line)  # Custom function for parsing

    # Similarly, parse memory and other metrics from /host_proc/meminfo or /host_sys
    return {
        "cpu_usage_percent": cpu_usage_percent,

    # Memory usage
    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    # Disk usage
    disk = psutil.disk_usage('/')
    disk_usage = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
    }

    # Temperature (specific to Raspberry Pi)
    try:
        # For Raspberry Pi, read temperature from vcgencmd
        temp_output = os.popen("vcgencmd measure_temp").readline()
        temperature = float(temp_output.replace("temp=", "").replace("'C\n", ""))
    except Exception as e:
        temperature = None

    # Network I/O
    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    # Combine all stats
    stats = {
        "cpu_usage_percent": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }
    return stats

# Test the function to ensure it works as expected
system_stats = get_system_stats()
system_stats
