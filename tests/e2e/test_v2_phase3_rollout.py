"""Phase 3 parity coverage under the LR-001 v2-only routing contract."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Phase 3 route keys (legacy /<key>.html  <->  /v2/<key>).
PHASE3_ROUTE_KEYS = ["stacks", "disks", "plugins", "pools", "mounts", "shares", "settings"]

# nasOS page headings (lowercase mono) per v2 route.
PHASE3_PAGE_HEADINGS = {
    "stacks": "docker_stacks",
    "disks": "disk_management",
    "plugins": "storage_plugins",
    "pools": "storage_pools",
    "mounts": "mount_management",
    "shares": "network_shares",
    "settings": "system_settings",
}


def test_legacy_urls_redirect_to_v2(page: Page, v2_server):
    base_url = v2_server["base_url"]
    for key in PHASE3_ROUTE_KEYS:
        response = page.request.get(f"{base_url}/{key}.html", max_redirects=0)
        assert response.status == 302, f"{key}.html should redirect to v2"
        assert response.headers["location"] == f"/v2/{key}"


def test_all_phase3_pages_render_in_v2(page: Page, v2_server, v2_login):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)

    for key, heading in PHASE3_PAGE_HEADINGS.items():
        page.goto(f"{base_url}/v2/{key}")
        expect(page).to_have_url(f"{base_url}/v2/{key}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()


def test_stacks_api_contract(page: Page, v2_server, v2_login):
    base_url = v2_server["base_url"]
    v2_login(page, base_url)
    response = page.request.get(f"{base_url}/api/stacks?status=true")
    assert response.status == 200
    assert "stacks" in response.json()
