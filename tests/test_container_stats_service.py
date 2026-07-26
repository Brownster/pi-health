from datetime import datetime, timezone

import pytest

from container_stats_service import ContainerStatsService


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


class FakeContainer:
    def __init__(self, container_id, name, status="running"):
        self.id = container_id
        self.name = name
        self.status = status


class FakeDocker:
    """Docker port returning scripted stats payloads, one per sample pass."""

    def __init__(self, containers, payloads, *, available=True):
        self.available = available
        self._containers = containers
        self._payloads = payloads
        self.pass_index = -1
        self.calls = []

    def list_containers(self, all=True):
        self.pass_index += 1
        return list(self._containers)

    def container_stats(self, container_id):
        self.calls.append(container_id)
        payload = self._payloads[min(self.pass_index, len(self._payloads) - 1)]
        return payload.get(container_id)

    def get_container(self, container_id):
        return None

    def pull_image(self, tag):
        return None

    def ping(self):
        return True


def payload(
    *,
    cpu_total,
    cpu_system,
    online_cpus=4,
    memory_usage=None,
    memory_limit=None,
    inactive_file=None,
    rx=None,
    tx=None,
    block_read=None,
    block_write=None,
    pids=None,
):
    memory_stats = {}
    if memory_usage is not None:
        memory_stats["usage"] = memory_usage
    if memory_limit is not None:
        memory_stats["limit"] = memory_limit
    if inactive_file is not None:
        memory_stats["stats"] = {"inactive_file": inactive_file}

    networks = {}
    if rx is not None:
        networks["eth0"] = {"rx_bytes": rx, "tx_bytes": tx}

    blkio = {}
    if block_read is not None:
        blkio["io_service_bytes_recursive"] = [
            {"op": "read", "value": block_read},
            {"op": "write", "value": block_write},
        ]

    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total},
            "system_cpu_usage": cpu_system,
            "online_cpus": online_cpus,
        },
        "memory_stats": memory_stats,
        "networks": networks,
        "blkio_stats": blkio,
        "pids_stats": {"current": pids} if pids is not None else {},
    }


class ManualClock:
    """A clock the test advances explicitly, so reads never consume ticks."""

    def __init__(self, start=100.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_service(docker, *, clock=None, sleep=None):
    return ContainerStatsService(
        docker=docker,
        clock=clock or ManualClock(),
        wall_clock=lambda: NOW,
        sleep=sleep or (lambda _seconds: None),
    )


def test_first_sample_has_no_rates_and_second_derives_them():
    docker = FakeDocker(
        [FakeContainer("abcdef1234567890", "jellyfin")],
        [
            {"abcdef1234567890": payload(cpu_total=1_000, cpu_system=100_000, rx=500, tx=200)},
            {"abcdef1234567890": payload(cpu_total=5_000, cpu_system=200_000, rx=1_500, tx=400)},
        ],
    )
    clock = ManualClock()
    service = make_service(docker, clock=clock)

    service.sample()
    first = service.snapshot()["containers"]["abcdef123456"]
    assert first["cpu_percent"] is None
    assert first["net_rx_rate"] is None

    clock.advance(5.0)
    service.sample()
    second = service.snapshot()["containers"]["abcdef123456"]
    # 4000/100000 of all cores over the interval, scaled to 4 cores.
    assert second["cpu_percent"] == pytest.approx(16.0)
    assert second["net_rx"] == 1_500
    assert second["net_rx_rate"] == pytest.approx(200.0)
    assert second["net_tx_rate"] == pytest.approx(40.0)


def test_memory_excludes_page_cache_and_reports_percent():
    docker = FakeDocker(
        [FakeContainer("aaaa111122223333", "sonarr")],
        [
            {
                "aaaa111122223333": payload(
                    cpu_total=1,
                    cpu_system=10,
                    memory_usage=500,
                    memory_limit=2_000,
                    inactive_file=100,
                )
            }
        ],
    )
    service = make_service(docker)
    service.sample()

    entry = service.snapshot()["containers"]["aaaa11112222"]
    assert entry["memory_used"] == 400
    assert entry["memory_limit"] == 2_000
    assert entry["memory_percent"] == pytest.approx(20.0)


def test_missing_memory_cgroup_reports_unavailable_rather_than_zero():
    """Raspberry Pi OS omits the memory controller; nulls must survive to the UI."""
    docker = FakeDocker(
        [FakeContainer("bbbb111122223333", "radarr")],
        [{"bbbb111122223333": payload(cpu_total=1, cpu_system=10, rx=1, tx=1)}],
    )
    service = make_service(docker)
    service.sample()

    snapshot = service.snapshot()
    assert snapshot["containers"]["bbbb11112222"]["memory_used"] is None
    assert snapshot["containers"]["bbbb11112222"]["memory_percent"] is None
    assert snapshot["capabilities"]["memory"] is False
    assert snapshot["capabilities"]["network"] is True


def test_restarted_container_reports_unknown_instead_of_negative_rates():
    docker = FakeDocker(
        [FakeContainer("cccc111122223333", "sabnzbd")],
        [
            {"cccc111122223333": payload(cpu_total=9_000, cpu_system=900_000, rx=9_000, tx=9_000)},
            {"cccc111122223333": payload(cpu_total=10, cpu_system=1_000_000, rx=10, tx=10)},
        ],
    )
    clock = ManualClock()
    service = make_service(docker, clock=clock)
    service.sample()
    clock.advance(5.0)
    service.sample()

    entry = service.snapshot()["containers"]["cccc11112222"]
    assert entry["cpu_percent"] is None
    assert entry["net_rx_rate"] is None


def test_stopped_containers_are_not_sampled():
    docker = FakeDocker(
        [
            FakeContainer("dddd111122223333", "running-one"),
            FakeContainer("eeee111122223333", "stopped-one", status="exited"),
        ],
        [{"dddd111122223333": payload(cpu_total=1, cpu_system=10)}],
    )
    service = make_service(docker)
    service.sample()

    assert docker.calls == ["dddd111122223333"]
    assert set(service.snapshot()["containers"]) == {"dddd11112222"}


def test_lookup_accepts_the_short_id_the_inventory_publishes():
    docker = FakeDocker(
        [FakeContainer("ffff111122223333", "jackett")],
        [{"ffff111122223333": payload(cpu_total=1, cpu_system=10, memory_usage=5, memory_limit=50)}],
    )
    service = make_service(docker)
    service.sample()

    legacy = service.stats_for("ffff11112222")
    assert legacy["memory"] == {"used": 5, "limit": 50, "percent": 10.0}
    assert service.get("ffff111122223333")["name"] == "jackett"
    assert service.get("nope") is None


def test_top_ranks_by_requested_key_and_skips_unknown_readings():
    docker = FakeDocker(
        [
            FakeContainer("1111111111111111", "busy"),
            FakeContainer("2222222222222222", "idle"),
        ],
        [
            {
                "1111111111111111": payload(cpu_total=0, cpu_system=0),
                "2222222222222222": payload(cpu_total=0, cpu_system=0),
            },
            {
                "1111111111111111": payload(cpu_total=40_000, cpu_system=100_000),
                "2222222222222222": payload(cpu_total=1_000, cpu_system=100_000),
            },
        ],
    )
    clock = ManualClock()
    service = make_service(docker, clock=clock)
    service.sample()
    clock.advance(5.0)
    service.sample()

    ranked = service.top(key="cpu_percent", limit=5)
    assert [item["name"] for item in ranked] == ["busy", "idle"]
    assert ranked[0]["cpu_percent"] > ranked[1]["cpu_percent"]


def test_unavailable_docker_yields_an_empty_snapshot():
    docker = FakeDocker([], [{}], available=False)
    service = make_service(docker)

    snapshot = service.snapshot()
    assert snapshot["containers"] == {}
    assert snapshot["capabilities"] == {"memory": False, "network": False, "block_io": False}


def test_cold_cache_primes_a_baseline_before_answering():
    """A reader arriving before the background thread still gets rates."""
    docker = FakeDocker(
        [FakeContainer("9999888877776666", "navidrome")],
        [
            {"9999888877776666": payload(cpu_total=1_000, cpu_system=100_000)},
            {"9999888877776666": payload(cpu_total=3_000, cpu_system=200_000)},
        ],
    )
    clock = ManualClock()
    # The priming sleep is what separates the two readings in real time.
    service = make_service(docker, clock=clock, sleep=clock.advance)

    entry = service.snapshot()["containers"]["999988887777"]
    assert entry["cpu_percent"] == pytest.approx(8.0)
