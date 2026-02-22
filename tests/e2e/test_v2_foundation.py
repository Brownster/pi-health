import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

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


def test_mode_switch_for_containers_route(profiled_page: Page, mode_server):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    _login(page, base_url)
    page.goto(f"{base_url}/containers.html")

    if mode == "legacy":
        expect(page).to_have_url(f"{base_url}/containers.html")
        expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
        return

    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="Containers Pilot Placeholder")).to_be_visible()


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
    expect(page.get_by_role("heading", name="Containers Pilot Placeholder")).to_be_visible()
