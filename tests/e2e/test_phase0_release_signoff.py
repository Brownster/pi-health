import json
import os
import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError, Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")
MOCK_CONTAINER_ID = "signoff-container-1"


def _json_fulfill(route, payload, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _login(page: Page, username: str, password: str) -> None:
    page.goto(f"{BASE_URL}/login.html")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-button")
    expect(page).to_have_url(f"{BASE_URL}/")


def _install_containers_signoff_mocks(page: Page):
    state = {
        "status": "running",
        "actions": {"start": 0, "stop": 0, "restart": 0},
    }

    def _container_payload():
        return [
            {
                "id": MOCK_CONTAINER_ID,
                "name": "pihealth-signoff-service",
                "image": "linuxserver/mock:latest",
                "status": state["status"],
                "cpu_percent": 3.8 if state["status"] == "running" else None,
                "memory_percent": 11.4 if state["status"] == "running" else None,
                "memory_used": 240000000 if state["status"] == "running" else None,
                "memory_limit": 2048000000 if state["status"] == "running" else None,
                "net_rx": 1024000 if state["status"] == "running" else None,
                "net_tx": 2048000 if state["status"] == "running" else None,
                "ports": [{"container_port": 8080, "host_port": 18080, "protocol": "tcp"}],
                "update_available": False,
            }
        ]

    def _stats_payload():
        if state["status"] != "running":
            return {}
        return {
            MOCK_CONTAINER_ID: {
                "cpu_percent": 4.9,
                "memory_percent": 12.1,
                "memory_used": 252000000,
                "memory_limit": 2048000000,
                "net_rx": 2048000,
                "net_tx": 3072000,
            }
        }

    def _handler(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        method = route.request.method

        if path == "/api/containers" and method == "GET":
            _json_fulfill(route, _container_payload())
            return

        if path == "/api/containers/stats" and method == "GET":
            _json_fulfill(route, _stats_payload())
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/stop" and method == "POST":
            state["status"] = "stopped"
            state["actions"]["stop"] += 1
            _json_fulfill(route, {"ok": True})
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/start" and method == "POST":
            state["status"] = "running"
            state["actions"]["start"] += 1
            _json_fulfill(route, {"ok": True})
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/restart" and method == "POST":
            state["actions"]["restart"] += 1
            _json_fulfill(route, {"ok": True})
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/logs" and method == "GET":
            _json_fulfill(
                route,
                {"container": "pihealth-signoff-service", "logs": "signoff log output"},
            )
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/network-test" and method == "POST":
            _json_fulfill(
                route,
                {
                    "ping_success": True,
                    "local_ip": "192.168.1.51",
                    "public_ip": "203.0.113.11",
                    "probe_method": "ping",
                    "ping_output": "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=9ms",
                },
            )
            return

        route.continue_()

    page.route("**/api/**", _handler)
    return state


def _wait_for_signoff_container_row(page: Page) -> None:
    page.wait_for_function(
        """(containerId) => !!document.querySelector(
            `#container-list tr[data-container-id="${containerId}"]`
        )""",
        arg=MOCK_CONTAINER_ID,
        timeout=10000,
    )


def test_login_logout_and_session_guard(
    profiled_page: Page,
    viewport_profile_name: str,
    test_user_credentials,
):
    page = profiled_page
    creds = test_user_credentials

    _login(page, creds["username"], creds["password"])

    expect(page.locator("button:has-text('Logout'):visible").first).to_be_visible()
    page.locator("button:has-text('Logout'):visible").first.click()
    expect(page).to_have_url(f"{BASE_URL}/login.html")

    _login(page, creds["username"], creds["password"])
    page.evaluate("() => sessionStorage.removeItem('loggedIn')")
    page.context.clear_cookies()
    try:
        # The auth guard redirects to login mid-navigation, which can interrupt the
        # goto before it resolves. That redirect is exactly the behavior under test, so
        # tolerate the interruption and assert the final URL below.
        page.goto(f"{BASE_URL}/system.html", wait_until="commit")
    except PlaywrightError:
        pass
    expect(page).to_have_url(f"{BASE_URL}/login.html")


def test_mobile_nav_reachability_without_hover(
    authenticated_profiled_page: Page,
    viewport_profile_name: str,
):
    if viewport_profile_name == "desktop":
        pytest.skip("Mobile touch-nav validation targets phone/tablet profiles")

    page = authenticated_profiled_page
    page.goto(f"{BASE_URL}/")

    menu_toggle = page.locator("[data-nav-mobile-menu-toggle]")
    expect(menu_toggle).to_be_visible()
    menu_toggle.click()

    mobile_panel = page.locator("[data-nav-mobile-panel]")
    page.wait_for_function(
        """() => {
            const panel = document.querySelector('[data-nav-mobile-panel]');
            return !!panel && !panel.classList.contains('hidden');
        }""",
        timeout=5000,
    )

    apps_section_toggle = page.locator("[data-nav-mobile-section-toggle]", has_text="My Apps")
    expect(apps_section_toggle).to_be_visible()
    apps_section_toggle.click()

    containers_link = page.locator("[data-nav-mobile-target='/containers.html']")
    expect(containers_link).to_be_visible()
    containers_link.click()
    expect(page).to_have_url(f"{BASE_URL}/containers.html")


def test_containers_lifecycle_actions_signoff(authenticated_profiled_page: Page):
    page = authenticated_profiled_page
    state = _install_containers_signoff_mocks(page)

    page.goto(f"{BASE_URL}/containers.html")
    _wait_for_signoff_container_row(page)

    row = page.locator(f"tr[data-container-id='{MOCK_CONTAINER_ID}']").first
    expect(row).to_be_visible()
    expect(row.locator("[data-cell='status']")).to_contain_text("running")

    row.locator("button[data-action='stop']").click()
    expect(row.locator("[data-cell='status']")).to_contain_text("stopped")

    row.locator("button[data-action='start']").click()
    expect(row.locator("[data-cell='status']")).to_contain_text("running")

    row.locator("button[data-action='restart']").click()
    expect(row.locator("[data-cell='status']")).to_contain_text("running")

    row.locator("button[data-dropdown-toggle]").click()
    dropdown = row.locator(f"[data-dropdown-menu-for='{MOCK_CONTAINER_ID}']")
    expect(dropdown).not_to_have_class(re.compile(r".*hidden.*"))

    dropdown.locator("button:has-text('Logs')").click()
    expect(page.locator("#logs-modal")).not_to_have_class(re.compile(r".*hidden.*"))
    page.click("#logs-modal-close")

    row.locator("button[data-dropdown-toggle]").click()
    dropdown.locator("button:has-text('Network Test')").click()
    expect(page.locator("#container-network-modal")).not_to_have_class(re.compile(r".*hidden.*"))
    page.click("#container-network-close")

    assert state["actions"]["stop"] >= 1
    assert state["actions"]["start"] >= 1
    assert state["actions"]["restart"] >= 1


def test_shell_routes_no_horizontal_overflow_signoff(
    authenticated_profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
):
    if viewport_profile_name == "desktop":
        pytest.skip("Shell overflow signoff targets phone/tablet profiles")

    page = authenticated_profiled_page
    for route in ["/", "/system.html", "/disks.html", "/settings.html"]:
        page.goto(f"{BASE_URL}{route}")
        assert_no_horizontal_overflow(page, f"shell route {route} ({viewport_profile_name})")
