"""CP-010 existing-provider assignment adapter coverage."""

import json

from disk_provider_assignments import StorageProviderAssignmentReader


def test_reader_maps_mergerfs_branches_and_snapraid_roles(tmp_path):
    (tmp_path / "mergerfs.json").write_text(
        json.dumps(
            {
                "pools": [
                    {
                        "id": "media",
                        "name": "Media Pool",
                        "branches": ["/mnt/data1", "/mnt/data2"],
                        "mount_point": "/mnt/pool",
                    }
                ]
            }
        )
    )
    (tmp_path / "snapraid.json").write_text(
        json.dumps(
            {
                "drives": [
                    {"name": "d1", "path": "/mnt/data1", "uuid": "data-1", "role": "data"},
                    {
                        "name": "parity",
                        "path": "/mnt/parity",
                        "uuid": "parity-1",
                        "role": "parity",
                    },
                ]
            }
        )
    )

    result = StorageProviderAssignmentReader(tmp_path).read()

    assert result["warnings"] == []
    assert result["assignments"] == [
        {
            "provider_id": "mergerfs",
            "capability_id": "storage.pooling",
            "role": "branch",
            "resource_id": "media",
            "resource_name": "Media Pool",
            "target_path": "/mnt/data1",
            "href": "/pools/mergerfs",
        },
        {
            "provider_id": "mergerfs",
            "capability_id": "storage.pooling",
            "role": "branch",
            "resource_id": "media",
            "resource_name": "Media Pool",
            "target_path": "/mnt/data2",
            "href": "/pools/mergerfs",
        },
        {
            "provider_id": "snapraid",
            "capability_id": "storage.protection",
            "role": "data",
            "resource_id": "d1",
            "resource_name": "d1",
            "target_path": "/mnt/data1",
            "target_uuid": "data-1",
            "href": "/protection/snapraid",
        },
        {
            "provider_id": "snapraid",
            "capability_id": "storage.protection",
            "role": "parity",
            "resource_id": "parity",
            "resource_name": "parity",
            "target_path": "/mnt/parity",
            "target_uuid": "parity-1",
            "href": "/protection/snapraid",
        },
    ]


def test_reader_isolates_missing_and_malformed_provider_files(tmp_path):
    (tmp_path / "mergerfs.json").write_text("not json")
    (tmp_path / "snapraid.json").write_text(json.dumps({"drives": []}))

    result = StorageProviderAssignmentReader(tmp_path).read()

    assert result["assignments"] == []
    assert result["warnings"] == [
        {
            "code": "provider_config_invalid",
            "source": "mergerfs",
            "message": "MergerFS assignments are unavailable",
        }
    ]


def test_reader_ignores_unsafe_or_unbounded_records(tmp_path):
    (tmp_path / "mergerfs.json").write_text(
        json.dumps(
            {
                "pools": [
                    {"name": "unsafe", "branches": ["/etc", "relative", "/mnt/safe"]},
                ]
                * 200
            }
        )
    )

    result = StorageProviderAssignmentReader(tmp_path).read()

    assert len(result["assignments"]) <= 256
    assert all(item["target_path"].startswith("/mnt/") for item in result["assignments"])
