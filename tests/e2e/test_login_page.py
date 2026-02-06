import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_login_button_state(page: Page, test_user_credentials):
    base_url = test_user_credentials["base_url"]
    page.goto(f"{base_url}/login.html")

    username = page.locator("#username")
    password = page.locator("#password")
    submit = page.locator("#login-button")

    expect(submit).to_be_disabled()

    username.fill("admin")
    expect(submit).to_be_disabled()

    password.fill("invalid")
    expect(submit).to_be_enabled()

    username.fill("   ")
    expect(submit).to_be_disabled()


def test_login_error_clears_on_input(page: Page, test_user_credentials):
    base_url = test_user_credentials["base_url"]
    page.goto(f"{base_url}/login.html")

    page.fill("#username", "wronguser")
    page.fill("#password", "wrongpass")
    page.click("#login-button")

    error = page.locator("#login-error")
    expect(error).to_be_visible(timeout=5000)
    expect(error).to_contain_text("Invalid")

    expect(page.locator("#username")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#password")).to_have_attribute("aria-invalid", "true")

    page.fill("#username", "admin")
    expect(error).to_be_hidden()
    expect(page.locator("#username")).to_have_attribute("aria-invalid", "false")
    expect(page.locator("#password")).to_have_attribute("aria-invalid", "false")
