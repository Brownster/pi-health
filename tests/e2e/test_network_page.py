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
            if (content.classList.contains('hidden')) return false;
            return true;
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

    resp = page.request.get(f"{BASE_URL}/api/network/info")
    if not resp.ok:
        page.wait_for_function(
            "() => document.getElementById('loading-state')?.textContent.includes('Failed to load')",
            timeout=10000
        )
        expect(page.locator("#loading-state")).to_contain_text("Failed to load network info")
        return

    _wait_for_network_content(page)

    page.wait_for_function(
        """() => {
            const el = document.getElementById('net-hostname');
            return el && el.textContent.trim() !== '-';
        }""",
        timeout=10000
    )
    expect(page.locator("#dns-servers")).to_be_visible()
    expect(page.locator("#interfaces-list")).to_be_visible()

    interfaces = resp.json().get("interfaces", [])
    if interfaces:
        expect(page.locator(".interface-card")).to_have_count(len(interfaces))
    else:
        expect(page.locator("#interfaces-list")).to_contain_text("No network interfaces found")
