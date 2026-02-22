import os
import re
import json
import pytest
from urllib.parse import urlparse
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")
MOCK_CONTAINER_ID = "mock-container-1"


def _json_fulfill(route, payload, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _install_container_api_mocks(page: Page) -> None:
    container_payload = [
        {
            "id": MOCK_CONTAINER_ID,
            "name": "pihealth-mock-service",
            "image": "linuxserver/mock:latest",
            "status": "running",
            "cpu_percent": 4.2,
            "memory_percent": 12.3,
            "memory_used": 256000000,
            "memory_limit": 2048000000,
            "net_rx": 1024000,
            "net_tx": 2048000,
            "ports": [{"container_port": 8080, "host_port": 18080, "protocol": "tcp"}],
            "update_available": False,
        }
    ]

    stats_payload = {
        MOCK_CONTAINER_ID: {
            "cpu_percent": 5.1,
            "memory_percent": 13.2,
            "memory_used": 268000000,
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
            _json_fulfill(route, container_payload)
            return

        if path == "/api/containers/stats" and method == "GET":
            _json_fulfill(route, stats_payload)
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/logs" and method == "GET":
            _json_fulfill(
                route,
                {"container": "pihealth-mock-service", "logs": "line 1\nline 2\nline 3"},
            )
            return

        if path == f"/api/containers/{MOCK_CONTAINER_ID}/network-test" and method == "POST":
            _json_fulfill(
                route,
                {
                    "ping_success": True,
                    "local_ip": "192.168.1.50",
                    "public_ip": "203.0.113.10",
                    "probe_method": "ping",
                    "ping_output": "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=10ms",
                },
            )
            return

        route.continue_()

    page.route("**/api/**", _handler)


def _wait_for_container_list(page: Page) -> None:
    page.wait_for_function(
        """() => {
            return !!document.querySelector('#container-list tr[data-container-id]');
        }""",
        timeout=10000,
    )


def test_login_smoke_viewport_matrix(
    profiled_page: Page,
    test_user_credentials,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
):
    page = profiled_page
    creds = test_user_credentials
    page.goto(f"{BASE_URL}/login.html")

    assert_no_horizontal_overflow(page, f"login page ({viewport_profile_name})")

    page.fill("#username", creds["username"])
    page.fill("#password", creds["password"])
    page.click("#login-button")

    expect(page).to_have_url(f"{BASE_URL}/")
    assert_no_horizontal_overflow(page, f"home page after login ({viewport_profile_name})")


def test_system_page_viewport_matrix(
    authenticated_profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
):
    page = authenticated_profiled_page
    page.goto(f"{BASE_URL}/system.html")
    expect(page.get_by_role("heading", name="System Metrics")).to_be_visible()

    stats_resp = page.request.get(f"{BASE_URL}/api/stats")
    if not stats_resp.ok:
        page.wait_for_function(
            """() => {
                const state = document.getElementById('system-state');
                return state && !state.classList.contains('hidden');
            }""",
            timeout=10000,
        )
    else:
        page.wait_for_function(
            """() => {
                const cpu = document.getElementById('cpu-usage');
                return cpu && !(cpu.textContent || '').includes('Loading');
            }""",
            timeout=10000,
        )

    assert_no_horizontal_overflow(page, f"system page ({viewport_profile_name})")


def test_containers_actions_and_modals_viewport_matrix(
    authenticated_profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
):
    page = authenticated_profiled_page
    _install_container_api_mocks(page)

    page.goto(f"{BASE_URL}/containers.html")
    _wait_for_container_list(page)
    assert_no_horizontal_overflow(page, f"containers page ({viewport_profile_name})")

    row = page.locator(f"tr[data-container-id='{MOCK_CONTAINER_ID}']").first
    expect(row).to_be_visible()

    expect(row.locator("button[data-action='start']")).to_be_visible()
    expect(row.locator("button[data-action='stop']")).to_be_visible()
    expect(row.locator("button[data-action='restart']")).to_be_visible()

    container_id = row.get_attribute("data-container-id")
    assert container_id

    row.locator("button[data-dropdown-toggle]").click()
    dropdown = row.locator(f"[data-dropdown-menu-for='{container_id}']")
    expect(dropdown).not_to_have_class(re.compile(r".*hidden.*"))

    dropdown.locator("button:has-text('Logs')").click()
    logs_modal = page.locator("#logs-modal")
    expect(logs_modal).not_to_have_class(re.compile(r".*hidden.*"))
    expect(page.locator("#logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    page.click("#logs-modal-close")
    expect(logs_modal).to_have_class(re.compile(r".*hidden.*"))

    row.locator("button[data-dropdown-toggle]").click()
    expect(dropdown).not_to_have_class(re.compile(r".*hidden.*"))
    dropdown.locator("button:has-text('Network Test')").click()
    network_modal = page.locator("#container-network-modal")
    expect(network_modal).not_to_have_class(re.compile(r".*hidden.*"))
    page.wait_for_function(
        """() => {
            const status = document.getElementById('container-network-status');
            const output = document.getElementById('container-network-output');
            if (!status || !output) return false;
            return !status.textContent.includes('Running') &&
                   !output.textContent.includes('Collecting');
        }""",
        timeout=15000,
    )
    page.click("#container-network-close")
    expect(network_modal).to_have_class(re.compile(r".*hidden.*"))

    assert_no_horizontal_overflow(page, f"containers after modal workflow ({viewport_profile_name})")
