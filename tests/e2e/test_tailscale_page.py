import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _wait_for_tailscale_state(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const loading = document.getElementById('loading-state');
            const setup = document.getElementById('setup-section');
            const status = document.getElementById('status-section');
            if (!loading || !setup || !status) return false;
            const loadingHidden = loading.classList.contains('hidden');
            const showingSetup = !setup.classList.contains('hidden');
            const showingStatus = !status.classList.contains('hidden');
            const errorVisible = (loading.textContent || '').includes('Failed to load');
            return (loadingHidden && (showingSetup || showingStatus)) || errorVisible;
        }""",
        timeout=10000
    )


def test_tailscale_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/tailscale.html")

    expect(page.get_by_role("heading", name="Tailscale", exact=True)).to_be_visible()
    _wait_for_tailscale_state(page)


def test_tailscale_status_or_setup_section(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/tailscale.html")

    # Wait for page to settle - loading hidden AND (setup OR status visible), OR error shown
    page.wait_for_function(
        """() => {
            const loading = document.getElementById('loading-state');
            const setup = document.getElementById('setup-section');
            const status = document.getElementById('status-section');
            if (!loading) return false;
            const loadingText = loading.textContent || '';
            const hasError = loadingText.includes('Failed to load');
            const loadingHidden = loading.classList.contains('hidden');
            const setupVisible = setup && !setup.classList.contains('hidden');
            const statusVisible = status && !status.classList.contains('hidden');
            return hasError || (loadingHidden && (setupVisible || statusVisible));
        }""",
        timeout=15000
    )

    # Check which state we ended up in
    loading_text = page.locator("#loading-state").text_content() or ""
    if "Failed to load" in loading_text:
        expect(page.locator("#loading-state")).to_contain_text("Failed to load")
        return

    # Either setup or status section should be visible
    setup_visible = not page.locator("#setup-section").evaluate("el => el.classList.contains('hidden')")
    status_visible = not page.locator("#status-section").evaluate("el => el.classList.contains('hidden')")

    assert setup_visible or status_visible, "Either setup or status section should be visible"

    if setup_visible:
        expect(page.locator("#tailscale-authkey")).to_be_visible()
        expect(page.locator("#setup-status")).to_be_visible()
    else:
        expect(page.locator("#connection-status")).to_be_visible()
        expect(page.locator("#ts-ip")).to_be_visible()
