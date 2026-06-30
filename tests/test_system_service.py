from types import SimpleNamespace

import system_stats
from system_service import SystemService


def test_system_service_composes_injected_readers(monkeypatch):
    calls = []
    monkeypatch.setenv("DISK_PATH", "/")
    monkeypatch.setenv("DISK_PATH_2", "/mnt/backup")

    def cpu_reader():
        calls.append("cpu")
        return 42.5, [{"core": "cpu0", "usage_percent": 40.0}]

    def disk_collector(metric, path, warnings):
        calls.append((metric, path))
        return {"total": 100, "used": 25, "free": 75, "percent": 25.0}

    def pi_metrics_reader():
        calls.append("pi")
        return {"is_raspberry_pi": True, "cpu_freq_mhz": 1800}

    monkeypatch.setattr(
        system_stats.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16, used=8, available=8, percent=50.0),
    )
    monkeypatch.setattr(
        system_stats.psutil,
        "net_io_counters",
        lambda: SimpleNamespace(bytes_sent=10, bytes_recv=20),
    )
    monkeypatch.setattr(system_stats.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(system_stats, "get_temperature_fallback", lambda: 51.0)

    stats = SystemService(
        cpu_reader=cpu_reader,
        disk_collector=disk_collector,
        pi_metrics_reader=pi_metrics_reader,
    ).stats()

    assert stats["cpu_usage_percent"] == 42.5
    assert stats["memory_usage"]["percent"] == 50.0
    assert stats["network_usage"] == {"bytes_sent": 10, "bytes_recv": 20}
    assert stats["temperature_celsius"] == 51.0
    assert stats["is_raspberry_pi"] is True
    assert calls == [
        "cpu",
        ("disk_usage", "/"),
        ("disk_usage_2", "/mnt/backup"),
        "pi",
    ]
