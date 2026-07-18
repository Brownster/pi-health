"""CP-010 authenticated disk summary API coverage."""

from unittest.mock import Mock


def test_disk_summary_requires_authentication(client):
    response = client.get("/api/disks/summary")

    assert response.status_code == 401


def test_disk_summary_delegates_to_injected_service(app, authenticated_client):
    snapshot = {
        "state": "healthy",
        "counts": {"total": 1},
        "capacity": {"mounted_total_bytes": 1_000},
        "sources": {"inventory": "available"},
        "devices": [],
        "warnings": [],
        "collected_at": "2026-07-18T12:30:00Z",
    }
    service = Mock()
    service.snapshot.return_value = snapshot
    app.extensions["disk_summary_service"] = service

    response = authenticated_client.get("/api/disks/summary")

    assert response.status_code == 200
    assert response.get_json() == snapshot
    service.snapshot.assert_called_once_with()
