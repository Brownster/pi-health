"""PH3-006: v2 storage plugins + pools tabbed surface.

Pinned to v2 UI mode; deterministic /api/storage/plugins* mocks (list, toggle,
detail, recovery 404, latest log, SSE command) keep the page reproducible.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_storage(page, base_url, route, v2_login, install_v2_storage_api_mocks):
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)
    page.goto(f"{base_url}/v2/{route}")
    expect(
        page.get_by_role("heading", name="storage_pools" if route == "pools" else "storage_plugins")
    ).to_be_visible()


def test_v2_storage_plugins_list_and_pools_tab(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Plugins tab shows both plugins.
    expect(page.get_by_text("MergerFS").first).to_be_visible()
    expect(page.get_by_text("Samba").first).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 storage plugins ({viewport_profile_name})")

    # Pools tab filters to pool-capable plugins (mergerfs), hiding samba.
    page.click("button[data-storage-tab='pools']")
    expect(page).to_have_url(f"{base_url}/v2/pools")
    expect(page.locator("button[data-storage-tab='pools']")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("button[data-storage-tab='plugins']")).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_text("MergerFS").first).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)


def test_v2_storage_pools_route_defaults_to_pools_tab(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "pools", v2_login, install_v2_storage_api_mocks)
    # /v2/pools opens with the Pools tab active -> only mergerfs.
    expect(page.locator("button[data-storage-tab='pools'][aria-pressed='true']")).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)
    # The pool-aware MergerFS card renders (unconfigured -> Set up CTA).
    expect(page.locator("[data-pool-plugin='mergerfs']")).to_be_visible()
    expect(
        page.locator("button[data-pool-action='setup'][data-plugin='mergerfs']")
    ).to_be_visible()


def test_v2_storage_tab_syncs_with_shell_nav(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)
    expect(page.locator("button[data-storage-tab='plugins'][aria-pressed='true']")).to_be_visible()

    # Client-side nav via the shell nav link must switch the active tab.
    page.get_by_role("link", name="Pools").click()
    expect(page).to_have_url(f"{base_url}/v2/pools")
    expect(page.locator("button[data-storage-tab='pools'][aria-pressed='true']")).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)


def test_v2_storage_remove_only_for_non_builtin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Builtin plugins cannot be removed (backend rejects it) -> no Remove control.
    expect(page.locator("button[data-plugin-action='remove'][data-plugin='mergerfs']")).to_have_count(0)
    expect(page.locator("button[data-plugin-action='remove'][data-plugin='samba']")).to_have_count(0)

    # A third-party (github) plugin can be removed, via confirm.
    page.click("button[data-plugin-action='remove'][data-plugin='customfs']")
    page.click("button[data-confirm-remove='customfs']")
    expect(page.get_by_text("Removed CustomFS")).to_be_visible(timeout=10000)


def test_v2_storage_toggle_plugin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='enable'][data-plugin='mergerfs']")
    expect(page.get_by_text("MergerFS enabled")).to_be_visible(timeout=10000)


def test_v2_storage_details_and_command(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='details'][data-plugin='mergerfs']")
    modal = page.locator("#v2-plugin-detail-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("Pool active")

    # Run a streamed plugin command (SSE over POST consumed via fetch reader).
    # `status` has no params and is not dangerous, so it runs on click.
    page.click("button[data-plugin-command='status']")
    expect(page.locator("#v2-plugin-command-output")).to_contain_text("checking pool mergerfs", timeout=10000)
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    page.click("#v2-plugin-detail-close")
    expect(page.locator("#v2-plugin-detail-modal")).to_have_count(0)


def test_v2_storage_config_editor(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='details'][data-plugin='mergerfs']")
    expect(page.locator("#v2-plugin-detail-modal")).to_be_visible()

    # Config editor is seeded with the plugin's JSON config and saves via /config.
    config_box = page.locator("#v2-plugin-config-textarea")
    expect(config_box).to_contain_text("mountpoint")
    config_box.fill('{"mountpoint": "/mnt/pool2"}')
    page.click("#v2-plugin-config-save")
    expect(page.locator("#v2-plugin-config-status")).to_have_text("Saved")


def test_v2_storage_install_plugin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("#v2-plugin-install-open")
    expect(page.locator("#v2-plugin-install-modal")).to_be_visible()
    page.fill("input[data-install-field='source']", "https://github.com/example/newfs")
    page.click("#v2-plugin-install-submit")
    expect(page.get_by_text("Plugin installed")).to_be_visible()
    expect(page.locator("#v2-plugin-install-modal")).to_have_count(0)
