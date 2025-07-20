import pytest
from unittest.mock import patch, MagicMock

from pihealth import create_app


@pytest.fixture
def client():
    with patch("docker.from_env", return_value=MagicMock()):
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client


def test_system_stats_endpoint(client):
    with patch("pihealth.system_routes.psutil") as mock_psutil:
        mock_psutil.virtual_memory.return_value = MagicMock(
            total=1, used=1, available=0, percent=50
        )
        mock_psutil.disk_usage.return_value = MagicMock(
            total=1, used=1, free=0, percent=50
        )
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=1,
            bytes_recv=1,
        )
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.get_json()
        assert "cpu_usage_percent" in data


def test_docker_list_containers(client):
    with patch(
        "pihealth.docker_routes.list_containers",
        return_value=[{"id": "1"}],
    ):
        response = client.get("/api/containers")
        assert response.status_code == 200
        assert response.get_json() == [{"id": "1"}]


def test_drive_list_disks(client):
    with patch("pihealth.drive_routes._drive_manager") as mock_dm:
        mock_dm.return_value.discover_drives.return_value = []
        response = client.get("/api/disks")
        assert response.status_code == 200
        assert response.get_json()["drives"] == []
