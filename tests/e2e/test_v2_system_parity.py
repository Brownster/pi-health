"""v2 System Health page (nasOS redesign expansion)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_v2_system(page, base_url, v2_login, install_v2_system_api_mocks):
    v2_login(page, base_url)
    install_v2_system_api_mocks(page)
    page.goto(f"{base_url}/v2/system")
    expect(page.get_by_role("heading", name="system_metrics", exact=True)).to_be_visible()


def test_v2_system_metrics_render(
    profiled_page: Page,
    viewport_profile_name: str,
    assert_no_horizontal_overflow,
    v2_mode_server,
    v2_login,
    install_v2_system_api_mocks,
):
    page = profiled_page
    base_url = v2_mode_server["base_url"]
    _open_v2_system(page, base_url, v2_login, install_v2_system_api_mocks)

    expect(page.get_by_text("48.0 °C")).to_be_visible()
    expect(page.get_by_text("cpu0").first).to_be_visible()
    expect(page.get_by_text("raspberry pi")).to_be_visible()
    assert_no_horizontal_overflow(page, f"v2 system ({viewport_profile_name})")


def test_v2_system_surfaces_optional_metric_warning(
    page: Page,
    v2_mode_server,
    v2_login,
    install_v2_system_api_mocks,
):
    base_url = v2_mode_server["base_url"]
    v2_login(page, base_url)
    install_v2_system_api_mocks(
        page,
        {
            "disk_usage_2": None,
            "warnings": [
                {
                    "code": "source_unavailable",
                    "metric": "disk_usage_2",
                    "source": "/mnt/backup",
                    "message": "Disk usage unavailable for /mnt/backup",
                }
            ],
        },
    )
    page.goto(f"{base_url}/v2/system")

    expect(page.get_by_text("Disk usage unavailable for /mnt/backup")).to_be_visible()
    expect(page.get_by_text("48.0 °C")).to_be_visible()
