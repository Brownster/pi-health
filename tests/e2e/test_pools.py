import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def test_pools_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/pools.html")

    expect(page).to_have_title("Storage Pools - Pi-Health Dashboard")
    expect(page.locator("h2")).to_contain_text("Storage Pools")
    expect(page.locator("#pool-plugins")).to_be_visible()


def test_pool_plugins_render_and_config_modal(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/pools.html")

    page.wait_for_function(
        """() => {
            const container = document.getElementById('pool-plugins');
            if (!container) return false;
            return container.textContent.includes('No storage plugins enabled') ||
                   container.querySelectorAll('section').length > 0;
        }""",
        timeout=10000
    )

    no_plugins = page.locator("#pool-plugins:has-text('No storage plugins enabled')")
    plugin_sections = page.locator("#pool-plugins section")

    if no_plugins.is_visible():
        expect(no_plugins).to_be_visible()
        return

    expect(plugin_sections.first).to_be_visible()
    status_pills = plugin_sections.first.locator(".status-pill")
    expect(status_pills.first).to_be_visible()

    configure_button = plugin_sections.first.locator("button:has-text('Configure')")
    if configure_button.count() == 0:
        pytest.skip("No configure button available")

    configure_button.first.click()
    modal = page.locator("#config-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)
    expect(page.locator("#config-modal-form")).to_be_visible()

    page.click("#config-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_pool_plugin_command_modal_optional(authenticated_page: Page):
    if os.getenv("ALLOW_E2E_PLUGIN_COMMANDS") != "1":
        pytest.skip("Set ALLOW_E2E_PLUGIN_COMMANDS=1 to run plugin command tests")

    page = authenticated_page
    page.goto(f"{BASE_URL}/pools.html")

    page.wait_for_function(
        """() => {
            const container = document.getElementById('pool-plugins');
            if (!container) return false;
            return container.textContent.includes('No storage plugins enabled') ||
                   container.querySelectorAll('section').length > 0;
        }""",
        timeout=10000
    )

    command_button = page.locator("#pool-plugins section button.coraline-button").first
    if command_button.count() == 0:
        pytest.skip("No plugin command buttons available")

    command_button.click()
    output_modal = page.locator("#output-modal")
    expect(output_modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    page.click("#output-modal button:has-text('Close')")
    expect(output_modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)
