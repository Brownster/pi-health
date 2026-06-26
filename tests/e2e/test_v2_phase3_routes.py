"""PH3 route scaffold: auth guard for v2 core-management routes.

All Phase 3 pages are now real routes (no remaining placeholders); their content is
covered by per-page parity suites. This asserts the shared auth guard still protects
a representative v2 route.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_v2_phase3_route_requires_auth(page: Page, v2_mode_server):
    base_url = v2_mode_server["base_url"]
    page.goto(f"{base_url}/v2/disks")
    expect(page).to_have_url(f"{base_url}/login.html")
