import pytest
import time
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

def open_nav_link(page: Page, menu_label: str, href: str) -> None:
    dropdown = page.locator("nav .nav-dropdown", has_text=menu_label)
    dropdown.hover()
    link = page.locator(f"nav a[href='{href}']")
    expect(link).to_be_visible()
    link.click()

def test_login_success(page: Page, browser_context_args, test_user_credentials):
    """
    Test 1: Verify login functionality works.
    This corresponds to 'Confidence in Core Functionality' regarding access.
    """
    # Use the base URL from fixtures
    creds = test_user_credentials
    base_url = creds["base_url"]
    
    page.goto(f"{base_url}/login.html")
    
    # Fill invalid credentials first (Regression Prevention)
    page.fill("#username", "wronguser")
    page.fill("#password", "wrongpass")
    page.click("button.login-button")
    
    # Expect error message
    expect(page.locator("#login-error")).to_be_visible(timeout=5000)
    
    # Fill valid credentials
    page.fill("#username", creds["username"])
    page.fill("#password", creds["password"])
    page.click("button.login-button")
    
    # Expect redirect to home
    expect(page).to_have_url(f"{base_url}/")
    
    # Verify we see the user in the navbar
    expect(page.locator("#logged-in-user")).to_contain_text(creds["username"])

def test_container_stop_workflow(authenticated_page: Page, test_container):
    """
    Test 2 & 3: Core Functionality & End-to-End Verification.
    
    Scenario:
    1. Logged in user navigates to "Containers" page.
    2. Identifies a running container ("pihealth-e2e-test-container").
    3. Clicks "Stop".
    4. Asserts that the UI updates the container status to "stopped".
    """
    page = authenticated_page
    
    # Navigate to Containers page using the navbar
    open_nav_link(page, "My Apps", "/containers.html")
    expect(page).to_have_url(r".*/containers.html")
    
    # Define selectors for our specific test container
    # The row has data-container-name attribute matching the name
    row_selector = f"tr[data-container-name='{test_container.name}']"
    status_locator = page.locator(f"{row_selector} td:nth-child(3) span")
    stop_button = page.locator(f"{row_selector} button[data-action='stop']")
    start_button = page.locator(f"{row_selector} button[data-action='start']")
    
    # Wait for the row to appear (handling AJAX load)
    expect(page.locator(row_selector)).to_be_visible(timeout=10000)
    
    # Verify initial state: It should be running
    expect(status_locator).to_have_text("running", ignore_case=True)
    expect(status_locator).to_have_class(r".*status-running.*")
    
    # Action: Click Stop
    stop_button.click()
    
    # Observation: The UI should show "Processing..." or similar, then update.
    # We just want to assert it eventually becomes "stopped".
    # Using a longer timeout as stopping a container takes time.
    expect(status_locator).to_have_text("stopped", ignore_case=True, timeout=15000)
    expect(status_locator).to_have_class(r".*status-stopped.*")
    
    # Verify button states update correctly
    expect(stop_button).to_be_disabled()
    expect(start_button).to_be_enabled()
    
    # Start it again so the fixture cleanup (if forceful) or subsequent tests are clean
    start_button.click()
    expect(status_locator).to_have_text("running", ignore_case=True, timeout=15000)

def test_navigation_regression(authenticated_page: Page):
    """
    Test 2: Regression Prevention.
    Ensure navigating between pages doesn't break basic rendering.
    """
    page = authenticated_page
    
    # Visit System Health
    page.click("nav a[href='/system.html']")
    expect(page.get_by_role("heading", name="System Metrics")).to_be_visible()
    
    # Visit Stacks
    open_nav_link(page, "My Apps", "/stacks.html")
    expect(page.get_by_role("heading", name="Docker Stacks")).to_be_visible()
    
    # Visit Storage Pools
    open_nav_link(page, "Storage", "/pools.html")
    expect(page.get_by_role("heading", name="Storage Pools")).to_be_visible()

def test_settings_backup_toggle(authenticated_page: Page):
    """
    Test 4: Settings Persistence.
    Verifies that changing a setting in the UI persists after reload.
    """
    page = authenticated_page
    
    # Navigate to Settings
    page.click("nav a[href='/settings.html']")
    expect(page.locator("h2")).to_contain_text("Settings")
    
    # Wait for config to load
    # The checkbox is hidden (opacity 0) due to custom styling, so we locate the label/slider to check visibility
    toggle_input = page.locator("#backup-enabled")
    toggle_slider = page.locator("#backup-enabled + .toggle-slider")
    expect(toggle_slider).to_be_visible()
    
    # Get initial state
    initial_state = toggle_input.is_checked()
    
    # Click toggle (force or click slider)
    toggle_slider.click()
    
    # Wait for notification
    expect(page.locator("#notification-area")).to_contain_text("Backup settings saved", timeout=5000)
    
    # Verify state changed in UI (checking hidden input state)
    expect(toggle_input).to_be_checked(checked=not initial_state)
    
    # Reload page to verify persistence
    page.reload()
    
    # Wait for it to load again
    expect(toggle_slider).to_be_visible()
    # It takes a moment for JS to fetch config and update checkbox
    # We wait for the spinner or just wait a safe moment/condition? 
    # Best to wait for the badge to update if possible.
    status_badge = page.locator("#backup-status-badge")
    if not initial_state: # If we turned it ON
        expect(status_badge).to_have_text("Enabled")
    else: # If we turned it OFF
        expect(status_badge).to_have_text("Disabled")
        
    expect(toggle_input).to_be_checked(checked=not initial_state)
    
    # Restore original state
    toggle_slider.click()
    expect(page.locator("#notification-area")).to_contain_text("Backup settings saved", timeout=5000)

def test_stack_lifecycle(authenticated_page: Page, docker_client):
    """
    Test 5: Stack Creation and Deletion.
    Creates a new stack, checks it appears, and deletes it.
    """
    page = authenticated_page
    stack_name = "e2e-test-stack"
    
    # Navigate to Stacks
    open_nav_link(page, "My Apps", "/stacks.html")

    # Ensure our test stack doesn't exist from a previous failed run via API.
    base_url = page.url.replace("/stacks.html", "")
    stacks_resp = page.request.get(f"{base_url}/api/stacks")
    if stacks_resp.ok:
        stacks = stacks_resp.json().get("stacks", [])
        if any(stack.get("name") == stack_name for stack in stacks):
            page.request.delete(f"{base_url}/api/stacks/{stack_name}")
            page.reload()
            expect(page.locator(f".stack-card:has-text('{stack_name}')")).to_have_count(0, timeout=10000)
    
    # Click New Stack
    page.click("button:has-text('New Stack')")
    expect(page.locator("#create-modal")).to_be_visible()
    
    # Fill Name
    page.fill("#new-stack-name", stack_name)
    
    # Fill Compose (CodeMirror if available)
    compose_content = """version: '3'
services:
  echo:
    image: alpine
    command: echo hello
"""
    page.wait_for_function(
        "() => document.querySelector('#new-stack-compose')",
        timeout=5000
    )
    page.evaluate(f"""
        const textarea = document.querySelector('#new-stack-compose');
        const cmWrapper = textarea && textarea.nextSibling;
        if (cmWrapper && cmWrapper.CodeMirror) {{
            cmWrapper.CodeMirror.setValue(`{compose_content}`);
            cmWrapper.CodeMirror.save();
        }} else {{
            textarea.value = `{compose_content}`;
        }}
    """)
    
    # Click Create and wait for API response
    with page.expect_response(f"**/api/stacks/{stack_name}") as response_info:
        page.click("#create-modal button:has-text('Create Stack')")
    if not response_info.value.ok:
        error_payload = {}
        try:
            error_payload = response_info.value.json()
        except Exception:
            pass
        error_text = str(error_payload).lower()
        if response_info.value.status >= 500 and ("docker" in error_text or "compose" in error_text):
            pytest.skip("Docker unavailable for stack lifecycle test")
        if response_info.value.status in (409, 400) or "exists" in error_text:
            page.request.delete(f"{base_url}/api/stacks/{stack_name}")
            page.reload()
            with page.expect_response(f"**/api/stacks/{stack_name}") as retry_info:
                page.click("#create-modal button:has-text('Create Stack')")
            assert retry_info.value.ok
        else:
            assert response_info.value.ok
    
    # Verify stack card appears
    expect(page.locator(f".stack-card:has-text('{stack_name}')")).to_be_visible(timeout=10000)
    
    # Open the stack to Delete it
    page.click(f".stack-card:has-text('{stack_name}')")
    expect(page.locator("#stack-modal")).to_be_visible()
    
    # Handle confirmation dialog for delete
    page.once("dialog", lambda dialog: dialog.accept())
    
    # Click Delete
    with page.expect_response(f"**/api/stacks/{stack_name}") as delete_info:
        page.click("#stack-modal button:has-text('Delete Stack')")

    assert delete_info.value.ok

    # Verify card is gone
    expect(page.locator(f".stack-card:has-text('{stack_name}')")).to_have_count(0, timeout=10000)
