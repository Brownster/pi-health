import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _open(page, base_url, v2_login, install_v2_integrations_api_mocks, *, installed=True):
    v2_login(page, base_url)
    install_v2_integrations_api_mocks(page, installed=installed)
    page.goto(f"{base_url}/v2/integrations")
    expect(page.get_by_role("heading", name="integrations")).to_be_visible()


def test_integrations_policy_and_silence(
    profiled_page: Page,
    viewport_profile_name,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    page = profiled_page
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)

    page.get_by_role("tab", name="Alert policy").click()
    expect(page.get_by_text("container:jellyfin").or_(page.get_by_text("jellyfin", exact=True))).to_be_visible()
    page.get_by_role("button", name="Silence container:jellyfin").click()
    expect(page.get_by_role("heading", name="Silence container:jellyfin")).to_be_visible()
    page.get_by_role("button", name="Silence", exact=True).click()
    expect(page.get_by_text("container:jellyfin silenced.")).to_be_visible()
    assert_no_horizontal_overflow(page, f"integrations ({viewport_profile_name})")


def test_integrations_setup_streams_progress(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    _open(
        page,
        v2_server["base_url"],
        v2_login,
        install_v2_integrations_api_mocks,
        installed=False,
    )

    page.locator("button[data-mattermost-setup]").click()
    page.get_by_label("Admin email").fill("admin@example.test")
    page.get_by_label("Admin password").fill("long-test-password")
    page.locator("button[data-mattermost-install]").click()
    expect(page.locator("[data-mattermost-install-log]")).to_contain_text(
        "Starting Postgres and Mattermost"
    )
    expect(page.locator("[data-mattermost-install-log]")).to_contain_text(
        "Mattermost and LimeOS alerts are ready"
    )


def test_integrations_setup_reports_stream_error_without_success(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    v2_login(page, v2_server["base_url"])
    install_v2_integrations_api_mocks(page, installed=False, install_error=True)
    page.goto(f"{v2_server['base_url']}/v2/integrations")

    page.locator("button[data-mattermost-setup]").click()
    page.get_by_label("Admin email").fill("admin@example.test")
    page.get_by_label("Admin password").fill("long-test-password")
    page.locator("button[data-mattermost-install]").click()

    expect(page.get_by_text("Setup failed")).to_be_visible()
    expect(page.get_by_text("Mattermost and LimeOS alerts are connected.")).not_to_be_visible()
    expect(page.get_by_text("no matching ARM64 manifest").first).to_be_visible()
