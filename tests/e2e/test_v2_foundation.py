import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Server lifecycle, login, and deterministic /api mocks are shared via conftest.py
# fixtures (v2_server, v2_login, install_v2_containers_api_mocks).


def test_v2_shell_viewport_matrix(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    response = page.goto(f"{base_url}/v2")
    assert response is not None
    assert response.status == 200
    page.goto(f"{base_url}/login.html")
    v2_login(page, base_url)
    page.goto(f"{base_url}/v2")
    expect(page.locator("[data-testid='lime-os-brand']:visible")).to_be_visible()
    expect(page.get_by_role("heading", name="overview", exact=True)).to_be_visible()

    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 shell ({viewport_profile_name})")


def test_v2_lime_dashboard(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    loaded_scripts = []
    page.on(
        "request",
        lambda request: loaded_scripts.append(request.url)
        if request.resource_type == "script"
        else None,
    )

    overview = {
        "health": {"state": "healthy", "issues": []},
        "metrics": {
            "cpu_percent": 12.5,
            "memory_percent": 37.5,
            "memory_used": 3_221_225_472,
            "memory_total": 8_589_934_592,
            "temperature_celsius": 52.4,
            "disk_percent": 60.0,
            "disk_used": 659_706_976_665,
            "disk_total": 1_099_511_627_776,
        },
        "workloads": {
            "containers": {"total": 18, "running": 18, "unhealthy": 0, "stopped": 0},
            "stacks": {"total": 4, "healthy": 4, "partial": 0, "down": 0, "unknown": 0},
        },
        "alerts": {
            "active": [],
            "recent_recoveries": [
                {
                    "event": "recovery",
                    "key": "disk:archive",
                    "kind": "disk",
                    "severity": "warning",
                    "summary": "Archive disk recovered",
                    "at": "2026-07-15T10:00:00Z",
                }
            ],
        },
        "applications": [
            {
                "id": "jellyfin-1",
                "name": "jellyfin",
                "image": "jellyfin/jellyfin:latest",
                "status": "running",
                "port": 8096,
                "web_url": "https://media.example.test/jellyfin",
                "web_scheme": None,
            },
            {
                "id": "sonarr-1",
                "name": "sonarr",
                "image": "linuxserver/sonarr:latest",
                "status": "running",
                "port": 8989,
                "web_url": None,
                "web_scheme": None,
            },
            *[
                {
                    "id": f"service-{index}",
                    "name": name,
                    "image": f"limeos/{name}:latest",
                    "status": "running",
                    "port": 9000 + index,
                    "web_url": None,
                    "web_scheme": None,
                }
                for index, name in enumerate(
                    ["radarr", "lidarr", "jackett", "transmission", "nzbget", "audiobookshelf", "airsonic-advanced", "get_iplayer", "rtdclient", "prowlarr", "bazarr"]
                )
            ],
        ],
        "warnings": [],
        "collected_at": "2026-07-15T12:00:00Z",
    }

    page.route(
        "**/api/overview",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(overview)),
    )
    page.goto(f"{base_url}/login.html")
    v2_login(page, base_url)
    page.goto(f"{base_url}/v2")

    expect(page.get_by_role("heading", name="overview", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="All systems operational")).to_be_visible()
    expect(page.get_by_text("18 running", exact=True)).to_be_visible()
    expect(page.get_by_text("4 healthy", exact=True)).to_be_visible()
    expect(page.get_by_text("Archive disk recovered", exact=True)).to_be_visible()
    expect(page.get_by_text("Jellyfin", exact=True)).to_be_visible()
    expect(page.locator("a[href='https://media.example.test/jellyfin']")).to_be_visible()
    expect(page.get_by_text("Sonarr", exact=True)).to_be_visible()
    expect(page.get_by_text("12.5%", exact=True)).to_be_visible()
    expect(page.get_by_text("52.4 °C", exact=True)).to_be_visible()
    expect(page.get_by_text("Bazarr", exact=True)).to_have_count(0)
    page.get_by_role("button", name="show 1 more").click()
    expect(page.get_by_text("Bazarr", exact=True)).to_be_visible()

    auto_refresh = page.get_by_role("switch", name="Auto refresh")
    expect(auto_refresh).to_have_attribute("aria-checked", "false")
    expect(page.get_by_role("button", name="30s")).to_be_disabled()
    auto_refresh.click()
    expect(auto_refresh).to_have_attribute("aria-checked", "true")
    page.get_by_role("button", name="60s").click()
    expect(page.get_by_role("button", name="60s")).to_have_attribute("aria-pressed", "true")
    page.reload()
    expect(page.get_by_role("switch", name="Auto refresh")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_role("button", name="60s")).to_have_attribute("aria-pressed", "true")
    assert not any("performance-history" in url for url in loaded_scripts)
    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"Lime OS dashboard ({viewport_profile_name})")


def test_v2_mobile_drawer_keyboard_and_background_isolation(
    page: Page,
    v2_server,
    v2_login,
):
    base_url = v2_server["base_url"]
    page.set_viewport_size({"width": 390, "height": 844})
    v2_login(page, base_url)
    page.goto(f"{base_url}/v2")

    skip_link = page.get_by_role("link", name="Skip to main content")
    page.keyboard.press("Tab")
    expect(skip_link).to_be_focused()
    expect(skip_link).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator("#lime-os-main-content")).to_be_focused()

    menu_button = page.get_by_role("button", name="Open navigation")
    menu_button.click()
    drawer = page.locator("#lime-os-mobile-navigation")
    background = page.locator("#lime-os-app-background")
    expect(drawer).to_be_visible()
    expect(page.get_by_role("button", name="Close navigation")).to_be_focused()
    assert background.get_attribute("inert") is not None
    expect(background).to_have_attribute("aria-hidden", "true")
    assert page.evaluate("document.body.style.overflow") == "hidden"
    assert page.evaluate("document.body.style.overscrollBehavior") == "none"

    page.keyboard.press("Shift+Tab")
    assert drawer.evaluate("(node) => node.contains(document.activeElement)")
    page.keyboard.press("Tab")
    assert drawer.evaluate("(node) => node.contains(document.activeElement)")

    page.keyboard.press("Escape")
    expect(drawer).to_have_count(0)
    expect(menu_button).to_be_focused()
    assert background.get_attribute("inert") is None
    assert page.evaluate("document.body.style.overflow") == ""
    assert page.evaluate("document.body.style.overscrollBehavior") == ""


def test_legacy_container_url_redirects_to_v2(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_containers_api_mocks(page)
    page.goto(f"{base_url}/containers.html")

    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
    expect(page.locator("button[data-action='stop']:visible").first).to_be_visible()
    expect(page.locator("button[data-action='restart']:visible").first).to_be_visible()
    expect(page.locator("button[data-action='start']:visible")).to_have_count(0)
    if viewport_profile_name in ("phone", "tablet"):
        assert_no_horizontal_overflow(page, f"v2 containers ({viewport_profile_name})")


def test_v2_containers_diagnostics_workflow(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_containers_api_mocks(page)
    page.goto(f"{base_url}/v2/containers")

    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
    logs_button = page.locator("button[data-diagnostic-action='logs']:visible").first
    expect(logs_button).to_be_visible()

    logs_button.click()
    logs_modal = page.locator("#v2-logs-modal")
    expect(logs_modal).to_be_visible()
    expect(page.locator("#v2-logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    page.click("#v2-logs-modal-close")
    expect(page.locator("#v2-logs-modal")).to_have_count(0)

    page.locator("button[data-container-menu]:visible").first.click()
    action_menu = page.locator("[data-container-actions-menu]")
    expect(action_menu).to_be_visible()
    action_menu.locator("button[data-diagnostic-action='network-test']").click()
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
        assert_no_horizontal_overflow(page, f"v2 diagnostics workflow ({viewport_profile_name})")


def test_v2_containers_auth_guard(profiled_page: Page, v2_server, v2_login):
    page = profiled_page
    base_url = v2_server["base_url"]
    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/login.html")

    v2_login(page, base_url)
    page.goto(f"{base_url}/v2/containers")
    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()
