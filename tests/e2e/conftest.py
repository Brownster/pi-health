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
