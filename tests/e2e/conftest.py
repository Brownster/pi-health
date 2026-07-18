import pytest
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Page, expect

# The full e2e run spawns a fresh app server per v2 test (viewport x mode matrix), so under
# heavy parallel load login/navigation can exceed Playwright's default 5s assertion timeout
# even though the same checks pass in isolation. Bump the default to absorb that load flake.
expect.set_options(timeout=10_000)

# Default credentials from appropriate environment variables or defaults
USERNAME = os.getenv('PIHEALTH_USER', 'admin')
PASSWORD = os.getenv('PIHEALTH_TEST_PASSWORD', os.getenv('PIHEALTH_PASSWORD', 'pihealth'))
PASSWORD_HASH = os.getenv(
    'PIHEALTH_PASSWORD_HASH',
    'pbkdf2:sha256:600000$WY9hNhygYgkvb3aQ$'
    '1d1076dc15e3201c5aaac3272ab5d7410097da87d8844ab9d5aa9e27e53ff465',
)
BASE_URL = os.getenv('BASE_URL', 'http://localhost:8002')

VIEWPORT_PROFILES = {
    'desktop': {'width': 1280, 'height': 720},
    'phone': {'width': 390, 'height': 844},
    'tablet': {'width': 768, 'height': 1024},
}

@pytest.fixture(scope="session")
def test_user_credentials():
    return {"username": USERNAME, "password": PASSWORD, "base_url": BASE_URL}

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """
    Configure the browser context (e.g., viewport size, ignoring https errors).
    """
    return {
        **browser_context_args,
        "ignore_https_errors": True,
        "viewport": VIEWPORT_PROFILES['desktop'],
    }

@pytest.fixture(params=['desktop', 'phone', 'tablet'], ids=lambda name: f'viewport_{name}')
def viewport_profile_name(request):
    return request.param

@pytest.fixture(scope='function')
def profiled_page(browser, viewport_profile_name):
    context = browser.new_context(
        ignore_https_errors=True,
        viewport=VIEWPORT_PROFILES[viewport_profile_name],
    )
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()

@pytest.fixture(scope='session')
def assert_no_horizontal_overflow():
    def _assert(page: Page, context: str = ''):
        page.wait_for_load_state("domcontentloaded")
        metrics = page.evaluate(
            """() => ({
                innerWidth: window.innerWidth,
                docScrollWidth: document.documentElement ? document.documentElement.scrollWidth : 0,
                bodyScrollWidth: document.body ? document.body.scrollWidth : 0
            })"""
        )

        max_width = max(metrics['docScrollWidth'], metrics['bodyScrollWidth'])
        overflow = max_width - metrics['innerWidth']
        assert overflow <= 1, (
            f"Horizontal overflow{f' on {context}' if context else ''}: "
            f"scrollWidth={max_width}, innerWidth={metrics['innerWidth']}"
        )

    return _assert

# ---------------------------------------------------------------------------
# Shared v2 (React) UI e2e scaffolding
#
# Reusable app server lifecycle, login helper, and deterministic /api mocks.
# ---------------------------------------------------------------------------

V2_REPO_ROOT = Path(__file__).resolve().parents[2]
V2_APP_PATH = V2_REPO_ROOT / "app.py"
V2_INDEX_PATH = V2_REPO_ROOT / "static" / "v2" / "index.html"

V2_MOCK_CONTAINER_ID = "v2-mock-container-1"


def _v2_find_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _v2_wait_for_server_ready(process, base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        # Fail fast with diagnostics if the server process died on startup — e.g. launched
        # under an interpreter missing app deps (ruamel.yaml etc.) — instead of silently
        # waiting out the full timeout.
        if process.poll() is not None:
            raise RuntimeError(
                f"App at {base_url} exited early (code {process.returncode}).\n"
                f"{_v2_server_log_tail(process)}"
            )
        try:
            # Readiness probes the always-200 public login page.
            # so it survives legacy theme-system removal (LR-006). Avoid endpoints that
            # return 401 unauthenticated — urlopen raises on 4xx and the probe never readies.
            with urlrequest.urlopen(f"{base_url}/login.html", timeout=1):
                return
        except (urlerror.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError(
        f"Timed out waiting for app at {base_url}\n{_v2_server_log_tail(process)}"
    )


def _v2_server_log_tail(process, limit: int = 2000) -> str:
    log_path = getattr(process, "_limeos_log_path", None)
    if not log_path or not os.path.exists(log_path):
        return ""
    with open(log_path, errors="replace") as handle:
        return handle.read()[-limit:]


def _v2_spawn():
    """Spawn the v2-only app. Returns (process, base_url)."""
    if not V2_APP_PATH.exists():
        pytest.skip(f"App entrypoint not found at {V2_APP_PATH}")
    if not V2_INDEX_PATH.exists():
        pytest.skip("v2 assets missing. Run `npm --prefix frontend run build:publish` first.")

    port = _v2_find_open_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.update(
        {
            "PORT": str(port),
            "PIHEALTH_USER": USERNAME,
            "PIHEALTH_PASSWORD_HASH": PASSWORD_HASH,
        }
    )
    env.pop("PIHEALTH_PASSWORD", None)

    # Provision isolated runtime roots when not already supplied (e.g. running the suite
    # directly rather than via scripts/run-e2e.sh), so the spawned server never touches the
    # system /etc/limeos, /var/lib/limeos, /var/log/limeos paths.
    runtime_root = None
    if not env.get("LIMEOS_CONFIG_DIR"):
        runtime_root = tempfile.mkdtemp(prefix="limeos-e2e-")
        env["LIMEOS_CONFIG_DIR"] = os.path.join(runtime_root, "config")
        env["LIMEOS_STATE_DIR"] = os.path.join(runtime_root, "state")
        env["LIMEOS_LOG_DIR"] = os.path.join(runtime_root, "log")
        env["LIMEOS_CREDENTIALS_FILE"] = os.path.join(env["LIMEOS_CONFIG_DIR"], "credentials.env")
        for key in ("LIMEOS_CONFIG_DIR", "LIMEOS_STATE_DIR", "LIMEOS_LOG_DIR"):
            os.makedirs(env[key], exist_ok=True)

    # Capture server output so a failed startup surfaces its error (see readiness check).
    log_fd, log_path = tempfile.mkstemp(prefix="limeos-e2e-", suffix=".log")
    process = subprocess.Popen(
        [sys.executable, str(V2_APP_PATH)],
        cwd=str(V2_REPO_ROOT),
        env=env,
        stdout=log_fd,
        stderr=subprocess.STDOUT,
    )
    os.close(log_fd)
    process._limeos_log_path = log_path
    process._limeos_runtime_root = runtime_root
    return process, base_url


def _v2_teardown(process) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log_path = getattr(process, "_limeos_log_path", None)
    if log_path and os.path.exists(log_path):
        os.remove(log_path)
    runtime_root = getattr(process, "_limeos_runtime_root", None)
    if runtime_root and os.path.isdir(runtime_root):
        shutil.rmtree(runtime_root, ignore_errors=True)


@pytest.fixture(scope="function")
def v2_server():
    """Isolated app server for v2 parity coverage."""
    process, base_url = _v2_spawn()
    try:
        _v2_wait_for_server_ready(process, base_url)
        yield {"base_url": base_url}
    finally:
        _v2_teardown(process)


@pytest.fixture(scope="function")
def v2_mock_container_id():
    return V2_MOCK_CONTAINER_ID


@pytest.fixture(scope="function")
def v2_login():
    """Returns a callable(page, base_url) that logs in and waits for the v2/home URL."""

    def _login(page: Page, base_url: str) -> None:
        page.goto(f"{base_url}/login.html")
        if "login.html" not in page.url:
            return
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("#login-button")
        page.wait_for_url(re.compile(rf"{re.escape(base_url)}/(v2/?|$)"), timeout=10000)
        page.wait_for_load_state("load")

    return _login


@pytest.fixture(scope="function")
def install_v2_containers_api_mocks():
    """Returns a callable(page) that installs deterministic /api/** mocks for v2 containers."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def _install(page: Page, extra_containers=None) -> None:
        container_payload = [
            {
                "id": V2_MOCK_CONTAINER_ID,
                "name": "v2-mock-service",
                "image": "linuxserver/mock:latest",
                "status": "running",
                "health": "healthy",
                "stack": "media",
                "cpu_percent": 7.5,
                "memory_percent": 22.1,
                "memory_used": 380000000,
                "memory_limit": 2048000000,
                "net_rx": 1234000,
                "net_tx": 2345000,
                "ports": [{"container_port": 8080, "host_port": 18080, "protocol": "tcp"}],
                "web_scheme": "https",
                "update_available": False,
            },
            *(extra_containers or []),
        ]

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/network-groups" and method == "GET":
                # v2-mock-service is orphaned from its VPN provider — the badge the
                # containers page must surface (PH5-005).
                _json_fulfill(route, {"groups": [{
                    "provider": "gluetun", "provider_status": "running",
                    "provider_health": None, "members": [],
                    "orphaned_members": ["v2-mock-service"], "status": "degraded",
                }]})
                return
            if path == "/api/containers" and method == "GET":
                _json_fulfill(route, container_payload)
                return

            if path == "/api/containers/stats" and method == "GET":
                _json_fulfill(
                    route,
                    {
                        V2_MOCK_CONTAINER_ID: {
                            "cpu_percent": 7.5,
                            "memory_percent": 22.1,
                            "memory_used": 380000000,
                            "memory_limit": 2048000000,
                            "net_rx": 1234000,
                            "net_tx": 2345000,
                        }
                    },
                )
                return

            if path == f"/api/containers/{V2_MOCK_CONTAINER_ID}" and method == "GET":
                include_values = parse_qs(parsed.query).get("env") == ["full"]
                environment = [{"key": "TOKEN"}, {"key": "TZ"}]
                if include_values:
                    environment = [
                        {"key": "TOKEN", "value": "secret-token"},
                        {"key": "TZ", "value": "Europe/London"},
                    ]
                _json_fulfill(
                    route,
                    {
                        "id": V2_MOCK_CONTAINER_ID,
                        "name": "v2-mock-service",
                        "status": "running",
                        "stack": "media",
                        "image": "linuxserver/mock:latest",
                        "image_id": "sha256:mock",
                        "image_tags": ["linuxserver/mock:latest"],
                        "image_digests": ["linuxserver/mock@sha256:digest"],
                        "created": "2026-07-07T08:00:00Z",
                        "started_at": "2026-07-07T09:00:00Z",
                        "uptime_seconds": 3600,
                        "restart_policy": {"Name": "unless-stopped"},
                        "mounts": [{"type": "bind", "source": "/mnt/media", "destination": "/media", "mode": "rw", "rw": True}],
                        "networks": [{"name": "media", "ip_address": "172.18.0.2", "gateway": "172.18.0.1", "mac_address": None, "aliases": []}],
                        "command": ["serve"],
                        "environment": environment,
                    },
                )
                return

            if path == f"/api/containers/{V2_MOCK_CONTAINER_ID}/health" and method == "GET":
                _json_fulfill(
                    route,
                    {"status": "healthy", "failing_streak": 0, "last_output": "probe ok"},
                )
                return

            if path == f"/api/containers/{V2_MOCK_CONTAINER_ID}/logs" and method == "GET":
                _json_fulfill(
                    route,
                    {"container": "v2-mock-service", "logs": "line 1\nline 2\nline 3"},
                )
                return

            if path == f"/api/containers/{V2_MOCK_CONTAINER_ID}/network-test" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "container_id": V2_MOCK_CONTAINER_ID,
                        "container_name": "v2-mock-service",
                        "ping_success": True,
                        "local_ip": "172.18.0.2",
                        "public_ip": "203.0.113.10",
                        "probe_method": "ping",
                        "ping_output": "64 bytes from 8.8.8.8: icmp_seq=1 ttl=57 time=10ms",
                    },
                )
                return

            if path == "/api/network-test" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "ping_success": True,
                        "local_ip": "192.168.1.50",
                        "public_ip": "203.0.113.20",
                        "probe_method": "ping",
                        "ping_output": "64 bytes from 8.8.8.8: icmp_seq=1 ttl=57 time=8ms",
                    },
                )
                return

            if path.startswith(f"/api/containers/{V2_MOCK_CONTAINER_ID}/") and method == "POST":
                action = path.rsplit("/", 1)[-1]
                if action in {"start", "stop", "restart", "check_update", "update"}:
                    _json_fulfill(route, {"status": f"{action} accepted", "update_available": False})
                    return

            # Generic action handler for extra_containers (PH5-006 check-all / provider update).
            action_match = re.match(
                r"^/api/containers/([^/]+)/(start|stop|restart|check_update|update)$", path
            )
            if action_match and method == "POST":
                cid, action = action_match.group(1), action_match.group(2)
                _json_fulfill(route, {
                    "status": f"{action} accepted",
                    "update_available": action == "check_update" and cid != V2_MOCK_CONTAINER_ID,
                })
                return
            if re.match(r"^/api/network-groups/[^/]+/recreate$", path) and method == "POST":
                _json_fulfill(route, {"status": "recreated"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_stacks_api_mocks():
    """Returns a callable(page) installing deterministic /api/stacks* mocks for v2 stacks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        stacks_payload = {
            "stacks": [
                {
                    "name": "media",
                    "path": "/opt/stacks/media",
                    "compose_file": "docker-compose.yml",
                    "status": "running",
                    "running_count": 2,
                    "container_count": 2,
                }
            ]
        }
        sse_body = (
            'data: {"line": "Pulling service web"}\n\n'
            'data: {"line": "Container media-web-1 Started"}\n\n'
            'data: {"done": true, "returncode": 0}\n\n'
        )

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/stacks" and method == "GET":
                _json_fulfill(route, stacks_payload)
                return

            if path == "/api/stacks/media" and method == "GET":
                _json_fulfill(
                    route,
                    {
                        "name": "media",
                        "path": "/opt/stacks/media",
                        "compose_file": "docker-compose.yml",
                        "compose_content": "services:\n  web:\n    image: nginx:latest\n",
                        "has_env": True,
                        "env_content": "PUID=1000\nPGID=1000\n",
                        "status": {"status": "running"},
                    },
                )
                return

            if path == "/api/stacks/media/operations" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "operation_id": "mock-stack-operation",
                        "stream_url": "/api/stacks/operations/mock-stack-operation/stream",
                    },
                    status=202,
                )
                return

            # Read-only lifecycle operation stream.
            if path == "/api/stacks/operations/mock-stack-operation/stream" and method == "GET":
                route.fulfill(status=200, content_type="text/event-stream", body=sse_body)
                return

            if path == "/api/stacks/media/logs" and method == "GET":
                _json_fulfill(route, {"logs": "stack log line 1\nstack log line 2", "returncode": 0})
                return

            if path == "/api/stacks/media/compose" and method == "GET":
                _json_fulfill(
                    route,
                    {"content": "services:\n  web:\n    image: nginx:latest\n", "filename": "docker-compose.yml"},
                )
                return
            if path == "/api/stacks/media/compose" and method == "POST":
                _json_fulfill(route, {"status": "saved"})
                return

            if path == "/api/stacks/media/env" and method == "GET":
                _json_fulfill(route, {"content": "PUID=1000\nPGID=1000\n", "exists": True})
                return
            if path == "/api/stacks/media/env" and method == "POST":
                _json_fulfill(route, {"status": "saved"})
                return

            if path == "/api/stacks/media/backups" and method == "GET":
                _json_fulfill(route, {"backups": ["docker-compose.yml.20260101-000000.bak"]})
                return
            if (
                path == "/api/stacks/media/backups/docker-compose.yml.20260101-000000.bak"
                and method == "GET"
            ):
                _json_fulfill(
                    route,
                    {
                        "content": "services:\n  web:\n    image: nginx:1.26\n",
                        "filename": "docker-compose.yml.20260101-000000.bak",
                    },
                )
                return
            if path == "/api/stacks/media/restore" and method == "POST":
                _json_fulfill(route, {"status": "restored", "backup": "docker-compose.yml.20260101-000000.bak"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_disks_api_mocks():
    """Returns a callable(page) installing deterministic /api/disks* mocks for v2 disks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page, failures=None) -> None:
        failures = failures or {}
        inventory = {
            "helper_available": True,
            "summary": {
                "state": "attention",
                "counts": {
                    "total": 1, "healthy": 0, "warning": 0, "failing": 0,
                    "unknown": 1, "mounted": 1, "unmounted": 0,
                    "assigned": 1, "unassigned": 0, "unused": 0,
                },
                "capacity": {
                    "mounted_total_bytes": 8000000000000,
                    "mounted_used_bytes": 5200000000000,
                    "mounted_available_bytes": 2800000000000,
                    "mounted_percent": 65,
                },
                "sources": {
                    "inventory": "available",
                    "smart": "not_checked",
                    "assignments": "available",
                },
                "devices": [{
                    "name": "sda", "path": "/dev/sda", "health": "unknown",
                    "temperature_c": None, "mounted": True,
                    "mounted_capacity": {
                        "mounted_total_bytes": 8000000000000,
                        "mounted_used_bytes": 5200000000000,
                        "mounted_available_bytes": 2800000000000,
                    },
                    "assignments": [{
                        "provider_id": "mergerfs", "capability_id": "storage.pooling",
                        "role": "branch", "resource_id": "media", "resource_name": "Media",
                        "href": "/pools/mergerfs", "device_path": "/dev/sda1",
                    }],
                }],
                "warnings": [],
                "collected_at": "2026-07-18T12:30:00Z",
            },
            "disks": [
                {
                    "name": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "size": "7.3T",
                    "model": "WDC WD80EDAZ-11CEWB0",
                    "serial": "WD-RD1ENASE",
                    "transport": "usb",
                    "mountpoint": "",
                    "fstype": "",
                    "partitions": [
                        {
                            "name": "sda1",
                            "path": "/dev/sda1",
                            "size": "7.3T",
                            "fstype": "ext4",
                            "mountpoint": "/mnt/storage",
                            "uuid": "abcd-1234",
                            "usage": {
                                "total": 8000000000000,
                                "used": 5200000000000,
                                "available": 2800000000000,
                                "percent": "65",
                            },
                        }
                    ],
                }
            ],
        }
        smart_device = {
            "device": "/dev/sda",
            "model": "WDC WD80EDAZ-11CEWB0",
            "serial": "WD-RD1ENASE",
            "drive_type": "hdd",
            "smart_available": True,
            "smart_enabled": True,
            "health_status": "healthy",
            "temperature_c": 38,
            "power_on_hours": 1234,
            "reallocated_sectors": 0,
            "pending_sectors": 0,
            "uncorrectable_errors": 0,
            "percentage_used": None,
            "available_spare": None,
            "media_errors": None,
            "error_message": None,
        }

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            failure = failures.get((method, path))
            if failure:
                status, content_type, body = failure
                route.fulfill(
                    status=status,
                    content_type=content_type,
                    body=json.dumps(body) if content_type == "application/json" else str(body),
                )
                return

            if path == "/api/disks" and method == "GET":
                _json_fulfill(route, inventory)
                return
            if path == "/api/disks/helper-status" and method == "GET":
                _json_fulfill(route, {"available": True, "socket_path": "/run/pihealth.sock"})
                return
            if path == "/api/disks/smart" and method == "GET":
                _json_fulfill(route, {"disks": [{"device": "/dev/sda", "data": smart_device}]})
                return
            if path == "/api/disks/sda/smart" and method == "GET":
                _json_fulfill(route, smart_device)
                return
            if path == "/api/disks/suggested-mounts" and method == "GET":
                _json_fulfill(
                    route,
                    {
                        "suggestions": [
                            {
                                "device": "/dev/sdb1",
                                "uuid": "sdb-uuid-1",
                                "size": "500G",
                                "fstype": "ext4",
                                "label": "",
                                "suggested_mount": "/mnt/backup",
                                "reason": "Small USB device - suitable for backups",
                            }
                        ]
                    },
                )
                return
            if path == "/api/disks/mount" and method == "POST":
                _json_fulfill(route, {"status": "mounted", "mountpoint": "/mnt/backup", "fstab_added": True})
                return
            if path == "/api/disks/unmount" and method == "POST":
                _json_fulfill(route, {"status": "unmounted", "mountpoint": "/mnt/storage", "fstab_removed": False})
                return
            if path == "/api/disks/sda/smart-test" and method == "POST":
                _json_fulfill(route, {"status": "started", "test_type": "short", "message": "SMART short self-test started"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


def _storage_capability_payload(plugin, detail, capability_id, surface, renderer_id):
    raw_status = detail.get("status", {}) if isinstance(detail, dict) else {}
    raw_details = raw_status.get("details", {}) if isinstance(raw_status, dict) else {}
    details = dict(raw_details) if isinstance(raw_details, dict) else {}
    configured = bool(plugin.get("configured"))
    enabled = bool(plugin.get("enabled"))
    legacy_state = str(raw_status.get("status", plugin.get("status", "unknown")))
    if not enabled:
        health = "disabled"
    elif not configured:
        health = "unconfigured"
    elif legacy_state in {"healthy", "ok", "active", "ready"}:
        health = "healthy"
    elif legacy_state in {"degraded", "warning", "unmounted", "sync_required"}:
        health = "warning"
    elif legacy_state in {"error", "failed"}:
        health = "error"
    else:
        health = "unknown"
    if capability_id == "storage.protection":
        config = detail.get("config", {}) if isinstance(detail, dict) else {}
        drives = config.get("drives", []) if isinstance(config, dict) else []
        data_drives = details.get(
            "data_drives", sum(drive.get("role") == "data" for drive in drives)
        )
        parity_drives = details.get(
            "parity_drives", sum(drive.get("role") == "parity" for drive in drives)
        )
        details["protection_sets"] = [{
            "name": "SnapRAID parity",
            "kind": "parity",
            "health": health,
            "protected_targets": data_drives,
            "unprotected_targets": None,
            "parity_targets": parity_drives,
            "last_run_at": details.get("last_run_at"),
            "next_run_at": None,
            "schedule": None,
            "sync_required": details.get("sync_required") is True,
            "required_action": (
                "Sync required" if details.get("sync_required") is True else None
            ),
        }] if configured else []
    status = {
        "schema_version": "1",
        "provider_id": plugin["id"],
        "capability_id": capability_id,
        "observed_at": "2026-07-18T20:00:00+00:00",
        "lifecycle": {
            "installed": bool(plugin.get("installed")),
            "enabled": enabled,
            "configured": configured,
            "compatibility": "compatible",
            "availability": "available" if detail else "unknown",
        },
        "health": {
            "state": health,
            "message": str(raw_status.get(
                "message", plugin.get("status_message", "Provider status is available.")
            )),
            "issues": [],
        },
        "summary": [],
        "metrics": [],
        "recent_activity": [],
        "details": details,
    }
    return {
        "schema_version": "1",
        "capability": {
            "id": capability_id,
            "surface": surface,
            "providers": [{
                "id": plugin["id"],
                "name": plugin["name"],
                "installed": bool(plugin.get("installed")),
                "enabled": enabled,
                "operational": bool(enabled and configured and health == "healthy"),
                "renderer": {"id": renderer_id, "mode": "tailored"},
                "status": status,
            }],
        },
        "errors": [],
    }


@pytest.fixture(scope="function")
def install_v2_storage_api_mocks():
    """Returns a callable(page) installing deterministic /api/storage/plugins* mocks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        plugins = [
            {
                "id": "mergerfs", "name": "MergerFS", "description": "Union filesystem pooling",
                "version": "1.0", "installed": True, "enabled": False, "configured": False,
                "status": "disabled", "status_message": "Disabled", "category": "storage",
                "kind": "pool", "type": "builtin",
            },
            {
                "id": "snapraid", "name": "SnapRAID", "description": "Parity protection",
                "version": "1.0", "installed": True, "enabled": True, "configured": False,
                "status": "unconfigured", "status_message": "No drives", "category": "storage",
                "kind": "pool", "type": "builtin",
            },
            {
                "id": "samba", "name": "Samba", "description": "SMB shares",
                "version": "1.0", "installed": True, "enabled": True, "configured": True,
                "status": "active", "status_message": "Running", "category": "shares", "type": "builtin",
            },
            {
                "id": "customfs", "name": "CustomFS", "description": "Third-party storage plugin",
                "version": "0.1", "installed": True, "enabled": False, "configured": False,
                "status": "disabled", "status_message": "Disabled", "category": "storage", "type": "github",
            },
        ]
        mergerfs_detail = {
            "id": "mergerfs", "name": "MergerFS", "description": "Union filesystem pooling",
            "version": "1.0", "installed": True,
            "status": {"status": "ok", "message": "Pool active"},
            "commands": [
                {"id": "mount", "name": "Mount Pool", "description": "Mount a MergerFS pool",
                 "dangerous": False, "params": ["pool_name"],
                 "param_schema": [{"name": "pool_name", "label": "Pool", "type": "select",
                                   "source": "status.details.pools[].name", "required": True}]},
                {"id": "unmount", "name": "Unmount Pool", "description": "Unmount a MergerFS pool",
                 "dangerous": True, "params": ["pool_name"],
                 "param_schema": [{"name": "pool_name", "label": "Pool", "type": "select",
                                   "source": "status.details.pools[].name", "required": True}]},
                {"id": "balance", "name": "Balance", "description": "Rebalance files across branches",
                 "dangerous": False, "params": ["pool_name"],
                 "param_schema": [{"name": "pool_name", "label": "Pool", "type": "select",
                                   "source": "status.details.pools[].name", "required": True}]},
                {"id": "status", "name": "Status", "description": "Show pool status",
                 "dangerous": False, "params": []},
            ],
            "schema": {"properties": {"mountpoint": {"type": "string", "description": "Pool mount point"}}},
            "config": {"enabled": True, "mountpoint": "/mnt/pool", "pools": []},
            "install_instructions": "",
        }
        snapraid_detail = {
            "id": "snapraid", "name": "SnapRAID", "description": "Parity protection",
            "version": "1.0", "installed": True, "kind": "pool",
            "status": {"status": "unconfigured", "message": "No drives", "details": {"sync_required": False}},
            "commands": [
                {"id": "status", "name": "Status", "description": "Show array status", "dangerous": False},
                {"id": "diff", "name": "Diff", "description": "Show pending changes", "dangerous": False},
                {"id": "sync", "name": "Sync", "description": "Update parity", "dangerous": False},
                {"id": "scrub", "name": "Scrub", "description": "Verify protected data", "dangerous": False,
                 "param_schema": [
                     {"name": "percent", "label": "Data percentage", "type": "number", "default": 8},
                     {"name": "age_days", "label": "Minimum age (days)", "type": "number", "default": 10},
                 ]},
                {"id": "check", "name": "Check", "description": "Check data and parity", "dangerous": False},
                {"id": "fix", "name": "Fix", "description": "Recover files from parity", "dangerous": True},
            ],
            "schema": {"properties": {}},
            "config": {"enabled": False, "drives": []},
            "install_instructions": "",
        }
        disks_inventory = {
            "helper_available": True,
            "disks": [
                {
                    "name": "sda", "path": "/dev/sda", "type": "disk", "size": "1T",
                    "model": None, "serial": None, "transport": "sata", "mountpoint": None,
                    "fstype": None, "uuid": None, "label": None,
                    "partitions": [{
                        "name": "sda1", "path": "/dev/sda1", "size": "1T", "fstype": "ext4",
                        "mountpoint": "/mnt/disk1", "uuid": "uuid-1", "label": None,
                    }],
                },
                {
                    "name": "sdb", "path": "/dev/sdb", "type": "disk", "size": "2T",
                    "model": None, "serial": None, "transport": "sata", "mountpoint": None,
                    "fstype": None, "uuid": None, "label": None,
                    "partitions": [{
                        "name": "sdb1", "path": "/dev/sdb1", "size": "2T", "fstype": "ext4",
                        "mountpoint": "/mnt/parity", "uuid": "uuid-2", "label": None,
                    }],
                },
            ],
        }
        command_sse = (
            'data: {"type": "output", "line": "checking pool mergerfs"}\n\n'
            'data: {"type": "complete", "success": true, "message": "pool healthy"}\n\n'
        )

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/storage/plugins" and method == "GET":
                _json_fulfill(route, {"plugins": plugins})
                return
            if path == "/api/capabilities/storage.pooling" and method == "GET":
                mergerfs = next(plugin for plugin in plugins if plugin["id"] == "mergerfs")
                _json_fulfill(route, _storage_capability_payload(
                    mergerfs, mergerfs_detail, "storage.pooling", "pools", "mergerfs",
                ))
                return
            if path == "/api/capabilities/storage.protection" and method == "GET":
                snapraid = next(plugin for plugin in plugins if plugin["id"] == "snapraid")
                _json_fulfill(route, _storage_capability_payload(
                    snapraid, snapraid_detail, "storage.protection", "protection", "snapraid",
                ))
                return
            if path == "/api/storage/plugins/mergerfs" and method == "GET":
                _json_fulfill(route, mergerfs_detail)
                return
            if path == "/api/storage/plugins/snapraid" and method == "GET":
                _json_fulfill(route, snapraid_detail)
                return
            if path == "/api/storage/plugins/snapraid/config-preview" and method == "POST":
                _json_fulfill(route, {"preview": "parity /mnt/parity/snapraid.parity\ndata d1 /mnt/disk1/\n"})
                return
            if path == "/api/storage/plugins/mergerfs/config-preview" and method == "POST":
                _json_fulfill(
                    route,
                    {"preview": "# pi-health mergerfs start\n/mnt/disk1:/mnt/parity /mnt/media fuse.mergerfs category.create=epmfs 0 0\n# pi-health mergerfs end\n"},
                )
                return
            if path == "/api/storage/plugins/snapraid/recovery" and method == "GET":
                _json_fulfill(route, {"error": "Recovery not supported"}, status=404)
                return
            if path == "/api/storage/plugins/snapraid/logs/latest" and method == "GET":
                route.fulfill(status=200, content_type="text/plain", body="snapraid log line")
                return
            if path == "/api/storage/plugins/snapraid/config" and method == "POST":
                _json_fulfill(route, {"status": "saved", "config": {"enabled": True, "drives": []}})
                return
            if path == "/api/storage/plugins/snapraid/commands/sync" and method == "POST":
                body = route.request.post_data or "{}"
                forced = '"force": true' in body or '"force":true' in body
                if forced:
                    # run:pos tag values are strings in production (from the log-tag parser);
                    # values[4]=percent, [5]=eta, [6]=speed.
                    sse = (
                        'data: {"type": "tag", "name": "run", "values": '
                        '["pos", "0", "0", "0", "42", "120", "3.5", "0", "0"]}\n\n'
                        'data: {"type": "complete", "success": true, "message": "sync done"}\n\n'
                    )
                else:
                    sse = (
                        'data: {"type": "output", "line": "WARNING: 51 files removed (threshold: 50)"}\n\n'
                        'data: {"type": "complete", "success": false, "data": {"force_allowed": true}}\n\n'
                    )
                route.fulfill(status=200, content_type="text/event-stream", body=sse)
                return
            if path.startswith("/api/storage/plugins/snapraid/commands/") and method == "POST":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'data: {"type": "output", "line": "snapraid operation complete"}\n\n'
                        'data: {"type": "complete", "success": true, "message": "done"}\n\n'
                    ),
                )
                return
            if path == "/api/disks" and method == "GET":
                _json_fulfill(route, disks_inventory)
                return
            if path.startswith("/api/storage/plugins/") and path.endswith("/toggle") and method == "POST":
                _json_fulfill(route, {"status": "ok", "enabled": True})
                return
            if path.startswith("/api/storage/plugins/") and path.endswith("/apply") and method == "POST":
                _json_fulfill(route, {"status": "applied", "message": "Applied"})
                return
            if path.startswith("/api/storage/plugins/") and path.endswith("/remove") and method == "DELETE":
                _json_fulfill(route, {"status": "removed"})
                return
            if path == "/api/storage/plugins/mergerfs/recovery" and method == "GET":
                _json_fulfill(route, {"error": "Recovery not supported"}, status=404)
                return
            if path == "/api/storage/plugins/mergerfs/logs/latest" and method == "GET":
                route.fulfill(status=200, content_type="text/plain", body="mergerfs pool log line")
                return
            if path.startswith("/api/storage/plugins/mergerfs/commands/") and method == "POST":
                route.fulfill(status=200, content_type="text/event-stream", body=command_sse)
                return
            if path == "/api/storage/plugins/mergerfs/config" and method == "POST":
                _json_fulfill(route, {"status": "saved", "config": {"mountpoint": "/mnt/pool"}})
                return
            if path == "/api/storage/plugins/install" and method == "POST":
                _json_fulfill(route, {"status": "installed", "plugin": {"id": "newfs"}})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_storage_configured_mocks():
    """Configured pools: healthy SnapRAID + MergerFS with a mounted and a degraded pool."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        plugins = [
            {
                "id": "snapraid", "name": "SnapRAID", "description": "Parity protection",
                "version": "1.0", "installed": True, "enabled": True, "configured": True,
                "status": "healthy", "status_message": "All data protected",
                "category": "storage", "kind": "pool", "type": "builtin",
            },
            {
                "id": "mergerfs", "name": "MergerFS", "description": "Union filesystem pooling",
                "version": "1.0", "installed": True, "enabled": True, "configured": True,
                "status": "ok", "status_message": "2 pool(s)",
                "category": "storage", "kind": "pool", "type": "builtin",
            },
        ]
        snapraid_detail = {
            "id": "snapraid", "name": "SnapRAID", "version": "1.0", "installed": True, "kind": "pool",
            "status": {
                "status": "healthy", "message": "All data protected",
                "details": {
                    "data_drives": 2, "parity_drives": 1, "sync_required": False,
                    "last_command": "sync", "last_run_at": "2026-07-05T00:00:00Z",
                    "last_summary": {"added": 3, "removed": 1, "updated": 2},
                },
            },
            "commands": [
                {"id": "status", "name": "Status", "description": "Show array status", "dangerous": False},
                {"id": "diff", "name": "Diff", "description": "Show pending changes", "dangerous": False},
                {"id": "sync", "name": "Sync", "description": "Update parity", "dangerous": False},
                {"id": "scrub", "name": "Scrub", "description": "Verify protected data", "dangerous": False,
                 "param_schema": [
                     {"name": "percent", "label": "Data percentage", "type": "number", "default": 8},
                     {"name": "age_days", "label": "Minimum age (days)", "type": "number", "default": 10},
                 ]},
                {"id": "check", "name": "Check", "description": "Check data and parity", "dangerous": False},
                {"id": "fix", "name": "Fix", "description": "Recover files from parity", "dangerous": True},
            ],
            "schema": {"properties": {}},
            "config": {
                "enabled": True,
                "drives": [
                    {"path": "/mnt/disk1", "role": "data", "content": True, "uuid": "uuid-1"},
                    {"path": "/mnt/parity", "role": "parity", "content": True, "uuid": "uuid-2"},
                ],
                "schedule": {
                    "sync": {"enabled": True, "cron": "0 2 * * *"},
                    "scrub": {"enabled": True, "cron": "0 3 * * 0"},
                },
                "scrub_percent": 8,
                "scrub_age_days": 10,
            },
            "install_instructions": "",
        }
        mergerfs_detail = {
            "id": "mergerfs", "name": "MergerFS", "version": "1.0", "installed": True, "kind": "pool",
            "status": {
                "status": "ok", "message": "2 pool(s)",
                "details": {"pools": [
                    {"name": "media", "mount_point": "/mnt/media", "mounted": True, "branches": 3,
                     "total_bytes": 4000000000000, "free_bytes": 2320000000000, "used_percent": 42},
                    {"name": "backup", "mount_point": "/mnt/backup", "mounted": False, "branches": 2},
                ]},
            },
            "commands": [
                {"id": command_id, "name": label, "description": description,
                 "dangerous": command_id == "unmount", "params": ["pool_name"],
                 "param_schema": [{"name": "pool_name", "label": "Pool", "type": "select",
                                   "source": "status.details.pools[].name", "required": True}]}
                for command_id, label, description in [
                    ("mount", "Mount Pool", "Mount a MergerFS pool"),
                    ("unmount", "Unmount Pool", "Unmount a MergerFS pool"),
                    ("balance", "Balance", "Rebalance files across branches"),
                ]
            ] + [{"id": "status", "name": "Status", "description": "Show pool status",
                  "dangerous": False, "params": []}],
            "schema": {"properties": {}}, "config": {"pools": []}, "install_instructions": "",
        }
        disks_inventory = {
            "helper_available": True,
            "disks": [
                {
                    "name": "sda", "path": "/dev/sda", "type": "disk", "size": "1T",
                    "model": "Data Disk", "serial": "data-1", "transport": "sata",
                    "mountpoint": None, "fstype": None, "uuid": None, "label": None,
                    "partitions": [{
                        "name": "sda1", "path": "/dev/sda1", "size": "1T", "fstype": "ext4",
                        "mountpoint": "/mnt/disk1", "uuid": "uuid-1", "label": "data",
                    }],
                },
                {
                    "name": "sdb", "path": "/dev/sdb", "type": "disk", "size": "2T",
                    "model": "Parity Disk", "serial": "parity-1", "transport": "sata",
                    "mountpoint": None, "fstype": None, "uuid": None, "label": None,
                    "partitions": [{
                        "name": "sdb1", "path": "/dev/sdb1", "size": "2T", "fstype": "ext4",
                        "mountpoint": "/mnt/parity", "uuid": "uuid-2", "label": "parity",
                    }],
                },
            ],
        }

        def _handler(route):
            path = urlparse(route.request.url).path
            method = route.request.method
            if path == "/api/storage/plugins" and method == "GET":
                _json_fulfill(route, {"plugins": plugins})
                return
            if path == "/api/capabilities/storage.pooling" and method == "GET":
                mergerfs = next(plugin for plugin in plugins if plugin["id"] == "mergerfs")
                _json_fulfill(route, _storage_capability_payload(
                    mergerfs, mergerfs_detail, "storage.pooling", "pools", "mergerfs",
                ))
                return
            if path == "/api/capabilities/storage.protection" and method == "GET":
                snapraid = next(plugin for plugin in plugins if plugin["id"] == "snapraid")
                _json_fulfill(route, _storage_capability_payload(
                    snapraid, snapraid_detail, "storage.protection", "protection", "snapraid",
                ))
                return
            if path == "/api/storage/plugins/snapraid" and method == "GET":
                _json_fulfill(route, snapraid_detail)
                return
            if path == "/api/storage/plugins/mergerfs" and method == "GET":
                _json_fulfill(route, mergerfs_detail)
                return
            if path == "/api/disks" and method == "GET":
                _json_fulfill(route, disks_inventory)
                return
            if path == "/api/storage/plugins/snapraid/recovery" and method == "GET":
                _json_fulfill(route, {
                    "recoverable": True,
                    "failed_drives": ["data2"],
                    "missing_files": 3,
                    "damaged_files": 1,
                    "recovery_options": [{
                        "id": "fix_missing", "name": "Recover missing files",
                        "command": "fix", "params": {"filter": "missing"},
                    }],
                })
                return
            if path.endswith("/recovery") and method == "GET":
                _json_fulfill(route, {"error": "Recovery not supported"}, status=404)
                return
            if path.endswith("/logs/latest") and method == "GET":
                route.fulfill(status=200, content_type="text/plain", body="log line")
                return
            if path.startswith("/api/storage/plugins/mergerfs/commands/") and method == "POST":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'data: {"type": "output", "line": "mergerfs operation complete"}\n\n'
                        'data: {"type": "complete", "success": true, "message": "done"}\n\n'
                    ),
                )
                return
            if path.startswith("/api/storage/plugins/snapraid/commands/") and method == "POST":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'data: {"type": "output", "line": "snapraid operation complete"}\n\n'
                        'data: {"type": "complete", "success": true, "message": "done"}\n\n'
                    ),
                )
                return
            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_mounts_api_mocks():
    """Returns a callable(page) installing deterministic mounts mocks (media paths + mount plugin)."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page, include_failed_provider: bool = False) -> None:
        paths = {
            "downloads": "/mnt/downloads",
            "storage": "/mnt/storage",
            "backup": "/mnt/backup",
            "config": "/home/pi/docker",
        }
        plugins = [
            {"id": "rclone", "name": "Rclone", "description": "Remote mounts", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "mounts", "type": "builtin"},
            {"id": "samba", "name": "Samba", "description": "SMB", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "shares", "type": "builtin"},
        ]
        if include_failed_provider:
            plugins.append(
                {"id": "sshfs", "name": "SSHFS", "description": "SSH mounts", "version": "1.0",
                 "installed": True, "enabled": True, "configured": True, "status": "error",
                 "status_message": "Helper offline", "category": "mounts", "type": "builtin"}
            )

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/disks/media-paths" and method == "GET":
                _json_fulfill(route, {"paths": paths})
                return
            if path == "/api/disks/media-paths" and method == "POST":
                _json_fulfill(route, {"status": "updated", "paths": paths})
                return
            if path == "/api/storage/plugins" and method == "GET":
                _json_fulfill(route, {"plugins": plugins})
                return
            if path == "/api/storage/mounts/rclone" and method == "GET":
                _json_fulfill(
                    route,
                    {"mounts": [{"id": "gdrive", "name": "gdrive", "mountpoint": "/mnt/remote/gdrive",
                                 "mounted": False, "type": "rclone"}]},
                )
                return
            if path == "/api/storage/mounts/samba" and method == "GET":
                _json_fulfill(route, {"error": "Not a remote mount plugin"}, status=400)
                return
            if path == "/api/storage/mounts/sshfs" and method == "GET":
                _json_fulfill(
                    route,
                    {"error": "SSHFS helper offline", "message": "Reconnect helper and retry"},
                    status=503,
                )
                return
            if path == "/api/storage/mounts/rclone/gdrive/mount" and method == "POST":
                _json_fulfill(route, {"status": "mounted"})
                return
            if path == "/api/storage/mounts/rclone/gdrive/unmount" and method == "POST":
                _json_fulfill(route, {"status": "unmounted"})
                return
            if path == "/api/storage/mounts/rclone/gdrive" and method == "DELETE":
                _json_fulfill(route, {"status": "removed"})
                return
            if path == "/api/storage/mounts/rclone" and method == "POST":
                _json_fulfill(route, {"status": "created", "message": "Mount created"})
                return
            if path == "/api/storage/mounts/rclone/gdrive" and method == "PUT":
                _json_fulfill(route, {"status": "updated", "message": "Mount updated"})
                return
            if path == "/api/disks/startup-service/preview" and method == "GET":
                _json_fulfill(
                    route,
                    {
                        "script": {"path": "/usr/local/bin/x.sh", "current": "", "proposed": "#!/bin/sh\n", "exists": False, "changed": True},
                        "service": {"path": "/etc/systemd/system/x.service", "current": "", "proposed": "[Unit]\n", "exists": False, "changed": True},
                    },
                )
                return
            if path == "/api/disks/startup-service" and method == "POST":
                _json_fulfill(route, {"status": "applied"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_shares_api_mocks():
    """Returns a callable(page) installing deterministic shares mocks (samba plugin + shares)."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page, include_failed_provider: bool = False) -> None:
        plugins = [
            {"id": "samba", "name": "Samba", "description": "SMB shares", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "shares", "type": "builtin"},
            {"id": "mergerfs", "name": "MergerFS", "description": "pool", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "storage", "type": "builtin"},
        ]
        if include_failed_provider:
            plugins.append(
                {"id": "nfs", "name": "NFS", "description": "NFS shares", "version": "1.0",
                 "installed": True, "enabled": True, "configured": True, "status": "error",
                 "status_message": "Service unavailable", "category": "shares", "type": "builtin"}
            )
        shares_payload = {
            "shares": [{"name": "media", "path": "/mnt/storage/media", "enabled": True}],
            "service_running": True,
            "status": "ok",
            "message": "Samba running",
        }

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/storage/plugins" and method == "GET":
                _json_fulfill(route, {"plugins": plugins})
                return
            if path == "/api/storage/shares/samba" and method == "GET":
                _json_fulfill(route, shares_payload)
                return
            if path == "/api/storage/shares/nfs" and method == "GET":
                _json_fulfill(
                    route,
                    {"error": "NFS status unavailable", "message": "Check the NFS service"},
                    status=503,
                )
                return
            if path == "/api/storage/shares/samba" and method == "POST":
                _json_fulfill(route, {"status": "created", "message": "Share created"})
                return
            if path == "/api/storage/shares/samba/media/toggle" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return
            if path == "/api/storage/shares/samba/media" and method == "PUT":
                _json_fulfill(route, {"status": "updated", "message": "Share updated"})
                return
            if path == "/api/storage/shares/samba/media" and method == "DELETE":
                _json_fulfill(route, {"status": "deleted"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_settings_api_mocks():
    """Returns a callable(page) installing deterministic settings mocks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/pihealth/update/config" and method == "GET":
                _json_fulfill(route, {"repo_path": "/opt/pi-health", "service_name": "pi-health"})
                return
            if path == "/api/pihealth/update/config" and method == "POST":
                _json_fulfill(route, {"status": "saved", "config": {}})
                return
            if path == "/api/auth/check" and method == "GET":
                _json_fulfill(route, {"authenticated": True, "username": "admin", "csrf_token": "mock-csrf"})
                return
            if path == "/api/pihealth/update" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "operation_id": "mock-update-op",
                        "stream_url": "/api/pihealth/update/operations/mock-update-op/stream",
                    },
                    status=202,
                )
                return
            if path == "/api/pihealth/update/operations/mock-update-op/stream" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'id: 0\ndata: {"step":"pull","line":"Pulling latest code\\u2026"}\n\n'
                        'id: 1\ndata: {"step":"pull","line":"Already up to date (abc123de); no restart needed.",'
                        '"new_commit":"abc123def456","done":true}\n\n'
                    ),
                )
                return
            if path == "/api/backups/config" and method == "GET":
                _json_fulfill(route, {"enabled": True, "schedule_preset": "daily", "retention_count": 5, "dest_dir": "/mnt/backup/ph"})
                return
            if path == "/api/backups/config" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return
            if path == "/api/backups/status" and method == "GET":
                _json_fulfill(route, {"enabled": True, "next_run": "2026-06-27 04:00", "backup_running": False,
                                      "last_run": "2026-06-26 04:00", "last_run_result": "success"})
                return
            if path == "/api/backups/run" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return
            if path == "/api/backups/list" and method == "GET":
                _json_fulfill(route, {"backups": ["ph-backup-20260626.tar.gz"]})
                return
            if path == "/api/backups/restore" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return
            if path == "/api/auto-update/config" and method == "GET":
                _json_fulfill(route, {"enabled": True, "schedule_preset": "daily_4am", "notify_on_update": False})
                return
            if path == "/api/auto-update/config" and method == "POST":
                _json_fulfill(route, {"status": "updated", "config": {}})
                return
            if path == "/api/auto-update/run-now" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_extensions_api_mocks():
    """Install deterministic capability extension list and detail responses."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _status(provider_id, capability_id, surface, state="healthy", message="Ready"):
        return {
            "id": capability_id,
            "provider_id": provider_id,
            "surface": surface,
            "operational": state == "healthy",
            "status": {
                "schema_version": "1",
                "provider_id": provider_id,
                "capability_id": capability_id,
                "observed_at": "2026-07-17T20:00:00+00:00",
                "lifecycle": {
                    "installed": True,
                    "enabled": True,
                    "configured": True,
                    "compatibility": "compatible",
                    "availability": "available",
                },
                "health": {"state": state, "message": message, "issues": []},
                "summary": [],
                "metrics": [],
                "recent_activity": [],
                "details": {},
            },
        }

    mergerfs = {
        "id": "mergerfs",
        "name": "MergerFS",
        "description": "Combine filesystem branches into a storage pool.",
        "version": "2.40.2",
        "runtime_kind": "builtin-python",
        "source": "builtin",
        "installed": True,
        "enabled": True,
        "contract_state": "valid",
        "compatibility": "compatible",
        "health": {"state": "healthy", "message": "2 providers healthy.", "counts": {"healthy": 2}},
        "capabilities": [
            _status("mergerfs", "storage.pooling", "pools"),
            _status("mergerfs", "storage.protection", "protection", "warning", "Protection page is pending."),
        ],
    }
    mattermost = {
        "id": "mattermost",
        "name": "Mattermost",
        "description": "Private chat and incident collaboration.",
        "version": "1.0.0",
        "runtime_kind": "integration-adapter",
        "source": "builtin",
        "installed": True,
        "enabled": True,
        "contract_state": "valid",
        "compatibility": "compatible",
        "health": {"state": "warning", "message": "Provider health requires attention: warning.", "counts": {"warning": 1}},
        "capabilities": [
            _status("mattermost", "integration.chat", "integrations", "warning", "Delivery status is delayed."),
        ],
    }
    openpool = {
        "id": "openpool",
        "name": "OpenPool",
        "description": "Third-party pooling provider.",
        "version": "1.4.0",
        "runtime_kind": "github-python",
        "source": "owner/openpool",
        "installed": True,
        "enabled": False,
        "contract_state": "valid",
        "compatibility": "compatible",
        "health": {"state": "disabled", "message": "Provider is disabled.", "counts": {"disabled": 1}},
        "capabilities": [
            _status("openpool", "storage.pooling", "pools", "disabled", "Provider is disabled."),
        ],
    }
    diagnostic = {
        "code": "provider_status_unavailable",
        "provider_id": "mattermost",
        "message": "Provider status is unavailable.",
    }
    extensions = [mattermost, mergerfs, openpool]

    def _install(page: Page, fail: bool = False) -> None:
        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method
            if not path.startswith("/api/extensions"):
                route.continue_()
                return
            if fail and method == "GET":
                _json_fulfill(
                    route,
                    {"code": "capability_registry_unavailable", "error": "Capability registry is unavailable."},
                    status=503,
                )
                return
            if path == "/api/extensions/install" and method == "POST":
                values = route.request.post_data_json
                _json_fulfill(
                    route,
                    {
                        "status": "installed",
                        "id": values.get("id") or "installed-extension",
                        "restart_required": True,
                    },
                    status=201,
                )
                return
            if method == "POST":
                provider_id, action = path.rsplit("/", 2)[-2:]
                extension = next((item for item in extensions if item["id"] == provider_id), None)
                if extension is None:
                    _json_fulfill(route, {"code": "extension_not_found", "error": "Extension was not found."}, status=404)
                    return
                if action in {"enable", "disable"}:
                    extension["enabled"] = action == "enable"
                _json_fulfill(route, {"status": action, "id": provider_id, "restart_required": True})
                return
            if method == "DELETE":
                provider_id = path.rsplit("/", 1)[-1]
                extension = next((item for item in extensions if item["id"] == provider_id), None)
                if extension is None:
                    _json_fulfill(route, {"code": "extension_not_found", "error": "Extension was not found."}, status=404)
                    return
                if extension["enabled"]:
                    _json_fulfill(route, {"code": "extension_must_be_disabled", "error": "Disable the extension before removing it."}, status=409)
                    return
                extensions.remove(extension)
                _json_fulfill(route, {"status": "remove", "id": provider_id, "removed": True})
                return
            if method != "GET":
                route.continue_()
                return
            if path == "/api/extensions":
                _json_fulfill(route, {"schema_version": "1", "extensions": extensions, "errors": [diagnostic]})
                return
            provider_id = path.rsplit("/", 1)[-1]
            extension = next((item for item in extensions if item["id"] == provider_id), None)
            if extension is None:
                _json_fulfill(route, {"code": "extension_not_found", "error": "Extension was not found."}, status=404)
                return
            errors = [diagnostic] if provider_id == "mattermost" else []
            _json_fulfill(route, {"schema_version": "1", "extension": extension, "errors": errors})

        page.route("**/api/extensions**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_system_api_mocks():
    """Returns a callable(page) installing a deterministic /api/stats mock."""

    def _install(page: Page, overrides=None) -> None:
        stats = {
            "cpu_usage_percent": 12.5,
            "cpu_usage_per_core": [10.0, 15.0, 8.0, 17.0],
            "memory_usage": {"total": 8000000000, "used": 2000000000, "free": 6000000000, "percent": 25.0},
            "disk_usage": {"total": 500000000000, "used": 250000000000, "free": 250000000000, "percent": 50.0},
            "disk_usage_2": {"total": 1000000000000, "used": 100000000000, "free": 900000000000, "percent": 10.0},
            "temperature_celsius": 48.0,
            "network_usage": {"bytes_sent": 1234000, "bytes_recv": 5678000},
            "throttling": "ok",
            "cpu_freq_mhz": 1800,
            "is_raspberry_pi": True,
        }
        stats.update(overrides or {})

        def _handler(route):
            parsed = urlparse(route.request.url)
            if parsed.path == "/api/stats":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(stats))
                return
            if parsed.path == "/api/system/history":
                selected_range = parse_qs(parsed.query).get("range", ["24h"])[0]
                bucket_seconds = {"24h": 300, "7d": 1800, "30d": 7200}.get(selected_range, 300)
                history = {
                    "range": selected_range,
                    "from": "2026-07-14T12:00:00Z",
                    "to": "2026-07-15T12:00:00Z",
                    "bucket_seconds": bucket_seconds,
                    "points": [
                        {
                            "at": "2026-07-15T09:00:00Z",
                            "cpu_percent": 10.0,
                            "memory_percent": 20.0,
                            "temperature_celsius": 46.0,
                            "disk_percent": 49.0,
                        },
                        {
                            "at": "2026-07-15T09:05:00Z",
                            "cpu_percent": 12.5,
                            "memory_percent": 22.5,
                            "temperature_celsius": 47.0,
                            "disk_percent": 49.5,
                        },
                        {
                            "at": "2026-07-15T09:10:00Z",
                            "cpu_percent": None,
                            "memory_percent": None,
                            "temperature_celsius": None,
                            "disk_percent": None,
                        },
                        {
                            "at": "2026-07-15T09:15:00Z",
                            "cpu_percent": 15.0,
                            "memory_percent": 27.5,
                            "temperature_celsius": 49.0,
                            "disk_percent": 50.0,
                        },
                        {
                            "at": "2026-07-15T09:20:00Z",
                            "cpu_percent": 12.5,
                            "memory_percent": 25.0,
                            "temperature_celsius": 48.0,
                            "disk_percent": 50.0,
                        },
                    ],
                    "summary": {
                        "cpu_percent": {"current": 12.5, "min": 10.0, "average": 12.5, "max": 15.0},
                        "memory_percent": {"current": 25.0, "min": 20.0, "average": 23.75, "max": 27.5},
                        "temperature_celsius": {"current": 48.0, "min": 46.0, "average": 47.5, "max": 49.0},
                        "disk_percent": {"current": 50.0, "min": 49.0, "average": 49.625, "max": 50.0},
                    },
                }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(history))
                return
            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_catalog_api_mocks():
    """Returns a callable(page) installing deterministic /api/catalog* mocks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        items = [
            {"id": "jellyfin", "name": "Jellyfin", "description": "Media server", "requires": []},
            {"id": "sonarr", "name": "Sonarr", "description": "TV library", "requires": ["vpn"]},
            {"id": "vpn", "name": "VPN", "description": "Network provider", "requires": []},
        ]

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/catalog" and method == "GET":
                _json_fulfill(route, {"items": items})
                return
            if path == "/api/catalog/status" and method == "GET":
                _json_fulfill(
                    route,
                    {
                        "services": ["jellyfin", "vpn"],
                        "service_stacks": {
                            "jellyfin": ["family", "media"],
                            "vpn": ["media"],
                        },
                    },
                )
                return
            if path == "/api/stacks" and method == "GET":
                _json_fulfill(route, {"stacks": [{"name": "family"}, {"name": "media"}]})
                return
            if path == "/api/catalog/sonarr" and method == "GET":
                _json_fulfill(
                    route,
                    {"item": {"id": "sonarr", "fields": [{"key": "PORT", "label": "Web UI port", "default": "8989", "required": True}]}},
                )
                return
            if path == "/api/catalog/jellyfin" and method == "GET":
                _json_fulfill(route, {"item": {"id": "jellyfin", "fields": []}})
                return
            if path == "/api/catalog/install" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "status": "installed",
                        "operation_id": "mock-catalog-operation",
                        "stream_url": "/api/catalog/operations/mock-catalog-operation/stream",
                    },
                    status=202,
                )
                return
            if path == "/api/catalog/operations/mock-catalog-operation/stream" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body='id: 0\ndata: {"line":"creating"}\n\nid: 1\ndata: {"done":true,"returncode":0}\n\n',
                )
                return
            if path == "/api/catalog/remove" and method == "POST":
                _json_fulfill(route, {"status": "removed"})
                return
            if path == "/api/media/quickstart" and method == "POST":
                _json_fulfill(
                    route,
                    {
                        "operation_id": "mock-media-quickstart",
                        "stream_url": "/api/media/quickstart/operations/mock-media-quickstart/stream",
                    },
                    status=202,
                )
                return
            if path == "/api/media/quickstart/operations/mock-media-quickstart/stream" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'id: 0\ndata: {"step":"layout","line":"Provisioned media folders"}\n\n'
                        'id: 1\ndata: {"step":"install","line":"Installed Jellyfin"}\n\n'
                        'id: 2\ndata: {"step":"complete","line":"Media quickstart complete","done":true}\n\n'
                    ),
                )
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_integrations_api_mocks():
    """Install deterministic Mattermost and AI Agents integration mocks."""

    def _install(
        page: Page,
        *,
        installed: bool = True,
        install_error: bool = False,
        agent_installed: bool = True,
        agent_authenticated: bool = True,
        agent_configured: bool = True,
    ) -> None:
        state = {
            "installed": installed,
            "agent_installed": agent_installed and installed,
            "agent_authenticated": agent_authenticated and agent_installed and installed,
            "agent_configured": agent_configured and agent_installed and installed,
            "agent_enabled": agent_installed and installed,
            "policy": {
                "version": 1,
                "categories": {
                    "container": {"enabled": True},
                    "smart": {"enabled": True},
                    "mount": {"enabled": True},
                    "snapraid": {"enabled": True},
                },
                "required_mounts": ["/mnt/media"],
                "silences": [],
            },
        }

        def _payload():
            return {
                "state": "connected" if state["installed"] else "not_installed",
                "installed": state["installed"],
                "site_url": "http://mattermost.test:8065" if state["installed"] else None,
                "stack_name": "mattermost",
                "team": "limeos",
                "channel": "limeos-alerts",
                "webhook_configured": state["installed"],
                "policy": state["policy"],
                "resources": [
                    {
                        "key": "container:jellyfin",
                        "kind": "container",
                        "ok": True,
                        "severity": "warning",
                        "summary": "jellyfin is healthy",
                    },
                    {
                        "key": "smart:/dev/sda",
                        "kind": "smart",
                        "ok": True,
                        "severity": "critical",
                        "summary": "/dev/sda SMART OK",
                    },
                ],
                "incidents": [],
                "delivery": {"at": "2026-07-10T12:00:00Z", "ok": True},
                "updated_at": 1783684800,
            }

        def _handler(route):
            path = urlparse(route.request.url).path
            method = route.request.method
            if path == "/api/integrations/agents" and method == "GET":
                if not state["installed"]:
                    agent_state = "setup_required"
                elif not state["agent_installed"]:
                    agent_state = "not_installed"
                elif not state["agent_enabled"]:
                    agent_state = "disabled"
                elif not state["agent_authenticated"] or not state["agent_configured"]:
                    agent_state = "setup_required"
                else:
                    agent_state = "connected"
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "state": agent_state,
                            "installed": state["agent_installed"],
                            "enabled": state["agent_enabled"],
                            "configured": state["agent_configured"],
                            "mattermost": {
                                "state": "connected" if state["installed"] else "not_installed",
                                "site_url": (
                                    "http://mattermost.test:8065" if state["installed"] else None
                                ),
                                "team": "limeos" if state["installed"] else None,
                                "channel": "limeos-alerts" if state["installed"] else None,
                            },
                            "gateway": {
                                "state": "active" if agent_state == "connected" else "inactive",
                                "broker_state": (
                                    "active" if agent_state == "connected" else "inactive"
                                ),
                            },
                            "provider": {
                                "id": "claude",
                                "installed": state["agent_installed"],
                                "version": "2.1.205" if state["agent_installed"] else None,
                                "compatible": state["agent_installed"],
                                "authenticated": state["agent_authenticated"],
                            },
                            "last_successful_turn": (
                                {
                                    "at": "2026-07-12T21:14:00+00:00",
                                    "outcome": "ok",
                                    "rounds": 2,
                                }
                                if agent_state == "connected"
                                else None
                            ),
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/providers" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "providers": [
                                {
                                    "id": "claude",
                                    "name": "Claude Code",
                                    "installed": state["agent_installed"],
                                    "version": "2.1.205",
                                    "authenticated": state["agent_authenticated"],
                                    "compatible": True,
                                    "state": "connected",
                                }
                            ]
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/permissions" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "profile": "read_only",
                            "allowed_operations": [
                                "system.status",
                                "container.logs",
                                "stack.inspect",
                            ],
                            "resources": {
                                "container.logs": ["jellyfin", "limeos-mattermost"],
                                "stack.inspect": ["mattermost", "media"],
                            },
                            "denied_capabilities": [
                                "container.restart",
                                "file.read",
                                "shell.execute",
                            ],
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/usage" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "totals": {
                                "total_turns": 12,
                                "total_invocations": 29,
                                "invocations_today": 3,
                            },
                            "records": [
                                {
                                    "at": "2026-07-12T21:14:00+00:00",
                                    "conversation_id": "thread-1",
                                    "correlation_id": "turn-1",
                                    "outcome": "ok",
                                    "rounds": 2,
                                    "duration_seconds": 4.2,
                                    "tool_operations": ["system.status", "container.logs"],
                                }
                            ],
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/audit" and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "records": [
                                {
                                    "ts": "2026-07-12T21:13:59+00:00",
                                    "phase": "execute",
                                    "request_id": "request-1",
                                    "audit_id": "audit-1",
                                    "operation": "container.logs",
                                    "actor_type": "mattermost",
                                    "actor_id": "user-1",
                                    "actor_username": "holly",
                                    "ok": True,
                                    "duration_ms": 84,
                                    "output_bytes": 2048,
                                }
                            ]
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/install" and method == "POST":
                state["agent_installed"] = True
                state["agent_enabled"] = True
                state["agent_authenticated"] = False
                state["agent_configured"] = True
                route.fulfill(
                    status=202,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "operation_id": "mock-agent-install",
                            "stream_url": "/api/integrations/agents/operations/mock-agent-install/stream",
                        }
                    ),
                )
                return
            if path.endswith("/mock-agent-install/stream") and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'id: 0\ndata: {"step":"provider","line":"Installing Claude Code"}\n\n'
                        'id: 1\ndata: {"step":"runtime","line":"Preparing isolated agent runtime"}\n\n'
                        'id: 2\ndata: {"step":"complete","line":"AI Agents is installed and requires Claude authentication","requires_auth":true,"done":true}\n\n'
                    ),
                )
                return
            if path == "/api/integrations/agents/repair" and method == "POST":
                state["agent_enabled"] = True
                values = route.request.post_data_json or {}
                if values.get("admin_username") and values.get("admin_password"):
                    state["agent_configured"] = True
                route.fulfill(
                    status=202,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "operation_id": "mock-agent-repair",
                            "stream_url": "/api/integrations/agents/operations/mock-agent-repair/stream",
                        }
                    ),
                )
                return
            if path == "/api/integrations/agents/providers/claude/auth" and method == "POST":
                values = route.request.post_data_json or {}
                if values.get("action") == "start":
                    route.fulfill(
                        status=202,
                        content_type="application/json",
                        body=json.dumps(
                            {
                                "operation_id": "mock-agent-auth",
                                "stream_url": "/api/integrations/agents/operations/mock-agent-auth/stream",
                            }
                        ),
                    )
                elif values.get("action") == "submit":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"accepted": True}),
                    )
                else:
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"cancelled": True}),
                    )
                return
            if path.endswith("/mock-agent-auth/stream") and method == "GET":
                state["agent_authenticated"] = True
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'id: 0\ndata: {"step":"started","operation_id":"mock-provider-auth"}\n\n'
                        'id: 1\ndata: {"step":"authorize","authorization_url":"https://claude.ai/oauth/authorize?code=short-lived"}\n\n'
                        'id: 2\ndata: {"step":"complete","line":"Claude authentication completed","done":true}\n\n'
                    ),
                )
                return
            if path.endswith("/mock-agent-repair/stream") and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body='id: 0\ndata: {"step":"complete","line":"AI Agents repair completed","done":true}\n\n',
                )
                return
            if path == "/api/integrations/agents/disable" and method == "POST":
                state["agent_enabled"] = False
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"state": "disabled"}),
                )
                return
            if path == "/api/integrations/agents/test" and method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"status": "sent"}),
                )
                return
            if path == "/api/integrations/mattermost" and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(_payload()))
                return
            if path == "/api/integrations/mattermost/policy" and method == "PUT":
                state["policy"] = route.request.post_data_json
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"policy": state["policy"]}),
                )
                return
            if path == "/api/integrations/mattermost/test" and method == "POST":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"status": "sent", "at": "2026-07-10T12:01:00Z"}),
                )
                return
            if path == "/api/integrations/mattermost/install" and method == "POST":
                state["installed"] = not install_error
                route.fulfill(
                    status=202,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "operation_id": "mock-mattermost-install",
                            "stream_url": "/api/integrations/mattermost/operations/mock-mattermost-install/stream",
                        }
                    ),
                )
                return
            if path.endswith("/mock-mattermost-install/stream") and method == "GET":
                if install_error:
                    route.fulfill(
                        status=200,
                        content_type="text/event-stream",
                        body=(
                            'id: 0\ndata: {"step":"services","line":"Starting Postgres and Mattermost"}\n\n'
                            'id: 1\ndata: {"step":"error","error":"no matching ARM64 manifest"}\n\n'
                        ),
                    )
                    return
                route.fulfill(
                    status=200,
                    content_type="text/event-stream",
                    body=(
                        'id: 0\ndata: {"step":"services","line":"Starting Postgres and Mattermost"}\n\n'
                        'id: 1\ndata: {"step":"complete","line":"Mattermost and LimeOS alerts are ready","done":true}\n\n'
                    ),
                )
                return
            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_network_api_mocks():
    """Returns a callable(page) installing deterministic network mocks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        groups = {
            "docker_available": True,
            "groups": [
                {
                    "provider": "gluetun", "provider_status": "running", "provider_health": "healthy",
                    "members": ["sonarr", "radarr"], "member_count": 2, "orphaned_members": [], "status": "ok",
                }
            ],
            "orphans": [],
        }

        def _handler(route):
            parsed = urlparse(route.request.url)
            path = parsed.path
            method = route.request.method

            if path == "/api/network-groups" and method == "GET":
                _json_fulfill(route, groups)
                return
            if path == "/api/network-groups/gluetun/recreate" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return
            if path == "/api/network-test" and method == "POST":
                _json_fulfill(route, {"ping_success": True, "local_ip": "192.168.1.50",
                                      "public_ip": "203.0.113.20", "probe_method": "ping",
                                      "ping_output": "64 bytes from 8.8.8.8"})
                return
            if path == "/api/tailscale/status" and method == "GET":
                _json_fulfill(route, {"backend_state": "Running", "self_ip": "100.64.0.1"})
                return
            if path == "/api/tailscale/logout" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install
