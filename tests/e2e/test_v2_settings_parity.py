"""PH3-009: v2 settings (Pi-Health self-update, backups, auto-update)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_settings(page, base_url, v2_login, install_v2_settings_api_mocks):
    v2_login(page, base_url)
    install_v2_settings_api_mocks(page)
    page.goto(f"{base_url}/v2/settings")
    expect(page.get_by_role("heading", name="system_settings")).to_be_visible()


def test_v2_settings_render(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_settings_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_settings(page, base_url, v2_login, install_v2_settings_api_mocks)

    expect(page.locator("input[data-setting='pihealth-repo']")).to_have_value("/opt/pi-health")
    expect(page.locator("#v2-settings-backups")).to_be_visible()
    expect(page.locator("#v2-settings-auto-update")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 settings ({viewport_profile_name})")


def test_v2_settings_pihealth_update_with_confirm(
    page: Page,
    v2_server,
    v2_login,
    install_v2_settings_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_settings(page, base_url, v2_login, install_v2_settings_api_mocks)

    page.click("#v2-settings-pihealth-update")
    page.click("#v2-settings-pihealth-update-confirm")
    progress = page.get_by_test_id("pihealth-update-progress")
    expect(progress).to_be_visible()
    expect(progress).to_contain_text("Pulling latest code")
    expect(progress).to_contain_text("Update complete")
    expect(progress).to_contain_text("abc123de")


def test_v2_settings_backup_save_and_restore(
    page: Page,
    v2_server,
    v2_login,
    install_v2_settings_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_settings(page, base_url, v2_login, install_v2_settings_api_mocks)

    page.click("#v2-settings-backup-save")
    expect(page.get_by_text("Backup config saved")).to_be_visible()

    archive = "ph-backup-20260626.tar.gz"
    page.click(f"button[data-restore='{archive}']")
    page.click(f"button[data-confirm-restore='{archive}']")
    expect(page.get_by_text(f"Restored {archive}")).to_be_visible()


def test_v2_settings_auto_update_save(
    page: Page,
    v2_server,
    v2_login,
    install_v2_settings_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_settings(page, base_url, v2_login, install_v2_settings_api_mocks)

    page.click("#v2-settings-auto-update-save")
    expect(page.get_by_text("Auto-update config saved")).to_be_visible()
