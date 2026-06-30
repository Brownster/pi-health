"""PH3-007: v2 mounts surface (media paths + configured mounts)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks):
    v2_login(page, base_url)
    install_v2_mounts_api_mocks(page)
    page.goto(f"{base_url}/v2/mounts")
    expect(page.get_by_role("heading", name="mount_management")).to_be_visible()


def test_v2_mounts_media_paths_and_list(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks)

    expect(page.locator("input[data-media-path='downloads']")).to_have_value("/mnt/downloads")
    # rclone is a mount plugin (mounts listed); samba is not (400 -> skipped).
    expect(page.get_by_text("Rclone mounts")).to_be_visible()
    expect(page.get_by_text("gdrive").first).to_be_visible()
    expect(page.get_by_text("Samba mounts")).to_have_count(0)
    assert_no_horizontal_overflow(page, f"v2 mounts ({viewport_profile_name})")


def test_v2_mounts_surfaces_partial_provider_failure(
    page: Page,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_mounts_api_mocks(page, include_failed_provider=True)
    page.goto(f"{base_url}/v2/mounts")

    expect(page.get_by_text("Rclone mounts")).to_be_visible()
    expect(page.get_by_text("gdrive").first).to_be_visible()
    expect(
        page.get_by_text(
            "SSHFS mounts unavailable: SSHFS helper offline: Reconnect helper and retry"
        )
    ).to_be_visible()
    expect(page.get_by_text("partial data")).to_be_visible()
    expect(page.get_by_text("No remote/local mount plugins configured.")).to_have_count(0)


def test_v2_mounts_save_media_paths(
    page: Page,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks)

    page.fill("input[data-media-path='downloads']", "/mnt/dl")
    page.click("#v2-media-paths-save")
    expect(page.locator("#v2-media-paths-notice")).to_have_text("Media paths saved", timeout=10000)


def test_v2_mounts_mount_and_delete(
    page: Page,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks)

    page.click("button[data-mount-action='mount'][data-mount='gdrive']")
    expect(page.get_by_text("Mounted gdrive")).to_be_visible(timeout=10000)

    page.click("button[data-delete-mount='gdrive']")
    page.click("button[data-confirm-delete-mount='gdrive']")
    expect(page.get_by_text("Deleted gdrive")).to_be_visible(timeout=10000)


def test_v2_mounts_add_and_edit_mount(
    page: Page,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks)

    # Add mount via JSON config modal.
    page.click("button[data-add-mount='rclone']")
    expect(page.locator("#v2-mount-config-modal")).to_be_visible()
    page.fill("textarea[data-mount-config-textarea]", '{"name": "dropbox", "type": "rclone"}')
    page.click("#v2-mount-config-save")
    expect(page.get_by_text("Mount created")).to_be_visible()

    # Edit existing mount.
    page.click("button[data-edit-mount='gdrive']")
    expect(page.locator("#v2-mount-config-modal")).to_be_visible()
    page.click("#v2-mount-config-save")
    expect(page.get_by_text("Mount updated")).to_be_visible()


def test_v2_mounts_startup_service_preview_and_apply(
    page: Page,
    v2_server,
    v2_login,
    install_v2_mounts_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_mounts(page, base_url, v2_login, install_v2_mounts_api_mocks)

    page.click("#v2-startup-preview")
    expect(page.locator("#v2-startup-proposed")).to_be_visible()
    page.click("#v2-startup-apply")
    page.click("#v2-startup-apply-confirm")
    expect(page.get_by_text("Startup service applied")).to_be_visible()
