"""v2 Network page (nasOS redesign expansion)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_network(page, base_url, v2_login, install_v2_network_api_mocks):
    v2_login(page, base_url)
    install_v2_network_api_mocks(page)
    page.goto(f"{base_url}/v2/network")
    expect(page.get_by_role("heading", name="network", exact=True)).to_be_visible()


def test_v2_network_render(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_network_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_network(page, base_url, v2_login, install_v2_network_api_mocks)

    expect(page.get_by_text("gluetun").first).to_be_visible()
    expect(page.get_by_text("connected")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 network ({viewport_profile_name})")


def test_v2_network_host_test_and_recreate(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_network_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_network(page, base_url, v2_login, install_v2_network_api_mocks)

    page.click("#v2-host-network-run")
    expect(page.locator("#v2-host-network-result")).to_contain_text("reachable")
    expect(page.locator("#v2-host-network-result")).to_contain_text("203.0.113.20")

    page.click("button[data-recreate='gluetun']")
    page.click("button[data-confirm-recreate='gluetun']")
    expect(page.get_by_text("Recreated gluetun group")).to_be_visible()


def test_v2_network_tailscale_logout(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_network_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_network(page, base_url, v2_login, install_v2_network_api_mocks)

    page.click("#v2-tailscale-logout")
    page.click("#v2-tailscale-logout-confirm")
    expect(page.get_by_text("Tailscale logged out")).to_be_visible()
