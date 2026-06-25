"""PH3-004: v2 disks parity suite (read path + SMART views).

Pinned to v2 UI mode; deterministic /api/disks* mocks (inventory, helper status,
SMART summary + per-device SMART) keep the page reproducible without the
privileged helper or a real disk.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks):
    v2_login(page, base_url)
    install_v2_disks_api_mocks(page)
    page.goto(f"{base_url}/v2/disks")
    expect(page.get_by_role("heading", name="Disks")).to_be_visible()


def test_v2_disks_inventory_renders(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    expect(page.get_by_text("/dev/sda").first).to_be_visible()
    expect(page.get_by_text("/mnt/storage").first).to_be_visible()
    # SMART summary badge merged onto the disk card.
    expect(page.get_by_text("healthy").first).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 disks ({viewport_profile_name})")


def test_v2_disks_smart_modal(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    page.locator("button[data-disk-action='smart'][data-disk='sda']:visible").first.click()
    modal = page.locator("#v2-disk-smart-modal")
    expect(modal).to_be_visible()
    expect(page.locator("#v2-disk-smart-content")).to_contain_text("38 °C")
    expect(page.locator("#v2-disk-smart-content")).to_contain_text("1234")
    page.click("#v2-disk-smart-close")
    expect(page.locator("#v2-disk-smart-modal")).to_have_count(0)
