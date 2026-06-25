"""PH3-001: Phase 3 placeholder route scaffold.

Verifies the reserved core-management routes render through the authenticated v2
shell and stay behind the auth guard. Functional parity for each page lands in
its own PH3 ticket; these tests lock the routing scaffold only.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

PHASE3_PLACEHOLDER_ROUTES = ["disks", "pools", "mounts", "shares", "plugins", "settings"]


@pytest.mark.parametrize("page_path", PHASE3_PLACEHOLDER_ROUTES)
def test_v2_phase3_placeholder_routes_render_in_shell(
    page: Page,
    v2_mode_server,
    v2_login,
    page_path,
):
    base_url = v2_mode_server["base_url"]
    v2_login(page, base_url)

    page.goto(f"{base_url}/v2/{page_path}")
    expect(page).to_have_url(f"{base_url}/v2/{page_path}")
    # v2 shell renders, and the placeholder offers the legacy fallback control.
    expect(page.get_by_role("heading", name="Pi-Health v2 Shell")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Open Legacy", re.I)).first).to_be_visible()


def test_v2_phase3_placeholder_route_requires_auth(page: Page, v2_mode_server):
    base_url = v2_mode_server["base_url"]
    page.goto(f"{base_url}/v2/disks")
    expect(page).to_have_url(f"{base_url}/login.html")
