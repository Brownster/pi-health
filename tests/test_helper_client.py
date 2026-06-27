#!/usr/bin/env python3
"""
Tests for helper_client module
"""
import sys
import os
import json
import struct
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
        payload = b'{"success": true}'
        mock_sock.recv.side_effect = [struct.pack('!I', len(payload)), payload]

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                response = helper_client.helper_call("ping")

        assert response["success"] is True
        mock_sock.connect.assert_called_once_with(helper_client.HELPER_SOCKET)
        request_frame = mock_sock.sendall.call_args.args[0]
        request_size = struct.unpack('!I', request_frame[:4])[0]
        assert request_size == len(request_frame[4:])
        assert json.loads(request_frame[4:])["command"] == "ping"

    def test_helper_call_timeout(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = helper_client.socket.timeout

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError):
                    helper_client.helper_call("ping")

    def test_helper_call_invalid_json(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [struct.pack('!I', 7), b"invalid"]

        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError):
                    helper_client.helper_call("ping")

    def test_helper_call_rejects_oversized_request(self):
        mock_sock = MagicMock()
        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError, match="exceeds maximum size"):
                    helper_client.helper_call("ping", {"value": "x" * 70000})
        mock_sock.sendall.assert_not_called()

    def test_helper_call_rejects_oversized_response_frame(self):
        mock_sock = MagicMock()
        mock_sock.recv.return_value = struct.pack('!I', helper_client.MAX_MESSAGE_SIZE + 1)
        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError, match="Invalid response size"):
                    helper_client.helper_call("ping")

    def test_helper_call_rejects_truncated_response_frame(self):
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [struct.pack('!I', 10), b"{}", b""]
        with patch("helper_client.os.path.exists", return_value=True):
            with patch("helper_client.socket.socket", return_value=mock_sock):
                with pytest.raises(HelperError, match="Incomplete response"):
                    helper_client.helper_call("ping")


class TestHelperAvailable:
    def test_helper_available_true(self):
        with patch("helper_client.helper_call", return_value={"success": True}):
            assert helper_client.helper_available() is True

    def test_helper_available_false(self):
        with patch("helper_client.helper_call", side_effect=HelperError("nope")):
            assert helper_client.helper_available() is False
