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
import subprocess
import threading
import time
from unittest.mock import MagicMock, call, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stack_manager import (
    validate_stack_name,
    find_compose_file,
    list_stacks,
    get_stack_status,
    run_compose_command,
    stream_compose_command,
    STACK_FILENAMES
)



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

    def test_duplicate_compose_files_raise_conflict(self, temp_stacks_dir):
        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        for filename in ('docker-compose.yml', 'compose.yaml'):
            with open(os.path.join(stack_dir, filename), 'w') as handle:
                handle.write('services: {}\n')

        with pytest.raises(RuntimeError) as exc_info:
            find_compose_file(stack_dir)

        assert getattr(exc_info.value, 'code', None) == 'compose_file_conflict'
        assert getattr(exc_info.value, 'filenames', None) == [
            'compose.yaml', 'docker-compose.yml'
        ]


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
        """Test that the legacy stacks URL redirects to v2."""
        response = client.get('/stacks.html', follow_redirects=False)
        assert response.status_code == 302
        assert response.headers['Location'] == '/v2/stacks'


class TestStackListing:
    """Test stack listing and status parsing."""

    def test_list_stacks_filters_and_sorts(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            os.makedirs(os.path.join(temp_stacks_dir, "beta"), exist_ok=True)
            os.makedirs(os.path.join(temp_stacks_dir, "alpha"), exist_ok=True)
            os.makedirs(os.path.join(temp_stacks_dir, ".hidden"), exist_ok=True)

            with open(os.path.join(temp_stacks_dir, "alpha", "compose.yaml"), "w") as f:
                f.write("services: {}\n")
            with open(os.path.join(temp_stacks_dir, "beta", "docker-compose.yml"), "w") as f:
                f.write("services: {}\n")

            stacks, error = list_stacks()
            assert error is None
            assert [stack["name"] for stack in stacks] == ["alpha", "beta"]
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_get_stack_status_parses_json(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            stdout = json.dumps({
                "Name": "alpha_web_1",
                "Service": "web",
                "State": "running",
                "Health": "healthy",
                "Publishers": []
            })
            mock_run = MagicMock(returncode=0, stdout=stdout, stderr="")
            with patch("stack_manager.subprocess.run", return_value=mock_run):
                status, error = get_stack_status("alpha")

            assert error is None
            assert status["status"] == "running"
            assert status["container_count"] == 1
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_get_stack_status_parses_json_lines(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            stdout = "\n".join([
                json.dumps({"Name": "c1", "Service": "web", "State": "running"}),
                json.dumps({"Name": "c2", "Service": "db", "State": "exited"}),
            ])
            mock_run = MagicMock(returncode=0, stdout=stdout, stderr="")
            with patch("stack_manager.subprocess.run", return_value=mock_run):
                status, error = get_stack_status("alpha")

            assert error is None
            assert status["status"] == "partial"
            assert status["container_count"] == 2
        finally:
            stack_manager.STACKS_PATH = original_path


class TestComposeCommands:
    """Test compose command execution mapping."""

    def test_run_compose_command_unknown(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            result, error = run_compose_command("alpha", "unknown")
            assert result is None
            assert "Unknown command" in error
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_run_compose_command_blocks_duplicate_files(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            for filename in ("compose.yaml", "docker-compose.yml"):
                with open(os.path.join(stack_dir, filename), "w") as handle:
                    handle.write("services: {}\n")

            with patch("stack_manager.subprocess.run") as run_mock:
                with pytest.raises(RuntimeError, match="compose.yaml"):
                    run_compose_command("alpha", "up")

            run_mock.assert_not_called()
        finally:
            stack_manager.STACKS_PATH = original_path


class TestComposeStreaming:
    """Test SSE streaming command output."""

    def test_stream_compose_command_stack_not_found(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            events = list(stream_compose_command("missing", "up"))
            assert "Stack not found" in events[0]
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_stream_compose_command_unknown(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            events = list(stream_compose_command("alpha", "nope"))
            assert "Unknown command" in events[0]
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_stream_compose_command_success(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            fake_proc = MagicMock()
            fake_proc.stdout.readline.side_effect = ["line one\n", "line two\n", ""]
            fake_proc.wait.return_value = 0
            fake_proc.returncode = 0

            with patch("stack_manager.subprocess.Popen", return_value=fake_proc) as popen_mock:
                events = list(stream_compose_command("alpha", "up"))

            assert any("line one" in event for event in events)
            assert any('"done": true' in event for event in events)
            assert popen_mock.call_args.args[0] == [
                "docker", "compose", "-f", "compose.yaml",
                "up", "-d", "--remove-orphans",
            ]
        finally:
            stack_manager.STACKS_PATH = original_path

    @pytest.mark.parametrize(
        ("detach", "expected_tail"),
        [
            (True, ["up", "-d", "--remove-orphans"]),
            (False, ["up", "--remove-orphans"]),
        ],
    )
    def test_run_compose_command_builds_up_args(
        self, temp_stacks_dir, detach, expected_tail
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
                f.write("services: {}\n")

            mock_run = MagicMock(returncode=0, stdout="ok", stderr="")
            with patch("stack_manager.subprocess.run", return_value=mock_run) as run_mock:
                result, error = run_compose_command("alpha", "up", detach=detach)

            assert error is None
            assert result["success"] is True
            run_mock.assert_called_once()
            args, kwargs = run_mock.call_args
            assert args[0] == [
                "docker", "compose", "-f", "compose.yaml", *expected_tail
            ]
            assert kwargs["cwd"] == stack_dir
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_run_compose_command_targets_one_service(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as handle:
                handle.write("services:\n  app:\n    image: nginx\n  db:\n    image: postgres\n")

            mock_run = MagicMock(returncode=0, stdout="ok", stderr="")
            with patch("stack_manager.subprocess.run", return_value=mock_run) as run_mock:
                result, error = run_compose_command("alpha", "stop", service="app")

            assert error is None
            assert result["success"] is True
            assert run_mock.call_args.args[0] == [
                "docker", "compose", "-f", "compose.yaml", "stop", "app"
            ]
        finally:
            stack_manager.STACKS_PATH = original_path

    @pytest.mark.parametrize(
        ("command", "expected_tail"),
        [
            ("down", ["down"]),
            ("restart", ["restart"]),
            ("pull", ["pull"]),
            ("start", ["start"]),
            ("stop", ["stop"]),
        ],
    )
    def test_run_compose_command_does_not_remove_orphans_for_other_actions(
        self, temp_stacks_dir, command, expected_tail
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        try:
            stack_dir = os.path.join(temp_stacks_dir, "alpha")
            os.makedirs(stack_dir, exist_ok=True)
            with open(os.path.join(stack_dir, "compose.yaml"), "w") as handle:
                handle.write("services: {}\n")

            mock_run = MagicMock(returncode=0, stdout="ok", stderr="")
            with patch("stack_manager.subprocess.run", return_value=mock_run) as run_mock:
                result, error = run_compose_command("alpha", command)

            assert error is None
            assert result["success"] is True
            assert run_mock.call_args.args[0] == [
                "docker", "compose", "-f", "compose.yaml", *expected_tail
            ]
        finally:
            stack_manager.STACKS_PATH = original_path


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

    def test_list_stacks_reports_duplicate_compose_files(self, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        for filename in ('compose.yml', 'docker-compose.yaml'):
            with open(os.path.join(stack_dir, filename), 'w') as handle:
                handle.write('services: {}\n')

        try:
            stacks, error = list_stacks()
            assert error is None
            assert stacks == [{
                'name': 'test-stack',
                'path': stack_dir,
                'compose_file': None,
                'compose_files': ['compose.yml', 'docker-compose.yaml'],
                'status': 'conflict',
                'error': 'Multiple Compose files found: compose.yml, docker-compose.yaml',
                'code': 'compose_file_conflict',
            }]
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_endpoint_exposes_conflict_without_status_probe(
        self, authenticated_client, temp_stacks_dir
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        for filename in ('compose.yaml', 'compose.yml'):
            with open(os.path.join(stack_dir, filename), 'w') as handle:
                handle.write('services: {}\n')

        try:
            with patch('stack_manager.subprocess.run') as run_mock:
                response = authenticated_client.get('/api/stacks?status=true')

            assert response.status_code == 200
            conflict = response.get_json()['stacks'][0]
            assert conflict['status'] == 'conflict'
            assert conflict['code'] == 'compose_file_conflict'
            assert conflict['compose_files'] == ['compose.yaml', 'compose.yml']
            run_mock.assert_not_called()
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_endpoint_uses_one_docker_snapshot_for_all_stacks(
        self, authenticated_client, temp_stacks_dir
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        for stack_name, filename in (
            ('alpha', 'compose.yaml'),
            ('beta', 'docker-compose.yml'),
        ):
            stack_dir = os.path.join(temp_stacks_dir, stack_name)
            os.makedirs(stack_dir)
            with open(os.path.join(stack_dir, filename), 'w') as handle:
                handle.write('services: {}\n')

        alpha_dir = os.path.join(temp_stacks_dir, 'alpha')
        beta_dir = os.path.join(temp_stacks_dir, 'beta')
        stdout = '\n'.join([
            '\t'.join([
                'alpha-web-id', 'alpha-web-1', 'running', 'Up 2 minutes', '8080/tcp',
                alpha_dir,
                f"{os.path.join(alpha_dir, 'compose.override.yaml')},"
                f"{os.path.join(alpha_dir, 'compose.yaml')}",
                'web',
            ]),
            '\t'.join([
                'alpha-db-id', 'alpha-db-1', 'exited', 'Exited (0)', '',
                alpha_dir, os.path.join(alpha_dir, 'compose.yaml'), 'db',
            ]),
            '\t'.join([
                'beta-web-id', 'beta-web-1', 'running', 'Up 1 minute', '',
                beta_dir, '', 'web',
            ]),
        ])
        mock_run = MagicMock(returncode=0, stdout=stdout, stderr='')

        try:
            with patch('stack_manager.subprocess.run', return_value=mock_run) as run_mock:
                response = authenticated_client.get('/api/stacks?status=true')

            assert response.status_code == 200
            stacks = {stack['name']: stack for stack in response.get_json()['stacks']}
            assert stacks['alpha']['status'] == 'partial'
            assert stacks['alpha']['running_count'] == 1
            assert stacks['alpha']['container_count'] == 2
            assert stacks['beta']['status'] == 'running'
            assert stacks['beta']['running_count'] == 1
            assert stacks['beta']['container_count'] == 1
            run_mock.assert_called_once()
            command = run_mock.call_args.args[0]
            assert command[:3] == ['docker', 'ps', '-a']
            assert 'compose' not in command
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_endpoint_snapshot_failure_marks_all_stacks_unknown(
        self, authenticated_client, temp_stacks_dir
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        for stack_name in ('alpha', 'beta'):
            stack_dir = os.path.join(temp_stacks_dir, stack_name)
            os.makedirs(stack_dir)
            with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as handle:
                handle.write('services: {}\n')

        mock_run = MagicMock(returncode=1, stdout='', stderr='Docker unavailable')
        try:
            with patch('stack_manager.subprocess.run', return_value=mock_run) as run_mock:
                response = authenticated_client.get('/api/stacks?status=true')

            assert response.status_code == 200
            stacks = response.get_json()['stacks']
            assert [stack['status'] for stack in stacks] == ['unknown', 'unknown']
            assert all(stack['status_error'] == 'Docker unavailable' for stack in stacks)
            run_mock.assert_called_once()
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

    def test_compose_endpoints_block_duplicate_files_without_writing(
        self, authenticated_client, temp_stacks_dir
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')

        stack_dir = os.path.join(temp_stacks_dir, 'test-stack')
        os.makedirs(stack_dir)
        originals = {}
        for filename in ('compose.yaml', 'docker-compose.yml'):
            content = f'# {filename}\nservices: {{}}\n'
            originals[filename] = content
            with open(os.path.join(stack_dir, filename), 'w') as handle:
                handle.write(content)

        try:
            get_response = authenticated_client.get('/api/stacks/test-stack/compose')
            save_response = authenticated_client.post(
                '/api/stacks/test-stack/compose',
                data=json.dumps({'content': 'services:\n  changed: {}\n'}),
                content_type='application/json',
            )

            for response in (get_response, save_response):
                assert response.status_code == 409
                assert response.get_json() == {
                    'code': 'compose_file_conflict',
                    'error': (
                        'Multiple Compose files found: '
                        'compose.yaml, docker-compose.yml'
                    ),
                    'files': ['compose.yaml', 'docker-compose.yml'],
                }
            for filename, content in originals.items():
                with open(os.path.join(stack_dir, filename)) as handle:
                    assert handle.read() == content
            assert not os.path.exists(stack_manager.BACKUP_DIR)
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

    @patch('stack_manager.run_compose_command')
    def test_delete_stack_success(self, mock_run, authenticated_client, temp_stacks_dir):
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
        mock_run.return_value = ({'success': True, 'returncode': 0, 'stdout': '', 'stderr': ''}, None)

        try:
            response = authenticated_client.delete('/api/stacks/to-delete')

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'deleted'

            # Verify directory was removed
            assert not os.path.exists(stack_dir)
            mock_run.assert_called_once_with('to-delete', 'down')
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

    @patch('stack_manager.run_compose_command')
    def test_delete_stack_preserves_directory_when_down_fails(
        self, mock_run, authenticated_client, temp_stacks_dir,
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')
        stack_dir = os.path.join(temp_stacks_dir, 'to-delete')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as handle:
            handle.write('services: {}\n')
        mock_run.return_value = ({
            'success': False,
            'returncode': 1,
            'stdout': '',
            'stderr': 'network is still in use',
        }, None)

        try:
            response = authenticated_client.delete('/api/stacks/to-delete')
            assert response.status_code == 409
            payload = response.get_json()
            assert payload['force_delete_available'] is True
            assert 'network is still in use' in payload['error']
            assert os.path.isdir(stack_dir)
            assert not os.path.exists(stack_manager.BACKUP_DIR)
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

    @patch('stack_manager.run_compose_command')
    def test_force_delete_requires_stack_name_confirmation(
        self, mock_run, authenticated_client, temp_stacks_dir,
    ):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, '.backups')
        stack_dir = os.path.join(temp_stacks_dir, 'to-delete')
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, 'compose.yaml'), 'w') as handle:
            handle.write('services: {}\n')
        mock_run.return_value = ({'success': False, 'returncode': 1, 'stderr': 'down failed'}, None)

        try:
            rejected = authenticated_client.delete(
                '/api/stacks/to-delete',
                json={'force': True, 'confirm_name': 'wrong-name'},
            )
            assert rejected.status_code == 400
            assert os.path.isdir(stack_dir)

            forced = authenticated_client.delete(
                '/api/stacks/to-delete',
                json={'force': True, 'confirm_name': 'to-delete'},
            )
            assert forced.status_code == 200
            assert forced.get_json()['forced'] is True
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


class TestStackAdditionalRoutes:
    """Test additional stack API routes with focused coverage."""

    def test_scan_stacks(self, authenticated_client, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
            f.write("services: {}\n")

        try:
            response = authenticated_client.post("/api/stacks/scan")
            assert response.status_code == 200
            data = response.get_json()
            assert data["count"] == 1
            assert data["stacks"][0]["name"] == "alpha"
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_list_route_delegates_status_query_to_service(self, authenticated_client):
        service = MagicMock()
        service.list_with_status.return_value = ([{"name": "alpha"}], None)
        authenticated_client.application.extensions["stack_read_service"] = service

        response = authenticated_client.get("/api/stacks?status=true")

        assert response.status_code == 200
        assert response.get_json() == {"stacks": [{"name": "alpha"}]}
        service.list_with_status.assert_called_once_with(include_status=True)

    def test_status_route_delegates_to_service(self, authenticated_client):
        service = MagicMock()
        service.status.return_value = ({"status": "running"}, None)
        authenticated_client.application.extensions["stack_read_service"] = service

        response = authenticated_client.get("/api/stacks/alpha/status")

        assert response.status_code == 200
        assert response.get_json() == {"status": "running"}
        service.status.assert_called_once_with("alpha")

    def test_compose_route_delegates_to_service(self, authenticated_client):
        service = MagicMock()
        service.compose.return_value = {"content": "services: {}", "filename": "compose.yaml"}
        authenticated_client.application.extensions["stack_read_service"] = service

        response = authenticated_client.get("/api/stacks/alpha/compose")

        assert response.status_code == 200
        assert response.get_json()["filename"] == "compose.yaml"
        service.compose.assert_called_once_with("alpha")

    def test_backup_routes_delegate_to_service(self, authenticated_client):
        backup_name = "compose-20240101010101.yaml"
        service = MagicMock()
        service.list_backups.return_value = [backup_name]
        service.backup.return_value = {"content": "services: {}", "filename": backup_name}
        authenticated_client.application.extensions["stack_read_service"] = service

        list_response = authenticated_client.get("/api/stacks/alpha/backups")
        get_response = authenticated_client.get(f"/api/stacks/alpha/backups/{backup_name}")

        assert list_response.get_json() == {"backups": [backup_name]}
        assert get_response.get_json()["filename"] == backup_name
        service.list_backups.assert_called_once_with("alpha")
        service.backup.assert_called_once_with("alpha", backup_name)

    def test_compose_save_delegates_to_mutation_service(self, authenticated_client):
        service = MagicMock()
        service.save_compose.return_value = {"status": "saved"}
        authenticated_client.application.extensions["stack_mutation_service"] = service

        response = authenticated_client.post(
            "/api/stacks/alpha/compose",
            json={"content": "services: {}\n"},
        )

        assert response.status_code == 200
        service.save_compose.assert_called_once_with("alpha", "services: {}\n")

    def test_env_save_delegates_to_mutation_service(self, authenticated_client):
        service = MagicMock()
        service.save_env.return_value = {"status": "saved"}
        authenticated_client.application.extensions["stack_mutation_service"] = service

        response = authenticated_client.post(
            "/api/stacks/alpha/env",
            json={"content": "KEY=value\n"},
        )

        assert response.status_code == 200
        service.save_env.assert_called_once_with("alpha", "KEY=value\n")

    def test_restore_delegates_to_mutation_service(self, authenticated_client):
        backup_name = "compose-20240101010101.yaml"
        service = MagicMock()
        service.restore.return_value = {"status": "restored", "backup": backup_name}
        authenticated_client.application.extensions["stack_mutation_service"] = service

        response = authenticated_client.post(
            "/api/stacks/alpha/restore",
            json={"backup": backup_name},
        )

        assert response.status_code == 200
        service.restore.assert_called_once_with("alpha", backup_name)

    def test_get_compose(self, authenticated_client, temp_stacks_dir):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        stack_manager.STACKS_PATH = temp_stacks_dir

        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir, exist_ok=True)
        compose_content = "services:\n  web:\n    image: nginx\n"
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
            f.write(compose_content)

        try:
            response = authenticated_client.get("/api/stacks/alpha/compose")
            assert response.status_code == 200
            data = response.get_json()
            assert data["filename"] == "compose.yaml"
            assert data["content"] == compose_content
        finally:
            stack_manager.STACKS_PATH = original_path

    def test_stack_status_endpoint(self, authenticated_client):
        service = MagicMock()
        service.status.return_value = (
            {"status": "running", "container_count": 2, "running_count": 2},
            None,
        )
        authenticated_client.application.extensions["stack_read_service"] = service

        response = authenticated_client.get("/api/stacks/alpha/status")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "running"
        assert data["container_count"] == 2

    def test_stack_restart_and_pull(self, authenticated_client):
        service = MagicMock()
        service.run.return_value = ({"success": True, "returncode": 0}, None)
        authenticated_client.application.extensions["stack_operations_service"] = service

        restart_response = authenticated_client.post("/api/stacks/alpha/restart")
        assert restart_response.status_code == 200
        assert restart_response.get_json()["success"] is True

        pull_response = authenticated_client.post("/api/stacks/alpha/pull")
        assert pull_response.status_code == 200
        assert pull_response.get_json()["success"] is True
        assert service.run.call_args_list == [
            call("alpha", "restart"),
            call("alpha", "pull"),
        ]

    def test_stack_logs(self, authenticated_client):
        service = MagicMock()
        service.logs.return_value = {"logs": "log line\n", "returncode": 0}
        authenticated_client.application.extensions["stack_operations_service"] = service

        response = authenticated_client.get("/api/stacks/alpha/logs?tail=20&service=web")
        assert response.status_code == 200
        assert response.get_json() == {"logs": "log line\n", "returncode": 0}
        service.logs.assert_called_once_with("alpha", tail="20", service="web")

    def test_stack_backups_and_restore(self, authenticated_client, temp_stacks_dir, monkeypatch):
        import stack_manager
        original_path = stack_manager.STACKS_PATH
        original_backup = stack_manager.BACKUP_DIR
        stack_manager.STACKS_PATH = temp_stacks_dir
        stack_manager.BACKUP_DIR = os.path.join(temp_stacks_dir, ".backups")

        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir, exist_ok=True)
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as f:
            f.write("services:\n  web:\n    image: nginx\n")

        backup_dir = os.path.join(stack_manager.BACKUP_DIR, "alpha")
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = "compose-20240101010101.yaml"
        with open(os.path.join(backup_dir, backup_name), "w") as f:
            f.write("services:\n  web:\n    image: redis\n")

        monkeypatch.setattr("stack_manager.backup_stack", lambda _name: "/tmp/backup")

        try:
            list_response = authenticated_client.get("/api/stacks/alpha/backups")
            assert list_response.status_code == 200
            assert backup_name in list_response.get_json()["backups"]

            get_response = authenticated_client.get(f"/api/stacks/alpha/backups/{backup_name}")
            assert get_response.status_code == 200
            assert "redis" in get_response.get_json()["content"]

            restore_response = authenticated_client.post(
                "/api/stacks/alpha/restore",
                data=json.dumps({"backup": backup_name}),
                content_type="application/json",
            )
            assert restore_response.status_code == 200
            assert restore_response.get_json()["status"] == "restored"
        finally:
            stack_manager.STACKS_PATH = original_path
            stack_manager.BACKUP_DIR = original_backup

class TestStackConcurrencyAndAtomicWrites:
    def _configure_stack_paths(self, monkeypatch, temp_stacks_dir):
        import stack_manager

        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        monkeypatch.setattr(
            stack_manager,
            "BACKUP_DIR",
            os.path.join(temp_stacks_dir, ".backups"),
        )

    def _create_stack(self, temp_stacks_dir, content="services: {}\n"):
        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir)
        compose_path = os.path.join(stack_dir, "compose.yaml")
        with open(compose_path, "w") as handle:
            handle.write(content)
        return stack_dir, compose_path

    def test_compose_replace_failure_preserves_original(
        self, authenticated_client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        _, compose_path = self._create_stack(temp_stacks_dir)
        real_replace = os.replace

        def fail_target_replace(source, destination):
            if destination == compose_path:
                raise OSError("replace failed")
            return real_replace(source, destination)

        monkeypatch.setattr(stack_manager.os, "replace", fail_target_replace)

        response = authenticated_client.post(
            "/api/stacks/alpha/compose",
            json={"content": "services:\n  changed:\n    image: redis\n"},
        )

        assert response.status_code == 500
        assert open(compose_path).read() == "services: {}\n"

    def test_env_replace_failure_preserves_original(
        self, authenticated_client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        stack_dir, _ = self._create_stack(temp_stacks_dir)
        env_path = os.path.join(stack_dir, ".env")
        with open(env_path, "w") as handle:
            handle.write("OLD=value\n")
        real_replace = os.replace

        def fail_target_replace(source, destination):
            if destination == env_path:
                raise OSError("replace failed")
            return real_replace(source, destination)

        monkeypatch.setattr(stack_manager.os, "replace", fail_target_replace)

        response = authenticated_client.post(
            "/api/stacks/alpha/env",
            json={"content": "NEW=value\n"},
        )

        assert response.status_code == 500
        assert open(env_path).read() == "OLD=value\n"

    def test_restore_replace_failure_preserves_original(
        self, authenticated_client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        _, compose_path = self._create_stack(
            temp_stacks_dir,
            "services:\n  current:\n    image: nginx\n",
        )
        backup_dir = os.path.join(stack_manager.BACKUP_DIR, "alpha")
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = "compose-20240101010101.yaml"
        with open(os.path.join(backup_dir, backup_name), "w") as handle:
            handle.write("services:\n  restored:\n    image: redis\n")
        real_replace = os.replace

        def fail_target_replace(source, destination):
            if destination == compose_path:
                raise OSError("replace failed")
            return real_replace(source, destination)

        monkeypatch.setattr(stack_manager.os, "replace", fail_target_replace)

        response = authenticated_client.post(
            "/api/stacks/alpha/restore",
            json={"backup": backup_name},
        )

        assert response.status_code == 500
        assert "current" in open(compose_path).read()

    def test_compose_action_serializes_with_save(
        self, app, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        _, compose_path = self._create_stack(temp_stacks_dir)
        action_started = threading.Event()
        release_action = threading.Event()
        save_finished = threading.Event()
        responses = []

        def blocked_run(*args, **kwargs):
            action_started.set()
            assert release_action.wait(timeout=3)
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(stack_manager.subprocess, "run", blocked_run)

        action_thread = threading.Thread(
            target=stack_manager.run_compose_command,
            args=("alpha", "up"),
        )

        def save_compose():
            with app.test_client() as thread_client:
                with thread_client.session_transaction() as session:
                    session["authenticated"] = True
                    session["username"] = "testuser"
                responses.append(
                    thread_client.post(
                        "/api/stacks/alpha/compose",
                        json={"content": "services:\n  changed:\n    image: redis\n"},
                    )
                )
            save_finished.set()

        action_thread.start()
        assert action_started.wait(timeout=2)
        save_thread = threading.Thread(target=save_compose)
        save_thread.start()
        time.sleep(0.1)

        assert not save_finished.is_set()
        assert open(compose_path).read() == "services: {}\n"

        release_action.set()
        action_thread.join(timeout=3)
        save_thread.join(timeout=3)
        assert responses[0].status_code == 200
        assert "changed" in open(compose_path).read()

    def test_stack_lock_serializes_separate_process(
        self, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        stack_lock = getattr(stack_manager, "stack_lock")
        script = (
            "import stack_manager\n"
            "print('ready', flush=True)\n"
            "with stack_manager.stack_lock('alpha'):\n"
            "    print('acquired', flush=True)\n"
        )
        env = os.environ.copy()
        env["STACKS_PATH"] = temp_stacks_dir

        with stack_lock("alpha"):
            process = subprocess.Popen(
                [sys.executable, "-c", script],
                cwd=os.path.dirname(os.path.dirname(__file__)),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout.readline().strip() == "ready"
            time.sleep(0.1)
            assert process.poll() is None

        stdout, stderr = process.communicate(timeout=3)
        assert process.returncode == 0, stderr
        assert stdout.strip() == "acquired"

    def test_different_stack_locks_do_not_block_each_other(
        self, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        self._configure_stack_paths(monkeypatch, temp_stacks_dir)
        acquired = threading.Event()

        def lock_beta():
            with stack_manager.stack_lock("beta"):
                acquired.set()

        with stack_manager.stack_lock("alpha"):
            thread = threading.Thread(target=lock_beta)
            thread.start()
            assert acquired.wait(timeout=1)
            thread.join(timeout=1)


class TestStackOperationApi:
    def _authenticate_with_csrf(self, client, username="testuser"):
        with client.session_transaction() as session:
            session["authenticated"] = True
            session["username"] = username
            session["csrf_token"] = "test-csrf-token"

    def test_operation_create_requires_csrf(self, authenticated_client):
        authenticated_client.environ_base.pop("HTTP_X_CSRF_TOKEN", None)
        missing = authenticated_client.post(
            "/api/stacks/alpha/operations",
            json={"action": "up"},
        )
        with authenticated_client.session_transaction() as session:
            session["csrf_token"] = "expected-token"
        invalid = authenticated_client.post(
            "/api/stacks/alpha/operations",
            json={"action": "up"},
            headers={"X-CSRF-Token": "wrong-token"},
        )

        assert missing.status_code == 403
        assert invalid.status_code == 403

    def test_operation_create_rejects_unknown_action(
        self, client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        self._authenticate_with_csrf(client)
        response = client.post(
            "/api/stacks/alpha/operations",
            json={"action": "destroy"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )

        assert response.status_code == 400

    def test_operation_stream_replays_without_relaunch(
        self, client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as handle:
            handle.write("services: {}\n")
        self._authenticate_with_csrf(client)
        runner = MagicMock(
            return_value=iter([
                'data: {"line":"starting"}\n\n',
                'data: {"done":true,"returncode":0}\n\n',
            ])
        )
        monkeypatch.setattr(stack_manager, "stream_compose_command", runner)

        created = client.post(
            "/api/stacks/alpha/operations",
            json={"action": "up"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )

        assert created.status_code == 202
        payload = created.get_json()
        assert payload["operation_id"]
        assert payload["stream_url"].endswith("/stream")

        first = client.get(payload["stream_url"])
        second = client.get(payload["stream_url"])
        resumed = client.get(
            payload["stream_url"],
            headers={"Last-Event-ID": "0"},
        )

        assert first.status_code == 200
        assert first.mimetype == "text/event-stream"
        assert '"starting"' in first.get_data(as_text=True)
        assert first.get_data() == second.get_data()
        assert '"starting"' not in resumed.get_data(as_text=True)
        assert '"done"' in resumed.get_data(as_text=True)
        runner.assert_called_once_with("alpha", "up")

    def test_operation_stream_is_owned_by_creating_user(
        self, client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as handle:
            handle.write("services: {}\n")
        self._authenticate_with_csrf(client, username="alice")
        monkeypatch.setattr(
            stack_manager,
            "stream_compose_command",
            lambda _name, _action: iter(['data: {"done":true,"returncode":0}\n\n']),
        )
        created = client.post(
            "/api/stacks/alpha/operations",
            json={"action": "up"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )
        stream_url = created.get_json()["stream_url"]

        with client.session_transaction() as session:
            session["authenticated"] = True
            session["username"] = "bob"
            session["csrf_token"] = "different-browser-token"
        response = client.get(stream_url)

        assert response.status_code == 404

    def test_thread_start_failure_removes_operation(
        self, client, temp_stacks_dir, monkeypatch
    ):
        import stack_manager

        monkeypatch.setattr(stack_manager, "STACKS_PATH", temp_stacks_dir)
        stack_dir = os.path.join(temp_stacks_dir, "alpha")
        os.makedirs(stack_dir)
        with open(os.path.join(stack_dir, "compose.yaml"), "w") as handle:
            handle.write("services: {}\n")
        self._authenticate_with_csrf(client)
        import operation_manager

        monkeypatch.setattr(
            operation_manager.threading.Thread,
            "start",
            MagicMock(side_effect=RuntimeError("thread unavailable")),
        )

        response = client.post(
            "/api/stacks/alpha/operations",
            json={"action": "up"},
            headers={"X-CSRF-Token": "test-csrf-token"},
        )

        assert response.status_code == 500
        assert "thread unavailable" in response.get_json()["error"]

    @pytest.mark.parametrize("action", ["up", "down", "pull", "restart"])
    def test_legacy_get_stream_trigger_is_retired(
        self, authenticated_client, action
    ):
        response = authenticated_client.get(f"/api/stacks/alpha/{action}/stream")

        assert response.status_code == 404

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
