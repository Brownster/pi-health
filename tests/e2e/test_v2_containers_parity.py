"""PH2-006: v2 containers parity suite.

Pinned to v2 UI mode (via the v2_mode_server fixture) so the matrix is the three
viewport profiles only. Validates, with deterministic /api mocks:
- no horizontal overflow on load and through modal/action workflows
- lifecycle actions are reachable on phone/tablet with user feedback
- dialog focus management: trap + restore to the triggering control
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_containers(page, base_url, v2_login, install_v2_containers_api_mocks):
    v2_login(page, base_url)
    install_v2_containers_api_mocks(page)
    page.goto(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()


def _focus_is_inside(page, modal_id: str) -> bool:
    return page.evaluate(
        """(id) => {
            const modal = document.getElementById(id);
            return Boolean(modal && document.activeElement && modal.contains(document.activeElement));
        }""",
        modal_id,
    )


def test_v2_containers_overflow_through_workflows(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]

    _open_v2_containers(page, base_url, v2_login, install_v2_containers_api_mocks)
    assert_no_horizontal_overflow(page, f"v2 containers load ({viewport_profile_name})")

    # Logs modal open -> overflow-safe -> close
    page.locator("button[data-diagnostic-action='logs']:visible").first.click()
    expect(page.locator("#v2-logs-modal")).to_be_visible()
    expect(page.locator("#v2-logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    assert_no_horizontal_overflow(page, f"v2 logs modal ({viewport_profile_name})")
    page.click("#v2-logs-modal-close")
    expect(page.locator("#v2-logs-modal")).to_have_count(0)

    # Container network modal open -> overflow-safe -> close
    page.locator("button[data-diagnostic-action='network-test']:visible").first.click()
    expect(page.locator("#v2-container-network-modal")).to_be_visible()
    page.wait_for_function(
        """() => {
            const status = document.getElementById('v2-container-network-status');
            return status && !status.textContent.includes('Running');
        }""",
        timeout=15000,
    )
    assert_no_horizontal_overflow(page, f"v2 container network modal ({viewport_profile_name})")
    page.click("#v2-container-network-modal-close")
    expect(page.locator("#v2-container-network-modal")).to_have_count(0)

    # Host network panel open -> overflow-safe
    page.click("#v2-host-network-test-button")
    expect(page.locator("#v2-host-network-panel")).to_be_visible()
    page.wait_for_function(
        """() => {
            const status = document.getElementById('v2-host-network-status');
            return status && !status.textContent.includes('Running');
        }""",
        timeout=15000,
    )
    assert_no_horizontal_overflow(page, f"v2 host network panel ({viewport_profile_name})")


def test_v2_containers_lifecycle_action_feedback(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]

    _open_v2_containers(page, base_url, v2_login, install_v2_containers_api_mocks)

    # Restart is enabled for the running mock container and reachable on every viewport.
    restart_button = page.locator("button[data-action='restart']:visible").first
    expect(restart_button).to_be_visible()
    restart_button.click()

    # Mocked endpoint returns {"status": "restart accepted"} -> surfaced in the notice region.
    expect(page.get_by_text("restart accepted")).to_be_visible(timeout=10000)
    assert_no_horizontal_overflow(page, f"v2 lifecycle feedback ({viewport_profile_name})")


def test_v2_containers_dialog_focus_trap_and_restore(
    profiled_page: Page,
    viewport_profile_name: str,
    v2_mode_server,
    v2_login,
    install_v2_containers_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]

    _open_v2_containers(page, base_url, v2_login, install_v2_containers_api_mocks)

    logs_button = page.locator("button[data-diagnostic-action='logs']:visible").first
    logs_button.click()
    expect(page.locator("#v2-logs-modal")).to_be_visible()

    # Focus moves into the dialog on open.
    assert _focus_is_inside(page, "v2-logs-modal"), "focus should move into the logs dialog on open"

    # Tab / Shift+Tab stay trapped within the dialog.
    page.keyboard.press("Tab")
    assert _focus_is_inside(page, "v2-logs-modal"), "Tab should stay trapped in the dialog"
    page.keyboard.press("Shift+Tab")
    assert _focus_is_inside(page, "v2-logs-modal"), "Shift+Tab should stay trapped in the dialog"

    # Escape closes the dialog and restores focus to the triggering control.
    page.keyboard.press("Escape")
    expect(page.locator("#v2-logs-modal")).to_have_count(0)
    restored = page.evaluate(
        "() => document.activeElement && document.activeElement.getAttribute('data-diagnostic-action')"
    )
    assert restored == "logs", "focus should return to the logs trigger button after close"
