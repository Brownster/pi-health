import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv("BASE_URL", "http://localhost:8002")


def _wait_for_container_list(page: Page) -> None:
    page.wait_for_function(
        """() => {
            const body = document.getElementById('container-list');
            if (!body) return false;
            return !(body.textContent || '').includes('Loading...');
        }""",
        timeout=10000
    )


def test_containers_filters(authenticated_page: Page):
    page = authenticated_page
    page.goto(f"{BASE_URL}/containers.html")
    _wait_for_container_list(page)

    expect(page.locator("#container-list")).to_be_visible()

    page.click("#filter-running")
    _wait_for_container_list(page)
    running_text = page.locator("#container-list").text_content() or ""
    if "No running containers found" not in running_text:
        assert page.locator("#container-list tr").count() > 0

    page.click("#filter-stopped")
    _wait_for_container_list(page)
    stopped_text = page.locator("#container-list").text_content() or ""
    if "No stopped containers found" not in stopped_text:
        assert page.locator("#container-list tr").count() > 0

    page.click("#filter-all")
    _wait_for_container_list(page)


def test_container_logs_and_network_modal(authenticated_page: Page, test_container):
    page = authenticated_page
    page.goto(f"{BASE_URL}/containers.html")
    _wait_for_container_list(page)

    row = page.locator(f"tr[data-container-name='{test_container.name}']").first
    if row.count() == 0:
        pytest.skip("Test container not listed in UI")

    container_id = row.get_attribute("data-container-id")
    assert container_id

    # Open logs from dropdown
    row.locator("button:has-text('⋮')").click()
    dropdown = page.locator(f"#dropdown-{container_id}")
    expect(dropdown).not_to_have_class(re.compile(r".*hidden.*"))
    dropdown.locator("button:has-text('Logs')").click()

    logs_modal = page.locator("#logs-modal")
    expect(logs_modal).not_to_have_class(re.compile(r".*hidden.*"))
    expect(page.locator("#logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    page.click("#logs-modal-close")
    expect(logs_modal).to_have_class(re.compile(r".*hidden.*"))

    # Open container network test from dropdown
    row.locator("button:has-text('⋮')").click()
    expect(dropdown).not_to_have_class(re.compile(r".*hidden.*"))
    dropdown.locator("button:has-text('Network Test')").click()

    network_modal = page.locator("#container-network-modal")
    expect(network_modal).not_to_have_class(re.compile(r".*hidden.*"))
    page.wait_for_function(
        """() => {
            const status = document.getElementById('container-network-status');
            const output = document.getElementById('container-network-output');
            if (!status || !output) return false;
            return !status.textContent.includes('Running') &&
                   !output.textContent.includes('Collecting');
        }""",
        timeout=15000
    )
    page.click("#container-network-close")
    expect(network_modal).to_have_class(re.compile(r".*hidden.*"))
