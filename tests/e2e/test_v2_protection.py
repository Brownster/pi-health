"""Protection capability and tailored SnapRAID provider coverage."""

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_protection(page, base_url, v2_login, install_mocks):
    v2_login(page, base_url)
    install_mocks(page)
    page.goto(f"{base_url}/v2/protection")
    expect(page.get_by_role("heading", name="storage_protection")).to_be_visible()


def test_v2_protection_snapraid_guided_setup_and_deep_link(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_protection(page, base_url, v2_login, install_v2_storage_api_mocks)

    setup = page.locator("[data-protection-provider-row='snapraid']")
    expect(setup).to_contain_text("No drives")
    expect(page.get_by_text("MergerFS")).to_have_count(0)
    setup.get_by_role("link", name="Set up").click()
    expect(page).to_have_url(f"{base_url}/v2/protection/snapraid")
    expect(page.locator("[data-capability-renderer='snapraid']")).to_be_visible()
    expect(page.locator("button[data-snapraid-tab='configuration'][aria-selected='true']")).to_be_visible()
    expect(page.locator("[data-snapraid-editor]")).to_be_visible()
    expect(page.get_by_role("link", name="Configure provider")).to_have_count(0)

    # A new setup must be saved before Apply is available. Preview remains a
    # read-only check of the generated snapraid.conf.
    page.select_option("select[data-drive-role='/mnt/disk1']", "data")
    page.select_option("select[data-drive-role='/mnt/parity']", "parity")
    expect(page.locator("button[data-snapraid-apply]")).to_be_disabled()
    page.click("button[data-snapraid-preview-open]")
    expect(page.locator("[data-snapraid-preview]")).to_contain_text("parity", timeout=10000)
    page.click("button[data-snapraid-save]")
    expect(page.get_by_text("Saved.")).to_be_visible(timeout=10000)
    expect(page.locator("button[data-snapraid-apply]")).to_be_enabled()
    page.click("button[data-snapraid-apply]")
    expect(page.locator("[data-snapraid-apply-confirm]")).to_contain_text("/etc/snapraid.conf")
    page.click("button[data-snapraid-apply-confirm-yes]")
    expect(page.get_by_text("Applied")).to_be_visible(timeout=10000)


def test_v2_protection_configured_cards_across_viewports(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_storage_configured_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_protection(page, base_url, v2_login, install_v2_storage_configured_mocks)

    summary = page.locator("[data-protection-summary]")
    expect(summary).to_contain_text("Protected")
    expect(summary).to_contain_text("2")
    expect(summary).to_contain_text("Not reported")

    protection_set = page.locator("[data-protection-set='SnapRAID parity']")
    expect(protection_set).to_contain_text("healthy")
    expect(protection_set).to_contain_text("parity")
    expect(protection_set).to_contain_text("SnapRAID")
    expect(page.get_by_text("MergerFS")).to_have_count(0)
    assert_no_horizontal_overflow(page, f"v2 protection configured ({viewport_profile_name})")


def test_v2_snapraid_tailored_operations_recovery_and_diagnostics(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_configured_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_configured_mocks(page)
    page.goto(f"{base_url}/v2/protection/snapraid")

    expect(page.locator("[data-capability-renderer='snapraid']")).to_be_visible()
    expect(page.locator("button[data-snapraid-tab='overview'][aria-selected='true']")).to_be_visible()
    expect(page.locator("[data-protection-set='SnapRAID parity']")).to_contain_text("healthy")

    overview_tab = page.locator("button[data-snapraid-tab='overview']")
    overview_tab.focus()
    overview_tab.press("ArrowRight")
    configuration_tab = page.locator("button[data-snapraid-tab='configuration']")
    expect(configuration_tab).to_have_attribute("aria-selected", "true")
    expect(configuration_tab).to_be_focused()
    configuration_tab.press("Home")
    expect(overview_tab).to_have_attribute("aria-selected", "true")

    # Sync is always explicitly confirmed because it writes parity. Scrub keeps
    # its bounded percentage and age controls visible before execution.
    page.click("button[data-snapraid-tab='operations']")
    page.click("button[data-plugin-command='sync']")
    expect(page.get_by_text("Sync updates parity from the current data drives.")).to_be_visible()
    page.click("button[data-command-confirm='sync']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    page.click("button[data-plugin-command='scrub']")
    expect(page.locator("input[data-command-param='percent']")).to_have_value("8")
    expect(page.locator("input[data-command-param='age_days']")).to_have_value("10")
    page.click("button[data-command-run='scrub']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    # Recovery is fetched only when its tab opens and keeps the provider's
    # declared options visible beside the guarded Fix command.
    page.click("button[data-snapraid-tab='recovery']")
    recovery = page.locator("[data-snapraid-recovery-status]")
    expect(recovery).to_contain_text("data2", timeout=10000)
    expect(recovery).to_contain_text("Recover missing files")
    expect(recovery).to_contain_text("3")
    page.click("button[data-plugin-command='fix']")
    expect(page.get_by_text("Fix can overwrite damaged files using parity.")).to_be_visible()
    page.click("button[data-command-confirm='fix']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    # Diagnostics exposes safe status commands and lazily loads the latest log.
    page.click("button[data-snapraid-tab='diagnostics']")
    expect(page.locator("[data-snapraid-log]")).to_contain_text("log line", timeout=10000)
    page.click("button[data-plugin-command='status']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)


def test_v2_protection_empty_state_keeps_provider_discovery_visible(
    page: Page,
    v2_server,
    v2_login,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)

    def handler(route):
        path = route.request.url.split("?", 1)[0]
        if path.endswith("/api/capabilities/storage.protection"):
            payload = {
                "schema_version": "1",
                "capability": {"id": "storage.protection", "surface": "protection", "providers": []},
                "errors": [],
            }
        elif path.endswith("/api/storage/plugins"):
            payload = {"plugins": []}
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/**", handler)
    page.goto(f"{base_url}/v2/protection")

    expect(page.locator("[data-protection-empty]")).to_be_visible()
    expect(page.get_by_role("link", name="Add provider").first).to_have_attribute(
        "href", "/v2/settings/extensions",
    )


def test_v2_protection_generic_provider_and_deep_link(
    page: Page,
    v2_server,
    v2_login,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    status = {
        "schema_version": "1",
        "provider_id": "backup-provider",
        "capability_id": "storage.protection",
        "observed_at": "2026-07-18T12:00:00Z",
        "lifecycle": {
            "installed": True,
            "enabled": True,
            "configured": True,
            "compatibility": "compatible",
            "availability": "available",
        },
        "health": {"state": "warning", "message": "One backup needs attention.", "issues": []},
        "summary": [{"id": "sets", "label": "Sets", "value": 1, "tone": "warning"}],
        "metrics": [],
        "recent_activity": [],
        "details": {"protection_sets": [{
            "name": "documents",
            "kind": "backup",
            "protected_targets": 4,
            "unprotected_targets": 1,
            "copies": 2,
            "last_success_at": "2026-07-18T10:00:00Z",
            "next_run_at": "2026-07-19T02:00:00Z",
            "required_action": "Connect the offline destination",
        }]},
    }

    def handler(route):
        path = route.request.url.split("?", 1)[0]
        if path.endswith("/api/capabilities/storage.protection"):
            payload = {
                "schema_version": "1",
                "capability": {
                    "id": "storage.protection",
                    "surface": "protection",
                    "providers": [{
                        "id": "backup-provider",
                        "name": "Backup Provider",
                        "enabled": True,
                        "operational": False,
                        "renderer": {"id": "generic", "mode": "generic"},
                        "status": status,
                    }],
                },
                "errors": [],
            }
        elif path.endswith("/api/storage/plugins"):
            payload = {"plugins": []}
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/**", handler)
    page.goto(f"{base_url}/v2/protection")

    card = page.locator("[data-protection-set='documents']")
    expect(card).to_contain_text("Connect the offline destination")
    expect(card).to_contain_text("Backup Provider")
    card.get_by_role("link", name="Manage documents").click()
    expect(page).to_have_url(f"{base_url}/v2/protection/backup-provider")
    expect(page.locator("[data-capability-renderer='generic']")).to_be_visible()
    expect(page.get_by_role("heading", name="Backup Provider")).to_be_visible()
