"""CP-015 provider-neutral Protection capability coverage."""

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_protection(page, base_url, v2_login, install_mocks):
    v2_login(page, base_url)
    install_mocks(page)
    page.goto(f"{base_url}/v2/protection")
    expect(page.get_by_role("heading", name="storage_protection")).to_be_visible()


def test_v2_protection_legacy_snapraid_setup_and_deep_link(
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
    expect(page.locator("[data-capability-renderer='generic']")).to_be_visible()
    expect(page.get_by_text("Provider setup is required")).to_be_visible()
    expect(page.get_by_role("link", name="Configure provider")).to_have_attribute("href", "/v2/plugins")


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
