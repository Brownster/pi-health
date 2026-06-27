"""PH3-002 / PH3-003: v2 stacks parity suite (read path + lifecycle/logs slice).

Pinned to v2 UI mode; deterministic /api/stacks* mocks (incl. an SSE stream body)
keep the streaming lifecycle console reproducible without a docker daemon.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks):
    v2_login(page, base_url)
    install_v2_stacks_api_mocks(page)
    page.goto(f"{base_url}/v2/stacks")
    expect(page.get_by_role("heading", name="docker_stacks")).to_be_visible()


def test_v2_stacks_list_renders(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_stacks_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks)

    expect(page.get_by_text("media").first).to_be_visible()
    expect(page.get_by_text("2 / 2 services up").first).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 stacks ({viewport_profile_name})")


def test_v2_stacks_logs_modal(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_stacks_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks)

    page.locator("button[data-stack-action='logs']:visible").first.click()
    expect(page.locator("#v2-stack-logs-modal")).to_be_visible()
    expect(page.locator("#v2-stack-logs-content")).not_to_have_text("Loading logs...", timeout=10000)
    expect(page.locator("#v2-stack-logs-content")).to_contain_text("stack log line 1")
    page.click("#v2-stack-logs-close")
    expect(page.locator("#v2-stack-logs-modal")).to_have_count(0)


def test_v2_stacks_lifecycle_streaming_console(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_stacks_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks)

    page.locator("button[data-action='up'][data-stack='media']:visible").first.click()
    expect(page.locator("#v2-stack-console")).to_be_visible()
    # Streamed output line, then completion status.
    expect(page.locator("#v2-stack-console-output")).to_contain_text("Started", timeout=15000)
    expect(page.locator("#v2-stack-console")).to_contain_text("Completed", timeout=15000)
    page.click("#v2-stack-console-close")
    expect(page.locator("#v2-stack-console")).to_have_count(0)


def test_v2_stacks_compose_env_editor(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_stacks_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks)

    page.locator("button[data-stack-action='edit']:visible").first.click()
    editor = page.locator("#v2-stack-editor-modal")
    expect(editor).to_be_visible()

    # Compose tab loads file content.
    textarea = page.locator("#v2-stack-editor-textarea")
    expect(textarea).to_have_value("services:\n  web:\n    image: nginx:latest\n")
    textarea.fill("services:\n  web:\n    image: nginx:1.27\n")
    page.click("#v2-stack-editor-save")
    expect(page.locator("#v2-stack-editor-status")).to_have_text("Saved", timeout=10000)

    # Env tab loads the .env content.
    page.click("button[data-editor-tab='env']")
    expect(textarea).to_have_value("PUID=1000\nPGID=1000\n")

    page.click("#v2-stack-editor-close")
    expect(page.locator("#v2-stack-editor-modal")).to_have_count(0)


def test_v2_stacks_backups_restore_with_confirm(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_stacks_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    _open_v2_stacks(page, base_url, v2_login, install_v2_stacks_api_mocks)

    page.locator("button[data-stack-action='backups']:visible").first.click()
    expect(page.locator("#v2-stack-backups-modal")).to_be_visible()

    backup = "docker-compose.yml.20260101-000000.bak"
    # Restore requires an explicit confirm step (no destructive one-click).
    page.click(f"button[data-restore='{backup}']")
    page.click(f"button[data-confirm-restore='{backup}']")
    expect(page.locator("#v2-stack-backups-modal")).to_contain_text("Restored", timeout=10000)

    page.click("#v2-stack-backups-close")
    expect(page.locator("#v2-stack-backups-modal")).to_have_count(0)
