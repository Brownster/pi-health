from unittest.mock import Mock


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
