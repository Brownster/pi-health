import psutil
import os
import time


def calculate_cpu_usage(cpu_line_start, cpu_line_end):
    """Calculate CPU usage based on two snapshots of /proc/stat values."""
    user_start, nice_start, system_start, idle_start, iowait_start, irq_start, softirq_start, steal_start = map(int, cpu_line_start[1:9])
    user_end, nice_end, system_end, idle_end, iowait_end, irq_end, softirq_end, steal_end = map(int, cpu_line_end[1:9])

    total_start = sum([user_start, nice_start, system_start, idle_start, iowait_start, irq_start, softirq_start, steal_start])
    total_end = sum([user_end, nice_end, system_end, idle_end, iowait_end, irq_end, softirq_end, steal_end])

    idle_start = idle_start + iowait_start
    idle_end = idle_end + iowait_end

    total_diff = total_end - total_start
    idle_diff = idle_end - idle_start

    usage_percent = 100 * (total_diff - idle_diff) / total_diff
    return usage_percent


def get_cpu_usage():
    """Get CPU usage over a time interval."""
    with open('/host_proc/stat', 'r') as f:
        cpu_line_start = f.readline().split()

    time.sleep(0.1)

    with open('/host_proc/stat', 'r') as f:
        cpu_line_end = f.readline().split()

    return calculate_cpu_usage(cpu_line_start, cpu_line_end)


def get_temperature():
    """Get the CPU temperature (Raspberry Pi specific)."""
    if not os.path.exists('/usr/bin/vcgencmd'):
        return None

    try:
        temp_output = os.popen("vcgencmd measure_temp").readline()
        temperature = float(temp_output.replace("temp=", "").replace("'C\n", ""))
        return temperature
    except Exception:
        return None


def get_system_stats():
    """Gather system statistics from the host."""
    try:
        cpu_usage = get_cpu_usage()
    except Exception:
        cpu_usage = None

    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    disk_path = os.getenv('DISK_PATH', '/')
    disk = psutil.disk_usage(disk_path)
    disk_usage = {
        "total": disk.total,
        "used": disk.used,
        "free": disk.free,
        "percent": disk.percent,
    }

    temperature = get_temperature()

    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    stats = {
        "cpu_usage_percent": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }
    return stats


if __name__ == "__main__":
    system_stats = get_system_stats()
    print(system_stats)
