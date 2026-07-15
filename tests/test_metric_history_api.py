from unittest.mock import Mock

from metric_history import InvalidMetricRange


def test_metric_history_requires_authentication(client):
    assert client.get("/api/system/history?range=24h").status_code == 401


def test_metric_history_delegates_to_injected_service(authenticated_client):
    payload = {
        "range": "7d",
        "from": "2026-07-08T12:00:00Z",
        "to": "2026-07-15T12:00:00Z",
        "bucket_seconds": 1800,
        "points": [],
        "summary": {},
    }
    service = Mock()
    service.query.return_value = payload
    authenticated_client.application.extensions["metric_history_service"] = service

    response = authenticated_client.get("/api/system/history?range=7d")

    assert response.status_code == 200
    assert response.get_json() == payload
    service.query.assert_called_once_with("7d")


def test_metric_history_defaults_to_24_hours(authenticated_client):
    service = Mock()
    service.query.return_value = {"range": "24h", "points": []}
    authenticated_client.application.extensions["metric_history_service"] = service

    assert authenticated_client.get("/api/system/history").status_code == 200
    service.query.assert_called_once_with("24h")


def test_metric_history_returns_400_for_invalid_range(authenticated_client):
    service = Mock()
    service.query.side_effect = InvalidMetricRange("range must be one of: 24h, 7d, 30d")
    authenticated_client.application.extensions["metric_history_service"] = service

    response = authenticated_client.get("/api/system/history?range=90d")

    assert response.status_code == 400
    assert response.get_json() == {"error": "range must be one of: 24h, 7d, 30d"}
