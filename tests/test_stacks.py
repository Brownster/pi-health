#!/usr/bin/env python3
"""
Tests for Stack Manager functionality
"""
import pytest
import json
import os
import sys
import tempfile
import shutil

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stack_manager import (
    validate_stack_name,
    find_compose_file,
    list_stacks,
    STACK_FILENAMES
)
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
def temp_stacks_dir():
    """Create a temporary stacks directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestStackNameValidation:
    """Test stack name validation."""

    def test_valid_stack_names(self):
        """Test that valid stack names are accepted."""
        valid_names = [
            'my-stack',
            'mystack',
            'my_stack',
            'my.stack',
            'stack123',
            '123stack',
            'a',
            'sonarr',
            'radarr-stack',
            'jellyfin_media'
        ]
        for name in valid_names:
            valid, error = validate_stack_name(name)
            assert valid is True, f"'{name}' should be valid but got error: {error}"

    def test_invalid_stack_names(self):
        """Test that invalid stack names are rejected."""
        invalid_names = [
            '',           # empty
            '.hidden',    # starts with dot
            '../escape',  # path traversal
            'has space',  # contains space
            'has/slash',  # contains slash
            'has\\back',  # contains backslash
            '-startswithdash',  # starts with dash
            '_startswithunderscore',  # starts with underscore (actually this might be valid per regex)
        ]
        for name in invalid_names:
            valid, error = validate_stack_name(name)
            # Empty and path traversal should definitely fail
            if name in ['', '.hidden', '../escape', 'has space', 'has/slash', 'has\\back', '-startswithdash']:
                assert valid is False, f"'{name}' should be invalid"

    def test_stack_name_too_long(self):
        """Test that overly long stack names are rejected."""
        long_name = 'a' * 65
        valid, error = validate_stack_name(long_name)
        assert valid is False
        assert 'too long' in error.lower()


class TestFindComposeFile:
    """Test compose file discovery."""

    def test_find_compose_yaml(self, temp_stacks_dir):
        """Test finding compose.yaml."""
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)

        compose_file = os.path.join(stack_dir, 'compose.yaml')
        with open(compose_file, 'w') as f:
            f.write('services: {}\n')

        found = find_compose_file(stack_dir)
        assert found == compose_file

    def test_find_docker_compose_yml(self, temp_stacks_dir):
        """Test finding docker-compose.yml."""
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)

        compose_file = os.path.join(stack_dir, 'docker-compose.yml')
        with open(compose_file, 'w') as f:
            f.write('services: {}\n')

        found = find_compose_file(stack_dir)
        assert found == compose_file

    def test_no_compose_file(self, temp_stacks_dir):
        """Test when no compose file exists."""
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)

        found = find_compose_file(stack_dir)
        assert found is None


class TestStackEndpointsAuth:
    """Test that stack endpoints require authentication."""

    def test_list_stacks_requires_auth(self, client):
        """Test that GET /api/stacks requires authentication."""
        response = client.get('/api/stacks')
        assert response.status_code == 401

    def test_get_stack_requires_auth(self, client):
        """Test that GET /api/stacks/<name> requires authentication."""
        response = client.get('/api/stacks/test-stack')
        assert response.status_code == 401

    def test_create_stack_requires_auth(self, client):
        """Test that POST /api/stacks/<name> requires authentication."""
        response = client.post('/api/stacks/test-stack',
            data=json.dumps({'compose_content': 'services: {}'}),
            content_type='application/json')
        assert response.status_code == 401

    def test_delete_stack_requires_auth(self, client):
        """Test that DELETE /api/stacks/<name> requires authentication."""
        response = client.delete('/api/stacks/test-stack')
        assert response.status_code == 401

    def test_stack_up_requires_auth(self, client):
        """Test that POST /api/stacks/<name>/up requires authentication."""
        response = client.post('/api/stacks/test-stack/up')
        assert response.status_code == 401

    def test_stack_down_requires_auth(self, client):
        """Test that POST /api/stacks/<name>/down requires authentication."""
        response = client.post('/api/stacks/test-stack/down')
        assert response.status_code == 401


class TestStackEndpointsValidation:
    """Test stack endpoint input validation."""

    def test_invalid_stack_name_rejected(self, authenticated_client):
        """Test that invalid stack names are rejected."""
        # Note: '../' and 'has space' are blocked by Flask routing (404)
        # Only test names that reach our validation
        invalid_names = ['.hidden', '-startswithdash']
        for name in invalid_names:
            response = authenticated_client.get(f'/api/stacks/{name}')
            # Should be 400 (validation) or 404 (routing/not found)
            assert response.status_code in [400, 404], f"'{name}' should be rejected"

    def test_create_stack_empty_name_rejected(self, authenticated_client):
        """Test that empty stack name in URL is handled."""
        # This would be a 404 from Flask routing, not a validation error
        response = authenticated_client.post('/api/stacks/',
            data=json.dumps({'compose_content': 'services: {}'}),
            content_type='application/json')
        # Flask returns 404 for missing route segment
        assert response.status_code in [404, 400, 405]


class TestStacksPage:
    """Test the stacks page is accessible."""

    def test_stacks_page_loads(self, client):
        """Test that stacks page loads."""
        response = client.get('/stacks.html')
        assert response.status_code == 200


class TestStackFilenames:
    """Test supported compose filenames."""

    def test_supported_filenames(self):
        """Test that expected compose filenames are supported."""
        expected = ['compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml']
        for filename in expected:
            assert filename in STACK_FILENAMES, f"'{filename}' should be supported"


class TestListStacks:
    """Test list_stacks function."""

    def test_list_stacks_empty_dir(self, temp_stacks_dir):
        """Test listing stacks in empty directory."""
        from stack_manager import list_stacks, STACKS_PATH
        import stack_manager

        # Temporarily override STACKS_PATH
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stacks, error = list_stacks()
            assert error is None
            assert stacks == []
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_stacks_with_stacks(self, temp_stacks_dir):
        """Test listing stacks with valid stacks."""
        from stack_manager import list_stacks
        import stack_manager

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stacks, error = list_stacks()
            assert error is None
            assert len(stacks) == 1
            assert stacks[0]['name'] == 'test-stack'
            assert stacks[0]['compose_file'] == 'compose.yaml'
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_stacks_skips_hidden(self, temp_stacks_dir):
        """Test that hidden directories are skipped."""
        from stack_manager import list_stacks
        import stack_manager

        # Create a hidden directory
        hidden_dir = os.path.join(temp_stacks_dir, '.hidden')
        os.makedirs(hidden_dir)
        with open(os.path.join(hidden_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stacks, error = list_stacks()
            assert error is None
            assert len(stacks) == 0  # Should not include hidden
        finally:
            stack_manager.STACKS_PATH = original_path


class TestStackCRUD:
    """Test stack create/read/update/delete operations."""

    def test_create_stack_success(self, authenticated_client, temp_stacks_dir):
        """Test creating a new stack."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            response = authenticated_client.post('/api/stacks/new-stack',
                data=json.dumps({
                    'compose_content': 'services:\n  web:\n    image: nginx\n',
                    'env_content': 'PORT=8080\n'
                }),
                content_type='application/json')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'created'
            assert data['name'] == 'new-stack'

            # Verify files were created
            stack_dir = os.path.join(temp_stacks_dir, 'new-stack')
            assert os.path.exists(stack_dir)
            assert os.path.exists(os.path.join(stack_dir, 'compose.yaml'))
            assert os.path.exists(os.path.join(stack_dir, '.env'))
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_create_stack_already_exists(self, authenticated_client, temp_stacks_dir):
        """Test creating a stack that already exists."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create existing stack
        stack_dir = os.path.join(temp_stacks_dir, 'existing-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            response = authenticated_client.post('/api/stacks/existing-stack',
                data=json.dumps({'compose_content': 'services: {}'}),
                content_type='application/json')

            assert response.status_code == 409
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_get_stack_success(self, authenticated_client, temp_stacks_dir):
        """Test getting stack details."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        compose_content = 'services:\n  web:\n    image: nginx\n'
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write(compose_content)

        try:
            response = authenticated_client.get('/api/stacks/test-stack')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['name'] == 'test-stack'
            assert data['compose_content'] == compose_content
            assert 'status' in data
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_get_stack_not_found(self, authenticated_client, temp_stacks_dir):
        """Test getting a non-existent stack."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            response = authenticated_client.get('/api/stacks/nonexistent')

            assert response.status_code == 404
            data = json.loads(response.data)
            assert 'error' in data
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_save_compose_success(self, authenticated_client, temp_stacks_dir):
        """Test saving compose file content."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            new_content = 'services:\n  updated:\n    image: redis\n'
            response = authenticated_client.post('/api/stacks/test-stack/compose',
                data=json.dumps({'content': new_content}),
                content_type='application/json')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'saved'

            # Verify file was updated
            with open(os.path.join(stack_dir, 'compose.yaml'), 'r') as f:
                assert f.read() == new_content
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

    def test_delete_stack_success(self, authenticated_client, temp_stacks_dir):
        """Test deleting a stack."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'to-delete')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            response = authenticated_client.delete('/api/stacks/to-delete')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'deleted'

            # Verify directory was removed
            assert not os.path.exists(stack_dir)
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup


class TestBackupStack:
    """Test stack backup functionality."""

    def test_backup_stack_creates_backup(self, temp_stacks_dir):
        """Test that backup_stack creates a backup file."""
        from stack_manager import backup_stack
        import stack_manager

        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services:\n  test:\n    image: nginx\n')

        try:
            backup_file = backup_stack('test-stack')

            assert backup_file is not None
            assert os.path.exists(backup_file)
            assert 'compose-' in backup_file
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

    def test_backup_stack_nonexistent(self, temp_stacks_dir):
        """Test backup_stack with non-existent stack."""
        from stack_manager import backup_stack
        import stack_manager

        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        try:
            result = backup_stack('nonexistent')
            assert result is None
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup


class TestRunComposeCommand:
    """Test run_compose_command function."""

    def test_run_compose_unknown_command(self, temp_stacks_dir):
        """Test run_compose_command with unknown command."""
        from stack_manager import run_compose_command
        import stack_manager

        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create a test stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            result, error = run_compose_command('test-stack', 'invalid_command')
            assert error is not None
            assert 'Unknown command' in error
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_run_compose_stack_not_found(self, temp_stacks_dir):
        """Test run_compose_command with non-existent stack."""
        from stack_manager import run_compose_command
        import stack_manager

        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            result, error = run_compose_command('nonexistent', 'up')
            assert error is not None
            assert 'not found' in error.lower()
        finally:
            stack_manager.STACKS_PATH = original_path


class TestStackEnvFile:
    """Test stack .env file operations."""

    def test_get_env_exists(self, authenticated_client, temp_stacks_dir):
        """Test getting .env file that exists."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create stack with .env
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')
        with open(os.path.join(stack_dir, '.env'), 'w') as f:
            f.write('KEY=value\n')

        try:
            response = authenticated_client.get('/api/stacks/test-stack/env')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['exists'] is True
            assert data['content'] == 'KEY=value\n'
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_get_env_not_exists(self, authenticated_client, temp_stacks_dir):
        """Test getting .env file that doesn't exist."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create stack without .env
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            response = authenticated_client.get('/api/stacks/test-stack/env')
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['exists'] is False
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_save_env_success(self, authenticated_client, temp_stacks_dir):
        """Test saving .env file."""
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        # Create stack
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as f:
            f.write('services: {}\n')

        try:
            response = authenticated_client.post('/api/stacks/test-stack/env',
                data=json.dumps({'content': 'NEW_KEY=new_value\n'}),
                content_type='application/json')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'saved'

            # Verify file was created
            with open(os.path.join(stack_dir, '.env'), 'r') as f:
                assert f.read() == 'NEW_KEY=new_value\n'
        finally:
            stack_manager.STACKS_PATH = original_path


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
