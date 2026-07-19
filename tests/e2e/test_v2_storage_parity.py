"""CP-013/14 Pools coverage and the CP-019 Plugins route cutover."""

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_pools(page, base_url, v2_login, install_v2_storage_api_mocks):
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)
    page.goto(f"{base_url}/v2/pools")
    expect(page.get_by_role("heading", name="storage_pools")).to_be_visible()


def test_v2_plugins_redirects_to_advanced_extensions(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_extensions_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_extensions_api_mocks(page)
    page.goto(f"{base_url}/v2/plugins")

    expect(page).to_have_url(f"{base_url}/v2/settings/extensions")
    expect(page.get_by_role("heading", name="extensions")).to_be_visible()
    if viewport_profile_name in ("phone", "tablet"):
        page.get_by_role("button", name="Open navigation").click()
    primary_nav = page.get_by_role("navigation", name="Primary")
    expect(primary_nav.get_by_role("link", name="Plugins")).to_have_count(0)
    expect(primary_nav.get_by_role("link", name="Settings")).to_have_attribute(
        "aria-current", "page"
    )
    if viewport_profile_name in ("phone", "tablet"):
        page.get_by_role("button", name="Close navigation").click()
    assert_no_horizontal_overflow(page, f"v2 extensions redirect ({viewport_profile_name})")


def test_v2_storage_pools_route_defaults_to_pools_tab(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_pools(page, base_url, v2_login, install_v2_storage_api_mocks)
    # The disabled legacy MergerFS adapter is discoverable, but does not create an
    # operational pool card or expose SnapRAID as pooling.
    expect(page.locator("[data-pools-empty]")).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)
    expect(page.locator("[data-pool-provider-row='mergerfs']")).to_contain_text("disabled")
    expect(page.get_by_text("SnapRAID")).to_have_count(0)


def test_v2_pools_configured_cards_across_viewports(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_storage_configured_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_configured_mocks(page)
    page.goto(f"{base_url}/v2/pools")
    expect(page.get_by_role("heading", name="storage_pools")).to_be_visible()

    # MergerFS remains operational through the read-only compatibility adapter;
    # SnapRAID is reserved for the Protection domain.
    expect(page.locator("[data-pool-summary]")).to_contain_text("2")
    expect(page.get_by_text("SnapRAID")).to_have_count(0)
    mounted = page.locator("[data-pool-card='media']")
    expect(mounted).to_contain_text("mounted")
    expect(mounted.get_by_text("3", exact=True)).to_be_visible()
    expect(mounted.locator("[role='progressbar']")).to_have_attribute("aria-valuenow", "42")
    expect(page.locator("[data-pool-card='backup']")).to_contain_text("unmounted")

    assert_no_horizontal_overflow(page, f"v2 pools configured ({viewport_profile_name})")


def test_v2_snapraid_pre_sync_threshold_gate(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)
    page.goto(f"{base_url}/v2/protection/snapraid")

    expect(page.locator("[data-capability-renderer='snapraid']")).to_be_visible()
    page.click("button[data-snapraid-tab='operations']")
    page.click("button[data-plugin-command='sync']")
    page.click("button[data-command-confirm='sync']")
    expect(page.locator("[data-command-threshold]")).to_be_visible(timeout=10000)
    expect(page.locator("#v2-plugin-command-output")).to_contain_text("51 files removed")

    # "Run anyway" retries with force; the run:pos tag (string values) drives the
    # progress bar — the regression that finding 1 fixed.
    page.click("button[data-command-force]")
    expect(page.locator("[data-command-progress]")).to_contain_text("42%", timeout=10000)
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)


def test_v2_mergerfs_provider_editor_preview_and_apply(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)
    page.goto(f"{base_url}/v2/pools/mergerfs")

    expect(page.locator("[data-capability-renderer='mergerfs']")).to_be_visible()
    expect(page.locator("button[data-mergerfs-tab='configuration'][aria-selected='true']")).to_be_visible()
    expect(page.locator("[data-mergerfs-editor]")).to_be_visible()

    # Build a two-branch pool, verify branch ordering, and preview fstab without writing it.
    page.click("button[data-pool-add]")
    page.locator("input[data-pool-name]").fill("media")
    page.click("button[data-pool-branch-add$=':/mnt/disk1']")
    page.click("button[data-pool-branch-add$=':/mnt/parity']")
    branches = page.locator("[data-pool-branches] li")
    expect(branches.nth(0)).to_contain_text("/mnt/disk1")
    expect(branches.nth(1)).to_contain_text("/mnt/parity")
    page.get_by_role("button", name="Move /mnt/parity up").click()
    expect(branches.nth(0)).to_contain_text("/mnt/parity")
    page.click("button[data-mergerfs-preview-open]")
    expect(page.locator("[data-mergerfs-preview]")).to_contain_text("pi-health mergerfs start", timeout=10000)

    page.click("button[data-mergerfs-save]")
    expect(page.get_by_text("Saved.")).to_be_visible(timeout=10000)

    # Apply warns about the fstab rewrite before proceeding.
    page.click("button[data-mergerfs-apply]")
    expect(page.locator("[data-apply-confirm]")).to_contain_text("fstab")
    page.click("button[data-apply-confirm-yes]")
    expect(page.get_by_text("Applied")).to_be_visible(timeout=10000)


def test_v2_mergerfs_provider_operations_and_diagnostics(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_configured_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_configured_mocks(page)
    page.goto(f"{base_url}/v2/pools/mergerfs")

    expect(page.locator("[data-capability-renderer='mergerfs']")).to_be_visible()
    expect(page.locator("[data-pool-card='media']")).to_contain_text("mounted")
    expect(page.locator("[data-pool-card='backup']")).to_contain_text("unmounted")

    overview_tab = page.locator("button[data-mergerfs-tab='overview']")
    overview_tab.focus()
    overview_tab.press("End")
    expect(page.locator("button[data-mergerfs-tab='diagnostics']")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.locator("button[data-mergerfs-tab='diagnostics']")).to_be_focused()
    page.locator("button[data-mergerfs-tab='diagnostics']").press("Home")
    expect(overview_tab).to_have_attribute("aria-selected", "true")
    expect(overview_tab).to_be_focused()

    # Pool operations use the provider's declared pool selector. Unmount adds a
    # resource-specific interruption warning before the command can run.
    page.click("button[data-plugin-command='mount']")
    expect(page.locator("select[data-command-param='pool_name']")).to_have_value("backup")
    page.click("button[data-command-run='mount']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    page.click("button[data-plugin-command='unmount']")
    page.locator("select[data-command-param='pool_name']").select_option("media")
    page.click("button[data-command-run='unmount']")
    expect(page.get_by_text("Unmounting can interrupt applications using this pool.")).to_be_visible()
    page.click("button[data-command-confirm='unmount']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    expect(page.locator("button[data-plugin-command='balance']")).to_be_visible()
    page.click("button[data-mergerfs-tab='diagnostics']")
    expect(page.locator("[data-mergerfs-log]")).to_contain_text("log line", timeout=10000)
    page.click("button[data-plugin-command='status']")
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)


def test_v2_pools_generic_capability_provider_and_deep_link(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)

    status = {
        "schema_version": "1",
        "provider_id": "openpool",
        "capability_id": "storage.pooling",
        "observed_at": "2026-07-18T12:00:00Z",
        "lifecycle": {
            "installed": True,
            "enabled": True,
            "configured": True,
            "compatibility": "compatible",
            "availability": "available",
        },
        "health": {"state": "healthy", "message": "Pool is available.", "issues": []},
        "summary": [{"id": "pools", "label": "Pools", "value": 1, "tone": "success"}],
        "metrics": [],
        "recent_activity": [],
        "details": {"pools": [{
            "name": "archive",
            "mount_point": "/mnt/archive",
            "mounted": True,
            "branches": 2,
            "policy": "most-free-space",
            "total_bytes": 2000000000000,
            "free_bytes": 1500000000000,
        }]},
    }

    def capability(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "schema_version": "1",
                "capability": {
                    "id": "storage.pooling",
                    "surface": "pools",
                    "providers": [{
                        "id": "openpool",
                        "name": "OpenPool",
                        "enabled": True,
                        "operational": True,
                        "renderer": {"id": "generic", "mode": "generic"},
                        "status": status,
                    }],
                },
                "errors": [],
            }),
        )

    page.route("**/api/capabilities/storage.pooling", capability)
    page.goto(f"{base_url}/v2/pools")

    archive = page.locator("[data-pool-card='archive']")
    expect(archive).to_contain_text("most-free-space")
    expect(archive).to_contain_text("OpenPool")
    archive.get_by_role("link", name="Manage archive").click()
    expect(page).to_have_url(f"{base_url}/v2/pools/openpool")
    expect(page.locator("[data-capability-renderer='generic']")).to_be_visible()
    expect(page.get_by_role("heading", name="OpenPool")).to_be_visible()
