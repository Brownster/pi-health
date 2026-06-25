"""PH3-001: Phase 3 placeholder route scaffold.

Verifies the reserved core-management routes render through the authenticated v2
shell and stay behind the auth guard. Functional parity for each page lands in
its own PH3 ticket; these tests lock the routing scaffold only.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# (route path, expected legacy fallback href). Pages promoted to real v2 routes
# (e.g. disks) are covered by their own parity suite, not here.
PHASE3_PLACEHOLDER_ROUTES = [
    ("pools", "/pools.html"),
    ("mounts", "/mounts.html"),
    ("shares", "/shares.html"),
    ("plugins", "/plugins.html"),
    ("settings", "/settings.html"),
]


@pytest.mark.parametrize("page_path,legacy_href", PHASE3_PLACEHOLDER_ROUTES)
def test_v2_phase3_placeholder_routes_render_in_shell(
    page: Page,
    v2_mode_server,
    v2_login,
    page_path,
    legacy_href,
):
    base_url = v2_mode_server["base_url"]
    v2_login(page, base_url)

    page.goto(f"{base_url}/v2/{page_path}")
    expect(page).to_have_url(f"{base_url}/v2/{page_path}")
    # v2 shell renders, and the placeholder offers a legacy fallback link to the
    # *matching* legacy page (not a one-size-fits-all default).
    expect(page.get_by_role("heading", name="Pi-Health v2 Shell")).to_be_visible()
    fallback = page.get_by_role("link", name=re.compile("Open Legacy", re.I)).first
    expect(fallback).to_be_visible()
    expect(fallback).to_have_attribute("href", legacy_href)


def test_v2_phase3_placeholder_route_requires_auth(page: Page, v2_mode_server):
    base_url = v2_mode_server["base_url"]
    page.goto(f"{base_url}/v2/disks")
    expect(page).to_have_url(f"{base_url}/login.html")
