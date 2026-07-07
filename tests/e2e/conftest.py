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
from urllib.parse import urlparse
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
            "commands": [{"id": "status", "label": "Pool Status", "params": []}],
            "schema": {"properties": {"mountpoint": {"type": "string", "description": "Pool mount point"}}},
            "config": {"mountpoint": "/mnt/pool"},
            "install_instructions": "",
        }
        snapraid_detail = {
            "id": "snapraid", "name": "SnapRAID", "description": "Parity protection",
            "version": "1.0", "installed": True, "kind": "pool",
            "status": {"status": "unconfigured", "message": "No drives", "details": {"sync_required": False}},
            "commands": [
                {"id": "sync", "name": "Sync", "dangerous": False},
                {"id": "scrub", "name": "Scrub", "dangerous": False,
                 "param_schema": [{"name": "percent", "type": "number", "default": 8}]},
                {"id": "fix", "name": "Fix", "dangerous": True},
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
            if path == "/api/storage/plugins/mergerfs" and method == "GET":
                _json_fulfill(route, mergerfs_detail)
                return
            if path == "/api/storage/plugins/snapraid" and method == "GET":
                _json_fulfill(route, snapraid_detail)
                return
            if path == "/api/storage/plugins/snapraid/config-preview" and method == "POST":
                _json_fulfill(route, {"preview": "parity /mnt/parity/snapraid.parity\ndata d1 /mnt/disk1/\n"})
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
            if path == "/api/storage/plugins/mergerfs/commands/status" and method == "POST":
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
            if urlparse(route.request.url).path == "/api/stats":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(stats))
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
