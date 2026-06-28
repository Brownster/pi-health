"""v2 App Catalog page (nasOS redesign expansion)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks):
    v2_login(page, base_url)
    install_v2_catalog_api_mocks(page)
    page.goto(f"{base_url}/v2/apps")
    expect(page.get_by_role("heading", name="app_catalog", exact=True)).to_be_visible()


def test_v2_catalog_render(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    expect(page.get_by_text("Jellyfin").first).to_be_visible()
    expect(page.get_by_text("installed").first).to_be_visible()
    jellyfin_installations = page.get_by_label("Jellyfin installations")
    expect(jellyfin_installations.get_by_text("family", exact=True)).to_be_visible()
    expect(jellyfin_installations.get_by_text("media", exact=True)).to_be_visible()
    expect(page.get_by_text("requires: vpn")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 catalog ({viewport_profile_name})")

    page.click("button[data-catalog-action='install'][data-item='sonarr']")
    expect(page.locator("#v2-catalog-install-modal")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 catalog install modal ({viewport_profile_name})")


def test_v2_catalog_install_with_fields(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='install'][data-item='sonarr']")
    expect(page.locator("#v2-catalog-install-modal")).to_be_visible()
    expect(page.locator("input[data-install-field='PORT']")).to_have_value("8989")
    expect(page.locator("select[data-install-target]")).to_have_value("media")
    page.click("#v2-catalog-install-submit")
    expect(page.get_by_text("Installed Sonarr")).to_be_visible()
    install_request = next(
        request for request in requests
        if request.method == "POST" and request.url.endswith("/api/catalog/install")
    )
    assert install_request.post_data_json["target_stack"] == "media"
    assert install_request.post_data_json["stack_name"] == ""
    assert any(
        request.method == "GET" and request.url.endswith("/api/catalog/operations/mock-catalog-operation/stream")
        for request in requests
    )


def test_v2_catalog_install_into_named_new_stack(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='install'][data-item='jellyfin']")
    expect(page.locator("select[data-install-target]")).to_have_value("new")
    stack_name = page.locator("input[data-install-stack-name]")
    expect(stack_name).to_have_value("jellyfin")
    stack_name.fill("jellyfin-kids")
    page.click("#v2-catalog-install-submit")
    expect(page.get_by_text("Installed Jellyfin")).to_be_visible()

    install_request = next(
        request for request in requests
        if request.method == "POST" and request.url.endswith("/api/catalog/install")
    )
    assert install_request.post_data_json["target_stack"] == "new"
    assert install_request.post_data_json["stack_name"] == "jellyfin-kids"


def test_v2_catalog_install_keeps_focus_while_typing(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='install'][data-item='sonarr']")
    field = page.locator("input[data-install-field='PORT']")
    field.click()
    field.press("ControlOrMeta+A")
    field.press_sequentially("12345", delay=25)

    expect(field).to_be_focused()
    expect(field).to_have_value("12345")


def test_v2_catalog_remove_with_confirm(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_catalog_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open_v2_catalog(page, base_url, v2_login, install_v2_catalog_api_mocks)

    page.click("button[data-catalog-action='remove'][data-item='jellyfin'][data-stack='media']")
    page.click("button[data-confirm-remove='jellyfin'][data-stack='media']")
    expect(page.get_by_text("Removed Jellyfin from media")).to_be_visible()
    remove_request = next(
        request for request in requests
        if request.method == "POST" and request.url.endswith("/api/catalog/remove")
    )
    assert remove_request.post_data_json == {
        "id": "jellyfin",
        "stop_service": True,
        "target_stack": "media",
    }
