import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _open(
    page,
    base_url,
    v2_login,
    install_v2_integrations_api_mocks,
    *,
    installed=True,
    agent_installed=True,
    agent_authenticated=True,
    agent_configured=True,
):
    v2_login(page, base_url)
    install_v2_integrations_api_mocks(
        page,
        installed=installed,
        agent_installed=agent_installed,
        agent_authenticated=agent_authenticated,
        agent_configured=agent_configured,
    )
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


def test_agent_integration_views_are_separate_and_operational(
    profiled_page: Page,
    viewport_profile_name,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    page = profiled_page
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)

    agent = page.locator("[data-agent-integration]")
    expect(agent.get_by_role("heading", name="AI Agents")).to_be_visible()
    expect(agent.get_by_text("@limeos", exact=True)).to_be_visible()
    agent.get_by_role("tab", name="Providers").click()
    expect(agent.get_by_text("Claude Code", exact=True)).to_be_visible()
    expect(agent.get_by_text("Authenticated", exact=True)).to_be_visible()
    agent.get_by_role("tab", name="Permissions").click()
    expect(agent.get_by_text("container / logs", exact=True)).to_be_visible()
    expect(agent.get_by_text("shell.execute", exact=True)).to_be_visible()
    agent.get_by_role("tab", name="Usage").click()
    expect(agent.get_by_text("29", exact=True)).to_be_visible()
    expect(agent.get_by_text("system.status, container.logs", exact=True)).to_be_visible()
    agent.get_by_role("tab", name="Audit").click()
    expect(agent.get_by_text("holly", exact=True)).to_be_visible()
    expect(agent.get_by_text("84 ms", exact=True)).to_be_visible()
    assert_no_horizontal_overflow(page, f"agent integrations ({viewport_profile_name})")


def test_agent_setup_streams_progress_then_requests_claude_authentication(
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
        agent_installed=False,
    )

    page.locator("button[data-agent-setup]").click()
    page.get_by_label("Mattermost admin password").fill("long-test-password")
    page.locator("button[data-agent-install]").click()
    log = page.locator("[data-agent-operation-log]")
    expect(log).to_contain_text("Installing Claude Code")
    expect(log).to_contain_text("Preparing isolated agent runtime")
    expect(
        page.get_by_role("dialog", name="Set up AI Agents").get_by_role(
            "button", name="Authenticate Claude"
        )
    ).to_be_visible()


def test_disabling_agent_leaves_mattermost_connected(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)

    page.get_by_role("button", name="Disable", exact=True).click()
    page.get_by_role("button", name="Disable assistant").click()
    expect(page.get_by_text("AI Agents is disabled. Mattermost and alert delivery remain active.")).to_be_visible()
    expect(page.locator("[data-agent-integration]").get_by_text("disabled", exact=True)).to_be_visible()
    expect(page.get_by_text("connected", exact=True).first).to_be_visible()
    page.reload()
    expect(page.locator("[data-agent-integration]").get_by_text("disabled", exact=True)).to_be_visible()
    expect(page.get_by_text("connected", exact=True).first).to_be_visible()


def test_agent_authentication_recovers_after_browser_reload(
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
        agent_authenticated=False,
    )

    page.get_by_role("button", name="Authenticate Claude").click()
    dialog = page.get_by_role("dialog", name="Connect Claude Code")
    expect(dialog.get_by_text("Claude connected", exact=True)).to_be_visible()
    expect(dialog.get_by_role("link", name="Open Claude authorization")).not_to_be_visible()
    stored = page.evaluate(
        """() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})"""
    )
    assert "claude.ai" not in stored
    assert "short-lived" not in stored
    dialog.get_by_role("button", name="Done").click()
    page.reload()
    expect(page.locator("[data-agent-integration]").get_by_text("connected", exact=True)).to_be_visible()


def test_agent_repair_can_restore_partial_mattermost_configuration(
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
        agent_configured=False,
    )
    agent = page.locator("[data-agent-integration]")
    expect(agent.get_by_text("setup required", exact=True)).to_be_visible()
    agent.get_by_role("button", name="Repair", exact=True).click()
    dialog = page.get_by_role("dialog", name="Repair AI Agents")
    dialog.get_by_label("Repair Mattermost bot and configuration").check()
    dialog.get_by_label("Mattermost admin password").fill("long-test-password")
    dialog.locator("button[data-agent-repair]").click()
    expect(dialog.locator("[data-agent-operation-log]")).to_contain_text(
        "AI Agents repair completed"
    )
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(agent.get_by_text("connected", exact=True)).to_be_visible()
