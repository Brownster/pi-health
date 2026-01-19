import os
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _wait_for_copyparty_status(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const status = document.getElementById('copyparty-service-status');
            const installed = document.getElementById('copyparty-installed');
            if (!status || !installed) return false;
            return status.textContent.trim() !== 'Loading...' &&
                   installed.textContent.trim() !== 'Loading...';
        }""",
        timeout=10000
    )


def test_tools_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/tools.html")

    expect(page.get_by_role("heading", name="Tools")).to_be_visible()
    expect(page.locator("#copyparty-share-path")).to_be_visible()
    expect(page.locator("#copyparty-port")).to_be_visible()


def test_tools_copyparty_status_renders(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/tools.html")

    resp = page.request.get(f"{BASE_URL}/api/tools/copyparty/status")
    if not resp.ok:
        expect(page.locator("#notification-area")).to_contain_text("CopyParty error", timeout=5000)
        return

    _wait_for_copyparty_status(page)

    data = resp.json()
    expect(page.locator("#copyparty-service-status")).to_have_text(data.get("service_status") or "unknown")
    expect(page.locator("#copyparty-installed")).to_have_text("Yes" if data.get("installed") else "No")
    expect(page.locator("#copyparty-share-path")).to_have_value(
        data.get("config", {}).get("share_path", "/srv/copyparty")
    )
    expect(page.locator("#copyparty-port")).to_have_value(
        str(data.get("config", {}).get("port", 3923))
    )
