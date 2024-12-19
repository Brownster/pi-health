import psutil
import os

def calculate_cpu_usage(cpu_line):
    """Calculate CPU usage based on /proc/stat values."""
    # Extract CPU times from /proc/stat
    user, nice, system, idle, iowait, irq, softirq, steal = map(int, cpu_line[1:9])

    # Calculate the total and idle time
    total_time = user + nice + system + idle + iowait + irq + softirq + steal
    idle_time = idle + iowait

    # Calculate CPU usage as a percentage
    usage_percent = 100 * (total_time - idle_time) / total_time
    return usage_percent


def get_system_stats():
    """Gather system statistics from the host."""
    # CPU usage from /proc/stat
    try:
        with open('/host_proc/stat', 'r') as f:
            cpu_line = f.readline().split()
            cpu_usage = calculate_cpu_usage(cpu_line)
    except Exception:
        cpu_usage = None

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
        temp_output = os.popen("vcgencmd measure_temp").readline()
        temperature = float(temp_output.replace("temp=", "").replace("'C\n", ""))
    except Exception:
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
if __name__ == "__main__":
    system_stats = get_system_stats()
    print(system_stats)
