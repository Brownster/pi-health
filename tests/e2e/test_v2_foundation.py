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
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()
