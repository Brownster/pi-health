import os
import re
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = REPO_ROOT / "app.py"
V2_INDEX_PATH = REPO_ROOT / "static" / "v2" / "index.html"

USERNAME = os.getenv("PIHEALTH_USER", "admin")
PASSWORD = os.getenv("PIHEALTH_PASSWORD", "pihealth")

MODE_CONFIG = {
    "legacy": {},
    "hybrid": {"PIHEALTH_UI_V2_PAGES": "index,containers"},
    "v2": {},
}
V2_MOCK_CONTAINER_ID = "v2-mock-container-1"


def _find_open_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server_ready(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlrequest.urlopen(f"{base_url}/api/theme", timeout=1):
                return
        except (urlerror.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for app at {base_url}")


def _login(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/login.html")

    if "login.html" not in page.url:
        return

    page.fill("#username", USERNAME)
    page.fill("#password", PASSWORD)
    page.click("#login-button")
    page.wait_for_url(re.compile(rf"{re.escape(base_url)}/(v2/?|$)"), timeout=10000)


def _json_fulfill(route, payload, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _install_v2_containers_api_mocks(page: Page) -> None:
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
        }
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


@pytest.fixture(params=["legacy", "hybrid", "v2"], ids=lambda mode: f"mode_{mode}")
def ui_mode(request):
    return request.param


@pytest.fixture(scope="function")
def mode_server(ui_mode):
    if not APP_PATH.exists():
        pytest.skip(f"App entrypoint not found at {APP_PATH}")

    if not V2_INDEX_PATH.exists():
        pytest.skip("v2 assets missing. Run `npm --prefix frontend run build:publish` first.")

    port = _find_open_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.update(
        {
            "PORT": str(port),
            "PIHEALTH_USER": USERNAME,
            "PIHEALTH_PASSWORD": PASSWORD,
            "PIHEALTH_UI_MODE": ui_mode,
        }
    )
    env.pop("PIHEALTH_UI_V2_PAGES", None)
    env.update(MODE_CONFIG.get(ui_mode, {}))

    process = subprocess.Popen(
        [sys.executable, str(APP_PATH)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        _wait_for_server_ready(base_url)
        yield {
            "base_url": base_url,
            "mode": ui_mode,
        }
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_v2_shell_viewport_matrix(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    response = page.goto(f"{base_url}/v2")
    assert response is not None

    if mode == "legacy":
        assert response.status == 404
        assert "disabled in legacy mode" in page.text_content("body")
        return

    assert response.status == 200
    expect(page.get_by_role("heading", name="Pi-Health v2 Shell")).to_be_visible()

    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 shell ({mode}, {viewport_profile_name})")


def test_mode_switch_for_containers_route(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    _login(page, base_url)
    page.goto(f"{base_url}/containers.html")

    if mode == "legacy":
        expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
        if viewport_profile_name in ("phone", "tablet"):
            assert_no_horizontal_overflow(page, f"legacy containers ({viewport_profile_name})")
        return

    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
    expect(page.get_by_role("button", name="Start").first).to_be_visible()
    expect(page.get_by_role("button", name="Restart").first).to_be_visible()
    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 containers ({mode}, {viewport_profile_name})")


def test_v2_containers_diagnostics_workflow(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    if mode == "legacy":
        pytest.skip("legacy mode does not expose v2 containers diagnostics")

    _login(page, base_url)
    _install_v2_containers_api_mocks(page)
    page.goto(f"{base_url}/v2/containers")

    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
    logs_button = page.locator("button[data-diagnostic-action='logs']:visible").first
    network_button = page.locator("button[data-diagnostic-action='network-test']:visible").first
    expect(logs_button).to_be_visible()

    logs_button.click()
    logs_modal = page.locator("#v2-logs-modal")
    expect(logs_modal).to_be_visible()
    expect(page.locator("#v2-logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    page.click("#v2-logs-modal-close")
    expect(page.locator("#v2-logs-modal")).to_have_count(0)

    network_button.click()
    network_modal = page.locator("#v2-container-network-modal")
    expect(network_modal).to_be_visible()
    page.wait_for_function(
        """() => {
            const status = document.getElementById('v2-container-network-status');
            const output = document.getElementById('v2-container-network-output');
            if (!status || !output) return false;
            return !status.textContent.includes('Running') &&
                   !output.textContent.includes('Collecting');
        }""",
        timeout=15000,
    )
    page.click("#v2-container-network-modal-close")
    expect(page.locator("#v2-container-network-modal")).to_have_count(0)

    page.click("#v2-host-network-test-button")
    expect(page.locator("#v2-host-network-panel")).to_be_visible()
    page.wait_for_function(
        """() => {
            const status = document.getElementById('v2-host-network-status');
            const output = document.getElementById('v2-host-network-output');
            if (!status || !output) return false;
            return !status.textContent.includes('Running') &&
                   !output.textContent.includes('Running test');
        }""",
        timeout=15000,
    )

    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 diagnostics workflow ({mode}, {viewport_profile_name})")


def test_v2_containers_auth_guard(profiled_page: Page, mode_server):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    if mode == "legacy":
        pytest.skip("legacy mode disables /v2 routes")

    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/login.html")

    _login(page, base_url)
    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
