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




def _mock_container(name, cid, status='running', network_mode='',
                    labels=None, health=None, exit_code=None):
    """Build a Mock that looks enough like a docker-py Container for the helpers."""
    container = Mock()
    container.name = name
    container.id = cid
    container.status = status
    container.image.tags = ['img:latest']
    container.ports = {}
    state = {}
    if health is not None:
        state['Health'] = {
            'Status': health,
            'FailingStreak': 0,
            'Log': [{'Output': 'ok', 'ExitCode': 0}],
        }
    if exit_code is not None:
        state['ExitCode'] = exit_code
    container.attrs = {
        'HostConfig': {'NetworkMode': network_mode},
        'Config': {'Labels': labels or {}, 'ExposedPorts': {}},
        'State': state,
        'NetworkSettings': {'Ports': {}},
    }
    return container


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


class TestContainerStatsBatch:
    """Test batch container stats endpoint."""

    def test_stats_batch_returns_dict(self, authenticated_client):
        """Test that /api/containers/stats returns a dict."""
        response = authenticated_client.get('/api/containers/stats?ids=test1,test2')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data, dict)

    def test_stats_batch_empty_ids(self, authenticated_client):
        """Test that empty ids returns empty dict."""
        response = authenticated_client.get('/api/containers/stats?ids=')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data == {}

    def test_stats_batch_no_ids_param(self, authenticated_client):
        """Test that missing ids param returns empty dict."""
        response = authenticated_client.get('/api/containers/stats')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data == {}


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

    def test_logs_success(self, authenticated_client):
        """Test logs endpoint returns decoded logs."""
        service = Mock()
        service.logs.return_value = {"logs": "hello\n", "container": "test"}
        authenticated_client.application.extensions["container_operations_service"] = service
        response = authenticated_client.get('/api/containers/test-container/logs')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["logs"].strip() == "hello"
        service.logs.assert_called_once_with("test-container", tail=200)


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


class TestContainerActions:
    """Test container action helpers with mocked docker client."""

    def test_control_container_invalid_action(self):
        from app import control_container
        result = control_container("id", "nope")
        assert "error" in result

    def test_control_container_docker_unavailable(self):
        from app import control_container
        with patch("app.docker_available", False):
            result = control_container("id", "start")
        assert "error" in result

    def test_check_container_update_no_tag(self):
        from app import check_container_update
        fake_container = Mock()
        fake_container.image.tags = []
        result = check_container_update(fake_container)
        assert "error" in result

    def test_update_container_no_tag(self):
        from app import update_container
        fake_container = Mock()
        fake_container.image.tags = []
        result = update_container(fake_container)
        assert "error" in result


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

    def test_container_network_test_docker_unavailable(self, authenticated_client, monkeypatch):
        """Test container network endpoint returns 503 when Docker is unavailable."""
        monkeypatch.setattr('app.docker_available', False)
        response = authenticated_client.post('/api/containers/test-container/network-test')
        assert response.status_code == 503
        data = json.loads(response.data)
        assert data['error'] == 'Docker is not available'

    def test_container_network_test_with_auth_calls_service(self, authenticated_client):
        service = Mock()
        service.container_test.return_value = {
            'container_name': 'test-container',
            'ping_success': True,
        }
        authenticated_client.application.extensions["network_diagnostics_service"] = service

        response = authenticated_client.post('/api/containers/test-container/network-test')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['container_name'] == 'test-container'
        assert data['ping_success'] is True
        service.container_test.assert_called_once_with('test-container')


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
        mock_container.attrs = {
            'Config': {'Labels': {'limeos.web.scheme': 'https'}},
            'NetworkSettings': {'Ports': {}},
        }
        mock_container.ports = {}

        mock_docker.containers.list.return_value = [mock_container]

        result = list_containers()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['name'] == 'test-container'
        assert result[0]['status'] == 'running'
        assert result[0]['web_url'] is None
        assert result[0]['web_scheme'] == 'https'

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


class TestContainerStats:
    """Test container stats calculation functions."""

    def test_calculate_container_cpu_percent_valid(self):
        """Test CPU percentage calculation with valid stats."""
        from app import calculate_container_cpu_percent

        stats = {
            'cpu_stats': {
                'cpu_usage': {'total_usage': 1000000000},
                'system_cpu_usage': 10000000000,
                'online_cpus': 4
            },
            'precpu_stats': {
                'cpu_usage': {'total_usage': 900000000},
                'system_cpu_usage': 9000000000
            }
        }
        result = calculate_container_cpu_percent(stats)

        assert result is not None
        assert isinstance(result, float)
        assert 0 <= result <= 100

    def test_calculate_container_cpu_percent_empty(self):
        """Test CPU calculation with empty stats."""
        from app import calculate_container_cpu_percent

        result = calculate_container_cpu_percent({})
        assert result is None

    def test_calculate_container_memory_stats_valid(self):
        """Test memory stats extraction with valid data."""
        from app import calculate_container_memory_stats

        stats = {
            'memory_stats': {
                'usage': 104857600,  # 100 MB
                'limit': 1073741824,  # 1 GB
                'stats': {'cache': 10485760}  # 10 MB cache
            }
        }
        result = calculate_container_memory_stats(stats)

        assert result['used'] == 94371840  # 100 MB - 10 MB cache
        assert result['limit'] == 1073741824
        assert result['percent'] is not None
        assert 0 <= result['percent'] <= 100

    def test_calculate_container_memory_stats_empty(self):
        """Test memory calculation with empty stats."""
        from app import calculate_container_memory_stats

        result = calculate_container_memory_stats({})
        # Empty stats return 0 for used/limit, None for percent
        assert result['used'] == 0
        assert result['limit'] == 0
        assert result['percent'] is None

    def test_calculate_container_network_stats_valid(self):
        """Test network stats extraction with valid data."""
        from app import calculate_container_network_stats

        stats = {
            'networks': {
                'eth0': {'rx_bytes': 1000000, 'tx_bytes': 500000},
                'bridge': {'rx_bytes': 200000, 'tx_bytes': 100000}
            }
        }
        result = calculate_container_network_stats(stats)

        assert result['rx'] == 1200000  # Sum of rx
        assert result['tx'] == 600000   # Sum of tx

    def test_calculate_container_network_stats_empty(self):
        """Test network calculation with empty stats."""
        from app import calculate_container_network_stats

        result = calculate_container_network_stats({})
        assert result['rx'] == 0
        assert result['tx'] == 0

    def test_calculate_container_network_stats_no_networks(self):
        """Test network calculation with no networks key."""
        from app import calculate_container_network_stats

        result = calculate_container_network_stats({'networks': {}})
        assert result['rx'] == 0
        assert result['tx'] == 0


class TestNetworkTopology:
    """Tests for VPN-style shared-network detection and orphan flagging."""

    def test_standalone_container(self):
        from app import analyze_network_topology
        c = _mock_container('jellyfin', 'J', network_mode='bridge')
        info, groups = analyze_network_topology([c])
        assert info['J']['role'] == 'standalone'
        assert info['J']['status'] == 'ok'
        assert groups == {}

    def test_member_and_provider(self):
        from app import analyze_network_topology
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge')
        sonarr = _mock_container('sonarr', 'S', network_mode='container:VPNID')
        info, groups = analyze_network_topology([vpn, sonarr])
        assert info['VPNID']['role'] == 'provider'
        assert info['S']['role'] == 'member'
        assert info['S']['provider'] == 'vpn'
        assert info['S']['status'] == 'ok'
        assert 'sonarr' in groups['vpn']['members']

    def test_orphan_detection(self):
        """A member pinned to a namespace id that no longer exists is orphaned."""
        from app import analyze_network_topology
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge')
        # transmission was left pinned to a dead vpn id; depends_on names the service
        trans = _mock_container(
            'transmission', 'T', status='created',
            network_mode='container:DEADID',
            labels={'com.docker.compose.depends_on': 'vpn:service_started:true'},
        )
        info, groups = analyze_network_topology([vpn, trans])
        assert info['T']['status'] == 'orphaned'
        assert info['T']['provider'] == 'vpn'
        assert 'transmission' in groups['vpn']['orphaned']


class TestNetworkGroups:
    """Tests for list_network_groups and the leak probe."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_groups_flag_orphans(self, mock_docker):
        from app import list_network_groups
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge', health='healthy')
        sonarr = _mock_container('sonarr', 'S', network_mode='container:VPNID')
        trans = _mock_container(
            'transmission', 'T', status='created',
            network_mode='container:DEADID',
            labels={'com.docker.compose.depends_on': 'vpn:service_started:true'},
        )
        mock_docker.containers.list.return_value = [vpn, sonarr, trans]
        result = list_network_groups(probe=False)
        assert result['docker_available'] is True
        group = next(g for g in result['groups'] if g['provider'] == 'vpn')
        assert group['status'] == 'degraded'
        assert 'transmission' in group['orphaned_members']
        assert any(o['name'] == 'transmission' for o in result['orphans'])

    @patch('app.get_container_public_ip', return_value='9.9.9.9')
    @patch('app.get_host_public_ip', return_value='9.9.9.9')
    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_vpn_leak_detected(self, mock_docker, mock_host_ip, mock_cip):
        from app import list_network_groups
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge', health='healthy')
        sonarr = _mock_container('sonarr', 'S', network_mode='container:VPNID')
        mock_docker.containers.list.return_value = [vpn, sonarr]
        result = list_network_groups(probe=True)
        group = next(g for g in result['groups'] if g['provider'] == 'vpn')
        assert group['vpn_leak'] is True
        assert group['provider_public_ip'] == '9.9.9.9'

    @patch('app.docker_available', False)
    def test_groups_docker_unavailable(self):
        from app import list_network_groups
        result = list_network_groups()
        assert result['docker_available'] is False
        assert result['groups'] == []


class TestRecreateNetworkGroup:
    """Tests for the one-click VPN-group recreate remedy."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_requires_compose_management(self, mock_docker):
        from app import recreate_network_group
        vpn = _mock_container('vpn', 'VPNID')  # no compose labels
        mock_docker.containers.get.return_value = vpn
        result = recreate_network_group('vpn')
        assert 'error' in result

    @patch('app.subprocess.run')
    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_recreate_builds_compose_command(self, mock_docker, mock_run):
        from app import recreate_network_group
        compose_labels = {
            'com.docker.compose.project.config_files': '/opt/stacks/media/docker-compose.yml',
            'com.docker.compose.project.working_dir': '/opt/stacks/media',
            'com.docker.compose.service': 'vpn',
        }
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge', labels=compose_labels)
        sonarr = _mock_container(
            'sonarr', 'S', network_mode='container:VPNID',
            labels={'com.docker.compose.service': 'sonarr'},
        )
        mock_docker.containers.get.return_value = vpn
        mock_docker.containers.list.return_value = [vpn, sonarr]
        mock_run.return_value = Mock(returncode=0, stdout='done', stderr='')

        result = recreate_network_group('vpn')
        assert result['status'] == 'recreated'
        assert result['services'][0] == 'vpn'  # provider recreated first
        assert 'sonarr' in result['services']
        cmd = mock_run.call_args[0][0]
        assert '--project-directory' in cmd
        assert '/opt/stacks/media' in cmd
        assert cmd[-2:] == ['vpn', 'sonarr'] or set(cmd[-2:]) == {'vpn', 'sonarr'}


class TestContainerHealth:
    """Tests for healthcheck status/output surfacing."""

    def test_health_none_when_absent(self):
        from app import get_container_health
        assert get_container_health(_mock_container('a', 'A')) is None

    def test_health_status(self):
        from app import get_container_health
        assert get_container_health(_mock_container('a', 'A', health='unhealthy')) == 'unhealthy'

    def test_health_detail_includes_output(self):
        from app import get_container_health_detail
        detail = get_container_health_detail(_mock_container('a', 'A', health='unhealthy'))
        assert detail['status'] == 'unhealthy'
        assert detail['last_output'] == 'ok'


class TestListContainersEnrichment:
    """list_containers now carries health, exit_code and network topology."""

    @patch('app.docker_client')
    @patch('app.docker_available', True)
    def test_enriched_fields(self, mock_docker):
        from app import list_containers
        vpn = _mock_container('vpn', 'VPNID', network_mode='bridge', health='healthy')
        sonarr = _mock_container('sonarr', 'S', network_mode='container:VPNID')
        mock_docker.containers.list.return_value = [vpn, sonarr]
        result = list_containers(include_stats=False)
        by_name = {c['name']: c for c in result}
        assert by_name['vpn']['health'] == 'healthy'
        assert by_name['vpn']['network']['role'] == 'provider'
        assert by_name['sonarr']['network']['provider'] == 'vpn'
        assert by_name['sonarr']['network']['status'] == 'ok'
        assert 'exit_code' in by_name['sonarr']


class TestNetworkGroupsAPI:
    """Tests for the network-group and health API routes."""

    def test_network_groups_requires_auth(self, client):
        assert client.get('/api/network-groups').status_code == 401

    def test_network_groups_delegates_probe_to_service(self, authenticated_client):
        service = Mock()
        service.list_groups.return_value = {
            'docker_available': True,
            'groups': [],
            'orphans': [],
        }
        authenticated_client.application.extensions["network_group_service"] = service

        response = authenticated_client.get('/api/network-groups?probe=true')

        assert response.status_code == 200
        assert 'groups' in json.loads(response.data)
        service.list_groups.assert_called_once_with(probe=True)

    def test_recreate_requires_auth(self, client):
        assert client.post('/api/network-groups/vpn/recreate').status_code == 401

    def test_recreate_docker_unavailable(self, authenticated_client, monkeypatch):
        monkeypatch.setattr('app.docker_available', False)
        response = authenticated_client.post('/api/network-groups/vpn/recreate')
        assert response.status_code == 503

    def test_recreate_delegates(self, authenticated_client):
        service = Mock()
        service.recreate.return_value = {'status': 'recreated', 'provider': 'vpn'}
        authenticated_client.application.extensions["network_group_service"] = service

        response = authenticated_client.post('/api/network-groups/vpn/recreate')

        assert response.status_code == 200
        assert json.loads(response.data)['provider'] == 'vpn'
        service.recreate.assert_called_once_with('vpn')

    def test_health_route_docker_unavailable(self, authenticated_client, monkeypatch):
        monkeypatch.setattr('app.docker_available', False)
        response = authenticated_client.get('/api/containers/x/health')
        assert response.status_code == 503

    def test_health_route_delegates_to_service(self, authenticated_client):
        service = Mock()
        service.health.return_value = {"status": "healthy"}
        authenticated_client.application.extensions["network_diagnostics_service"] = service

        response = authenticated_client.get('/api/containers/x/health')

        assert response.status_code == 200
        assert response.get_json() == {"status": "healthy"}
        service.health.assert_called_once_with("x")

    def test_health_route_maps_missing_container(self, authenticated_client):
        from network_diagnostics_service import ContainerNotFoundError

        service = Mock()
        service.health.side_effect = ContainerNotFoundError("not found")
        authenticated_client.application.extensions["network_diagnostics_service"] = service

        response = authenticated_client.get('/api/containers/missing/health')

        assert response.status_code == 404
        assert response.get_json() == {"error": "not found"}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
