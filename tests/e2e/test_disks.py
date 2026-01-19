"""
E2E tests for the Disks page (/disks.html).

Tests cover:
- Page load and basic rendering
- SMART health section and refresh
- SMART detail modal interactions
- Helper service status handling
"""
import os
import re
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8002')


def test_disks_page_loads(authenticated_page: Page):
    """
    Test that the disks page loads and shows basic structure.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Verify page title and heading
    expect(page).to_have_title("Disks - Pi-Health Dashboard")
    expect(page.locator("h2")).to_contain_text("Disk Management")

    # Verify main sections exist
    expect(page.locator("h3:has-text('Storage Devices')")).to_be_visible()
    expect(page.locator("h3:has-text('SMART Health')")).to_be_visible()

    # Verify Refresh buttons exist
    expect(page.get_by_role("button", name="Refresh", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Refresh SMART")).to_be_visible()


def test_disks_page_disk_list_loads(authenticated_page: Page):
    """
    Test that the disk list section attempts to load data.
    It will either show disks, a helper warning, or 'no devices' message.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Wait for the loading state to resolve
    disk_list = page.locator("#disk-list")
    expect(disk_list).to_be_visible()

    # Wait for loading to complete (either shows disks, warning, or no devices)
    page.wait_for_function(
        """() => {
            const el = document.getElementById('disk-list');
            const text = el ? el.textContent : '';
            return !text.includes('Loading...');
        }""",
        timeout=10000
    )

    # Check for one of three valid states:
    # 1. Helper not running warning banner
    # 2. No storage devices message
    # 3. Actual disk cards
    helper_warning = page.locator("#helper-status:not(.hidden)")
    no_devices_msg = page.locator("#disk-list:has-text('No storage devices')")
    disk_cards = page.locator(".disk-card")

    # At least one of these should be true
    has_helper_warning = helper_warning.count() > 0 and "Helper" in helper_warning.text_content()
    has_no_devices = no_devices_msg.count() > 0
    has_disk_cards = disk_cards.count() > 0

    assert has_helper_warning or has_no_devices or has_disk_cards, \
        "Disk list should show helper warning, no devices message, or disk cards"


def test_smart_refresh_button_works(authenticated_page: Page):
    """
    Test that clicking Refresh SMART triggers data load.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    smart_list = page.locator("#smart-list")
    expect(smart_list).to_be_visible()

    # Initial state shows prompt to click refresh
    expect(smart_list).to_contain_text("Click")

    # Click Refresh SMART
    page.click("button:has-text('Refresh SMART')")

    # Wait for loading to complete
    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            const text = el ? el.textContent : '';
            return !text.includes('Loading SMART data...');
        }""",
        timeout=15000
    )

    # After refresh, should show one of:
    # - SMART cards (if disks with SMART are available)
    # - "No SMART-capable devices" message
    # - Error message (if helper not running)
    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg")
    no_smart_msg = page.locator("#smart-list:has-text('No SMART-capable')")
    error_msg = page.locator("#smart-list .text-red-400")

    has_cards = smart_cards.count() > 0
    has_no_smart = no_smart_msg.count() > 0
    has_error = error_msg.count() > 0

    assert has_cards or has_no_smart or has_error, \
        "SMART refresh should show cards, no devices message, or error"


def test_smart_card_click_opens_modal(authenticated_page: Page):
    """
    Test that clicking a SMART card opens the detail modal.
    Skip if no SMART devices are available.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Refresh SMART data
    page.click("button:has-text('Refresh SMART')")

    # Wait for loading
    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=15000
    )

    # Check if we have any SMART cards
    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg.cursor-pointer")

    if smart_cards.count() == 0:
        pytest.skip("No SMART-capable devices available for modal test")

    # Click the first SMART card
    first_card = smart_cards.first
    first_card.click()

    # Verify modal opens
    modal = page.locator("#smart-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    # Verify modal has expected elements
    expect(page.locator("#smart-modal-title")).to_contain_text("SMART Details")
    expect(page.locator("#smart-modal-content")).to_be_visible()

    # Verify action buttons in modal
    expect(page.locator("#smart-modal button:has-text('Short Test')")).to_be_visible()
    expect(page.locator("#smart-modal button:has-text('Long Test')")).to_be_visible()
    expect(page.locator("#smart-modal button:has-text('Close')")).to_be_visible()


def test_smart_modal_close_button(authenticated_page: Page):
    """
    Test that the SMART modal can be closed via the Close button.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Refresh SMART data
    page.click("button:has-text('Refresh SMART')")

    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=15000
    )

    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg.cursor-pointer")

    if smart_cards.count() == 0:
        pytest.skip("No SMART-capable devices available for modal test")

    # Open modal
    smart_cards.first.click()
    modal = page.locator("#smart-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    # Close via Close button
    page.click("#smart-modal button:has-text('Close')")

    # Verify modal is hidden
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_smart_modal_close_via_x_button(authenticated_page: Page):
    """
    Test that the SMART modal can be closed via the X button.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    page.click("button:has-text('Refresh SMART')")

    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=15000
    )

    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg.cursor-pointer")

    if smart_cards.count() == 0:
        pytest.skip("No SMART-capable devices available for modal test")

    # Open modal
    smart_cards.first.click()
    modal = page.locator("#smart-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    # Close via X button (the × character button in header)
    page.click("#smart-modal .border-b button")

    # Verify modal is hidden
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_smart_modal_close_via_backdrop(authenticated_page: Page):
    """
    Test that the SMART modal can be closed by clicking the backdrop.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    page.click("button:has-text('Refresh SMART')")

    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=15000
    )

    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg.cursor-pointer")

    if smart_cards.count() == 0:
        pytest.skip("No SMART-capable devices available for modal test")

    # Open modal
    smart_cards.first.click()
    modal = page.locator("#smart-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    # Click backdrop (the modal container itself, not the content)
    # Use position to click outside the modal content
    modal.click(position={"x": 10, "y": 10})

    # Verify modal is hidden
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_disk_refresh_button_works(authenticated_page: Page):
    """
    Test that the main Refresh button reloads disk data.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Wait for initial load
    page.wait_for_function(
        """() => {
            const el = document.getElementById('disk-list');
            return el && !el.textContent.includes('Loading...');
        }""",
        timeout=10000
    )

    # Click refresh
    page.click("button:has-text('Refresh'):not(:has-text('SMART'))")

    # Should show loading briefly then resolve
    # We just verify no error occurs and page still renders
    page.wait_for_function(
        """() => {
            const el = document.getElementById('disk-list');
            return el && !el.textContent.includes('Loading...');
        }""",
        timeout=10000
    )

    # Page should still have the disk list section
    expect(page.locator("#disk-list")).to_be_visible()


def test_helper_warning_displays_instructions(authenticated_page: Page):
    """
    Test that when helper is not available, helpful instructions are shown.
    This test checks the UI handles the 'no helper' case gracefully.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    # Wait for page to load
    page.wait_for_function(
        """() => {
            const el = document.getElementById('disk-list');
            return el && !el.textContent.includes('Loading...');
        }""",
        timeout=10000
    )

    # Check if helper warning is shown
    helper_warning = page.locator("#helper-status")

    if helper_warning.is_visible():
        # If helper warning is shown, verify it has useful content
        expect(helper_warning).to_contain_text("Helper")
        expect(helper_warning).to_contain_text("pihealth-helper")
    # If no warning, helper is available - test passes


def test_navigation_to_disks_via_menu(authenticated_page: Page):
    """
    Test navigating to disks page via the Storage dropdown menu.
    """
    page = authenticated_page

    # Start at home
    page.goto(f"{BASE_URL}/")

    # Hover over Storage dropdown
    storage_dropdown = page.locator("nav .nav-dropdown", has_text="Storage")
    storage_dropdown.hover()

    # Click Disks link
    disks_link = page.locator("nav a[href='/disks.html']")
    expect(disks_link).to_be_visible()
    disks_link.click()

    # Verify navigation
    expect(page).to_have_url(re.compile(r".*/disks\.html"))
    expect(page.locator("h2")).to_contain_text("Disk Management")


def test_mount_modal_validation_error(authenticated_page: Page):
    """
    Test that the mount modal validates mountpoint input.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    suggestions_resp = page.request.get(f"{BASE_URL}/api/disks/suggested-mounts")
    if not suggestions_resp.ok:
        pytest.skip("Suggested mounts API not available")

    suggestions = suggestions_resp.json().get("suggestions", [])
    if not suggestions:
        pytest.skip("No suggested mounts available")

    page.wait_for_selector("#suggestions-list")
    mount_button = page.locator("#suggestions-list button").first
    if mount_button.count() == 0:
        pytest.skip("No mount suggestion buttons found")

    mount_button.click()

    modal = page.locator("#mount-modal")
    expect(modal).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    page.fill("#mount-point", "/invalid")
    page.click("#mount-modal button:has-text('Mount')")

    expect(page.locator("#notification-area")).to_contain_text(
        "Mountpoint must start with /mnt/",
        timeout=5000
    )

    page.click("#mount-modal button:has-text('Cancel')")
    expect(modal).to_have_class(re.compile(r".*hidden.*"), timeout=5000)


def test_unmount_confirmation_cancel(authenticated_page: Page):
    """
    Test that the unmount confirmation dialog appears and can be canceled.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    page.wait_for_function(
        """() => {
            const el = document.getElementById('disk-list');
            return el && !el.textContent.includes('Loading...');
        }""",
        timeout=10000
    )

    unmount_buttons = page.locator("button:has-text('Unmount')")
    if unmount_buttons.count() == 0:
        pytest.skip("No mounted partitions available for unmount test")

    dialog_message = {"text": ""}

    def handle_dialog(dialog):
        dialog_message["text"] = dialog.message
        dialog.dismiss()

    page.once("dialog", handle_dialog)
    unmount_buttons.first.click()

    assert "Unmount" in dialog_message["text"]
    expect(page.locator("#disk-list")).to_be_visible()


def test_smart_self_test_confirmation(authenticated_page: Page):
    """
    Test that SMART self-test buttons prompt for confirmation.
    """
    page = authenticated_page
    page.goto(f"{BASE_URL}/disks.html")

    page.click("button:has-text('Refresh SMART')")
    page.wait_for_function(
        """() => {
            const el = document.getElementById('smart-list');
            return el && !el.textContent.includes('Loading');
        }""",
        timeout=15000
    )

    smart_cards = page.locator("#smart-list .bg-gray-900.rounded-lg.cursor-pointer")
    if smart_cards.count() == 0:
        pytest.skip("No SMART-capable devices available for self-test")

    smart_cards.first.click()
    expect(page.locator("#smart-modal")).not_to_have_class(re.compile(r".*hidden.*"), timeout=5000)

    dialog_message = {"text": ""}

    def handle_dialog(dialog):
        dialog_message["text"] = dialog.message
        dialog.dismiss()

    page.once("dialog", handle_dialog)
    page.click("#smart-modal button:has-text('Short Test')")

    assert "SMART self-test" in dialog_message["text"]
