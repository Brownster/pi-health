"""PB-003 slice 3: held-update approval flow (helper store + commands + API)."""

import importlib
import json
import logging
import os
import sys
from unittest.mock import patch

from werkzeug.security import generate_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import AppDependencies, LoginRateLimiter, create_app
from limeos_packages import PackageApproval, PendingUpdate

with patch("logging.FileHandler", return_value=logging.StreamHandler()):
    helper = importlib.import_module("pihealth_helper")


# -- helper: store + approve + pending ------------------------------------------
def test_approvals_store_roundtrip(tmp_path):
    store = tmp_path / "package-approvals.json"
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(store)):
        helper._write_package_approvals([PackageApproval("claude-code", "2.1.212-1", "admin", "2026-07-20T00:00:00Z")])
        loaded = helper._load_package_approvals()
    assert [a.name for a in loaded] == ["claude-code"] and loaded[0].version == "2.1.212-1"
    assert oct(store.stat().st_mode)[-3:] == "600"


def test_load_approvals_tolerates_missing_and_malformed(tmp_path):
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(tmp_path / "nope.json")):
        assert helper._load_package_approvals() == []
    bad = tmp_path / "bad.json"
    bad.write_text('{"approvals": [{"name": "x"}, "junk", {"name": "ok", "version": "1"}]}')
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(bad)):
        assert [a.name for a in helper._load_package_approvals()] == ["ok"]


def test_approve_rejects_a_version_that_is_not_pending(tmp_path):
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(tmp_path / "s.json")):
        with patch("pihealth_helper._compute_pending_updates",
                   return_value=[PendingUpdate("claude-code", "2.1.207-1", "2.1.212-1", True)]):
            result = helper.cmd_packages_approve({"name": "claude-code", "version": "9.9.9", "approved_by": "admin"})
    assert result["success"] is False
    assert not (tmp_path / "s.json").exists()  # nothing recorded


def test_approve_records_a_matching_pending_update(tmp_path):
    store = tmp_path / "s.json"
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(store)):
        with patch("pihealth_helper._compute_pending_updates",
                   return_value=[PendingUpdate("claude-code", "2.1.207-1", "2.1.212-1", True)]):
            result = helper.cmd_packages_approve(
                {"name": "claude-code", "version": "2.1.212-1", "approved_by": "holly"})
    assert result["success"] is True
    assert result["approval"]["approved_by"] == "holly" and result["approval"]["approved_at"]
    stored = json.loads(store.read_text())["approvals"]
    assert stored[0]["name"] == "claude-code" and stored[0]["version"] == "2.1.212-1"


def test_approve_upserts_by_name(tmp_path):
    store = tmp_path / "s.json"
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(store)):
        with patch("pihealth_helper._compute_pending_updates",
                   return_value=[PendingUpdate("claude-code", "2.1.207-1", "2.1.213-1", True)]):
            helper._write_package_approvals([PackageApproval("claude-code", "2.1.212-1", "a", "t")])
            helper.cmd_packages_approve({"name": "claude-code", "version": "2.1.213-1", "approved_by": "b"})
    stored = json.loads(store.read_text())["approvals"]
    assert len(stored) == 1 and stored[0]["version"] == "2.1.213-1"


def test_approve_rejects_unknown_params():
    assert helper.cmd_packages_approve({"name": "x", "version": "1", "evil": "1"})["success"] is False


def test_pending_command_reports_pending_and_approvals(tmp_path):
    store = tmp_path / "s.json"
    with patch("pihealth_helper.PACKAGE_APPROVALS_STORE", str(store)):
        helper._write_package_approvals([PackageApproval("claude-code", "2.1.212-1", "a", "t")])
        with patch("pihealth_helper._compute_pending_updates",
                   return_value=[PendingUpdate("claude-code", "2.1.207-1", "2.1.212-1", True)]):
            result = helper.cmd_packages_pending({})
    assert result["success"] is True
    assert result["pending"][0]["approved"] is True
    assert result["approvals"][0]["name"] == "claude-code"


# -- API ------------------------------------------------------------------------
def _client(*, authenticated=True):
    app = create_app(
        {"TESTING": True, "SECRET_KEY": "k", "INIT_PLUGINS": False, "START_SCHEDULERS": False},
        AppDependencies(
            users={"admin": generate_password_hash("pw", method="pbkdf2:sha256:600000")},
            login_rate_limiter=LoginRateLimiter(),
            docker_client=None,
        ),
    )
    client = app.test_client()
    if authenticated:
        with client.session_transaction() as s:
            s["authenticated"] = True
            s["username"] = "holly"
            s["csrf_token"] = "csrf"
        client.environ_base["HTTP_X_CSRF_TOKEN"] = "csrf"
    return client


def test_pending_endpoint_requires_auth():
    assert _client(authenticated=False).get("/api/integrations/packages/pending").status_code == 401


def test_pending_endpoint_returns_helper_data():
    with patch("integrations_manager.helper_call",
               return_value={"success": True, "pending": [{"name": "claude-code"}], "approvals": []}):
        response = _client().get("/api/integrations/packages/pending")
    assert response.status_code == 200 and response.get_json()["pending"][0]["name"] == "claude-code"


def test_approve_endpoint_passes_actor_and_payload_to_helper():
    with patch("integrations_manager.helper_call",
               return_value={"success": True, "approval": {"name": "claude-code"}}) as hc:
        response = _client().post(
            "/api/integrations/packages/approve",
            json={"name": "claude-code", "version": "2.1.212-1"},
        )
    assert response.status_code == 201
    args = hc.call_args.args
    assert args[0] == "packages_approve"
    assert args[1] == {"name": "claude-code", "version": "2.1.212-1", "approved_by": "holly"}


def test_approve_endpoint_rejects_bad_body_and_helper_failure():
    client = _client()
    assert client.post("/api/integrations/packages/approve", json={"name": "x"}).status_code == 400
    with patch("integrations_manager.helper_call", return_value={"success": False, "error": "nope"}):
        response = client.post(
            "/api/integrations/packages/approve", json={"name": "x", "version": "1"})
    assert response.status_code == 400
