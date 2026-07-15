from datetime import datetime, timezone

from overview_service import MAX_APPLICATIONS, MAX_ISSUES, OverviewService


NOW = datetime(2026, 7, 15, 12, 30, tzinfo=timezone.utc)


def healthy_stats(**overrides):
    stats = {
        "cpu_usage_percent": 12.5,
        "memory_usage": {"percent": 37.5, "used": 3_000, "total": 8_000},
        "temperature_celsius": 52.4,
        "disk_usage": {"percent": 41.0, "used": 400, "total": 1_000},
        "warnings": [],
    }
    stats.update(overrides)
    return stats


def container(
    name,
    *,
    status="running",
    health=None,
    restart_policy="unless-stopped",
    port=None,
    web_url=None,
):
    ports = [] if port is None else [
        {"container_port": port, "protocol": "tcp", "host_port": port, "host_ip": None}
    ]
    return {
        "id": f"{name}-id",
        "name": name,
        "status": status,
        "health": health,
        "restart_policy": restart_policy,
        "image": f"{name}:latest",
        "ports": ports,
        "web_url": web_url,
        "web_scheme": None,
    }


def make_service(
    *,
    stats=None,
    containers=None,
    stacks=None,
    alert_status=None,
    recoveries=None,
):
    return OverviewService(
        system_stats_provider=lambda: healthy_stats() if stats is None else stats,
        container_provider=lambda: [] if containers is None else containers,
        stack_provider=lambda: ([] if stacks is None else stacks, None),
        alert_status_provider=lambda: {"installed": False, "incidents": [], "resources": []}
        if alert_status is None
        else alert_status,
        recent_recoveries_provider=lambda: [] if recoveries is None else recoveries,
        clock=lambda: NOW,
    )


def test_healthy_snapshot_composes_counts_metrics_and_web_apps():
    service = make_service(
        containers=[container("jellyfin", port=8096), container("worker")],
        stacks=[{"name": "media", "status": "running"}],
    )

    result = service.snapshot()

    assert result["health"] == {"state": "healthy", "issues": []}
    assert result["metrics"] == {
        "cpu_percent": 12.5,
        "memory_percent": 37.5,
        "memory_used": 3_000,
        "memory_total": 8_000,
        "temperature_celsius": 52.4,
        "disk_percent": 41.0,
        "disk_used": 400,
        "disk_total": 1_000,
    }
    assert result["workloads"]["containers"] == {
        "total": 2,
        "running": 2,
        "unhealthy": 0,
        "stopped": 0,
    }
    assert result["workloads"]["stacks"] == {
        "total": 1,
        "healthy": 1,
        "partial": 0,
        "down": 0,
        "unknown": 0,
    }
    assert [application["name"] for application in result["applications"]] == ["jellyfin"]
    assert result["applications"][0]["port"] == 8096
    assert result["collected_at"] == "2026-07-15T12:30:00Z"


def test_health_uses_strongest_state_and_distinguishes_intentional_stops():
    service = make_service(
        stats=healthy_stats(cpu_usage_percent=65.0),
        containers=[
            container("bad", health="unhealthy"),
            container("job", status="exited", restart_policy="no"),
            container("api", status="exited", restart_policy="always"),
        ],
        stacks=[
            {"name": "media", "status": "partial"},
            {"name": "chat", "status": "stopped"},
        ],
        alert_status={
            "installed": True,
            "state": "degraded",
            "resources": [],
            "incidents": [
                {
                    "key": "mount:/mnt/media",
                    "kind": "mount",
                    "severity": "critical",
                    "summary": "Media mount is missing",
                    "opened_at": "2026-07-15T12:00:00Z",
                }
            ],
        },
    )

    result = service.snapshot()
    codes = {issue["code"] for issue in result["health"]["issues"]}

    assert result["health"]["state"] == "critical"
    assert "container.bad.unhealthy" in codes
    assert "container.api.stopped" in codes
    assert "container.job.stopped" not in codes
    assert "stack.chat.down" in codes
    assert "alert.mount:/mnt/media" in codes
    assert result["workloads"]["containers"]["stopped"] == 2


def test_current_failed_alert_resource_is_visible_before_incident_threshold():
    result = make_service(
        alert_status={
            "installed": True,
            "state": "connected",
            "incidents": [],
            "resources": [
                {
                    "key": "smart:/dev/sda",
                    "kind": "smart",
                    "ok": False,
                    "severity": "critical",
                    "summary": "Disk health check failed",
                }
            ],
        }
    ).snapshot()

    assert result["health"]["state"] == "critical"
    assert result["health"]["issues"][0]["code"] == "resource.smart:/dev/sda"


def test_partial_source_failures_return_a_bounded_unknown_snapshot():
    def unavailable():
        raise RuntimeError("private provider detail")

    service = OverviewService(
        system_stats_provider=unavailable,
        container_provider=unavailable,
        stack_provider=unavailable,
        alert_status_provider=unavailable,
        recent_recoveries_provider=unavailable,
        clock=lambda: NOW,
    )

    result = service.snapshot()

    assert result["health"]["state"] == "unknown"
    assert {warning["source"] for warning in result["warnings"]} == {
        "system",
        "containers",
        "stacks",
        "alerts",
        "alert_history",
    }
    assert "private provider detail" not in str(result)
    assert result["alerts"] == {"active": [], "recent_recoveries": []}


def test_recoveries_are_filtered_sorted_and_limited():
    recoveries = [
        {
            "event": "recovery",
            "key": f"container:{index}",
            "kind": "container",
            "severity": "warning",
            "summary": "Recovered",
            "at": f"2026-07-15T{index:02d}:00:00Z",
        }
        for index in range(8)
    ]
    recoveries.append({"event": "incident", "key": "ignored", "at": "later"})

    result = make_service(recoveries=recoveries).snapshot()

    assert [record["key"] for record in result["alerts"]["recent_recoveries"]] == [
        "container:7",
        "container:6",
        "container:5",
        "container:4",
        "container:3",
    ]


def test_application_links_are_validated_sorted_and_bounded():
    containers = [container(f"app-{index:03d}", port=8_000 + index) for index in range(140)]
    containers.extend(
        [
            container("explicit", web_url="https://example.test/app"),
            container("unsafe", web_url="https://user:secret@example.test"),
        ]
    )

    result = make_service(containers=containers).snapshot()

    assert len(result["applications"]) == MAX_APPLICATIONS
    assert all(application["name"] != "unsafe" for application in result["applications"])
    assert any(warning["code"] == "result_truncated" for warning in result["warnings"])


def test_visible_issues_are_bounded_without_weakening_health_state():
    containers = [container(f"bad-{index}", health="unhealthy") for index in range(150)]

    result = make_service(containers=containers).snapshot()

    assert result["health"]["state"] == "critical"
    assert len(result["health"]["issues"]) == MAX_ISSUES
    assert any(warning["source"] == "health" for warning in result["warnings"])
