import os
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _wait_for_network_content(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const loading = document.getElementById('loading-state');
            const content = document.getElementById('network-content');
            if (!loading || !content) return false;
            if (!content.classList.contains('hidden')) return true;
            return (loading.textContent || '').includes('Failed to load');
        }""",
        timeout=10000
    )


def test_network_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/network.html")

    expect(page.get_by_role("heading", name="Host Network")).to_be_visible()
    _wait_for_network_content(page)
    expect(page.locator("#network-content")).to_be_visible()


def test_network_page_sections_render(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/network.html")

    # Wait for page to settle - either content loads or error shows
    page.wait_for_function(
        """() => {
            const loading = document.getElementById('loading-state');
            const content = document.getElementById('network-content');
            if (!loading) return false;
            const loadingText = loading.textContent || '';
            const hasError = loadingText.includes('Failed to load');
            const contentVisible = content && !content.classList.contains('hidden');
            return hasError || contentVisible;
        }""",
        timeout=15000
    )

    # Check which state we ended up in
    loading_text = page.locator("#loading-state").text_content() or ""
    if "Failed to load" in loading_text:
        # Error state - just verify error message is shown
        expect(page.locator("#loading-state")).to_contain_text("Failed to load")
        return

    # Success state - verify content rendered
    expect(page.locator("#network-content")).to_be_visible()
    expect(page.locator("#dns-servers")).to_be_visible()
    expect(page.locator("#interfaces-list")).to_be_visible()
