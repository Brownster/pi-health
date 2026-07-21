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
    **mock_options,
):
    v2_login(page, base_url)
    install_v2_integrations_api_mocks(
        page,
        installed=installed,
        agent_installed=agent_installed,
        agent_authenticated=agent_authenticated,
        agent_configured=agent_configured,
        **mock_options,
    )
    page.goto(f"{base_url}/v2/integrations")
    expect(page.get_by_role("heading", name="integrations")).to_be_visible()


def _open_agent_manage_menu(page: Page):
    trigger = page.locator("[data-agent-lifecycle-menu-trigger='agents']")
    trigger.click()
    menu = page.locator("[data-agent-lifecycle-menu='agents']")
    expect(menu).to_be_visible()
    return trigger, menu


def _open_mattermost_manage_menu(page: Page):
    trigger = page.locator("[data-mattermost-lifecycle-menu-trigger='mattermost']")
    trigger.click()
    menu = page.locator("[data-mattermost-lifecycle-menu='mattermost']")
    expect(menu).to_be_visible()
    return trigger, menu


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


def test_mattermost_dependency_blocker_moves_focus_to_ai_agents(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)

    _, menu = _open_mattermost_manage_menu(page)
    expect(menu.get_by_role("menuitem", name="Disable (AI Agents first)")).to_be_visible()
    expect(menu.get_by_role("menuitem", name="Uninstall (AI Agents first)")).to_be_visible()
    menu.get_by_role("menuitem", name="Disable (AI Agents first)").click()
    dialog = page.get_by_role("dialog", name="Disable AI Agents first")
    expect(dialog).to_contain_text("Disable AI Agents before stopping Mattermost.")
    dialog.locator("[data-mattermost-go-to-agents]").click()
    expect(page.locator("#ai-agents")).to_be_focused()


def test_mattermost_disable_and_enable_use_server_authorized_actions(
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
        agent_enabled=False,
    )

    _, menu = _open_mattermost_manage_menu(page)
    menu.get_by_role("menuitem", name="Disable", exact=True).click()
    dialog = page.get_by_role("dialog", name="Disable Mattermost?")
    expect(dialog).to_contain_text("complete Mattermost stack and alert delivery")
    dialog.get_by_role("button", name="Disable Mattermost").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    dialog.get_by_role("button", name="Close", exact=True).click()
    mattermost = page.locator("[data-mattermost-integration]")
    expect(mattermost.get_by_text("disabled", exact=True).first).to_be_visible()
    expect(mattermost.get_by_text("Chat, alert delivery, and the full managed stack are stopped.")).to_be_visible()

    _, menu = _open_mattermost_manage_menu(page)
    menu.get_by_role("menuitem", name="Enable", exact=True).click()
    dialog = page.get_by_role("dialog", name="Enable Mattermost?")
    dialog.get_by_role("button", name="Enable Mattermost").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(mattermost.get_by_text("connected", exact=True).first).to_be_visible()


def test_mattermost_uninstall_retains_data_without_inferring_purge(
    profiled_page: Page,
    viewport_profile_name,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    page = profiled_page
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open(
        page,
        v2_server["base_url"],
        v2_login,
        install_v2_integrations_api_mocks,
        agent_installed=False,
    )

    _, menu = _open_mattermost_manage_menu(page)
    menu.get_by_role("menuitem", name="Uninstall", exact=True).click()
    dialog = page.get_by_role("dialog", name="Uninstall Mattermost?")
    expect(dialog).to_contain_text("Database records, messages, uploads, plugins")
    expect(dialog.locator("[data-lifecycle-confirm]")).to_be_disabled()
    dialog.locator("[data-lifecycle-confirmation]").fill("Mattermost")
    dialog.locator("[data-lifecycle-confirm]").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    assert_no_horizontal_overflow(page, f"Mattermost uninstall ({viewport_profile_name})")
    request = next(
        item for item in requests
        if item.method == "POST" and item.url.endswith("/api/integrations/mattermost/uninstall")
    )
    assert request.post_data_json == {"confirmation": "Mattermost"}
    dialog.get_by_role("button", name="Close", exact=True).click()

    mattermost = page.locator("[data-mattermost-integration]")
    expect(mattermost.get_by_text("retained data", exact=True)).to_be_visible()
    expect(mattermost.locator("[data-mattermost-retained-setup]")).to_be_visible()
    expect(mattermost.locator("[data-mattermost-purge]")).to_have_count(0)
    expect(mattermost.get_by_text("Permanent data deletion is not available in this release.")).to_be_visible()
    expect(mattermost).to_be_focused()


def test_mattermost_purge_requires_release_action_confirmation_and_acknowledgement(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open(
        page,
        v2_server["base_url"],
        v2_login,
        install_v2_integrations_api_mocks,
        mattermost_retained_data=True,
        mattermost_purge_enabled=True,
        agent_installed=False,
    )

    page.locator("[data-mattermost-purge]").click()
    dialog = page.get_by_role("dialog", name="Delete retained Mattermost data?")
    expect(dialog).to_contain_text("database records, messages, uploads, plugins, retained logs")
    confirm = dialog.locator("[data-lifecycle-confirm]")
    expect(confirm).to_be_disabled()
    dialog.locator("[data-lifecycle-confirmation]").fill("Mattermost")
    expect(confirm).to_be_disabled()
    dialog.locator("[data-lifecycle-acknowledgement]").check()
    confirm.click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    request = next(
        item for item in requests
        if item.method == "POST" and item.url.endswith("/api/integrations/mattermost/purge")
    )
    assert request.post_data_json == {
        "confirmation": "Mattermost",
        "acknowledge_data_loss": True,
    }
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(page.locator("[data-mattermost-integration]").get_by_text("not installed", exact=True)).to_be_visible()


def test_mattermost_cleanup_required_can_resume_after_refresh(
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
        mattermost_cleanup_action="disable",
        agent_installed=False,
    )
    mattermost = page.locator("[data-mattermost-integration]")
    expect(mattermost.get_by_text("Cleanup needs attention", exact=True)).to_be_visible()
    mattermost.locator("[data-mattermost-retry-cleanup]").click()
    dialog = page.get_by_role("dialog", name="Retry Mattermost disable")
    dialog.get_by_role("button", name="Retry disable").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(mattermost.get_by_text("disabled", exact=True).first).to_be_visible()


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
    overview_tab = agent.get_by_role("tab", name="Overview")
    overview_tab.focus()
    overview_tab.press("ArrowRight")
    expect(agent.get_by_role("tab", name="Providers")).to_be_focused()
    expect(agent.get_by_role("tabpanel")).to_have_attribute(
        "aria-labelledby", "agent-tab-providers"
    )
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

    trigger, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Disable", exact=True).click()
    page.get_by_role("button", name="Disable assistant").click()
    expect(page.get_by_role("dialog", name="Disable AI Agents?")).to_contain_text(
        "Operation completed"
    )
    page.get_by_role("dialog", name="Disable AI Agents?").get_by_role(
        "button", name="Close", exact=True
    ).click()
    expect(page.get_by_text("AI Agents is disabled. Mattermost and alert delivery remain active.")).to_be_visible()
    expect(page.locator("[data-agent-integration]").get_by_text("disabled", exact=True)).to_be_visible()
    expect(trigger).to_be_focused()
    expect(page.get_by_text("connected", exact=True).first).to_be_visible()


def test_agent_lifecycle_failure_retains_progress_retries_and_refreshes_both_cards(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    requests = []
    page.on("request", lambda request: requests.append(request))
    v2_login(page, v2_server["base_url"])
    install_v2_integrations_api_mocks(page, agent_disable_fails_once=True)
    page.goto(f"{v2_server['base_url']}/v2/integrations")
    expect(page.get_by_role("heading", name="integrations")).to_be_visible()
    expect(page.get_by_text("connected", exact=True).first).to_be_visible()
    expect(
        page.locator("[data-agent-integration]").get_by_text(
            "connected", exact=True
        )
    ).to_be_visible()
    initial_agent_reads = len([
        request for request in requests
        if request.method == "GET" and request.url.endswith("/api/integrations/agents")
    ])
    initial_mattermost_reads = len([
        request for request in requests
        if request.method == "GET" and request.url.endswith("/api/integrations/mattermost")
    ])

    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Disable", exact=True).click()
    dialog = page.get_by_role("dialog", name="Disable AI Agents?")
    dialog.get_by_role("button", name="Disable assistant").click()
    expect(dialog.get_by_role("alert")).to_contain_text(
        "AI Agents lifecycle operation failed"
    )
    expect(dialog.locator("[data-lifecycle-progress]")).to_contain_text(
        "Stopping AI Agents"
    )
    expect(dialog.get_by_role("button", name="Retry")).to_be_visible()
    expect(page.get_by_text("Cleanup needs attention", exact=True)).to_be_visible()

    dialog.get_by_role("button", name="Retry").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    expect(page.locator("[data-agent-integration]").get_by_text("disabled", exact=True)).to_be_visible()
    assert len([
        request for request in requests
        if request.method == "GET" and request.url.endswith("/api/integrations/agents")
    ]) >= initial_agent_reads + 2
    assert len([
        request for request in requests
        if request.method == "GET" and request.url.endswith("/api/integrations/mattermost")
    ]) >= initial_mattermost_reads + 2
    page.reload()
    expect(page.locator("[data-agent-integration]").get_by_text("disabled", exact=True)).to_be_visible()
    expect(page.get_by_text("connected", exact=True).first).to_be_visible()


def test_agent_enable_and_repair_uses_server_authorized_action(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)
    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Disable", exact=True).click()
    page.get_by_role("button", name="Disable assistant").click()
    dialog = page.get_by_role("dialog", name="Disable AI Agents?")
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    dialog.get_by_role("button", name="Close", exact=True).click()

    _, menu = _open_agent_manage_menu(page)
    expect(menu.get_by_role("menuitem", name="Enable and repair")).to_be_visible()
    menu.get_by_role("menuitem", name="Enable and repair").click()
    repair = page.get_by_role("dialog", name="Repair AI Agents")
    repair.locator("[data-agent-repair]").click()
    expect(repair).to_contain_text("Operation finished")
    expect(page.locator("[data-agent-integration]").get_by_text("connected", exact=True)).to_be_visible()


def test_agent_uninstall_requires_confirmation_and_clears_password(
    profiled_page: Page,
    viewport_profile_name,
    assert_no_horizontal_overflow,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    page = profiled_page
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)

    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Uninstall", exact=True).click()
    dialog = page.get_by_role("dialog", name="Uninstall AI Agents?")
    expect(dialog).to_contain_text("Mattermost, alert delivery, channels, messages")
    expect(dialog.locator("[data-agent-remove-claude]")).to_be_checked()
    confirm = dialog.locator("[data-lifecycle-confirm]")
    expect(confirm).to_be_disabled()
    dialog.locator("[data-agent-uninstall-password]").fill("first-test-password")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Uninstall", exact=True).click()
    dialog = page.get_by_role("dialog", name="Uninstall AI Agents?")
    expect(dialog.locator("[data-agent-uninstall-password]")).to_have_value("")
    assert_no_horizontal_overflow(page, f"AI Agents uninstall ({viewport_profile_name})")
    confirm = dialog.locator("[data-lifecycle-confirm]")
    dialog.locator("[data-agent-uninstall-password]").fill("first-test-password")
    dialog.locator("[data-lifecycle-confirmation]").fill("AI Agents")
    confirm.click()

    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    uninstall_request = next(
        request for request in requests
        if request.method == "POST" and request.url.endswith("/api/integrations/agents/uninstall")
    )
    assert uninstall_request.post_data_json == {
        "confirmation": "AI Agents",
        "admin_username": "limeadmin",
        "admin_password": "first-test-password",
        "remove_claude_code": True,
    }
    stored = page.evaluate(
        """() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})"""
    )
    assert "first-test-password" not in stored
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(page.locator("[data-agent-integration]").get_by_text("not installed", exact=True)).to_be_visible()
    expect(page.locator("[data-agent-setup]")).to_be_visible()
    expect(page.locator("#ai-agents")).to_be_focused()


def test_agent_uninstall_failure_requires_fresh_credentials_for_retry(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    requests = []
    page.on("request", lambda request: requests.append(request))
    _open(
        page,
        v2_server["base_url"],
        v2_login,
        install_v2_integrations_api_mocks,
        agent_uninstall_fails_once=True,
    )
    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Uninstall", exact=True).click()
    dialog = page.get_by_role("dialog", name="Uninstall AI Agents?")
    dialog.locator("[data-agent-uninstall-password]").fill("first-test-password")
    dialog.locator("[data-lifecycle-confirmation]").fill("AI Agents")
    dialog.locator("[data-lifecycle-confirm]").click()
    expect(dialog.get_by_role("alert")).to_contain_text("AI Agents lifecycle operation failed")
    expect(page.get_by_text("Cleanup needs attention", exact=True)).to_be_visible()

    dialog.get_by_role("button", name="Retry").click()
    retry = page.get_by_role("dialog", name="Retry AI Agents uninstall")
    expect(retry.locator("[data-agent-uninstall-password]")).to_have_value("")
    expect(retry.locator("[data-lifecycle-confirmation]")).to_have_value("")
    retry.locator("[data-agent-uninstall-password]").fill("second-test-password")
    retry.locator("[data-lifecycle-confirmation]").fill("AI Agents")
    retry.locator("[data-lifecycle-confirm]").click()
    expect(retry.get_by_role("status")).to_contain_text("Operation completed")

    payloads = [
        request.post_data_json for request in requests
        if request.method == "POST" and request.url.endswith("/api/integrations/agents/uninstall")
    ]
    assert [payload["admin_password"] for payload in payloads] == [
        "first-test-password",
        "second-test-password",
    ]


def test_agent_uninstall_remote_bot_warning_remains_distinct(
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
        agent_uninstall_warning=True,
    )
    _, menu = _open_agent_manage_menu(page)
    menu.get_by_role("menuitem", name="Uninstall", exact=True).click()
    dialog = page.get_by_role("dialog", name="Uninstall AI Agents?")
    dialog.locator("[data-agent-uninstall-password]").fill("warning-test-password")
    dialog.locator("[data-lifecycle-confirmation]").fill("AI Agents")
    dialog.locator("[data-lifecycle-confirm]").click()

    expect(dialog.get_by_role("status")).to_contain_text("attention needed")
    expect(dialog.locator("[data-lifecycle-warnings]")).to_contain_text(
        "Mattermost bot could not be removed"
    )
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(page.locator("[data-agent-lifecycle-warnings]")).to_contain_text(
        "Mattermost bot could not be removed"
    )


def test_agent_cleanup_required_can_resume_after_refresh(
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
        agent_cleanup_action="uninstall",
    )
    expect(page.get_by_text("Cleanup needs attention", exact=True)).to_be_visible()
    page.locator("[data-agent-retry-cleanup]").click()
    dialog = page.get_by_role("dialog", name="Retry AI Agents uninstall")
    expect(dialog).to_contain_text("original Claude Code removal choice")
    dialog.locator("[data-agent-uninstall-password]").fill("retry-test-password")
    dialog.locator("[data-lifecycle-confirmation]").fill("AI Agents")
    dialog.locator("[data-lifecycle-confirm]").click()
    expect(dialog.get_by_role("status")).to_contain_text("Operation completed")
    expect(page.locator("[data-agent-integration]").get_by_text("not installed", exact=True)).to_be_visible()


def test_agent_lifecycle_controls_are_hidden_from_viewers(
    page: Page,
    v2_server,
    v2_login,
    install_v2_integrations_api_mocks,
):
    _open(page, v2_server["base_url"], v2_login, install_v2_integrations_api_mocks)
    page.route(
        "**/api/auth/check",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"authenticated":true,"username":"viewer","role":"viewer","permissions":["capability.view"],"csrf_token":"viewer-token"}',
        ),
    )
    page.reload()

    expect(page.locator("[data-agent-lifecycle-menu-trigger='agents']")).to_have_count(0)
    expect(page.locator("[data-agent-setup]")).to_have_count(0)
    expect(page.locator("[data-mattermost-lifecycle-menu-trigger='mattermost']")).to_have_count(0)
    expect(page.locator("[data-mattermost-setup]")).to_have_count(0)


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
    agent.get_by_role("button", name="Finish setup", exact=True).click()
    dialog = page.get_by_role("dialog", name="Finish AI Agents setup")
    expect(dialog.get_by_label("Repair Mattermost bot and configuration")).to_be_checked()
    dialog.get_by_label("Mattermost admin password").fill("long-test-password")
    dialog.locator("button[data-agent-repair]").click()
    expect(dialog.locator("[data-agent-operation-log]")).to_contain_text(
        "AI Agents repair completed"
    )
    dialog.get_by_role("button", name="Close", exact=True).click()
    expect(agent.get_by_text("connected", exact=True)).to_be_visible()
