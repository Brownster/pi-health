from __future__ import annotations

import os
from typing import Any

import psutil
from flask import current_app


def _config_value(key: str, default: Any) -> Any:
    try:
        value = current_app.config.get(key)  # type: ignore[attr-defined]
    except RuntimeError:
        value = None
    return value if value is not None else os.getenv(key, default)


def calculate_cpu_usage(cpu_line):
    user, nice, system, idle, iowait, irq, softirq, steal = map(int, cpu_line[1:9])
    total_time = user + nice + system + idle + iowait + irq + softirq + steal
    idle_time = idle + iowait
    usage_percent = 100 * (total_time - idle_time) / total_time
    return usage_percent


def get_system_stats():
    try:
        with open('/host_proc/stat', 'r') as f:
            cpu_line = f.readline().split()
            cpu_usage = calculate_cpu_usage(cpu_line)
    except Exception:
        cpu_usage = None

    memory = psutil.virtual_memory()
    memory_usage = {
        "total": memory.total,
        "used": memory.used,
        "free": memory.available,
        "percent": memory.percent,
    }

    disk_path = str(_config_value('DISK_PATH', '/'))
    try:
        disk = psutil.disk_usage(disk_path)
        disk_usage = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
        }
    except Exception:
        disk_usage = None

    disk_path_2 = _config_value('DISK_PATH_2', '/mnt/backup')
    try:
        disk_2 = psutil.disk_usage(str(disk_path_2))
        disk_usage_2 = {
            "total": disk_2.total,
            "used": disk_2.used,
            "free": disk_2.free,
            "percent": disk_2.percent,
        }
    except Exception:
        disk_usage_2 = None

    if os.path.exists('/usr/bin/vcgencmd'):
        try:
            temp_output = os.popen("vcgencmd measure_temp").readline()
            temperature = float(temp_output.replace("temp=", "").replace("'C\n", ""))
        except Exception:
            temperature = None
    else:
        temperature = None

    net_io = psutil.net_io_counters()
    network_usage = {
        "bytes_sent": net_io.bytes_sent,
        "bytes_recv": net_io.bytes_recv,
    }

    return {
        "cpu_usage_percent": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "disk_usage_2": disk_usage_2,
        "temperature_celsius": temperature,
        "network_usage": network_usage,
    }
