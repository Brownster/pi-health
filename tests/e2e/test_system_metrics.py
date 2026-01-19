import os
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def test_system_metrics_page_renders(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/system.html")

    expect(page).to_have_title("System Health - Pi-Health Dashboard")
    expect(page.locator("h2")).to_contain_text("System Metrics")

    stats_resp = page.request.get(f"{BASE_URL}/api/stats")
    if not stats_resp.ok:
        page.wait_for_function(
            "() => document.getElementById('cpu-usage')?.textContent.includes('Error')",
            timeout=10000
        )
        expect(page.locator("#notification-area")).to_contain_text(
            "Error fetching system metrics",
            timeout=5000
        )
        return

    page.wait_for_function(
        """() => {
            const el = document.getElementById('cpu-usage');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=10000
    )

    expect(page.locator("#cpu-usage")).not_to_contain_text("Error")
    expect(page.locator("#memory-usage")).not_to_contain_text("Loading")
    expect(page.locator("#network-recv")).not_to_contain_text("Loading")
