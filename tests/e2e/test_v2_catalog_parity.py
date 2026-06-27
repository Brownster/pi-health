"""v2 App Catalog page (nasOS redesign expansion)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks):
    v2_login(page, base_url)
    install_v2_catalog_api_mocks(page)
    page.goto(f"{base_url}/v2/apps")
    expect(page.get_by_role("heading", name="app_catalog", exact=True)).to_be_visible()


def test_v2_catalog_render(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    expect(page.get_by_text("Jellyfin").first).to_be_visible()
    expect(page.get_by_text("installed").first).to_be_visible()
    expect(page.get_by_text("requires: vpn")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 catalog ({viewport_profile_name})")


def test_v2_catalog_install_with_fields(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='install'][data-item='sonarr']")
    expect(page.locator("#v2-catalog-install-modal")).to_be_visible()
    expect(page.locator("input[data-install-field='PORT']")).to_have_value("8989")
    page.click("#v2-catalog-install-submit")
    expect(page.get_by_text("Installed Sonarr")).to_be_visible()


def test_v2_catalog_remove_with_confirm(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='remove'][data-item='jellyfin']")
    page.click("button[data-confirm-remove='jellyfin']")
    expect(page.get_by_text("Removed Jellyfin")).to_be_visible()
