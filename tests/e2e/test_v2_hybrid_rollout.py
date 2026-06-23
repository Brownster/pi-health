"""PH2-007: containers hybrid rollout and rollback validation."""

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


def test_hybrid_containers_rollout_redirects_only_selected_route(
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
    assert system_response.status == 200

    home_response = _route_response(page, base_url, "/")
    assert home_response.status == 200

    page.goto(f"{base_url}/containers.html")
    expect(page).to_have_url(f"{base_url}/v2/containers")
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()

    page.goto(f"{base_url}/system.html")
    expect(page).to_have_url(f"{base_url}/system.html")
    assert "/v2" not in page.url

    page.goto(f"{base_url}/")
    expect(page).to_have_url(f"{base_url}/")
    assert "/v2" not in page.url


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


def test_legacy_mode_rollback_restores_legacy_containers_without_rebuild(
    page: Page,
    v2_server_factory,
    v2_login,
):
    hybrid = v2_server_factory("hybrid", v2_pages="containers")
    _login(page, hybrid["base_url"], v2_login)
    page.goto(f"{hybrid['base_url']}/containers.html")
    expect(page).to_have_url(f"{hybrid['base_url']}/v2/containers")

    legacy = v2_server_factory("legacy")
    _login(page, legacy["base_url"], v2_login)
    page.goto(f"{legacy['base_url']}/containers.html")
    expect(page).to_have_url(f"{legacy['base_url']}/containers.html")
    expect(page.get_by_role("heading", name="Docker Containers")).to_be_visible()

    response = page.goto(f"{legacy['base_url']}/v2/containers")
    assert response is not None
    assert response.status == 404
    assert "disabled in legacy mode" in page.text_content("body")


@pytest.mark.parametrize("path", ["/api/containers?stats=false", "/api/containers/stats?ids="])
def test_container_api_contract_is_unchanged_across_ui_modes(
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
