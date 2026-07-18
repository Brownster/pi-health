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


def test_disk_inventory_embeds_summary_without_repeating_privileged_reads(
    app, authenticated_client
):
    inventory = {"helper_available": True, "disks": [{"name": "sda"}]}
    summary = {
        "state": "attention",
        "counts": {"total": 1, "unknown": 1},
        "capacity": {"mounted_total_bytes": 0},
        "sources": {"inventory": "available", "smart": "not_checked"},
        "devices": [],
        "warnings": [],
        "collected_at": "2026-07-18T12:30:00Z",
    }
    inventory_service = Mock()
    inventory_service.inventory.return_value = inventory
    summary_service = Mock()
    summary_service.snapshot.return_value = summary
    app.extensions["disk_inventory_service"] = inventory_service
    app.extensions["disk_summary_service"] = summary_service

    response = authenticated_client.get("/api/disks")

    assert response.status_code == 200
    assert response.get_json() == {**inventory, "summary": summary}
    inventory_service.inventory.assert_called_once_with()
    summary_service.snapshot.assert_called_once_with(
        inventory=inventory, include_smart=False
    )
