from unittest.mock import Mock

from alert_evaluator import Notification
from alert_history import AlertEventLedger
from app import _default_overview_service


def test_overview_requires_authentication(client):
    assert client.get("/api/overview").status_code == 401


def test_overview_delegates_to_injected_service(authenticated_client):
    snapshot = {
        "health": {"state": "healthy", "issues": []},
        "metrics": {},
        "workloads": {},
        "alerts": {},
        "applications": [],
        "warnings": [],
        "collected_at": "2026-07-15T12:30:00Z",
    }
    service = Mock()
    service.snapshot.return_value = snapshot
    authenticated_client.application.extensions["overview_service"] = service

    response = authenticated_client.get("/api/overview")

    assert response.status_code == 200
    assert response.get_json() == snapshot
    service.snapshot.assert_called_once_with()


def test_default_overview_service_reads_recent_recoveries(tmp_path):
    ledger = AlertEventLedger(tmp_path / "alert-events.jsonl")
    ledger.record(
        Notification(
            event="incident",
            key="container:jellyfin",
            kind="container",
            severity="warning",
            summary="jellyfin stopped",
            at="2026-07-15T12:00:00Z",
        )
    )
    ledger.record(
        Notification(
            event="recovery",
            key="container:jellyfin",
            kind="container",
            severity="warning",
            summary="jellyfin running",
            at="2026-07-15T12:05:00Z",
        )
    )
    system = Mock()
    system.stats.return_value = {
        "cpu_usage_percent": 10,
        "memory_usage": {"percent": 20},
        "temperature_celsius": 40,
        "disk_usage": {"percent": 30},
    }
    containers = Mock()
    containers.list_containers.return_value = []
    stacks = Mock()
    stacks.list_with_status.return_value = ([], None)
    mattermost = Mock()
    mattermost.status.return_value = {"installed": False, "incidents": [], "resources": []}

    service = _default_overview_service(
        system,
        containers,
        stacks,
        mattermost,
        alert_history=ledger,
    )

    assert service.snapshot()["alerts"]["recent_recoveries"][0]["key"] == "container:jellyfin"
