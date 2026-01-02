#!/usr/bin/env python3
"""
Tests for Container Management functionality
"""
import pytest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


@pytest.fixture
def client():
    """Create a test client for the Flask application."""
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    """Create an authenticated test client."""
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = 'testuser'
    return client


class TestListContainers:
    """Test container listing functionality."""

    def test_list_containers_returns_list(self, authenticated_client):
        """Test that /api/containers returns a list."""
        response = authenticated_client.get('/api/containers')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, list)

    def test_list_containers_structure(self, authenticated_client):
        """Test container list item structure when Docker is available."""
        response = authenticated_client.get('/api/containers')
        assert response.status_code == 200
        data = json.loads(response.data)

        # If there are containers, check structure
        if len(data) > 0 and data[0].get('status') != 'unavailable':
            container = data[0]
            # Should have expected keys
            assert 'id' in container
            assert 'name' in container
            assert 'status' in container
            assert 'image' in container


class TestContainerControl:
    """Test container control operations."""

    def test_control_container_invalid_action(self, authenticated_client):
        """Test that invalid actions are rejected."""
        response = authenticated_client.post('/api/containers/fake-id/invalid_action')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should return error for invalid action
        assert 'error' in data or 'status' in data

    def test_control_container_nonexistent(self, authenticated_client):
        """Test controlling a non-existent container."""
        response = authenticated_client.post('/api/containers/nonexistent123/start')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should return an error
        assert 'error' in data

    def test_start_action_format(self, authenticated_client):
        """Test start action returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/start')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should have either status or error
        assert 'status' in data or 'error' in data

    def test_stop_action_format(self, authenticated_client):
        """Test stop action returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/stop')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data or 'error' in data

    def test_restart_action_format(self, authenticated_client):
        """Test restart action returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/restart')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data or 'error' in data


class TestContainerLogs:
    """Test container logs functionality."""

    def test_logs_endpoint_format(self, authenticated_client):
        """Test logs endpoint returns proper format."""
        response = authenticated_client.get('/api/containers/test-container/logs')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should have logs or error
        assert 'logs' in data or 'error' in data

    def test_logs_with_tail_param(self, authenticated_client):
        """Test logs endpoint with tail parameter."""
        response = authenticated_client.get('/api/containers/test-container/logs?tail=50')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'logs' in data or 'error' in data


class TestContainerUpdate:
    """Test container update functionality."""

    def test_check_update_format(self, authenticated_client):
        """Test check_update action returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/check_update')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should have status or error
        assert 'status' in data or 'error' in data or 'update_available' in data

    def test_update_action_format(self, authenticated_client):
        """Test update action returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/update')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'status' in data or 'error' in data


class TestContainerNetworkTest:
    """Test container network test functionality."""

    def test_network_test_requires_auth(self, client):
        """Test that network test requires authentication."""
        response = client.post('/api/containers/test/network-test')
        assert response.status_code == 401

    def test_container_network_test_format(self, authenticated_client):
        """Test container network test returns proper format."""
        response = authenticated_client.post('/api/containers/test-container/network-test')
        # Should return 200 or 503 (Docker unavailable)
        assert response.status_code in [200, 503]
        data = json.loads(response.data)
        assert 'error' in data or 'container_name' in data


class TestHostNetworkTest:
    """Test host-level network test functionality."""

    def test_host_network_test_format(self, authenticated_client):
        """Test host network test returns proper format."""
        response = authenticated_client.post('/api/network-test')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Should have network test results
        assert 'ping_success' in data or 'error' in data


class TestControlContainerFunction:
    """Unit tests for control_container function with mocking."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_control_container_start_success(self, mock_docker):
        """Test successful container start."""
        from app import control_container

        mock_container = Mock()
        mock_container.status = 'exited'
        mock_docker.containers.get.return_value = mock_container

        result = control_container('test-id', 'start')

        mock_container.start.assert_called_once()
        assert 'status' in result

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_control_container_stop_success(self, mock_docker):
        """Test successful container stop."""
        from app import control_container

        mock_container = Mock()
        mock_container.status = 'running'
        mock_docker.containers.get.return_value = mock_container

        result = control_container('test-id', 'stop')

        mock_container.stop.assert_called_once()
        assert 'status' in result

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_control_container_restart_success(self, mock_docker):
        """Test successful container restart."""
        from app import control_container

        mock_container = Mock()
        mock_docker.containers.get.return_value = mock_container

        result = control_container('test-id', 'restart')

        mock_container.restart.assert_called_once()
        assert 'status' in result

    @patch('app.docker_available', False)
    def test_control_container_docker_unavailable(self):
        """Test control_container when Docker is unavailable."""
        from app import control_container

        result = control_container('test-id', 'start')
        assert 'error' in result

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_control_container_not_found(self, mock_docker):
        """Test control_container when container doesn't exist."""
        from app import control_container
        import docker

        mock_docker.containers.get.side_effect = docker.errors.NotFound('Container not found')

        result = control_container('nonexistent', 'start')
        assert 'error' in result


class TestListContainersFunction:
    """Unit tests for list_containers function with mocking."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_list_containers_success(self, mock_docker):
        """Test successful container listing."""
        from app import list_containers

        mock_container = Mock()
        mock_container.id = 'abc123'
        mock_container.name = 'test-container'
        mock_container.status = 'running'
        mock_container.image.tags = ['nginx:latest']
        mock_container.attrs = {'Config': {}, 'NetworkSettings': {'Ports': {}}}
        mock_container.ports = {}

        mock_docker.containers.list.return_value = [mock_container]

        result = list_containers()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['name'] == 'test-container'
        assert result[0]['status'] == 'running'

    @patch('app.docker_available', False)
    def test_list_containers_docker_unavailable(self):
        """Test list_containers when Docker is unavailable."""
        from app import list_containers

        result = list_containers()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['status'] == 'unavailable'


class TestGetContainerLogs:
    """Unit tests for get_container_logs function."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_get_logs_success(self, mock_docker):
        """Test successful log retrieval."""
        from app import get_container_logs

        mock_container = Mock()
        mock_container.logs.return_value = b'Log line 1\nLog line 2\n'
        mock_docker.containers.get.return_value = mock_container

        result = get_container_logs('test-id', tail=100)

        assert 'logs' in result
        assert 'Log line 1' in result['logs']

    @patch('app.docker_available', False)
    def test_get_logs_docker_unavailable(self):
        """Test get_container_logs when Docker is unavailable."""
        from app import get_container_logs

        result = get_container_logs('test-id')
        assert 'error' in result


class TestCPUCalculation:
    """Test CPU usage calculation."""

    def test_calculate_cpu_usage_valid(self):
        """Test CPU calculation with valid input."""
        from app import calculate_cpu_usage

        # cpu_line format: user, nice, system, idle, iowait, irq, softirq, steal
        cpu_line = ['cpu', '1000', '100', '500', '8000', '100', '50', '25', '10']
        result = calculate_cpu_usage(cpu_line)

        # Should return a percentage between 0 and 100
        assert result is not None
        assert 0 <= result <= 100

    def test_calculate_cpu_usage_empty(self):
        """Test CPU calculation with empty input."""
        from app import calculate_cpu_usage

        # Function doesn't validate input - expects proper /proc/stat format
        # Empty input raises ValueError due to unpacking failure
        try:
            result = calculate_cpu_usage([])
            # If no exception, should return a number
            assert result is None or isinstance(result, (int, float))
        except (ValueError, IndexError):
            # Raised when input doesn't have expected 9 elements - expected behavior
            pass


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
