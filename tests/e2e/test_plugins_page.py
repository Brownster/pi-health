import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _load_plugins(page: Page):
    resp = page.request.get(f"{BASE_URL}/api/storage/plugins")
    if not resp.ok:
        pytest.skip("Plugins API unavailable")
    plugins = resp.json().get("plugins", [])
    if not plugins:
        pytest.skip("No plugins available")
    return plugins


def _wait_for_plugins(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const list = document.getElementById('plugins-list');
            if (!list) return false;
            const text = list.textContent || '';
            return !text.includes('Loading plugins');
        }""",
        timeout=10000
    )


def test_plugins_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/plugins.html")

    expect(page.get_by_role("heading", name="Plugins")).to_be_visible()
    _wait_for_plugins(page)
    expect(page.locator("#plugins-list")).to_be_visible()


def test_plugins_install_modal_toggles(authenticated_page: Page):
    page = authenticated_page
    _load_plugins(page)

    page.goto(f"{BASE_URL}/plugins.html")
    _wait_for_plugins(page)

    page.click("button:has-text('+ Add Plugin')")
    modal = page.locator("#install-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"))

    # Default: GitHub
    expect(page.locator("#plugin-id-field")).to_be_visible()
    expect(page.locator("#pip-fields")).to_have_class(re.compile(r".*hidden.*"))

    # Switch to pip to show fields
    page.select_option("#install-form select[name='type']", "pip")
    expect(page.locator("#pip-fields")).not_to_have_class(re.compile(r".*hidden.*"))
    expect(page.locator("#install-form input[name='entry']")).to_be_visible()
    expect(page.locator("#install-form input[name='class_name']")).to_be_visible()

    # Close modal
    page.click("#install-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"))


def test_plugins_list_renders_cards(authenticated_page: Page):
    page = authenticated_page
    plugins = _load_plugins(page)
    plugin = plugins[0]

    page.goto(f"{BASE_URL}/plugins.html")
    _wait_for_plugins(page)

    card = page.locator("div.bg-gray-800", has=page.locator("h4", has_text=plugin["name"])).first
    expect(card).to_be_visible(timeout=10000)
    expect(card.locator(".status-pill")).to_be_visible()
    expect(card.locator(".toggle-slider")).to_be_visible()
