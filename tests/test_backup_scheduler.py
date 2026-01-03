#!/usr/bin/env python3
"""
Tests for Backup Scheduler module
"""
import json
import os
import sys
import tempfile
import shutil
from unittest.mock import patch
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test-secret-key'
    with app.test_client() as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['username'] = 'testuser'
    return client


@pytest.fixture
def temp_config_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestBackupConfig:
    def test_load_config_default(self, temp_config_dir):
        import backup_scheduler
        original_config_file = backup_scheduler.CONFIG_FILE
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        try:
            config = backup_scheduler.load_config()
            assert config is not None
            assert config['enabled'] is False
            assert config['schedule_preset'] == 'disabled'
            assert config['retention_count'] >= 1
        finally:
            backup_scheduler.CONFIG_FILE = original_config_file

    def test_save_config_round_trip(self, temp_config_dir):
        import backup_scheduler
        original_config_dir = backup_scheduler.CONFIG_DIR
        original_config_file = backup_scheduler.CONFIG_FILE

        backup_scheduler.CONFIG_DIR = temp_config_dir
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        try:
            config = {
                'version': 1,
                'enabled': True,
                'schedule_preset': 'daily_2am',
                'retention_count': 3,
                'plugin_retention_count': 5,
                'plugin_backup_enabled': True,
                'dest_dir': '/mnt/backup',
                'config_dir': '/home/pi/docker',
                'stacks_path': '/opt/stacks',
                'include_env': True,
                'compression': 'zst',
                'last_run': None,
                'last_run_result': None,
                'last_plugin_backup': None,
                'last_plugin_backup_result': None
            }
            backup_scheduler.save_config(config)
            loaded = backup_scheduler.load_config()
            assert loaded['enabled'] is True
            assert loaded['schedule_preset'] == 'daily_2am'
            assert loaded['retention_count'] == 3
            assert loaded['plugin_retention_count'] == 5
        finally:
            backup_scheduler.CONFIG_DIR = original_config_dir
            backup_scheduler.CONFIG_FILE = original_config_file


class TestBackupEndpoints:
    def test_config_requires_auth(self, client):
        response = client.get('/api/backups/config')
        assert response.status_code == 401

    def test_config_with_auth(self, authenticated_client, temp_config_dir):
        import backup_scheduler
        original_config_dir = backup_scheduler.CONFIG_DIR
        original_config_file = backup_scheduler.CONFIG_FILE

        backup_scheduler.CONFIG_DIR = temp_config_dir
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        try:
            response = authenticated_client.get('/api/backups/config')
            assert response.status_code == 200
            data = response.get_json()
            assert 'dest_dir' in data
            assert 'retention_count' in data
        finally:
            backup_scheduler.CONFIG_DIR = original_config_dir
            backup_scheduler.CONFIG_FILE = original_config_file

    def test_restore_requires_auth(self, client):
        response = client.post('/api/backups/restore', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_restore_invalid_payload(self, authenticated_client, temp_config_dir):
        import backup_scheduler
        original_config_dir = backup_scheduler.CONFIG_DIR
        original_config_file = backup_scheduler.CONFIG_FILE

        backup_scheduler.CONFIG_DIR = temp_config_dir
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        try:
            response = authenticated_client.post('/api/backups/restore',
                                                 data=json.dumps({'archive_name': '../bad.tar.gz'}),
                                                 content_type='application/json')
            assert response.status_code == 400
        finally:
            backup_scheduler.CONFIG_DIR = original_config_dir
            backup_scheduler.CONFIG_FILE = original_config_file

    def test_restore_helper_unavailable(self, authenticated_client, temp_config_dir):
        import backup_scheduler
        original_config_dir = backup_scheduler.CONFIG_DIR
        original_config_file = backup_scheduler.CONFIG_FILE

        backup_scheduler.CONFIG_DIR = temp_config_dir
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        dest_dir = os.path.join(temp_config_dir, 'backups')
        os.makedirs(dest_dir, exist_ok=True)
        archive_name = 'pi-health-backup-20240101_000000.tar.zst'
        archive_path = os.path.join(dest_dir, archive_name)
        with open(archive_path, 'w') as f:
            f.write('test')

        try:
            config = backup_scheduler.load_config()
            config['dest_dir'] = dest_dir
            backup_scheduler.save_config(config)

            with patch('backup_scheduler.helper_available', return_value=False):
                response = authenticated_client.post('/api/backups/restore',
                                                     data=json.dumps({'archive_name': archive_name}),
                                                     content_type='application/json')
                assert response.status_code == 503
        finally:
            backup_scheduler.CONFIG_DIR = original_config_dir
            backup_scheduler.CONFIG_FILE = original_config_file

    def test_restore_plugins_requires_auth(self, client):
        response = client.post('/api/backups/restore-plugins', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_restore_plugins_invalid(self, authenticated_client, temp_config_dir):
        import backup_scheduler
        original_config_dir = backup_scheduler.CONFIG_DIR
        original_config_file = backup_scheduler.CONFIG_FILE

        backup_scheduler.CONFIG_DIR = temp_config_dir
        backup_scheduler.CONFIG_FILE = os.path.join(temp_config_dir, 'backup_config.json')

        try:
            response = authenticated_client.post('/api/backups/restore-plugins',
                                                 data=json.dumps({'archive_name': 'pi-health-backup-20240101.tar.zst'}),
                                                 content_type='application/json')
            assert response.status_code == 400
        finally:
            backup_scheduler.CONFIG_DIR = original_config_dir
            backup_scheduler.CONFIG_FILE = original_config_file
