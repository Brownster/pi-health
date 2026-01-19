import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def test_mounts_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/mounts.html")

    expect(page).to_have_title("Mounts - Pi-Health Dashboard")
    expect(page.locator("h2")).to_contain_text("Mounts")
    expect(page.locator("h3:has-text('Media Paths')")).to_be_visible()
    expect(page.locator("#mount-plugins")).to_be_visible()


def test_media_paths_save_and_restore(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/mounts.html")

    media_paths_resp = page.request.get(f"{BASE_URL}/api/disks/media-paths")
    if not media_paths_resp.ok:
        pytest.skip("Media paths API unavailable")

    expect(page.locator("#path-downloads")).to_be_visible()

    original = {
        "downloads": page.locator("#path-downloads").input_value(),
        "storage": page.locator("#path-storage").input_value(),
        "backup": page.locator("#path-backup").input_value(),
        "config": page.locator("#path-config").input_value(),
    }

    updated = {
        "downloads": f"{original['downloads']}-e2e" if original["downloads"] else "/mnt/e2e-downloads",
        "storage": f"{original['storage']}-e2e" if original["storage"] else "/mnt/e2e-storage",
        "backup": f"{original['backup']}-e2e" if original["backup"] else "/mnt/e2e-backup",
        "config": f"{original['config']}-e2e" if original["config"] else "/mnt/e2e-config",
    }

    page.fill("#path-downloads", updated["downloads"])
    page.fill("#path-storage", updated["storage"])
    page.fill("#path-backup", updated["backup"])
    page.fill("#path-config", updated["config"])
    page.click("button:has-text('Save Paths')")

    expect(page.locator("#notification-area")).to_contain_text(
        "Media paths saved",
        timeout=5000
    )

    page.reload()
    expect(page.locator("#path-downloads")).to_have_value(updated["downloads"])
    expect(page.locator("#path-storage")).to_have_value(updated["storage"])
    expect(page.locator("#path-backup")).to_have_value(updated["backup"])
    expect(page.locator("#path-config")).to_have_value(updated["config"])

    page.fill("#path-downloads", original["downloads"])
    page.fill("#path-storage", original["storage"])
    page.fill("#path-backup", original["backup"])
    page.fill("#path-config", original["config"])
    page.click("button:has-text('Save Paths')")
    expect(page.locator("#notification-area")).to_contain_text(
        "Media paths saved",
        timeout=5000
    )


def test_startup_service_preview_modal(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/mounts.html")

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.click("button:has-text('Regenerate Startup Service...')")

    page.wait_for_function(
        """() => {
            const modal = document.getElementById('diff-modal');
            const notices = document.getElementById('notification-area');
            return (modal && !modal.classList.contains('hidden')) ||
                   (notices && notices.children.length > 0);
        }""",
        timeout=10000
    )

    diff_modal = page.locator("#diff-modal")
    if diff_modal.is_visible():
        expect(page.locator("#diff-content")).to_be_visible()
        page.click("#diff-modal button:has-text('Cancel')")
        expect(diff_modal).to_have_class(re.compile(r".*hidden.*"))
    else:
        page.wait_for_function(
            "() => document.getElementById('notification-area')?.children.length > 0",
            timeout=5000
        )


def test_mount_plugins_render_and_modal(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/mounts.html")

    page.wait_for_function(
        """() => {
            const container = document.getElementById('mount-plugins');
            if (!container) return false;
            return container.textContent.includes('No mount plugins enabled') ||
                   container.querySelectorAll('section').length > 0;
        }""",
        timeout=10000
    )

    no_plugins = page.locator("#mount-plugins:has-text('No mount plugins enabled')")
    plugin_sections = page.locator("#mount-plugins section")
    if no_plugins.is_visible():
        expect(no_plugins).to_be_visible()
        return

    expect(plugin_sections.first).to_be_visible()

    add_buttons = page.locator("#mount-plugins button:has-text('+ Add Mount')")
    if add_buttons.count() == 0:
        pytest.skip("No add mount buttons available")

    add_button = add_buttons.first
    if add_button.is_disabled():
        pytest.skip("Mount plugin is not installed")

    add_button.click()
    modal = page.locator("#mount-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)
    expect(page.locator("#mount-modal-form")).to_be_visible()
    page.click("#mount-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)
