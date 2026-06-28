#!/usr/bin/env python3
"""
Tests for helper functions in app.py
"""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (
    parse_port_key,
    get_container_ports,
    inherit_ports_from_network_service,
    calculate_cpu_usage,
    get_system_stats,
    run_network_test,
    run_container_network_test,
    container_http_probe_script,
    run_container_fallback_probe,
    command_missing,
    calculate_container_cpu_percent,
    calculate_container_memory_stats,
    calculate_container_network_stats,
    exec_in_container,
    system_action,
)


class FakeContainer:
    def __init__(self, name, attrs):
        self.name = name
        self.attrs = attrs
        self.id = f"{name}-id"


class TestPortParsing:
    def test_parse_port_key_int(self):
        port, proto = parse_port_key(8080)
        assert port == 8080
        assert proto == "tcp"

    def test_parse_port_key_string(self):
        port, proto = parse_port_key("443/tcp")
        assert port == 443
        assert proto == "tcp"

    def test_parse_port_key_invalid(self):
        port, proto = parse_port_key("notaport/udp")
        assert port is None
        assert proto == "udp"


class TestContainerPorts:
    def test_get_container_ports(self):
        container = FakeContainer(
            "app",
            {
                "NetworkSettings": {
                    "Ports": {
                        "8080/tcp": [{"HostPort": "8081", "HostIp": "0.0.0.0"}],
                        "9090/tcp": None,
                    }
                },
                "Config": {"ExposedPorts": {"7070/udp": {}, "8080/tcp": {}}},
            },
        )

        ports = get_container_ports(container)

        assert any(
            p["container_port"] == 8080
            and p["protocol"] == "tcp"
            and p["host_port"] == 8081
            and p["host_ip"] is None
            for p in ports
        )
        assert any(
            p["container_port"] == 9090
            and p["protocol"] == "tcp"
            and p["host_port"] is None
            for p in ports
        )
        assert any(
            p["container_port"] == 7070
            and p["protocol"] == "udp"
            and p["host_port"] is None
            for p in ports
        )
    def test_inherit_ports_from_network_service(self):
        service_container = FakeContainer(
            "web",
            {
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostPort": "8081", "HostIp": "127.0.0.1"}]}
                },
                "Config": {"ExposedPorts": {"8080/tcp": {}}},
            },
        )

        app_container = FakeContainer(
            "app",
            {
                "HostConfig": {"NetworkMode": "service:web"},
                "Config": {"ExposedPorts": {"8080/tcp": {}, "8443/tcp": {}}},
            },
        )

        ports = inherit_ports_from_network_service(
            app_container,
            {"web": service_container},
            {},
        )

        assert any(
            p["container_port"] == 8080
            and p["host_port"] == 8081
            and p["host_ip"] == "127.0.0.1"
            and p["via_service"] == "web"
            for p in ports
        )
        assert any(
            p["container_port"] == 8443
            and p["host_port"] is None
            and p["via_service"] == "web"
            for p in ports
        )


class TestContainerWebMetadata:
    def test_explicit_url_takes_precedence(self, monkeypatch):
        from app import get_container_web_metadata

        monkeypatch.setenv("PIHEALTH_SERVICE_LINK_SCHEME", "http")
        container = FakeContainer(
            "app",
            {
                "Config": {
                    "Labels": {
                        "limeos.web.url": "https://media.example.test/app",
                        "limeos.web.scheme": "http",
                    }
                }
            },
        )

        assert get_container_web_metadata(container) == {
            "web_url": "https://media.example.test/app",
            "web_scheme": "https",
        }

    def test_scheme_label_precedes_deployment_fallback(self, monkeypatch):
        from app import get_container_web_metadata

        monkeypatch.setenv("PIHEALTH_SERVICE_LINK_SCHEME", "http")
        container = FakeContainer(
            "app",
            {"Config": {"Labels": {"limeos.web.scheme": "HTTPS"}}},
        )

        assert get_container_web_metadata(container) == {
            "web_url": None,
            "web_scheme": "https",
        }

    def test_deployment_fallback_is_explicit_and_bounded(self, monkeypatch):
        from app import get_container_web_metadata

        container = FakeContainer("app", {"Config": {"Labels": {}}})
        monkeypatch.setenv("PIHEALTH_SERVICE_LINK_SCHEME", "https")
        assert get_container_web_metadata(container)["web_scheme"] == "https"

        monkeypatch.setenv("PIHEALTH_SERVICE_LINK_SCHEME", "ftp")
        assert get_container_web_metadata(container) == {
            "web_url": None,
            "web_scheme": None,
        }

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "ftp://media.example.test/app",
            "https://user:password@media.example.test/app",
            "https:///missing-host",
        ],
    )
    def test_unsafe_explicit_url_is_rejected(self, monkeypatch, url):
        from app import get_container_web_metadata

        monkeypatch.delenv("PIHEALTH_SERVICE_LINK_SCHEME", raising=False)
        container = FakeContainer(
            "app",
            {"Config": {"Labels": {"limeos.web.url": url}}},
        )

        assert get_container_web_metadata(container) == {
            "web_url": None,
            "web_scheme": None,
        }


class TestContainerStatsHelpers:
    def test_calculate_container_cpu_percent(self):
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1]},
                "system_cpu_usage": 1000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100},
                "system_cpu_usage": 500,
            },
        }
        assert calculate_container_cpu_percent(stats) == 40.0

    def test_calculate_container_memory_stats(self):
        stats = {
            "memory_stats": {
                "usage": 1000,
                "limit": 2000,
                "stats": {"cache": 200},
            }
        }
        memory = calculate_container_memory_stats(stats)
        assert memory["used"] == 800
        assert memory["limit"] == 2000
        assert memory["percent"] == 40.0

    def test_calculate_container_network_stats(self):
        stats = {
            "networks": {
                "eth0": {"rx_bytes": 100, "tx_bytes": 200},
                "eth1": {"rx_bytes": 300, "tx_bytes": 400},
            }
        }
        network = calculate_container_network_stats(stats)
        assert network["rx"] == 400
        assert network["tx"] == 600


class TestSystemStats:
    def test_calculate_cpu_usage(self):
        cpu_line = ["cpu", "10", "0", "10", "80", "0", "0", "0", "0"]
        assert round(calculate_cpu_usage(cpu_line), 2) == 20.0

    def test_get_system_stats(self):
        with patch.dict(os.environ, {"DISK_PATH": "/mnt/data", "DISK_PATH_2": "/mnt/backup"}):
            with patch("app.get_cpu_usage_delta", return_value=(20.0, [])):
                with patch("app.psutil.virtual_memory") as mock_mem:
                    with patch("app.psutil.disk_usage") as mock_disk:
                        with patch("app.psutil.net_io_counters") as mock_net:
                            with patch("app.os.path.exists", return_value=False):
                                with patch("app.get_pi_metrics", return_value={"throttling": None, "is_raspberry_pi": False}):
                                    mock_mem.return_value = MagicMock(total=1, used=2, available=3, percent=4)
                                    mock_disk.side_effect = [
                                        MagicMock(total=5, used=6, free=7, percent=8),
                                        MagicMock(total=9, used=10, free=11, percent=12),
                                    ]
                                    mock_net.return_value = MagicMock(bytes_sent=13, bytes_recv=14)

                                    stats = get_system_stats()

        assert stats["cpu_usage_percent"] == 20.0
        assert stats["disk_usage"]["total"] == 5
        assert stats["disk_usage_2"]["total"] == 9


class TestHelpers:
    def test_command_missing(self):
        assert command_missing(127, "not found")
        assert command_missing(126, "permission denied") is True
        assert command_missing(1, "other") is False

    def test_exec_in_container_decodes_tuple(self):
        fake_container = MagicMock()
        fake_container.exec_run.return_value.exit_code = 0
        fake_container.exec_run.return_value.output = (b"ok", b"err")

        exit_code, output = exec_in_container(fake_container, "echo ok")

        assert exit_code == 0
        assert "ok" in output
        assert "err" in output

    def test_system_action_shutdown(self):
        with patch("app.subprocess.Popen") as mock_popen:
            result = system_action("shutdown")
        mock_popen.assert_called_once_with(["sudo", "shutdown", "-h", "now"])
        assert result["status"] == "Shutdown initiated"

    def test_system_action_reboot(self):
        with patch("app.subprocess.Popen") as mock_popen:
            result = system_action("reboot")
        mock_popen.assert_called_once_with(["sudo", "reboot"])
        assert result["status"] == "Reboot initiated"

    def test_system_action_invalid(self):
        result = system_action("invalid")
        assert result["error"] == "Invalid system action"


class TestNetworkDiagnostics:
    def test_container_http_probe_script(self):
        script = container_http_probe_script("curl")
        assert "curl" in script
        script = container_http_probe_script("python3")
        assert "python3" in script

    def test_run_container_fallback_probe_success(self):
        container = MagicMock()
        with patch("app.exec_in_container", return_value=(0, "ok")):
            success, message, tool, public_ip = run_container_fallback_probe(container)
        assert success is True
        assert tool in ("curl", "wget", "busybox", "python3")

    def test_run_container_fallback_probe_missing_tools(self):
        container = MagicMock()
        with patch("app.exec_in_container", return_value=(127, "not found")):
            success, message, tool, public_ip = run_container_fallback_probe(container)
        assert success is False
        assert tool == "unavailable"

    def test_run_network_test_socket_fallback(self):
        socket_probe_result = (True, "Socket connection to 8.8.8.8:53 succeeded.")
        hostname_result = MagicMock(stdout="192.168.1.2\n", stderr="", returncode=0)

        with patch("app.subprocess.run", side_effect=[FileNotFoundError(), hostname_result]):
            with patch("app.socket_probe", return_value=socket_probe_result):
                with patch("app.urlrequest.urlopen") as mock_urlopen:
                    mock_urlopen.return_value.__enter__.return_value.read.return_value = b"1.2.3.4"
                    result = run_network_test()

        assert result["ping_success"] is True
        assert result["probe_method"] == "socket"
        assert result["public_ip"] == "1.2.3.4"

    def test_run_container_network_test_not_found(self):
        fake_client = MagicMock()
        fake_client.containers.get.side_effect = Exception("nope")
        with patch("app.docker_client", fake_client):
            result = run_container_network_test("missing")
        assert "error" in result
