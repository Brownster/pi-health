"""PH3-010: consolidated Phase 3 rollout + parity suite.

Validates legacy|hybrid|v2 routing, selective rollout via PIHEALTH_UI_V2_PAGES,
rollback to legacy without rebuild, that every Phase 3 page renders under the v2
shell, and that a representative API contract is stable across UI modes.
"""

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


def test_v2_mode_redirects_all_phase3_legacy_routes(page: Page, v2_server_factory):
    server = v2_server_factory("v2")
    base_url = server["base_url"]
    for key in PHASE3_ROUTE_KEYS:
        response = page.request.get(f"{base_url}/{key}.html", max_redirects=0)
        assert response.status == 302, f"{key}.html should redirect in v2 mode"
        assert response.headers["location"] == f"/v2/{key}"


def test_legacy_mode_serves_legacy_and_disables_v2(page: Page, v2_server_factory):
    server = v2_server_factory("legacy")
    base_url = server["base_url"]
    for key in PHASE3_ROUTE_KEYS:
        legacy = page.request.get(f"{base_url}/{key}.html", max_redirects=0)
        assert legacy.status == 200, f"{key}.html should serve legacy in legacy mode"
        v2 = page.request.get(f"{base_url}/v2/{key}", max_redirects=0)
        assert v2.status == 404, f"/v2/{key} should be disabled in legacy mode"


def test_hybrid_redirects_only_selected_routes(page: Page, v2_server_factory):
    server = v2_server_factory("hybrid", v2_pages="stacks,disks")
    base_url = server["base_url"]

    # Selected routes redirect to v2.
    for key in ["stacks", "disks"]:
        response = page.request.get(f"{base_url}/{key}.html", max_redirects=0)
        assert response.status == 302
        assert response.headers["location"] == f"/v2/{key}"

    # Unselected routes stay on legacy (instant rollback granularity, no rebuild).
    for key in ["plugins", "pools", "mounts", "shares", "settings"]:
        response = page.request.get(f"{base_url}/{key}.html", max_redirects=0)
        assert response.status == 200, f"{key}.html should remain legacy when unselected"


def test_all_phase3_pages_render_in_v2(page: Page, v2_server_factory, v2_login):
    server = v2_server_factory("v2")
    base_url = server["base_url"]
    v2_login(page, base_url)

    for key, heading in PHASE3_PAGE_HEADINGS.items():
        page.goto(f"{base_url}/v2/{key}")
        expect(page).to_have_url(f"{base_url}/v2/{key}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()


def test_stacks_api_contract_stable_across_modes(page: Page, v2_server_factory, v2_login):
    # The API blueprints are registered regardless of UI mode; the contract must not
    # shift between legacy and v2 rollout.
    for mode in ["legacy", "v2"]:
        server = v2_server_factory(mode)
        base_url = server["base_url"]
        v2_login(page, base_url)
        response = page.request.get(f"{base_url}/api/stacks?status=true")
        assert response.status == 200
        assert "stacks" in response.json()
