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
import threading
import yaml
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))




@pytest.fixture
def temp_catalog_dir():
    """Create a temporary catalog directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_stacks_dir():
    """Create a temporary stacks directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


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

    def test_catalog_status_returns_services(self, authenticated_client, temp_stacks_dir):
        """Test GET /api/catalog/status returns installed services."""
        import stack_manager
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        stack_dir = os.path.join(temp_stacks_dir, 'media')
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            yaml.dump({'version': '3.8', 'services': {'app1': {'image': 'test1'}, 'app2': {'image': 'test2'}}}, f)

        try:
            response = authenticated_client.get('/api/catalog/status')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert 'services' in data
            assert 'app1' in data['services']
            assert 'app2' in data['services']
            assert data['service_stacks'] == {'app1': ['media'], 'app2': ['media']}
        finally:
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    def test_catalog_status_deduplicates_stack_membership(self, authenticated_client, temp_stacks_dir):
        """Each installed app is represented once per stack."""
        import stack_manager
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        for stack_name in ('family', 'media'):
            stack_dir = os.path.join(temp_stacks_dir, stack_name)
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
                yaml.dump({'services': {'jellyfin': {'image': 'jellyfin'}}}, f)

        try:
            response = authenticated_client.get('/api/catalog/status')

            assert response.status_code == 200
            assert response.get_json() == {
                'services': ['jellyfin'],
                'service_stacks': {'jellyfin': ['family', 'media']},
            }
        finally:
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup


class TestCatalogInstall:
    """Test catalog install functionality."""

    def test_install_requires_auth(self, client):
        """Test that /api/catalog/install requires authentication."""
        response = client.post('/api/catalog/install',
                              data=json.dumps({'id': 'test'}),
                              content_type='application/json')
        assert response.status_code == 401

    def test_install_requires_csrf(self, client):
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['username'] = 'testuser'
            sess['csrf_token'] = 'expected-token'

        response = client.post('/api/catalog/install', json={'id': 'test-app'})

        assert response.status_code == 403

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
                                        temp_stacks_dir, vpn_dependent_item):
        """Test install with missing dependency returns error."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        with open(os.path.join(temp_catalog_dir, 'vpn-app.yaml'), 'w') as f:
            yaml.dump(vpn_dependent_item, f)

        # Empty stack - no VPN installed
        stack_dir = os.path.join(temp_stacks_dir, 'vpn-stack')
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            yaml.dump({'version': '3.8', 'services': {}}, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({'id': 'vpn-app', 'target_stack': 'vpn-stack'}),
                                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'missing_dependencies' in data
            assert 'vpn' in data['missing_dependencies']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    def test_install_already_installed(self, authenticated_client, temp_catalog_dir,
                                       temp_stacks_dir, sample_catalog_item):
        """Test install of already installed app returns error."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        stack_dir = os.path.join(temp_stacks_dir, 'media')
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            yaml.dump({'version': '3.8', 'services': {'test-app': {'image': 'test'}}}, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({'id': 'test-app', 'target_stack': 'media'}),
                                                 content_type='application/json')
            assert response.status_code == 409
            data = json.loads(response.data)
            assert 'already installed' in data['error'].lower()
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    def test_install_success(self, authenticated_client, temp_catalog_dir,
                            temp_stacks_dir, sample_catalog_item):
        """Test successful install adds service to compose file."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        try:
            response = authenticated_client.post('/api/catalog/install',
                                                 data=json.dumps({
                                                     'id': 'test-app',
                                                     'stack_name': 'media',
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
            with open(os.path.join(temp_stacks_dir, 'media', 'compose.yaml'), 'r') as f:
                compose_data = yaml.safe_load(f)
            assert 'test-app' in compose_data['services']
            service = compose_data['services']['test-app']
            assert '/custom/path/test:/config' in service['volumes']
            assert '9090:8080' in service['ports']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    def test_started_install_returns_replayable_operation_without_waiting(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        sample_catalog_item,
        monkeypatch,
    ):
        import catalog_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, 'CATALOG_DIR', temp_catalog_dir)
        monkeypatch.setattr(stack_manager, 'STACKS_PATH', temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            'BACKUP_DIR',
            os.path.join(temp_stacks_dir, '.backups'),
        )
        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as handle:
            yaml.safe_dump(sample_catalog_item, handle)

        producer_started = threading.Event()
        release_producer = threading.Event()
        runner = MagicMock()

        def stream_command(stack_name, action):
            runner(stack_name, action)
            producer_started.set()
            yield 'data: {"line":"creating"}\n\n'
            release_producer.wait(timeout=2)
            yield 'data: {"done":true,"returncode":0}\n\n'

        monkeypatch.setattr(catalog_manager, 'stream_compose_command', stream_command)

        response = authenticated_client.post(
            '/api/catalog/install',
            json={
                'id': 'test-app',
                'stack_name': 'media',
                'start_service': True,
            },
        )

        assert response.status_code == 202
        assert producer_started.wait(timeout=1)
        payload = response.get_json()
        assert payload['status'] == 'installed'
        assert payload['operation_id']
        assert payload['stream_url'].endswith('/stream')
        with open(os.path.join(temp_stacks_dir, 'media', 'compose.yaml')) as handle:
            assert 'test-app' in yaml.safe_load(handle)['services']

        release_producer.set()
        first = authenticated_client.get(payload['stream_url'])
        second = authenticated_client.get(payload['stream_url'])
        wrong_kind = authenticated_client.get(
            f"/api/stacks/operations/{payload['operation_id']}/stream"
        )

        assert first.status_code == 200
        assert first.get_data() == second.get_data()
        assert wrong_kind.status_code == 404
        assert '"creating"' in first.get_data(as_text=True)
        assert '"done"' in first.get_data(as_text=True)
        runner.assert_called_once_with('media', 'up')

    def test_start_thread_failure_keeps_installed_config_and_reports_error(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        sample_catalog_item,
        monkeypatch,
    ):
        import catalog_manager
        import operation_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, 'CATALOG_DIR', temp_catalog_dir)
        monkeypatch.setattr(stack_manager, 'STACKS_PATH', temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            'BACKUP_DIR',
            os.path.join(temp_stacks_dir, '.backups'),
        )
        monkeypatch.setattr(
            operation_manager.threading.Thread,
            'start',
            MagicMock(side_effect=RuntimeError('thread unavailable')),
        )
        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as handle:
            yaml.safe_dump(sample_catalog_item, handle)

        response = authenticated_client.post(
            '/api/catalog/install',
            json={
                'id': 'test-app',
                'stack_name': 'media',
                'start_service': True,
            },
        )

        assert response.status_code == 500
        payload = response.get_json()
        assert payload['status'] == 'installed'
        assert payload['started'] is False
        assert 'thread unavailable' in payload['error']
        with open(os.path.join(temp_stacks_dir, 'media', 'compose.yaml')) as handle:
            assert 'test-app' in yaml.safe_load(handle)['services']


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

    def test_remove_not_installed(self, authenticated_client, temp_stacks_dir):
        """Test remove of non-installed app returns error."""
        import stack_manager
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'nonexistent'}),
                                                 content_type='application/json')
            assert response.status_code == 404
        finally:
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    def test_remove_with_dependents(self, authenticated_client, temp_catalog_dir,
                                    temp_stacks_dir, vpn_dependent_item):
        """Test remove of app with dependents returns error."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

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

        stack_dir = os.path.join(temp_stacks_dir, 'vpn-stack')
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            yaml.dump({
                'version': '3.8',
                'services': {
                    'vpn': {'image': 'vpn'},
                    'vpn-app': {'image': 'vpn-app'}
                }
            }, f)

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'vpn', 'stop_service': False, 'target_stack': 'vpn-stack'}),
                                                 content_type='application/json')
            assert response.status_code == 400
            data = json.loads(response.data)
            assert 'dependents' in data
            assert 'vpn-app' in data['dependents']
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    @patch('catalog_manager.run_compose_command')
    def test_remove_success(self, mock_run, authenticated_client, temp_catalog_dir,
                           temp_stacks_dir, sample_catalog_item):
        """Test successful remove deletes service from compose file."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR

        catalog_manager.CATALOG_DIR = temp_catalog_dir
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        mock_run.return_value = ({'success': True, 'stdout': 'Stopped', 'stderr': ''}, None)

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as f:
            yaml.dump(sample_catalog_item, f)

        stack_dir = os.path.join(temp_stacks_dir, 'media')
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            yaml.dump({
                'version': '3.8',
                'services': {
                    'test-app': {'image': 'test'},
                    'keep-running': {'image': 'nginx'},
                }
            }, f)

        try:
            response = authenticated_client.post('/api/catalog/remove',
                                                 data=json.dumps({'id': 'test-app', 'target_stack': 'media'}),
                                                 content_type='application/json')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'removed'

            # Verify compose file was updated
            with open(os.path.join(temp_stacks_dir, 'media', 'compose.yaml'), 'r') as f:
                compose_data = yaml.safe_load(f)
            assert 'test-app' not in compose_data['services']
            assert 'keep-running' in compose_data['services']
            mock_run.assert_called_once_with('media', 'stop', service='test-app')
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup

    @patch('catalog_manager.run_compose_command')
    def test_remove_aborts_when_target_stop_fails(
        self, mock_run, authenticated_client, temp_catalog_dir,
        temp_stacks_dir, sample_catalog_item,
    ):
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')
        mock_run.return_value = ({
            'success': False,
            'stdout': '',
            'stderr': 'container stop failed',
            'returncode': 1,
        }, None)

        with open(os.path.join(temp_catalog_dir, 'test-app.yaml'), 'w') as handle:
            yaml.dump(sample_catalog_item, handle)
        stack_dir = os.path.join(temp_stacks_dir, 'media')
        os.makedirs(stack_dir, exist_ok=True)
        compose_path = os.path.join(stack_dir, 'compose.yaml')
        with open(compose_path, 'w') as handle:
            yaml.dump({'services': {
                'test-app': {'image': 'test'},
                'keep-running': {'image': 'nginx'},
            }}, handle)

        try:
            response = authenticated_client.post(
                '/api/catalog/remove',
                json={'id': 'test-app', 'target_stack': 'media'},
            )
            assert response.status_code == 409
            assert 'container stop failed' in response.get_json()['error']
            with open(compose_path) as handle:
                compose_data = yaml.safe_load(handle)
            assert set(compose_data['services']) == {'test-app', 'keep-running'}
            assert not os.path.exists(stack_manager.BACKUP_DIR)
        finally:
            catalog_manager.CATALOG_DIR = original_dir
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup


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
                                                 temp_stacks_dir, vpn_dependent_item):
        """Test check-dependencies endpoint returns correct status."""
        import catalog_manager
        import stack_manager
        original_dir = catalog_manager.CATALOG_DIR
        catalog_manager.CATALOG_DIR = temp_catalog_dir
        original_stacks = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        with open(os.path.join(temp_catalog_dir, 'vpn-app.yaml'), 'w') as f:
            yaml.dump(vpn_dependent_item, f)

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
            stack_manager.STACKS_PATH = original_stacks
            stack_manager.BACKUP_DIR = original_backup


class TestCatalogConcurrency:
    def test_parallel_installs_preserve_both_services(
        self, app, temp_catalog_dir, temp_stacks_dir, monkeypatch
    ):
        import catalog_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, "CATALOG_DIR", temp_catalog_dir)
        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            "BACKUP_DIR",
            os.path.join(temp_stacks_dir, ".backups"),
        )
        stack_dir = os.path.join(temp_stacks_dir, "media")
        os.makedirs(stack_dir)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        with open(compose_path, "w") as handle:
            handle.write("services: {}\n")

        for item_id in ("app-one", "app-two"):
            with open(os.path.join(temp_catalog_dir, f"{item_id}.yaml"), "w") as handle:
                yaml.safe_dump(
                    {
                        "id": item_id,
                        "name": item_id,
                        "requires": [],
                        "service": {"image": f"example/{item_id}:latest"},
                    },
                    handle,
                )

        original_load = catalog_manager._load_stack_compose
        load_barrier = threading.Barrier(2)

        def synchronized_load(stack_path):
            result = original_load(stack_path)
            try:
                load_barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
            return result

        monkeypatch.setattr(
            catalog_manager,
            "_load_stack_compose",
            synchronized_load,
        )
        responses = []

        def install(item_id):
            with app.test_client() as thread_client:
                with thread_client.session_transaction() as session:
                    session["authenticated"] = True
                    session["username"] = "testuser"
                    session["csrf_token"] = "test-csrf-token"
                response = thread_client.post(
                    "/api/catalog/install",
                    json={"id": item_id, "target_stack": "media"},
                    headers={"X-CSRF-Token": "test-csrf-token"},
                )
                responses.append((item_id, response.status_code, response.get_json()))

        threads = [
            threading.Thread(target=install, args=(item_id,))
            for item_id in ("app-one", "app-two")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)

        assert sorted(status for _, status, _ in responses) == [200, 200]
        with open(compose_path) as handle:
            compose_data = yaml.safe_load(handle)
        assert set(compose_data["services"]) == {"app-one", "app-two"}


class TestCatalogComposeRoundTrip:
    def test_install_and_remove_preserve_user_yaml_formatting(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
    ):
        import catalog_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, "CATALOG_DIR", temp_catalog_dir)
        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            "BACKUP_DIR",
            os.path.join(temp_stacks_dir, ".backups"),
        )
        stack_dir = os.path.join(temp_stacks_dir, "media")
        os.makedirs(stack_dir)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        original = (
            "# keep this stack comment\n"
            "x-shared: &shared\n"
            '  image: "redis:7" # keep this image comment\n'
            "services:\n"
            "  existing:\n"
            "    <<: *shared\n"
            "    environment:\n"
            "      MODE: 'prod'\n"
        )
        with open(compose_path, "w") as handle:
            handle.write(original)
        with open(os.path.join(temp_catalog_dir, "test-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "test-app",
                    "name": "Test App",
                    "requires": [],
                    "service": {"image": "example/test-app:latest"},
                },
                handle,
            )

        install_response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "test-app", "target_stack": "media"},
        )

        assert install_response.status_code == 200
        installed = open(compose_path).read()
        assert "# keep this stack comment" in installed
        assert 'image: "redis:7" # keep this image comment' in installed
        assert "x-shared: &shared" in installed
        assert "<<: *shared" in installed
        assert "MODE: 'prod'" in installed
        assert installed.index("existing:") < installed.index("test-app:")

        monkeypatch.setattr(
            catalog_manager,
            "run_compose_command",
            lambda *args, **kwargs: ({"success": True}, None),
        )
        remove_response = authenticated_client.post(
            "/api/catalog/remove",
            json={"id": "test-app", "target_stack": "media"},
        )

        assert remove_response.status_code == 200
        removed = open(compose_path).read()
        assert "# keep this stack comment" in removed
        assert 'image: "redis:7" # keep this image comment' in removed
        assert "x-shared: &shared" in removed
        assert "<<: *shared" in removed
        assert "MODE: 'prod'" in removed
        assert "test-app:" not in removed

    def test_install_rejects_malformed_compose_without_overwriting(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
    ):
        import catalog_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, "CATALOG_DIR", temp_catalog_dir)
        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            "BACKUP_DIR",
            os.path.join(temp_stacks_dir, ".backups"),
        )
        stack_dir = os.path.join(temp_stacks_dir, "media")
        os.makedirs(stack_dir)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        malformed = "services: [\n"
        with open(compose_path, "w") as handle:
            handle.write(malformed)
        with open(os.path.join(temp_catalog_dir, "test-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "test-app",
                    "name": "Test App",
                    "requires": [],
                    "service": {"image": "example/test-app:latest"},
                },
                handle,
            )

        response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "test-app", "target_stack": "media"},
        )

        assert response.status_code == 400
        assert response.get_json()["code"] == "invalid_compose_yaml"
        assert open(compose_path).read() == malformed


class TestCatalogTopLevelSections:
    @staticmethod
    def _configure(temp_catalog_dir, temp_stacks_dir, monkeypatch):
        import catalog_manager
        import stack_manager

        monkeypatch.setattr(catalog_manager, "CATALOG_DIR", temp_catalog_dir)
        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        backup_dir = os.path.join(temp_stacks_dir, ".backups")
        monkeypatch.setattr(stack_manager, "BACKUP_DIR", backup_dir)
        stack_dir = os.path.join(temp_stacks_dir, "media")
        os.makedirs(stack_dir)
        return stack_dir, backup_dir

    def test_install_merges_all_allowed_top_level_sections(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
    ):
        stack_dir, _ = self._configure(temp_catalog_dir, temp_stacks_dir, monkeypatch)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        with open(compose_path, "w") as handle:
            handle.write(
                "# user resources\n"
                "services: {}\n"
                "networks:\n  user-net:\n    external: true\n"
                "volumes:\n  user-data: {}\n"
                "configs:\n  user-config:\n    file: ./user.conf\n"
                "secrets:\n  user-secret:\n    external: true\n"
            )
        item = {
            "id": "resource-app",
            "name": "Resource App",
            "requires": [],
            "fields": [
                {"key": "CONFIG_DIR", "label": "Config", "default": "/etc/resource-app"}
            ],
            "service": {
                "image": "example/resource-app:latest",
                "networks": ["app-net"],
                "volumes": ["app-data:/data"],
                "configs": [{"source": "app-config", "target": "/app/config"}],
                "secrets": ["app-secret"],
            },
            "networks": {"app-net": {"driver": "bridge"}},
            "volumes": {"app-data": {}},
            "configs": {"app-config": {"file": "{{CONFIG_DIR}}/app.conf"}},
            "secrets": {"app-secret": {"file": "{{CONFIG_DIR}}/app.secret"}},
        }
        with open(os.path.join(temp_catalog_dir, "resource-app.yaml"), "w") as handle:
            yaml.safe_dump(item, handle)

        response = authenticated_client.post(
            "/api/catalog/install",
            json={
                "id": "resource-app",
                "target_stack": "media",
                "values": {"CONFIG_DIR": "/srv/resource-app"},
            },
        )

        assert response.status_code == 200
        with open(compose_path) as handle:
            content = handle.read()
        assert content.startswith("# user resources\n")
        compose = yaml.safe_load(content)
        assert set(compose["networks"]) == {"user-net", "app-net"}
        assert set(compose["volumes"]) == {"user-data", "app-data"}
        assert set(compose["configs"]) == {"user-config", "app-config"}
        assert set(compose["secrets"]) == {"user-secret", "app-secret"}
        assert compose["configs"]["app-config"]["file"] == "/srv/resource-app/app.conf"
        assert compose["secrets"]["app-secret"]["file"] == "/srv/resource-app/app.secret"

    def test_catalog_mutations_block_duplicate_compose_files(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
    ):
        stack_dir, backup_dir = self._configure(
            temp_catalog_dir, temp_stacks_dir, monkeypatch
        )
        originals = {
            "compose.yaml": "services:\n  resource-app:\n    image: old\n",
            "docker-compose.yml": "services: {}\n",
        }
        for filename, content in originals.items():
            with open(os.path.join(stack_dir, filename), "w") as handle:
                handle.write(content)
        with open(os.path.join(temp_catalog_dir, "resource-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "resource-app",
                    "requires": [],
                    "service": {"image": "example/resource-app:latest"},
                },
                handle,
            )

        install_response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "resource-app", "target_stack": "media"},
        )
        remove_response = authenticated_client.post(
            "/api/catalog/remove",
            json={"id": "resource-app", "target_stack": "media"},
        )
        untargeted_remove_response = authenticated_client.post(
            "/api/catalog/remove",
            json={"id": "resource-app"},
        )

        for response in (
            install_response,
            remove_response,
            untargeted_remove_response,
        ):
            assert response.status_code == 409
            assert response.get_json()["code"] == "compose_file_conflict"
            assert response.get_json()["files"] == [
                "compose.yaml", "docker-compose.yml"
            ]
        for filename, content in originals.items():
            assert open(os.path.join(stack_dir, filename)).read() == content
        assert not os.path.exists(backup_dir)

    @pytest.mark.parametrize("section", ["networks", "volumes", "configs", "secrets"])
    def test_install_rejects_conflicting_resource_without_writing(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
        section,
    ):
        stack_dir, backup_dir = self._configure(temp_catalog_dir, temp_stacks_dir, monkeypatch)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        original = f"# unchanged\nservices: {{}}\n{section}:\n  shared:\n    external: true\n"
        with open(compose_path, "w") as handle:
            handle.write(original)
        with open(os.path.join(temp_catalog_dir, "resource-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "resource-app",
                    "requires": [],
                    "service": {"image": "example/resource-app:latest"},
                    section: {"shared": {"external": False}},
                },
                handle,
            )

        response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "resource-app", "target_stack": "media"},
        )

        assert response.status_code == 409
        assert response.get_json()["code"] == "compose_resource_conflict"
        assert open(compose_path).read() == original
        assert not os.path.exists(backup_dir)

    def test_install_reuses_identical_existing_resource(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
    ):
        stack_dir, _ = self._configure(temp_catalog_dir, temp_stacks_dir, monkeypatch)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        with open(compose_path, "w") as handle:
            handle.write(
                "services: {}\n"
                "networks:\n"
                "  shared:\n"
                "    external: true # keep shared network\n"
            )
        with open(os.path.join(temp_catalog_dir, "resource-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "resource-app",
                    "requires": [],
                    "service": {"image": "example/resource-app:latest"},
                    "networks": {"shared": {"external": True}},
                },
                handle,
            )

        response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "resource-app", "target_stack": "media"},
        )

        assert response.status_code == 200
        with open(compose_path) as handle:
            content = handle.read()
        assert "external: true # keep shared network" in content
        assert list(yaml.safe_load(content)["networks"]) == ["shared"]

    @pytest.mark.parametrize(
        ("catalog_section", "compose_section", "expected_code"),
        [
            (["not-a-mapping"], {}, "invalid_catalog_section"),
            ({"app-config": {"file": "./app.conf"}}, [], "compose_section_conflict"),
        ],
    )
    def test_install_rejects_invalid_section_shape_without_writing(
        self,
        authenticated_client,
        temp_catalog_dir,
        temp_stacks_dir,
        monkeypatch,
        catalog_section,
        compose_section,
        expected_code,
    ):
        stack_dir, backup_dir = self._configure(temp_catalog_dir, temp_stacks_dir, monkeypatch)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        original = yaml.safe_dump({"services": {}, "configs": compose_section})
        with open(compose_path, "w") as handle:
            handle.write(original)
        with open(os.path.join(temp_catalog_dir, "resource-app.yaml"), "w") as handle:
            yaml.safe_dump(
                {
                    "id": "resource-app",
                    "requires": [],
                    "service": {"image": "example/resource-app:latest"},
                    "configs": catalog_section,
                },
                handle,
            )

        response = authenticated_client.post(
            "/api/catalog/install",
            json={"id": "resource-app", "target_stack": "media"},
        )

        assert response.status_code in (400, 409)
        assert response.get_json()["code"] == expected_code
        assert open(compose_path).read() == original
        assert not os.path.exists(backup_dir)


class TestAppsPage:
    """Test apps page accessibility."""

    def test_apps_page_loads(self, authenticated_client):
        """Test the legacy apps URL redirects to v2."""
        response = authenticated_client.get('/apps.html', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['Location'] == '/v2/apps'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
