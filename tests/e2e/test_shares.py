import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _load_share_plugins(page: Page):
    resp = page.request.get(f"{BASE_URL}/api/storage/plugins")
    if not resp.ok:
        pytest.skip("Storage plugins API unavailable")
    plugins = resp.json().get("plugins", [])
    share_plugins = [p for p in plugins if p.get("category") == "share" and p.get("enabled")]
    if not share_plugins:
        pytest.skip("No enabled share plugins")
    return share_plugins


def _wait_for_shares_content(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const loading = document.getElementById('loading-state');
            const content = document.getElementById('shares-content');
            if (!loading || !content) return false;
            if (loading.classList.contains('hidden')) return true;
            return content.textContent.includes('No share plugins enabled') ||
                   content.querySelectorAll('section').length > 0;
        }""",
        timeout=10000
    )


def test_shares_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/shares.html")

    expect(page).to_have_title("Shares - Pi-Health Dashboard")
    expect(page.locator("h2")).to_contain_text("Shares")
    _wait_for_shares_content(page)
    expect(page.locator("#shares-content")).to_be_visible()


def test_shares_plugin_render_and_modal(authenticated_page: Page):
    page = authenticated_page
    share_plugins = _load_share_plugins(page)
    plugin = share_plugins[0]

    page.goto(f"{BASE_URL}/shares.html")
    _wait_for_shares_content(page)

    section = page.locator("section", has=page.locator("h3", has_text=plugin["name"])).first
    expect(section).to_be_visible(timeout=10000)

    add_button = section.locator("button:has-text('+ Add Share')")
    expect(add_button).to_be_visible()

    if not plugin.get("installed"):
        expect(add_button).to_be_disabled()
        expect(section.locator("code")).to_be_visible()
        pytest.skip("Share plugin not installed; skipping modal interactions")

    add_button.click()
    modal = page.locator("#share-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)
    expect(page.locator("#modal-title")).to_have_text("Add Share")
    expect(page.locator("#share-name")).to_be_visible()
    expect(page.locator("#share-path")).to_be_visible()
    page.click("#share-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    shares_resp = page.request.get(f"{BASE_URL}/api/storage/shares/{plugin['id']}")
    if not shares_resp.ok:
        pytest.skip("Shares API unavailable")

    shares = shares_resp.json().get("shares", [])
    if not shares:
        expect(section).to_contain_text("No shares configured")
        return

    share = shares[0]
    edit_button = section.locator("button:has-text('Edit')").first
    edit_button.click()
    expect(page.locator("#modal-title")).to_have_text("Edit Share")
    name_field = page.locator("#share-name")
    expect(name_field).to_be_disabled()
    if share.get("name"):
        expect(name_field).to_have_value(share["name"])
    page.click("#share-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_shares_delete_confirmation_dismiss(authenticated_page: Page):
    page = authenticated_page
    share_plugins = _load_share_plugins(page)
    plugin = share_plugins[0]

    page.goto(f"{BASE_URL}/shares.html")
    _wait_for_shares_content(page)

    shares_resp = page.request.get(f"{BASE_URL}/api/storage/shares/{plugin['id']}")
    if not shares_resp.ok:
        pytest.skip("Shares API unavailable")

    shares = shares_resp.json().get("shares", [])
    if not shares:
        pytest.skip("No shares configured")

    dialog_text = {"value": ""}

    def handle_dialog(dialog):
        dialog_text["value"] = dialog.message
        dialog.dismiss()

    page.once("dialog", handle_dialog)
    page.locator("button:has-text('Delete')").first.click()

    assert "Delete share" in dialog_text["value"]
