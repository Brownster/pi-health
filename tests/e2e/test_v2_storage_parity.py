"""Storage extension compatibility and CP-013 Pools capability coverage.

Pinned to v2 UI mode; deterministic /api/storage/plugins* mocks (list, toggle,
detail, recovery 404, latest log, SSE command) keep the page reproducible.
"""

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_storage(page, base_url, route, v2_login, install_v2_storage_api_mocks):
    v2_login(page, base_url)
    install_v2_storage_api_mocks(page)
    page.goto(f"{base_url}/v2/{route}")
    expect(
        page.get_by_role("heading", name="storage_pools" if route == "pools" else "storage_plugins")
    ).to_be_visible()


def test_v2_storage_plugins_list_and_pools_tab(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Plugins tab shows both plugins.
    expect(page.get_by_text("MergerFS").first).to_be_visible()
    expect(page.get_by_text("Samba").first).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 storage plugins ({viewport_profile_name})")

    # Pools is now a capability-owned route, while the Plugins tab remains as a
    # compatibility path until CP-019.
    page.click("button[data-storage-tab='pools']")
    expect(page).to_have_url(f"{base_url}/v2/pools")
    expect(page.get_by_role("heading", name="storage_pools")).to_be_visible()
    expect(page.get_by_text("MergerFS").first).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)


def test_v2_storage_pools_route_defaults_to_pools_tab(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "pools", v2_login, install_v2_storage_api_mocks)
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


def test_v2_snapraid_guided_editor(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Unconfigured SnapRAID -> Set up opens the modal on the guided editor.
    page.click("button[data-plugin-action='details'][data-plugin='snapraid']")
    expect(page.locator("[data-snapraid-editor]")).to_be_visible()

    # Mounted /mnt/* disks from /api/disks are listed as assignable drives.
    expect(page.locator("[data-drive='/mnt/disk1']")).to_be_visible()
    expect(page.locator("[data-drive='/mnt/parity']")).to_be_visible()

    # Assign roles, then preview the generated snapraid.conf.
    page.select_option("select[data-drive-role='/mnt/disk1']", "data")
    page.select_option("select[data-drive-role='/mnt/parity']", "parity")
    page.get_by_role("button", name="Preview").click()
    expect(page.locator("[data-snapraid-preview]")).to_contain_text("parity", timeout=10000)

    # Schedule section (PH4-006): enabling sync reveals the cron row.
    expect(page.locator("[data-snapraid-schedule]")).to_be_visible()
    page.check("input[data-schedule-enabled='sync']")
    expect(page.locator("input[data-schedule-cron='sync']")).to_be_visible()

    # Advanced tab still exposes the raw JSON editor (fallback / third-party parity).
    page.click("button[data-config-view='advanced']")
    expect(page.locator("#v2-plugin-config-textarea")).to_be_visible()


def test_v2_snapraid_pre_sync_threshold_gate(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Open the SnapRAID detail and run Sync; the mock aborts over the delete threshold.
    page.click("button[data-plugin-action='details'][data-plugin='snapraid']")
    page.click("button[data-plugin-command='sync']")
    expect(page.locator("[data-command-threshold]")).to_be_visible(timeout=10000)
    expect(page.locator("#v2-plugin-command-output")).to_contain_text("51 files removed")

    # "Run anyway" retries with force; the run:pos tag (string values) drives the
    # progress bar — the regression that finding 1 fixed.
    page.click("button[data-command-force]")
    expect(page.locator("[data-command-progress]")).to_contain_text("42%", timeout=10000)
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)


def test_v2_mergerfs_pool_editor(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Unconfigured MergerFS -> Set up opens the modal on the guided pool editor.
    page.click("button[data-plugin-action='details'][data-plugin='mergerfs']")
    expect(page.locator("[data-mergerfs-editor]")).to_be_visible()

    # Build a two-branch pool without JSON.
    page.click("button[data-pool-add]")
    page.locator("input[data-pool-name]").fill("media")
    page.click("button[data-pool-branch-add$=':/mnt/disk1']")
    page.click("button[data-pool-branch-add$=':/mnt/parity']")
    page.click("button[data-mergerfs-save]")
    expect(page.get_by_text("Saved.")).to_be_visible(timeout=10000)

    # Apply warns about the fstab rewrite before proceeding.
    page.click("button[data-mergerfs-apply]")
    expect(page.locator("[data-apply-confirm]")).to_contain_text("fstab")
    page.click("button[data-apply-confirm-yes]")
    expect(page.get_by_text("Applied")).to_be_visible(timeout=10000)


def test_v2_storage_tab_syncs_with_shell_nav(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)
    expect(page.locator("button[data-storage-tab='plugins'][aria-pressed='true']")).to_be_visible()

    # Client-side nav via the shell nav link must switch the active tab.
    page.get_by_role("link", name="Pools").click()
    expect(page).to_have_url(f"{base_url}/v2/pools")
    expect(page.get_by_role("heading", name="storage_pools")).to_be_visible()
    expect(page.get_by_text("Samba")).to_have_count(0)


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


def test_v2_storage_remove_only_for_non_builtin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    # Builtin plugins cannot be removed (backend rejects it) -> no Remove control.
    expect(page.locator("button[data-plugin-action='remove'][data-plugin='mergerfs']")).to_have_count(0)
    expect(page.locator("button[data-plugin-action='remove'][data-plugin='samba']")).to_have_count(0)

    # A third-party (github) plugin can be removed, via confirm.
    page.click("button[data-plugin-action='remove'][data-plugin='customfs']")
    page.click("button[data-confirm-remove='customfs']")
    expect(page.get_by_text("Removed CustomFS")).to_be_visible(timeout=10000)


def test_v2_storage_toggle_plugin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='enable'][data-plugin='mergerfs']")
    expect(page.get_by_text("MergerFS enabled")).to_be_visible(timeout=10000)


def test_v2_storage_details_and_command(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='details'][data-plugin='mergerfs']")
    modal = page.locator("#v2-plugin-detail-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("Pool active")

    # Run a streamed plugin command (SSE over POST consumed via fetch reader).
    # `status` has no params and is not dangerous, so it runs on click.
    page.click("button[data-plugin-command='status']")
    expect(page.locator("#v2-plugin-command-output")).to_contain_text("checking pool mergerfs", timeout=10000)
    expect(page.locator("[data-command-summary]")).to_contain_text("Completed", timeout=10000)

    page.click("#v2-plugin-detail-close")
    expect(page.locator("#v2-plugin-detail-modal")).to_have_count(0)


def test_v2_storage_config_editor(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("button[data-plugin-action='details'][data-plugin='mergerfs']")
    expect(page.locator("#v2-plugin-detail-modal")).to_be_visible()

    # Pool plugins default to the guided editor; the raw JSON editor is the Advanced tab.
    page.click("button[data-config-view='advanced']")

    # Config editor is seeded with the plugin's JSON config and saves via /config.
    config_box = page.locator("#v2-plugin-config-textarea")
    expect(config_box).to_contain_text("mountpoint")
    config_box.fill('{"mountpoint": "/mnt/pool2"}')
    page.click("#v2-plugin-config-save")
    expect(page.locator("#v2-plugin-config-status")).to_have_text("Saved")


def test_v2_storage_install_plugin(
    page: Page,
    v2_server,
    v2_login,
    install_v2_storage_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_storage(page, base_url, "plugins", v2_login, install_v2_storage_api_mocks)

    page.click("#v2-plugin-install-open")
    expect(page.locator("#v2-plugin-install-modal")).to_be_visible()
    page.fill("input[data-install-field='source']", "https://github.com/example/newfs")
    page.click("#v2-plugin-install-submit")
    expect(page.get_by_text("Plugin installed")).to_be_visible()
    expect(page.locator("#v2-plugin-install-modal")).to_have_count(0)
