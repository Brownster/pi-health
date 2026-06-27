import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Server lifecycle, login, and deterministic /api mocks are shared via conftest.py
# fixtures (mode_server, ui_mode, v2_login, install_v2_containers_api_mocks).


def test_v2_shell_viewport_matrix(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
    v2_login,
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
    page.goto(f"{base_url}/login.html")
    v2_login(page, base_url)
    page.goto(f"{base_url}/v2")
    expect(page.locator("[data-testid='lime-os-brand']:visible")).to_be_visible()
    expect(page.get_by_role("heading", name="web_services")).to_be_visible()

    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 shell ({mode}, {viewport_profile_name})")


def test_v2_lime_dashboard(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]

    containers = [
        {
            "id": "jellyfin-1",
            "name": "jellyfin",
            "image": "jellyfin/jellyfin:latest",
            "status": "running",
            "ports": [{"host_port": 8096, "container_port": 8096, "protocol": "tcp"}],
        },
        {
            "id": "sonarr-1",
            "name": "sonarr",
            "image": "linuxserver/sonarr:latest",
            "status": "running",
            "ports": [{"host_port": 8989, "container_port": 8989, "protocol": "tcp"}],
        },
    ]
    stats = {
        "cpu_usage_percent": 12.5,
        "memory_usage": {"total": 8_589_934_592, "used": 3_221_225_472, "free": 5_368_709_120, "percent": 37.5},
        "disk_usage": {"total": 1_099_511_627_776, "used": 659_706_976_665, "free": 439_804_651_111, "percent": 60.0},
        "temperature_celsius": 52.4,
        "network_usage": {"bytes_recv": 1_000_000, "bytes_sent": 500_000},
    }

    page.route(
        "**/api/containers?stats=false",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(containers)),
    )
    page.route(
        "**/api/stats",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(stats)),
    )
    page.goto(f"{base_url}/login.html")
    v2_login(page, base_url)
    page.goto(f"{base_url}/v2")

    expect(page.get_by_role("heading", name="web_services")).to_be_visible()
    expect(page.get_by_text("2 up", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Jellyfin")).to_be_visible()
    expect(page.get_by_role("heading", name="Sonarr")).to_be_visible()
    expect(page.get_by_text("12.5%", exact=True)).to_be_visible()
    expect(page.get_by_text("52.4 °C", exact=True)).to_be_visible()
    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"Lime OS dashboard ({viewport_profile_name})")


def test_mode_switch_for_containers_route(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
    v2_login,
):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    v2_login(page, base_url)
    page.goto(f"{base_url}/containers.html")

    if mode == "legacy":
        expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
        if viewport_profile_name in ("phone", "tablet"):
            assert_no_horizontal_overflow(page, f"legacy containers ({viewport_profile_name})")
        return

    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
    expect(page.get_by_role("button", name="Start").first).to_be_visible()
    expect(page.get_by_role("button", name="Restart").first).to_be_visible()
    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 containers ({mode}, {viewport_profile_name})")


def test_v2_containers_diagnostics_workflow(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    mode_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    if mode == "legacy":
        pytest.skip("legacy mode does not expose v2 containers diagnostics")

    v2_login(page, base_url)
    install_v2_containers_api_mocks(page)
    page.goto(f"{base_url}/v2/containers")

    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
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


def test_v2_containers_auth_guard(profiled_page: Page, mode_server, v2_login):
    page = profiled_page
    base_url = mode_server["base_url"]
    mode = mode_server["mode"]

    if mode == "legacy":
        pytest.skip("legacy mode disables /v2 routes")

    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/login.html")

    v2_login(page, base_url)
    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
