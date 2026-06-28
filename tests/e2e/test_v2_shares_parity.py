"""PH3-008: v2 shares surface (share-capable plugins + share toggle/delete)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_shares(page, base_url, v2_login, install_v2_shares_api_mocks):
    v2_login(page, base_url)
    install_v2_shares_api_mocks(page)
    page.goto(f"{base_url}/v2/shares")
    expect(page.get_by_role("heading", name="network_shares")).to_be_visible()


def test_v2_shares_list(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_shares_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_shares(page, base_url, v2_login, install_v2_shares_api_mocks)

    # Samba is share-capable; mergerfs (storage) is filtered out.
    expect(page.get_by_text("Samba").first).to_be_visible()
    expect(page.get_by_text("media").first).to_be_visible()
    expect(page.get_by_role("heading", name="MergerFS")).to_have_count(0)
    assert_no_horizontal_overflow(page, f"v2 shares ({viewport_profile_name})")


def test_v2_shares_surfaces_partial_provider_failure(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_shares_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    v2_login(page, base_url)
    install_v2_shares_api_mocks(page, include_failed_provider=True)
    page.goto(f"{base_url}/v2/shares")

    expect(page.get_by_text("Samba").first).to_be_visible()
    expect(page.get_by_text("media").first).to_be_visible()
    expect(
        page.get_by_text(
            "NFS shares unavailable: NFS status unavailable: Check the NFS service"
        )
    ).to_be_visible()
    expect(page.get_by_text("partial data")).to_be_visible()
    expect(page.get_by_text("No share plugins configured.")).to_have_count(0)


def test_v2_shares_toggle_and_delete(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_shares_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_shares(page, base_url, v2_login, install_v2_shares_api_mocks)

    page.click("button[data-share-action='toggle'][data-share='media']")
    expect(page.get_by_text("Toggled media")).to_be_visible()

    page.click("button[data-delete-share='media']")
    page.click("button[data-confirm-delete-share='media']")
    expect(page.get_by_text("Deleted media")).to_be_visible()


def test_v2_shares_add_and_edit_share(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_shares_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_shares(page, base_url, v2_login, install_v2_shares_api_mocks)

    page.click("button[data-add-share='samba']")
    expect(page.locator("#v2-share-config-modal")).to_be_visible()
    page.fill("textarea[data-share-config-textarea]", '{"name": "backups", "path": "/mnt/storage/backups"}')
    page.click("#v2-share-config-save")
    expect(page.get_by_text("Share created")).to_be_visible()

    page.click("button[data-edit-share='media']")
    expect(page.locator("#v2-share-config-modal")).to_be_visible()
    page.click("#v2-share-config-save")
    expect(page.get_by_text("Share updated")).to_be_visible()
