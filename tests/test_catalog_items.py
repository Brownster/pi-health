"""Integrity checks over the real shipped catalog/*.yaml items."""

import glob
import os

import yaml

CATALOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "catalog")


def _load_all_items() -> dict:
    items = {}
    for path in glob.glob(os.path.join(CATALOG_DIR, "*.yaml")):
        with open(path) as handle:
            data = yaml.safe_load(handle)
        assert isinstance(data, dict), f"{path} is not a mapping"
        items[data.get("id")] = data
    return items


def test_every_item_has_id_name_and_a_body():
    for path in glob.glob(os.path.join(CATALOG_DIR, "*.yaml")):
        with open(path) as handle:
            item = yaml.safe_load(handle)
        assert item.get("id"), f"{path} missing id"
        assert item.get("name"), f"{path} missing name"
        assert item.get("service") or item.get("members"), f"{path} has no service/members"


def test_all_requires_resolve_to_a_known_item():
    items = _load_all_items()
    ids = set(items)
    for item in items.values():
        for dependency in item.get("requires") or []:
            assert dependency in ids, f"{item['id']} requires unknown item {dependency!r}"


def test_field_keys_are_unique_per_item():
    for item in _load_all_items().values():
        keys = [field["key"] for field in (item.get("fields") or [])]
        assert len(keys) == len(set(keys)), f"{item['id']} has duplicate field keys"


def test_mattermost_and_alertd_items_are_wired():
    items = _load_all_items()
    assert "mattermost-db" in items
    assert items["mattermost"]["requires"] == ["mattermost-db"]
    assert items["limeos-alertd"]["requires"] == ["mattermost"]
    # The daemon runs the alert loop and reaches the host containers via the docker socket.
    alertd = items["limeos-alertd"]["service"]
    assert alertd["command"] == ["python", "alert_daemon.py"]
    assert any("docker.sock" in v for v in alertd["volumes"])


def test_mattermost_placeholders_all_declared_as_fields():
    # Every {{KEY}} used in the mattermost service must have a matching field so install
    # never leaves an unresolved placeholder.
    items = _load_all_items()
    for item_id in ("mattermost", "mattermost-db", "limeos-alertd"):
        item = items[item_id]
        declared = {field["key"] for field in item.get("fields", [])}
        blob = yaml.safe_dump(item["service"])
        used = set()
        for token in blob.split("{{")[1:]:
            used.add(token.split("}}")[0].strip())
        missing = used - declared
        assert not missing, f"{item_id} uses undeclared placeholders {missing}"
