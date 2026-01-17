#!/usr/bin/env python3
"""
Tests for helper_client module
"""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import helper_client
from helper_client import HelperError


class TestHelperCall:
    def test_helper_call_socket_missing(self):
        with patch("helper_client.os.path.exists", return_value=False):
            with pytest.raises(HelperError):
                helper_client.helper_call("ping")

    def test_helper_call_success(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b'{"success": true}', b""]

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                response = helper_client.helper_call("ping")

        assert response["success"] is True
        mock_sock.connect.assert_called_once_with(helper_client.HELPER_SOCKET)
        mock_sock.sendall.assert_called_once()

    def test_helper_call_timeout(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = helper_client.socket.timeout

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError):
                    helper_client.helper_call("ping")

    def test_helper_call_invalid_json(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"invalid", b""]

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError):
                    helper_client.helper_call("ping")


class TestHelperAvailable:
    def test_helper_available_true(self):
        with patch("helper_client.helper_call", return_value={"success": True}):
            assert helper_client.helper_available() is True

    def test_helper_available_false(self):
        with patch("helper_client.helper_call", side_effect=HelperError("nope")):
            assert helper_client.helper_available() is False
