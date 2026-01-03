#!/usr/bin/env python3
"""
Tests for App Catalog Manager module
"""
import pytest
import json
import sys
import os
import tempfile
import shutil
import yaml
from unittest.mock import patch, Mock

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


@pytest.fixture
def temp_catalog_dir():
    """Create a temporary catalog directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_compose_file():
    """Create a temporary compose file for testing."""
    fd, temp_path = tempfile.mkstemp(suffix='.yml')
    os.close(fd)
    yield temp_path
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def sample_catalog_item():
    """Sample catalog item for testing."""
    return {
        'id': 'test-app',
        'name': 'Test App',
        'description': 'A test application',
        'requires': [],
        'disabled_by_default': False,
        'fields': [
            {'key': 'CONFIG_DIR', 'label': 'Config directory', 'default': '/home/pi/docker'},
            {'key': 'PORT', 'label': 'Port', 'default': '8080'}
        ],
        'service': {
            'image': 'test/image:latest',
            'container_name': 'test-app',
            'ports': ['{{PORT}}:8080'],
            'volumes': ['{{CONFIG_DIR}}/test:/config'],
            'restart': 'unless-stopped'
        }
    }


@pytest.fixture
def vpn_dependent_item():
    """Catalog item that requires VPN."""
    return {
        'id': 'vpn-app',
        'name': 'VPN App',
        'description': 'An app that requires VPN',
        'requires': ['vpn'],
        'fields': [
            {'key': 'CONFIG_DIR', 'label': 'Config directory', 'default': '/home/pi/docker'}
        ],
        'service': {
            'image': 'test/vpn-app:latest',
            'container_name': 'vpn-app',
            'network_mode': 'service:vpn',
            'volumes': ['{{CONFIG_DIR}}/vpn-app:/config'],
            'restart': 'unless-stopped'
        }
    }


class TestCatalogEndpoints:
    """Test catalog API endpoints."""

    def test_catalog_list_requires_auth(self, client):
        """Test that /api/catalog requires authentication."""
        response = client.get('/api/catalog')
        assert response.status_code == 401

    def test_catalog_list_with_auth(self, authenticated_client, temp_catalog_dir, sample_catalog_item):
        """Test GET /api/catalog returns catalog items."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir

        # Write a sample catalog item
        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        try:
            response = authenticated_client.get('/api/catalog')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'items' in data
            assert len(data['items']) == 1
            assert data['items'][0]['id'] == 'test-app'
            assert data['items'][0]['name'] == 'Test App'
        finally:
            catalog_manager.CATALOG_DIR = original_dir

    def test_catalog_get_item_requires_auth(self, client):
        """Test that /api/catalog/<id> requires authentication."""
        response = client.get('/api/catalog/test-app')
        assert response.status_code == 401

    def test_catalog_get_item_not_found(self, authenticated_client, temp_catalog_dir):
        """Test GET /api/catalog/<id> returns 404 for missing item."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir

        try:
            response = authenticated_client.get('/api/catalog/nonexistent')
            assert response.status_code == 404
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            catalog_manager.CATALOG_DIR = original_dir

    def test_catalog_get_item_success(self, authenticated_client, temp_catalog_dir, sample_catalog_item):
        """Test GET /api/catalog/<id> returns item details."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        try:
            response = authenticated_client.get('/api/catalog/test-app')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'item' in data
            assert data['item']['id'] == 'test-app'
            assert 'fields' in data['item']
            assert 'service' in data['item']
        finally:
            catalog_manager.CATALOG_DIR = original_dir

    def test_catalog_status_requires_auth(self, client):
        """Test that /api/catalog/status requires authentication."""
        response = client.get('/api/catalog/status')
        assert response.status_code == 401

    def test_catalog_status_returns_services(self, authenticated_client, temp_compose_file):
        """Test GET /api/catalog/status returns installed services."""
        import catalog_manager
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        compose_data = {
            'version': '3.8',
            'services': {
                'app1': {'image': 'test1'},
                'app2': {'image': 'test2'}
            }
        }
        with open(temp_compose_file, 'w') as f:
            yaml.dump(compose_data, f)

        try:
            response = authenticated_client.get('/api/catalog/status')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'services' in data
            assert 'app1' in data['services']
            assert 'app2' in data['services']
        finally:
            catalog_manager.DOCKER_COMPOSE_PATH = original_path


class TestCatalogInstall:
    """Test catalog install functionality."""

    def test_install_requires_auth(self, client):
        """Test that /api/catalog/install requires authentication."""
        response = client.post('/api/catalog/install',
                              data=json.dumps({'id': 'test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_install_missing_id(self, authenticated_client):
        """Test install without id returns error."""
        response = authenticated_client.post('/api/catalog/install',
                                             data=json.dumps({}),
                                             content_type='application/json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_install_item_not_found(self, authenticated_client, temp_catalog_dir):
        """Test install with nonexistent item returns error."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({'id': 'nonexistent'}),
                                                 content_type='application/json')
            assert response.status_code == 404
        finally:
            catalog_manager.CATALOG_DIR = original_dir

    def test_install_missing_dependency(self, authenticated_client, temp_catalog_dir,
                                        temp_compose_file, vpn_dependent_item):
        """Test install with missing dependency returns error."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        with open(os.path.join(temp_catalog_dir, 'vpn-app.yaml'), 'w') as f:
            yaml.dump(vpn_dependent_item, f)

        # Empty compose file - no VPN installed
        with open(temp_compose_file, 'w') as f:
            yaml.dump({'version': '3.8', 'services': {}}, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({'id': 'vpn-app'}),
                                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'missing_dependencies' in data
            assert 'vpn' in data['missing_dependencies']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path

    def test_install_already_installed(self, authenticated_client, temp_catalog_dir,
                                       temp_compose_file, sample_catalog_item):
        """Test install of already installed app returns error."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        # App already in compose file
        with open(temp_compose_file, 'w') as f:
            yaml.dump({'version': '3.8', 'services': {'test-app': {'image': 'test'}}}, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({'id': 'test-app'}),
                                                 content_type='application/json')
            assert response.status_code == 409
            data = json.loads(response.data)
            assert 'already installed' in data['error'].lower()
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path

    def test_install_success(self, authenticated_client, temp_catalog_dir,
                            temp_compose_file, sample_catalog_item):
        """Test successful install adds service to compose file."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        original_backup = catalog_manager.BACKUP_DIR

        temp_backup_dir = tempfile.mkdtemp()
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file
        catalog_manager.BACKUP_DIR = temp_backup_dir

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        with open(temp_compose_file, 'w') as f:
            yaml.dump({'version': '3.8', 'services': {}}, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({
                                                     'id': 'test-app',
                                                     'values': {
                                                         'CONFIG_DIR': '/custom/path',
                                                         'PORT': '9090'
                                                     }
                                                 }),
                                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'installed'
            assert data['id'] == 'test-app'

            # Verify compose file was updated
            with open(temp_compose_file, 'r') as f:
                compose_data = yaml.safe_load(f)
            assert 'test-app' in compose_data['services']
            service = compose_data['services']['test-app']
            assert '/custom/path/test:/config' in service['volumes']
            assert '9090:8080' in service['ports']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path
            catalog_manager.BACKUP_DIR = original_backup
            shutil.rmtree(temp_backup_dir, ignore_errors=True)


class TestCatalogRemove:
    """Test catalog remove functionality."""

    def test_remove_requires_auth(self, client):
        """Test that /api/catalog/remove requires authentication."""
        response = client.post('/api/catalog/remove',
                              data=json.dumps({'id': 'test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_remove_missing_id(self, authenticated_client):
        """Test remove without id returns error."""
        response = authenticated_client.post('/api/catalog/remove',
                                             data=json.dumps({}),
                                             content_type='application/json')
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_remove_not_installed(self, authenticated_client, temp_compose_file):
        """Test remove of non-installed app returns error."""
        import catalog_manager
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        with open(temp_compose_file, 'w') as f:
            yaml.dump({'version': '3.8', 'services': {}}, f)

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'nonexistent'}),
                                                 content_type='application/json')
            assert response.status_code == 404
        finally:
            catalog_manager.DOCKER_COMPOSE_PATH = original_path

    def test_remove_with_dependents(self, authenticated_client, temp_catalog_dir,
                                    temp_compose_file, vpn_dependent_item):
        """Test remove of app with dependents returns error."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        # Create VPN catalog item
        vpn_item = {
            'id': 'vpn',
            'name': 'VPN',
            'requires': [],
            'service': {'image': 'vpn:latest'}
        }
        with open(os.path.join(temp_catalog_dir, 'vpn.yaml'), 'w') as f:
            yaml.dump(vpn_item, f)
        with open(os.path.join(temp_catalog_dir, 'vpn-app.yaml'), 'w') as f:
            yaml.dump(vpn_dependent_item, f)

        # Both vpn and vpn-app are installed
        with open(temp_compose_file, 'w') as f:
            yaml.dump({
                'version': '3.8',
                'services': {
                    'vpn': {'image': 'vpn'},
                    'vpn-app': {'image': 'vpn-app'}
                }
            }, f)

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'vpn', 'stop_service': False}),
                                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'dependents' in data
            assert 'vpn-app' in data['dependents']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path

    @patch('subprocess.run')
    def test_remove_success(self, mock_run, authenticated_client, temp_catalog_dir,
                           temp_compose_file, sample_catalog_item):
        """Test successful remove deletes service from compose file."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        original_backup = catalog_manager.BACKUP_DIR

        temp_backup_dir = tempfile.mkdtemp()
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file
        catalog_manager.BACKUP_DIR = temp_backup_dir

        mock_run.return_value = Mock(returncode=0, stdout='Stopped', stderr='')

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        with open(temp_compose_file, 'w') as f:
            yaml.dump({
                'version': '3.8',
                'services': {'test-app': {'image': 'test'}}
            }, f)

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'test-app'}),
                                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'removed'

            # Verify compose file was updated
            with open(temp_compose_file, 'r') as f:
                compose_data = yaml.safe_load(f)
            assert 'test-app' not in compose_data['services']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path
            catalog_manager.BACKUP_DIR = original_backup
            shutil.rmtree(temp_backup_dir, ignore_errors=True)


class TestTemplateRendering:
    """Test template rendering functionality."""

    def test_render_template_simple(self):
        """Test simple template variable substitution."""
        from catalog_manager import _render_template

        template = {
            'image': 'test:latest',
            'volumes': ['{{CONFIG_DIR}}/app:/config'],
            'ports': ['{{PORT}}:8080']
        }
        values = {'CONFIG_DIR': '/home/pi', 'PORT': '9000'}

        result = _render_template(template, values)

        assert result['volumes'] == ['/home/pi/app:/config']
        assert result['ports'] == ['9000:8080']

    def test_render_template_nested(self):
        """Test nested structure substitution."""
        from catalog_manager import _render_template

        template = {
            'environment': {
                'HOME': '{{HOME_DIR}}',
                'TZ': '{{TIMEZONE}}'
            }
        }
        values = {'HOME_DIR': '/home/user', 'TIMEZONE': 'UTC'}

        result = _render_template(template, values)

        assert result['environment']['HOME'] == '/home/user'
        assert result['environment']['TZ'] == 'UTC'

    def test_render_template_missing_value(self):
        """Test that missing values are left as placeholders."""
        from catalog_manager import _render_template

        template = {'path': '{{MISSING}}/config'}
        values = {}

        result = _render_template(template, values)

        assert result['path'] == '{{MISSING}}/config'


class TestDependencyChecks:
    """Test dependency checking functionality."""

    def test_check_dependencies_satisfied(self):
        """Test dependency check when all deps are installed."""
        from catalog_manager import _check_dependencies

        item = {'requires': ['vpn', 'db']}
        installed = ['vpn', 'db', 'app1']

        satisfied, missing = _check_dependencies(item, installed)

        assert satisfied is True
        assert missing == []

    def test_check_dependencies_missing(self):
        """Test dependency check when deps are missing."""
        from catalog_manager import _check_dependencies

        item = {'requires': ['vpn', 'db']}
        installed = ['app1']

        satisfied, missing = _check_dependencies(item, installed)

        assert satisfied is False
        assert 'vpn' in missing
        assert 'db' in missing

    def test_check_dependencies_no_requires(self):
        """Test dependency check with no requirements."""
        from catalog_manager import _check_dependencies

        item = {'requires': []}
        installed = []

        satisfied, missing = _check_dependencies(item, installed)

        assert satisfied is True
        assert missing == []


class TestCheckDependenciesEndpoint:
    """Test the check-dependencies endpoint."""

    def test_check_dependencies_endpoint_requires_auth(self, client):
        """Test that /api/catalog/check-dependencies requires auth."""
        response = client.post('/api/catalog/check-dependencies',
                              data=json.dumps({'id': 'test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_check_dependencies_endpoint_success(self, authenticated_client, temp_catalog_dir,
                                                 temp_compose_file, vpn_dependent_item):
        """Test check-dependencies endpoint returns correct status."""
        import catalog_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_path = catalog_manager.DOCKER_COMPOSE_PATH
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        catalog_manager.DOCKER_COMPOSE_PATH = temp_compose_file

        with open(os.path.join(temp_catalog_dir, 'vpn-app.yaml'), 'w') as f:
            yaml.dump(vpn_dependent_item, f)

        with open(temp_compose_file, 'w') as f:
            yaml.dump({'version': '3.8', 'services': {}}, f)

        try:
            response = authenticated_client.post('/api/catalog/check-dependencies',
                                                 data=json.dumps({'id': 'vpn-app'}),
                                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['satisfied'] is False
            assert 'vpn' in data['missing']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            catalog_manager.DOCKER_COMPOSE_PATH = original_path


class TestAppsPage:
    """Test apps page accessibility."""

    def test_apps_page_loads(self, authenticated_client):
        """Test apps page loads successfully."""
        response = authenticated_client.get('/apps.html')
        assert response.status_code == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
