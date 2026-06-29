"""LR-001: v2-only routing and retired mode-flag validation."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _login(page: Page, base_url: str, v2_login) -> None:
    v2_login(page, base_url)


def _api_payload(page: Page, base_url: str, path: str):
    response = page.request.get(f"{base_url}{path}")
    assert response.status == 200
    return response.json()


def _route_response(page: Page, base_url: str, path: str):
    return page.request.get(f"{base_url}{path}", max_redirects=0)


def test_retired_hybrid_flags_cannot_restore_legacy_routes(
    page: Page,
    v2_server_factory,
    v2_login,
):
    server = v2_server_factory("hybrid", v2_pages="containers")
    base_url = server["base_url"]
    _login(page, base_url, v2_login)

    containers_response = _route_response(page, base_url, "/containers.html")
    assert containers_response.status == 302
    assert containers_response.headers["location"] == "/v2/containers"

    system_response = _route_response(page, base_url, "/system.html")
    assert system_response.status == 302
    assert system_response.headers["location"] == "/v2/system"

    home_response = _route_response(page, base_url, "/")
    assert home_response.status == 200

    page.goto(f"{base_url}/containers.html")
    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()

    page.goto(f"{base_url}/system.html")
    expect(page).to_have_url(f"{base_url}/v2/system")
    expect(page.get_by_role("heading", name="system_metrics")).to_be_visible()

    page.goto(f"{base_url}/")
    expect(page).to_have_url(f"{base_url}/")
    expect(page.get_by_role("heading", name="web_services")).to_be_visible()


def test_v2_mode_redirects_containers_and_other_legacy_routes(
    page: Page,
    v2_server_factory,
    v2_login,
):
    server = v2_server_factory("v2")
    base_url = server["base_url"]
    _login(page, base_url, v2_login)

    containers_response = _route_response(page, base_url, "/containers.html")
    assert containers_response.status == 302
    assert containers_response.headers["location"] == "/v2/containers"

    system_response = _route_response(page, base_url, "/system.html")
    assert system_response.status == 302
    assert system_response.headers["location"] == "/v2/system"


def test_retired_legacy_flag_cannot_restore_legacy_containers(
    page: Page,
    v2_server_factory,
    v2_login,
):
    legacy = v2_server_factory("legacy")
    _login(page, legacy["base_url"], v2_login)
    page.goto(f"{legacy['base_url']}/containers.html")
    expect(page).to_have_url(f"{legacy['base_url']}/v2/containers")
    expect(page.get_by_role("heading", name="docker_containers")).to_be_visible()

    response = page.goto(f"{legacy['base_url']}/v2/containers")
    assert response is not None
    assert response.status == 200


@pytest.mark.parametrize("path", ["/api/containers?stats=false", "/api/containers/stats?ids="])
def test_container_api_contract_is_unchanged_by_retired_mode_flags(
    page: Page,
    path: str,
    v2_server_factory,
    v2_login,
):
    payloads = []
    for mode, pages in [("legacy", None), ("hybrid", "containers"), ("v2", None)]:
        server = v2_server_factory(mode, v2_pages=pages)
        _login(page, server["base_url"], v2_login)
        payloads.append(_api_payload(page, server["base_url"], path))

    assert payloads[1] == payloads[0]
    assert payloads[2] == payloads[0]
