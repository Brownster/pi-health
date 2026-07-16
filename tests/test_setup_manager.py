#!/usr/bin/env python3
"""
Tests for setup manager endpoints.
"""
import json
import os
import sys
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))




class TestSetupEndpoints:
    def test_defaults_requires_auth(self, client):
        response = client.get('/api/setup/defaults')
        assert response.status_code == 401

    def test_tailscale_requires_auth(self, client):
        response = client.post('/api/setup/tailscale', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_vpn_requires_auth(self, client):
        response = client.post('/api/setup/vpn', data=json.dumps({}),
                               content_type='application/json')
        assert response.status_code == 401

    def test_defaults_with_auth(self, authenticated_client):
        with patch('setup_manager.load_media_paths', return_value={'config': '/tmp/config'}):
            response = authenticated_client.get('/api/setup/defaults')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['config_dir'] == '/tmp/config'
        assert data['network_name'] == 'vpn_network'

    def test_tailscale_helper_unavailable(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=False):
            response = authenticated_client.post('/api/setup/tailscale',
                                                 data=json.dumps({}),
                                                 content_type='application/json')
            assert response.status_code == 503

    def test_tailscale_success(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            with patch('setup_manager.helper_call') as helper_call:
                helper_call.side_effect = [
                    {'success': True},
                    {'success': True}
                ]
                response = authenticated_client.post(
                    '/api/setup/tailscale',
                    data=json.dumps({'auth_key': 'tskey-123'}),
                    content_type='application/json'
                )
        assert response.status_code == 200
        assert helper_call.call_count == 2

    def test_vpn_invalid_payload(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            response = authenticated_client.post('/api/setup/vpn',
                                                 data=json.dumps({'config_dir': 'relative'}),
                                                 content_type='application/json')
            assert response.status_code == 400

    def test_vpn_missing_credentials(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            response = authenticated_client.post(
                '/api/setup/vpn',
                data=json.dumps({'config_dir': '/home/pi/docker', 'network_name': 'vpn_network'}),
                content_type='application/json'
            )
            assert response.status_code == 400

    def test_vpn_success(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            with patch('setup_manager.helper_call') as helper_call:
                helper_call.side_effect = [
                    {'success': True},
                    {'success': True}
                ]
                response = authenticated_client.post(
                    '/api/setup/vpn',
                    data=json.dumps({
                        'config_dir': '/home/pi/docker',
                        'network_name': 'vpn_network',
                        'pia_username': 'user',
                        'pia_password': 'pass'
                    }),
                    content_type='application/json'
                )
        assert response.status_code == 200

    def test_vpn_env_includes_firewall_outbound_subnets(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            with patch('setup_manager.helper_call') as helper_call:
                helper_call.side_effect = [{'success': True}, {'success': True}]
                authenticated_client.post(
                    '/api/setup/vpn',
                    data=json.dumps({
                        'config_dir': '/home/pi/docker',
                        'network_name': 'vpn_network',
                        'pia_username': 'user',
                        'pia_password': 'pass',
                        'outbound_subnets': '10.1.2.0/24',
                    }),
                    content_type='application/json'
                )
        write_call = next(c for c in helper_call.call_args_list if c.args[0] == 'write_vpn_env')
        assert 'FIREWALL_OUTBOUND_SUBNETS=10.1.2.0/24' in write_call.args[1]['content']

    def test_vpn_env_derives_lan_subnet_when_not_supplied(self, authenticated_client):
        with patch('setup_manager.helper_available', return_value=True):
            with patch('setup_manager._default_lan_subnet', return_value='192.168.5.0/24'):
                with patch('setup_manager.helper_call') as helper_call:
                    helper_call.side_effect = [{'success': True}, {'success': True}]
                    authenticated_client.post(
                        '/api/setup/vpn',
                        data=json.dumps({
                            'config_dir': '/home/pi/docker',
                            'network_name': 'vpn_network',
                            'pia_username': 'user',
                            'pia_password': 'pass',
                        }),
                        content_type='application/json'
                    )
        write_call = next(c for c in helper_call.call_args_list if c.args[0] == 'write_vpn_env')
        assert 'FIREWALL_OUTBOUND_SUBNETS=192.168.5.0/24' in write_call.args[1]['content']


class TestLanSubnetDerivation:
    def test_derives_24_from_host_ip(self):
        from setup_manager import _lan_subnet_from_ip
        assert _lan_subnet_from_ip('192.168.0.45') == '192.168.0.0/24'

    def test_rejects_loopback_and_malformed(self):
        from setup_manager import _lan_subnet_from_ip
        assert _lan_subnet_from_ip('127.0.0.1') is None
        assert _lan_subnet_from_ip('') is None
        assert _lan_subnet_from_ip(None) is None
        assert _lan_subnet_from_ip('not.an.ip.addr') is None
        assert _lan_subnet_from_ip('10.0.0.999') is None
