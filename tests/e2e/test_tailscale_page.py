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

    resp = page.request.get(f"{BASE_URL}/api/tailscale/status")
    if not resp.ok:
        page.wait_for_function(
            "() => document.getElementById('loading-state')?.textContent.includes('Failed to load')",
            timeout=10000
        )
        expect(page.locator("#loading-state")).to_contain_text("Failed to load Tailscale status")
        return

    _wait_for_tailscale_state(page)
    loading_text = page.locator("#loading-state").text_content() or ""
    if "Failed to load" in loading_text:
        expect(page.locator("#loading-state")).to_contain_text("Failed to load Tailscale status")
        return
    data = resp.json()

    if not data.get("installed") or not data.get("running"):
        expect(page.locator("#setup-section")).not_to_have_class(re.compile(r".*hidden.*"))
        expect(page.locator("#tailscale-authkey")).to_be_visible()
        expect(page.locator("#setup-status")).to_have_text(
            "Not Installed" if not data.get("installed") else "Not Running"
        )
        return

    expect(page.locator("#status-section")).not_to_have_class(re.compile(r".*hidden.*"))
    expect(page.locator("#connection-status")).to_be_visible()
    expect(page.locator("#ts-ip")).to_be_visible()
    expect(page.locator("#access-url")).to_be_visible()
