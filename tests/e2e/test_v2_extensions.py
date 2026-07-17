"""CP-007: Settings > Advanced extension inspection."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_extensions(page, base_url, v2_login, install_v2_extensions_api_mocks):
    v2_login(page, base_url)
    install_v2_extensions_api_mocks(page)
    page.goto(f"{base_url}/v2/settings/extensions")
    expect(page.get_by_role("heading", name="extensions")).to_be_visible()


def test_v2_extensions_grouped_list_across_viewports(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_extensions_api_mocks,
):
    page = profiled_page
    _open_extensions(page, v2_server["base_url"], v2_login, install_v2_extensions_api_mocks)

    expect(page.get_by_role("heading", name="Integration chat")).to_be_visible()
    expect(page.get_by_role("heading", name="Storage pooling")).to_be_visible()
    expect(page.locator("[data-extension-id='mattermost']")).to_contain_text("Mattermost")
    expect(page.locator("[data-extension-id='mergerfs']")).to_contain_text("2.40.2")
    expect(page.get_by_role("heading", name="Extension diagnostics")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 extensions ({viewport_profile_name})")


def test_v2_extension_details_link_to_owned_capabilities(
    page: Page,
    v2_server,
    v2_login,
    install_v2_extensions_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_extensions(page, base_url, v2_login, install_v2_extensions_api_mocks)

    page.click("[data-extension-id='mergerfs']")
    expect(page).to_have_url(f"{base_url}/v2/settings/extensions/mergerfs")
    expect(page.get_by_role("heading", name="MergerFS")).to_be_visible()
    expect(page.get_by_text("2.40.2", exact=True)).to_be_visible()
    expect(page.get_by_text("not reported", exact=True)).to_be_visible()
    expect(page.locator("[data-capability-id='storage.pooling']").get_by_role("link", name="Open")).to_have_attribute("href", "/v2/pools")
    expect(page.locator("[data-capability-id='storage.protection']")).to_contain_text("page not available yet")
    expect(page.get_by_role("button", name="Install")).to_have_count(0)
    expect(page.get_by_role("button", name="Remove")).to_have_count(0)


def test_v2_extensions_registry_failure_is_bounded(
    page: Page,
    v2_server,
    v2_login,
    install_v2_extensions_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_extensions_api_mocks(page, fail=True)
    page.goto(f"{base_url}/v2/settings/extensions")

    expect(page.get_by_role("alert")).to_contain_text("Extension registry is unavailable")
    expect(page.get_by_role("alert")).to_contain_text("Capability registry is unavailable.")
