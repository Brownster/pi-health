"""PH3-004: v2 disks parity suite (read path + SMART views).

Pinned to v2 UI mode; deterministic /api/disks* mocks (inventory, helper status,
SMART summary + per-device SMART) keep the page reproducible without the
privileged helper or a real disk.
"""

import json
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks):
    v2_login(page, base_url)
    install_v2_disks_api_mocks(page)
    page.goto(f"{base_url}/v2/disks")
    expect(page.get_by_role("heading", name="disk_management")).to_be_visible()


def test_v2_disks_inventory_renders(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    expect(page.get_by_text("/dev/sda").first).to_be_visible()
    expect(page.get_by_text("/mnt/storage").first).to_be_visible()
    usage = page.locator("[data-disk-usage='sda']")
    expect(usage).to_contain_text("65% used")
    expect(usage).to_contain_text("Used 4.7 TB")
    expect(usage).to_contain_text("Free 2.5 TB")
    expect(usage.get_by_role("progressbar")).to_have_attribute("aria-valuenow", "65")
    # SMART summary badge merged onto the disk card.
    expect(page.get_by_text("healthy").first).to_be_visible()
    summary = page.locator("[data-disk-summary]")
    expect(summary).to_contain_text("1 healthy")
    expect(summary).to_contain_text("4.7 TB used")
    expect(summary).to_contain_text("2.5 TB free")
    expect(page.get_by_role("link", name="Media")).to_have_attribute("href", "/v2/pools")
    assert_no_horizontal_overflow(page, f"v2 disks ({viewport_profile_name})")


def test_v2_disks_smart_modal(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    page = profiled_page
    base_url = v2_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    page.locator("button[data-disk-action='smart'][data-disk='sda']:visible").first.click()
    modal = page.locator("#v2-disk-smart-modal")
    expect(modal).to_be_visible()
    expect(page.locator("#v2-disk-smart-content")).to_contain_text("38 °C")
    expect(page.locator("#v2-disk-smart-content")).to_contain_text("1234")
    assert_no_horizontal_overflow(page, f"v2 SMART details ({viewport_profile_name})")
    page.click("#v2-disk-smart-close")
    expect(page.locator("#v2-disk-smart-modal")).to_have_count(0)


def test_v2_disks_helper_unavailable_state(page: Page, v2_server, v2_login):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)

    def _handler(route):
        path = urlparse(route.request.url).path
        if path == "/api/disks":
            body = {"disks": [], "helper_available": False}
        elif path == "/api/disks/helper-status":
            body = {"available": False, "socket_path": "/run/pihealth.sock"}
        elif path == "/api/disks/smart":
            body = {"disks": []}
        else:
            route.continue_()
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/**", _handler)
    page.goto(f"{base_url}/v2/disks")
    expect(page.get_by_role("heading", name="disk_management")).to_be_visible()

    # Helper-unavailable surfaces as a warning, NOT a misleading "No disks found." empty state.
    expect(page.get_by_text("Privileged helper unavailable")).to_be_visible()
    expect(page.get_by_text("No disks found.")).to_have_count(0)


def test_v2_disks_suggested_mount_with_confirm(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    suggestions = page.get_by_role("region", name="Suggested mounts")
    expect(suggestions).to_be_visible()
    expect(suggestions).to_contain_text("1 suggested mount")
    page.click("button[data-mount='sdb-uuid-1']")
    page.click("button[data-confirm-mount='sdb-uuid-1']")
    expect(page.get_by_text("Mounted /dev/sdb1 at /mnt/backup")).to_be_visible(timeout=10000)
    mount_request = next(
        request for request in requests
        if request.method == "POST" and request.url.endswith("/api/disks/mount")
    )
    assert mount_request.post_data_json == {
        "uuid": "sdb-uuid-1",
        "mountpoint": "/mnt/backup",
        "fstype": "ext4",
        "add_to_fstab": True,
    }


def test_v2_disks_mount_confirmation_can_be_cancelled(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    page.click("button[data-mount='sdb-uuid-1']")
    page.get_by_role("button", name="Cancel").click()

    assert not any(
        request.method == "POST" and request.url.endswith("/api/disks/mount")
        for request in requests
    )


def test_v2_disks_unmount_with_confirm(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    page.click("button[data-disk-menu='sda']")
    page.click("button[data-unmount='/mnt/storage']")
    page.click("button[data-confirm-unmount='/mnt/storage']")
    expect(page.get_by_text("Unmounted /mnt/storage")).to_be_visible(timeout=10000)


def test_v2_disks_preserves_json_error_guidance(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_disks_api_mocks(
        page,
        {
            ("POST", "/api/disks/unmount"): (
                409,
                "application/json",
                {
                    "code": "mount_in_use",
                    "error": "Unmount blocked",
                    "message": "Stop dependent containers and retry",
                    "details": ["container: media"],
                },
            )
        },
    )
    page.goto(f"{base_url}/v2/disks")

    page.click("button[data-disk-menu='sda']")
    page.click("button[data-unmount='/mnt/storage']")
    page.click("button[data-confirm-unmount='/mnt/storage']")

    expect(
        page.get_by_text(
            "Unmount blocked: Stop dependent containers and retry (container: media)"
        )
    ).to_be_visible()


def test_v2_disks_preserves_text_error(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    install_v2_disks_api_mocks(
        page,
        {
            ("POST", "/api/disks/mount"): (
                503,
                "text/plain",
                "Mount helper unavailable; reconnect the helper service",
            )
        },
    )
    page.goto(f"{base_url}/v2/disks")

    page.click("button[data-mount='sdb-uuid-1']")
    page.click("button[data-confirm-mount='sdb-uuid-1']")

    expect(
        page.get_by_text("Mount helper unavailable; reconnect the helper service")
    ).to_be_visible()


def test_v2_disks_smart_self_test_with_confirm(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)

    page.locator("button[data-disk-action='smart'][data-disk='sda']:visible").first.click()
    expect(page.locator("#v2-disk-smart-modal")).to_be_visible()
    page.click("button[data-smarttest='short']")
    page.click("button[data-confirm-smarttest='short']")
    modal = page.locator("#v2-disk-smart-modal")
    expect(modal.get_by_text("SMART short self-test started")).to_be_visible(timeout=10000)
    assert sum(
        request.method == "GET" and urlparse(request.url).path == "/api/disks"
        for request in requests
    ) == 1


def test_v2_disks_smart_failure_can_retry_in_place(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)
    attempts = 0

    def _smart_handler(route):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"error": "SMART helper is unavailable"}),
            )
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "device": "/dev/sda",
                    "model": "WDC WD80EDAZ-11CEWB0",
                    "health_status": "healthy",
                    "temperature_c": 38,
                }
            ),
        )

    page.route("**/api/disks/sda/smart", _smart_handler)
    page.locator("button[data-disk-action='smart'][data-disk='sda']:visible").first.click()

    modal = page.locator("#v2-disk-smart-modal")
    expect(modal.get_by_text("SMART helper is unavailable")).to_be_visible()
    modal.get_by_role("button", name="Retry SMART details").click()
    expect(page.locator("#v2-disk-smart-content")).to_contain_text("38 °C")
    assert attempts == 2


def test_v2_disks_failed_refresh_keeps_visible_inventory_with_warning(
    page: Page,
    v2_server,
    v2_login,
    install_v2_disks_api_mocks,
):
    base_url = v2_server["base_url"]
    _open_v2_disks(page, base_url, v2_login, install_v2_disks_api_mocks)
    expect(page.get_by_text("/dev/sda").first).to_be_visible()

    page.route(
        "**/api/disks",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"error": "Disk inventory is temporarily unavailable"}),
        ),
    )
    page.get_by_role("button", name="refresh").click()

    expect(page.get_by_text("Refresh failed. Showing data synced")).to_be_visible()
    expect(page.get_by_text("/dev/sda").first).to_be_visible()
