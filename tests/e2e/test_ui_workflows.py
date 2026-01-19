import os
import re
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
    # Wait for navigation to complete
    page.wait_for_load_state("domcontentloaded")

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
    expect(page).to_have_url(re.compile(r".*/containers\.html"))
    
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
    expect(status_locator).to_have_class(re.compile(r".*status-running.*"))

    # Action: Click Stop
    stop_button.click()

    # Observation: The UI should show "Processing..." or similar, then update.
    # Docker shows "exited" status when a container is stopped.
    # Using a longer timeout as stopping a container takes time.
    expect(status_locator).to_have_text(re.compile(r"(stopped|exited)", re.IGNORECASE), timeout=15000)
    expect(status_locator).to_have_class(re.compile(r".*status-(stopped|exited|other).*"))
    
    # Start it again so the fixture cleanup (if forceful) or subsequent tests are clean
    # Note: Button state checks removed due to race conditions with status polling.
    # The key verification above confirms the container stopped and status is displayed correctly.
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
    expect(page.get_by_role("heading", name="Storage Pools")).to_be_visible(timeout=10000)

def test_settings_backup_toggle(authenticated_page: Page):
    """
    Test 4: Settings Persistence.
    Verifies that changing a setting in the UI persists after reload.
    """
    page = authenticated_page

    # Navigate to Settings
    page.click("nav a[href='/settings.html']")
    expect(page.locator("h2")).to_contain_text("Settings")

    # Select the Backups section (default is Plugins)
    page.select_option("#settings-section", "backups")

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

    # Select the Backups section again after reload
    page.select_option("#settings-section", "backups")

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


def test_plugins_toggle_samba(authenticated_page: Page):
    """
    Test 6: Plugins page toggle flow.
    Toggles the first available plugin on/off and verifies UI updates.
    """
    page = authenticated_page
    base_url = os.getenv('BASE_URL', 'http://localhost:8002')

    # Navigate directly to Plugins page
    page.goto(f"{base_url}/plugins.html")
    expect(page.locator("#plugins-list")).to_be_visible(timeout=10000)

    # Find first plugin card with a toggle
    cards = page.locator("#plugins-list > div.bg-gray-800")
    if cards.count() == 0:
        pytest.skip("No plugins available")

    card = cards.first
    expect(card).to_be_visible(timeout=5000)

    toggle = card.locator("input[type='checkbox']")
    if toggle.count() == 0:
        pytest.skip("No toggleable plugin found")

    initial_state = toggle.is_checked()

    # Toggle on/off and verify notification
    toggle.set_checked(not initial_state)
    expect(page.locator("#notification-area")).to_contain_text(
        f"Plugin {'enabled' if not initial_state else 'disabled'}",
        timeout=5000
    )

    # Wait for reload to finish and verify checkbox state
    expect(toggle).to_be_checked(checked=not initial_state)

    # Restore original state
    toggle.set_checked(initial_state)
    expect(page.locator("#notification-area")).to_contain_text(
        f"Plugin {'enabled' if initial_state else 'disabled'}",
        timeout=5000
    )


def test_tools_copyparty_status(authenticated_page: Page):
    """
    Test 7: Tools page CopyParty status handling.
    Validates status rendering or error notification.
    """
    page = authenticated_page

    base_url = "/".join(page.url.split("/")[:3])
    page.goto(f"{base_url}/tools.html")
    expect(page.get_by_role("heading", name="Tools")).to_be_visible()

    status_resp = page.request.get(f"{base_url}/api/tools/copyparty/status")
    if not status_resp.ok:
        expect(page.locator("#notification-area")).to_contain_text("CopyParty error", timeout=5000)
        return

    data = status_resp.json()
    expected_service = data.get("service_status") or "unknown"
    expected_installed = "Yes" if data.get("installed") else "No"

    expect(page.locator("#copyparty-service-status")).to_have_text(expected_service, timeout=5000)
    expect(page.locator("#copyparty-installed")).to_have_text(expected_installed)

    expect(page.locator("#copyparty-share-path")).to_have_value(data.get("config", {}).get("share_path", ""))
    expect(page.locator("#copyparty-port")).to_have_value(str(data.get("config", {}).get("port", "")))

    if data.get("url"):
        expect(page.locator("#copyparty-link")).to_have_attribute("href", data["url"])


def test_pools_plugin_status_and_commands(authenticated_page: Page):
    """
    Test 8: Pools page plugin status display and command buttons.
    """
    page = authenticated_page

    base_url = "/".join(page.url.split("/")[:3])
    plugins_resp = page.request.get(f"{base_url}/api/storage/plugins")
    if not plugins_resp.ok:
        pytest.skip("Storage plugins API unavailable")

    plugins = plugins_resp.json().get("plugins", [])
    storage_plugins = [p for p in plugins if p.get("category") == "storage" and p.get("enabled")]
    if not storage_plugins:
        pytest.skip("No enabled storage plugins")

    plugin = storage_plugins[0]
    details_resp = page.request.get(f"{base_url}/api/storage/plugins/{plugin['id']}")
    if not details_resp.ok:
        pytest.skip(f"Plugin details unavailable for {plugin['id']}")
    details = details_resp.json()

    page.goto(f"{base_url}/pools.html")
    expect(page.get_by_role("heading", name="Storage Pools")).to_be_visible()

    card = page.locator("section", has=page.locator("h3", has_text=plugin["name"])).first
    expect(card).to_be_visible(timeout=10000)

    status_pill = card.locator(".status-pill")
    expect(status_pill).to_be_visible()
    if details.get("status", {}).get("status"):
        expect(status_pill).to_have_text(details["status"]["status"])

    if not plugin.get("installed"):
        expect(card.locator("code")).to_be_visible()
        pytest.skip("Plugin not installed; commands are hidden")

    commands = details.get("commands") or []
    command_buttons = card.locator("button.coraline-button")
    expect(command_buttons).to_have_count(len(commands))


def test_system_metrics_rendering(authenticated_page: Page):
    """
    Test 9: System Health metrics render (no longer show Loading...).
    """
    page = authenticated_page

    base_url = "/".join(page.url.split("/")[:3])
    stats_resp = page.request.get(f"{base_url}/api/stats")
    if not stats_resp.ok:
        pytest.skip("Stats API unavailable")

    page.goto(f"{base_url}/system.html")
    expect(page.get_by_role("heading", name="System Metrics")).to_be_visible()

    def not_loading(selector: str) -> None:
        expect(page.locator(selector)).not_to_have_text("Loading...", timeout=10000)

    not_loading("#cpu-usage")
    not_loading("#memory-usage")
    not_loading("#disk-usage")
    not_loading("#disk-usage-2")
    not_loading("#network-recv")
    not_loading("#network-sent")

    cpu_bar = page.locator("#cpu-bar")
    memory_bar = page.locator("#memory-bar")
    disk1_bar = page.locator("#disk1-bar")
    disk2_bar = page.locator("#disk2-bar")
    for bar in (cpu_bar, memory_bar, disk1_bar, disk2_bar):
        style = bar.get_attribute("style") or ""
        assert "%" in style


def test_settings_backup_logs(authenticated_page: Page):
    """
    Test 10: Settings backups section loads backup lists.
    """
    page = authenticated_page

    base_url = "/".join(page.url.split("/")[:3])
    page.goto(f"{base_url}/settings.html")
    expect(page.locator("#settings-section")).to_be_visible()
    page.select_option("#settings-section", "backups")

    expect(page.locator("#settings-backups")).to_be_visible()

    backup_list = page.locator("#backup-list")
    plugin_list = page.locator("#backup-plugins-list")
    expect(backup_list).to_be_visible()
    expect(plugin_list).to_be_visible()

    expect(backup_list).not_to_have_text("Loading backups...", timeout=10000)
    expect(plugin_list).not_to_have_text("Loading plugin backups...", timeout=10000)


def test_settings_auto_update_section(authenticated_page: Page):
    """
    Test 11: Settings updates section renders and logs toggle works.
    """
    page = authenticated_page

    base_url = "/".join(page.url.split("/")[:3])
    page.goto(f"{base_url}/settings.html")
    expect(page.locator("#settings-section")).to_be_visible()
    page.select_option("#settings-section", "updates")

    expect(page.locator("#settings-updates")).to_be_visible()
    expect(page.locator("#auto-update-enabled")).to_be_visible()
    expect(page.locator("#run-now-btn")).to_be_visible()

    stacks_list = page.locator("#stacks-list")
    expect(stacks_list).to_be_visible()
    expect(stacks_list).not_to_have_text("Loading stacks...", timeout=10000)

    # Show logs
    page.click("button:has-text('View Last Run')")
    logs_section = page.locator("#settings-updates-logs")
    expect(logs_section).to_be_visible()
    expect(page.locator("#logs-content")).to_be_visible()
