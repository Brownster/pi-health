import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _load_stacks(page: Page):
    resp = page.request.get(f"{BASE_URL}/api/stacks?status=true")
    if not resp.ok:
        pytest.skip("Stacks API unavailable")
    stacks = resp.json().get("stacks", [])
    if not stacks:
        pytest.skip("No stacks configured")
    return stacks


def _wait_for_stacks_grid(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const grid = document.getElementById('stacks-grid');
            if (!grid) return false;
            const text = grid.textContent || '';
            return !text.includes('Loading stacks');
        }""",
        timeout=10000
    )


def test_stacks_page_loads(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/stacks.html")

    expect(page.get_by_role("heading", name="Docker Stacks")).to_be_visible()
    _wait_for_stacks_grid(page)
    expect(page.locator("#stacks-grid")).to_be_visible()


def test_stack_modal_tabs_and_logs(authenticated_page: Page):
    page = authenticated_page
    stacks = _load_stacks(page)
    stack = stacks[0]

    page.goto(f"{BASE_URL}/stacks.html")
    _wait_for_stacks_grid(page)

    card = page.locator(".stack-card", has_text=stack["name"]).first
    expect(card).to_be_visible(timeout=10000)
    card.click()

    modal = page.locator("#stack-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"))
    expect(page.locator("#modal-stack-name")).to_have_text(stack["name"])

    # Environment tab renders textarea
    page.click("button[data-tab='env']")
    expect(page.locator("#tab-env")).to_be_visible()
    expect(page.locator("#edit-env")).to_be_visible()

    # Logs tab refresh updates output
    page.click("button[data-tab='logs']")
    expect(page.locator("#tab-logs")).to_be_visible()
    logs_output = page.locator("#logs-output")
    expect(logs_output).to_contain_text("Refresh Logs", timeout=5000)
    page.click("button:has-text('Refresh Logs')")
    expect(logs_output).not_to_contain_text("Click \"Refresh Logs\"", timeout=10000)

    # Close modal
    page.click("#stack-modal .modal-backdrop")
    expect(modal).to_have_class(re.compile(r".*hidden.*"))
