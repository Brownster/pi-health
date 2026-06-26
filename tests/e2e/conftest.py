import pytest
import docker
import json
import re
import socket
import subprocess
import sys
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
PASSWORD = os.getenv('PIHEALTH_PASSWORD', 'pihealth')
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

@pytest.fixture(scope="function")
def authenticated_page(page: Page):
    """
    Returns a Page object that is already logged in.
    """
    # Go to the login page
    page.goto(f"{BASE_URL}/login.html")
    
    # Check if we are already redirected to home (if session persisted, though scope is function/new context usually)
    if "login.html" in page.url:
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("#login-button")
        
        # Expect to be redirected to the home page
        expect(page).to_have_url(f"{BASE_URL}/")
    
    return page

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

@pytest.fixture(scope='function')
def authenticated_profiled_page(profiled_page: Page):
    page = profiled_page
    page.goto(f"{BASE_URL}/login.html")

    if "login.html" in page.url:
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("#login-button")
        expect(page).to_have_url(f"{BASE_URL}/")

    return page

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

@pytest.fixture(scope="session")
def docker_client():
    """Returns a docker client."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.skip(f"Docker not available: {e}")

@pytest.fixture(scope="function")
def test_container(docker_client):
    """
    Creates a temporary container for testing purposes.
    Returns the container object.
    Teardown removes the container.
    """
    container_name = "pihealth-e2e-test-container"
    
    # Cleanup if it already exists
    try:
        old = docker_client.containers.get(container_name)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    # Run a simple container that stays alive (alpine sleep)
    print(f"Starting test container: {container_name}")
    container = docker_client.containers.run(
        "alpine:latest",
        "sleep 300",
        name=container_name,
        detach=True
    )
    
    # Wait a moment for it to be fully registered/up
    time.sleep(2)
    
    yield container
    
    # Teardown
    print(f"Removing test container: {container_name}")
    try:
        container.remove(force=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shared v2 (React) UI e2e scaffolding
#
# Reusable across the v2 foundation suite and the containers parity suite:
# per-mode app server lifecycle, login helper, and deterministic /api mocks.
# ---------------------------------------------------------------------------

V2_REPO_ROOT = Path(__file__).resolve().parents[2]
V2_APP_PATH = V2_REPO_ROOT / "app.py"
V2_INDEX_PATH = V2_REPO_ROOT / "static" / "v2" / "index.html"

V2_MODE_CONFIG = {
    "legacy": {},
    "hybrid": {"PIHEALTH_UI_V2_PAGES": "index,containers"},
    "v2": {},
}
V2_MOCK_CONTAINER_ID = "v2-mock-container-1"


def _v2_find_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _v2_wait_for_server_ready(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(f"{base_url}/api/theme", timeout=1):
                return
        except (urlerror.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for app at {base_url}")


def _v2_spawn(mode: str, v2_pages: str | None = None):
    """Spawn app.py in the given UI mode. Returns (process, base_url)."""
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
            "PIHEALTH_PASSWORD": PASSWORD,
            "PIHEALTH_UI_MODE": mode,
        }
    )
    env.pop("PIHEALTH_UI_V2_PAGES", None)
    env.update(V2_MODE_CONFIG.get(mode, {}))
    if v2_pages is not None:
        if v2_pages:
            env["PIHEALTH_UI_V2_PAGES"] = v2_pages
        else:
            env.pop("PIHEALTH_UI_V2_PAGES", None)

    process = subprocess.Popen(
        [sys.executable, str(V2_APP_PATH)],
        cwd=str(V2_REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    return process, base_url


def _v2_teardown(process) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture(params=["legacy", "hybrid", "v2"], ids=lambda mode: f"mode_{mode}")
def ui_mode(request):
    return request.param


@pytest.fixture(scope="function")
def mode_server(ui_mode):
    """App server parametrized across legacy/hybrid/v2 UI modes."""
    process, base_url = _v2_spawn(ui_mode)
    try:
        _v2_wait_for_server_ready(base_url)
        yield {"base_url": base_url, "mode": ui_mode}
    finally:
        _v2_teardown(process)


@pytest.fixture(scope="function")
def v2_mode_server():
    """App server pinned to v2 UI mode (for v2-only parity coverage)."""
    process, base_url = _v2_spawn("v2")
    try:
        _v2_wait_for_server_ready(base_url)
        yield {"base_url": base_url, "mode": "v2"}
    finally:
        _v2_teardown(process)


@pytest.fixture(scope="function")
def v2_server_factory():
    """Start one or more app.py instances with explicit v2 rollout settings."""
    processes = []

    def _start(mode: str, v2_pages: str | None = None):
        process, base_url = _v2_spawn(mode, v2_pages=v2_pages)
        processes.append(process)
        _v2_wait_for_server_ready(base_url)
        return {"base_url": base_url, "mode": mode, "v2_pages": v2_pages}

    try:
        yield _start
    finally:
        for process in reversed(processes):
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

            # Streaming lifecycle output (EventSource / SSE).
            if path.startswith("/api/stacks/media/") and path.endswith("/stream") and method == "GET":
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

            # Non-streaming lifecycle fallback.
            if path.startswith("/api/stacks/media/") and method == "POST":
                action = path.rsplit("/", 1)[-1]
                if action in {"up", "down", "restart", "pull"}:
                    _json_fulfill(route, {"success": True, "stdout": "done", "stderr": "", "returncode": 0})
                    return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_disks_api_mocks():
    """Returns a callable(page) installing deterministic /api/disks* mocks for v2 disks."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
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
                "status": "disabled", "status_message": "Disabled", "category": "storage", "type": "builtin",
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
            "schema": {}, "config": {}, "install_instructions": "",
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
            if path.startswith("/api/storage/plugins/") and path.endswith("/toggle") and method == "POST":
                _json_fulfill(route, {"status": "ok", "enabled": True})
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

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_mounts_api_mocks():
    """Returns a callable(page) installing deterministic mounts mocks (media paths + mount plugin)."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
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
            if path == "/api/storage/mounts/rclone/gdrive/mount" and method == "POST":
                _json_fulfill(route, {"status": "mounted"})
                return
            if path == "/api/storage/mounts/rclone/gdrive/unmount" and method == "POST":
                _json_fulfill(route, {"status": "unmounted"})
                return
            if path == "/api/storage/mounts/rclone/gdrive" and method == "DELETE":
                _json_fulfill(route, {"status": "removed"})
                return

            route.continue_()

        page.route("**/api/**", _handler)

    return _install


@pytest.fixture(scope="function")
def install_v2_shares_api_mocks():
    """Returns a callable(page) installing deterministic shares mocks (samba plugin + shares)."""

    def _json_fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def _install(page: Page) -> None:
        plugins = [
            {"id": "samba", "name": "Samba", "description": "SMB shares", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "shares", "type": "builtin"},
            {"id": "mergerfs", "name": "MergerFS", "description": "pool", "version": "1.0",
             "installed": True, "enabled": True, "configured": True, "status": "active",
             "status_message": "", "category": "storage", "type": "builtin"},
        ]
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
            if path == "/api/storage/shares/samba/media/toggle" and method == "POST":
                _json_fulfill(route, {"status": "ok"})
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
            if path == "/api/pihealth/update" and method == "POST":
                _json_fulfill(route, {"status": "updating"})
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
