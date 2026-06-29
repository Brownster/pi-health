"""System telemetry collection independent of Flask routing."""

import os
import time

import psutil


def calculate_cpu_usage(cpu_line):
    user, nice, system, idle, iowait, irq, softirq, steal = map(int, cpu_line[1:9])
    total_time = user + nice + system + idle + iowait + irq + softirq + steal
    idle_time = idle + iowait
    return 100 * (total_time - idle_time) / total_time


def get_cpu_usage_per_core(stat_lines):
    per_core = []
    for line in stat_lines:
        if not line.startswith('cpu') or line.startswith('cpu '):
            continue
        parts = line.split()
        if len(parts) >= 9:
            per_core.append({'core': parts[0], 'usage_percent': calculate_cpu_usage(parts)})
    return per_core


def get_temperature_fallback():
    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
    except Exception:
        return None
    if not temperatures:
        return None

    preferred = ('cpu_thermal', 'cpu-thermal', 'coretemp', 'k10temp', 'soc_thermal', 'cpu')
    for key in preferred:
        for entry in temperatures.get(key, []):
            if getattr(entry, 'current', None) is not None:
                return entry.current
    for entries in temperatures.values():
        for entry in entries:
            if getattr(entry, 'current', None) is not None:
                return entry.current
    return None


def _read_proc_stat_cpu(path):
    counters = {}
    with open(path, 'r') as stat_file:
        for line in stat_file:
            if line.startswith('cpu'):
                parts = line.split()
                try:
                    counters[parts[0]] = list(map(int, parts[1:9]))
                except (ValueError, IndexError):
                    continue
            elif counters:
                break
    return counters


def _cpu_percent_from_delta(start, end):
    total = sum(end) - sum(start)
    idle = (end[3] + end[4]) - (start[3] + start[4])
    if total <= 0:
        return None
    return round(100 * (total - idle) / total, 1)


def get_cpu_usage_delta(interval=0.1, *, stat_reader=_read_proc_stat_cpu):
    for stat_path in ['/host_proc/stat', '/proc/stat']:
        try:
            start = stat_reader(stat_path)
            if not start:
                continue
            time.sleep(interval)
            end = stat_reader(stat_path)
            aggregate = None
            if 'cpu' in start and 'cpu' in end:
                aggregate = _cpu_percent_from_delta(start['cpu'], end['cpu'])
            per_core = [
                {'core': name, 'usage_percent': _cpu_percent_from_delta(start[name], end[name])}
                for name in sorted(start)
                if name != 'cpu' and name in end
            ]
            return aggregate, per_core
        except Exception:
            continue
    return None, []


def _safe_disk_usage(path):
    try:
        usage = psutil.disk_usage(path)
    except Exception:
        return None
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": usage.percent,
    }


def _collect_disk_usage(metric, path, warnings, *, disk_reader=_safe_disk_usage):
    usage = disk_reader(path)
    if usage is None:
        warnings.append({
            'code': 'source_unavailable',
            'metric': metric,
            'source': path,
            'message': f'Disk usage unavailable for {path}',
        })
    return usage


def get_system_stats(
    *,
    cpu_reader=get_cpu_usage_delta,
    disk_collector=_collect_disk_usage,
    pi_metrics_reader,
):
    cpu_usage, per_core = cpu_reader()
    memory = psutil.virtual_memory()
    warnings = []
    disk_usage = disk_collector('disk_usage', os.getenv('DISK_PATH', '/'), warnings)
    disk_usage_2 = disk_collector(
        'disk_usage_2',
        os.getenv('DISK_PATH_2', '/mnt/backup'),
        warnings,
    )

    temperature = None
    if os.path.exists('/usr/bin/vcgencmd'):
        try:
            output = os.popen("vcgencmd measure_temp").readline()
            temperature = float(output.replace("temp=", "").replace("'C\n", ""))
        except Exception:
            pass
    if temperature is None:
        temperature = get_temperature_fallback()

    network = psutil.net_io_counters()
    pi_metrics = pi_metrics_reader()
    return {
        "cpu_usage_percent": cpu_usage,
        "cpu_usage_per_core": per_core,
        "memory_usage": {
            "total": memory.total,
            "used": memory.used,
            "free": memory.available,
            "percent": memory.percent,
        },
        "disk_usage": disk_usage,
        "disk_usage_2": disk_usage_2,
        "temperature_celsius": temperature,
        "network_usage": {
            "bytes_sent": network.bytes_sent,
            "bytes_recv": network.bytes_recv,
        },
        "throttling": pi_metrics.get('throttling'),
        "cpu_freq_mhz": pi_metrics.get('cpu_freq_mhz'),
        "cpu_voltage": pi_metrics.get('cpu_voltage'),
        "wifi_signal": pi_metrics.get('wifi_signal'),
        "is_raspberry_pi": pi_metrics.get('is_raspberry_pi', False),
        "warnings": warnings,
    }
