import json
from datetime import datetime, timezone

import pytest

from activity_credentials import (
    CredentialUnavailable,
    read_arr_api_key,
    read_jellyfin_api_key,
    read_sabnzbd_api_key,
)
from activity_service import ActivityService, HttpResponse


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)


# --- credential readers -------------------------------------------------------


def test_sabnzbd_key_survives_the_bare_preamble_line(tmp_path):
    # sabnzbd.ini opens with "__version__" outside any section.
    (tmp_path / "sabnzbd.ini").write_text(
        "__version__ = 19\n[misc]\nport = 8080\napi_key = deadbeef\n"
    )
    assert read_sabnzbd_api_key(tmp_path) == "deadbeef"


def test_sabnzbd_reader_reports_a_missing_key(tmp_path):
    (tmp_path / "sabnzbd.ini").write_text("__version__ = 19\n[misc]\nport = 8080\n")
    with pytest.raises(CredentialUnavailable, match="No api_key"):
        read_sabnzbd_api_key(tmp_path)


def test_arr_key_is_read_from_config_xml(tmp_path):
    (tmp_path / "config.xml").write_text("<Config><ApiKey>abc123</ApiKey></Config>")
    assert read_arr_api_key(tmp_path) == "abc123"


def test_missing_config_file_is_reported_clearly(tmp_path):
    with pytest.raises(CredentialUnavailable, match="No config file"):
        read_arr_api_key(tmp_path)


def test_jellyfin_key_is_read_from_its_database(tmp_path):
    database = tmp_path / "data" / "data" / "jellyfin.db"
    database.parent.mkdir(parents=True)
    database.touch()
    captured = {}

    def query(path, statement):
        captured["path"] = path
        captured["statement"] = statement
        return [("", ), ("token-value",)]

    assert read_jellyfin_api_key(tmp_path, query=query) == "token-value"
    assert captured["path"] == database


def test_jellyfin_without_a_stored_key_says_how_to_create_one(tmp_path):
    (tmp_path / "jellyfin.db").touch()
    with pytest.raises(CredentialUnavailable, match="Dashboard > API Keys"):
        read_jellyfin_api_key(tmp_path, query=lambda path, statement: [])


# --- activity service ---------------------------------------------------------


def container(name, *, image=None, status="running", ports=None, container_id=None):
    return {
        "id": container_id or f"{name}-id",
        "name": name,
        "status": status,
        "image": image or f"linuxserver/{name}:latest",
        "ports": ports if ports is not None else [],
    }


def published(container_port, host_port, *, via_service=None):
    return {
        "container_port": container_port,
        "protocol": "tcp",
        "host_port": host_port,
        "host_ip": "0.0.0.0",
        "via_service": via_service,
    }


class FakeTransport:
    """Answers loopback calls from a {(method, url-fragment): response} table."""

    def __init__(self, routes):
        self._routes = routes
        self.requests = []

    def __call__(self, method, url, headers=None, body=None, timeout=None):
        self.requests.append((method, url, dict(headers or {})))
        for fragment, response in self._routes.items():
            if fragment in url:
                return response(method, headers) if callable(response) else response
        return HttpResponse(404, {}, b"")


def ok(payload):
    return HttpResponse(200, {}, json.dumps(payload).encode("utf-8"))


def make_service(containers, transport, *, mounts=None, readers=None):
    return ActivityService(
        container_provider=lambda: containers,
        inspect_reader=lambda container_id: {
            "mounts": mounts if mounts is not None else [
                {"type": "bind", "source": "/srv/config", "destination": "/config"}
            ]
        },
        transport=transport,
        credential_readers=readers
        or {"arr": lambda root: "arr-key", "sabnzbd": lambda root: "sab-key", "jellyfin": lambda root: "jf-key"},
        wall_clock=lambda: NOW,
        ttl_seconds=0.0,
    )


def test_jellyfin_sessions_become_streams():
    transport = FakeTransport(
        {
            "/Sessions": ok(
                [
                    {
                        "UserName": "holly",
                        "Client": "Jellyfin Web",
                        "DeviceName": "Firefox",
                        "NowPlayingItem": {
                            "Name": "Reservoir Dogs",
                            "Type": "Episode",
                            "SeriesName": "Copycat Killers",
                            "ParentIndexNumber": 2,
                            "IndexNumber": 10,
                            "RunTimeTicks": 36_000_000_000,
                        },
                        "PlayState": {
                            "PositionTicks": 9_000_000_000,
                            "PlayMethod": "Transcode",
                            "IsPaused": False,
                        },
                        "TranscodingInfo": {
                            "Bitrate": 4_000_000,
                            "TranscodeReasons": ["VideoCodecNotSupported"],
                        },
                    },
                    {"UserName": "idle-session", "PlayState": {}},
                ]
            )
        }
    )
    service = make_service([container("jellyfin", ports=[published(8096, 8096)])], transport)

    snapshot = service.snapshot()
    assert len(snapshot["streams"]) == 1
    stream = snapshot["streams"][0]
    assert stream["title"] == "Reservoir Dogs"
    assert stream["subtitle"] == "Copycat Killers · S02E10"
    assert stream["user"] == "holly"
    assert stream["is_transcoding"] is True
    assert stream["transcode_reason"] == "VideoCodecNotSupported"
    assert stream["progress_percent"] == pytest.approx(25.0)
    assert stream["duration_seconds"] == 3_600
    assert snapshot["totals"] == {
        "streams": 1,
        "transcodes": 1,
        "downloads": 0,
        "download_speed": 0,
        "queued": 0,
        "queue_problems": 0,
    }


def test_sabnzbd_queue_becomes_downloads_with_byte_rates():
    transport = FakeTransport(
        {
            "mode=queue": ok(
                {
                    "queue": {
                        "status": "Downloading",
                        "kbpersec": "5120.0",
                        "slots": [
                            {
                                "filename": "Some.Show.S01E01",
                                "status": "Downloading",
                                "percentage": "42",
                                "mb": "1024",
                                "mbleft": "512",
                                "timeleft": "0:02:30",
                            },
                            {
                                "filename": "Queued.Item",
                                "status": "Queued",
                                "percentage": "0",
                                "mb": "700",
                                "mbleft": "700",
                                "timeleft": "0:00:00",
                            },
                        ],
                    }
                }
            )
        }
    )
    service = make_service([container("sabnzbd", ports=[published(8080, 8085)])], transport)

    snapshot = service.snapshot()
    assert [item["name"] for item in snapshot["downloads"]] == [
        "Some.Show.S01E01",
        "Queued.Item",
    ]
    active = snapshot["downloads"][0]
    assert active["progress_percent"] == pytest.approx(42.0)
    assert active["size_bytes"] == 1024 * 1024 * 1024
    assert active["remaining_bytes"] == 512 * 1024 * 1024
    assert active["speed_bytes"] == pytest.approx(5120.0 * 1024)
    # Only the item actually being fetched carries the rate.
    assert snapshot["downloads"][1]["speed_bytes"] == 0.0
    assert "8085" in transport.requests[0][1]


def test_transmission_retries_once_with_the_session_id_it_is_handed():
    responses = iter(
        [
            HttpResponse(409, {"X-Transmission-Session-Id": "session-abc"}, b"conflict"),
            ok(
                {
                    "arguments": {
                        "torrents": [
                            {
                                "name": "Ubuntu ISO",
                                "status": 4,
                                "rateDownload": 2_000_000,
                                "percentDone": 0.5,
                                "eta": 5_400,
                                "totalSize": 4_000_000_000,
                            },
                            {"name": "Idle", "status": 0},
                        ]
                    }
                }
            ),
        ]
    )
    transport = FakeTransport({"/transmission/rpc": lambda method, headers: next(responses)})
    service = make_service([container("transmission", ports=[published(9091, 9091)])], transport)

    snapshot = service.snapshot()
    assert transport.requests[1][2]["X-Transmission-Session-Id"] == "session-abc"
    assert len(snapshot["downloads"]) == 1
    torrent = snapshot["downloads"][0]
    assert torrent["state"] == "downloading"
    assert torrent["progress_percent"] == pytest.approx(50.0)
    assert torrent["remaining_bytes"] == 2_000_000_000
    assert torrent["eta"] == "1h 30m"


def test_arr_queue_counts_problem_records():
    transport = FakeTransport(
        {
            "/api/v3/queue": ok(
                {
                    "totalRecords": 3,
                    "records": [
                        {"title": "A", "status": "warning", "trackedDownloadState": "downloading"},
                        {"title": "B", "status": "completed", "trackedDownloadStatus": "error"},
                        {"title": "C", "status": "downloading", "trackedDownloadStatus": "ok"},
                    ],
                }
            )
        }
    )
    service = make_service([container("sonarr", ports=[published(8989, 8989)])], transport)

    snapshot = service.snapshot()
    assert snapshot["queues"][0]["total"] == 3
    assert snapshot["queues"][0]["problems"] == 2
    assert snapshot["totals"]["queued"] == 3
    assert transport.requests[0][2]["X-Api-Key"] == "arr-key"


def test_a_service_behind_a_vpn_sidecar_is_reached_on_the_published_port():
    transport = FakeTransport({"/api/v3/queue": ok({"totalRecords": 0, "records": []})})
    service = make_service(
        [container("radarr", ports=[published(7878, 7878, via_service="vpn")])], transport
    )

    service.snapshot()
    assert "127.0.0.1:7878" in transport.requests[0][1]


def test_a_service_with_no_published_port_is_reported_unreachable():
    transport = FakeTransport({})
    service = make_service(
        [
            container(
                "sonarr",
                ports=[{"container_port": 8989, "protocol": "tcp", "host_port": None}],
            )
        ],
        transport,
    )

    snapshot = service.snapshot()
    assert snapshot["services"][0]["reachable"] is False
    assert snapshot["services"][0]["detail"] == (
        "No reachable host port is published for this container"
    )
    assert transport.requests == []


def test_a_container_outside_the_known_provider_set_is_skipped():
    transport = FakeTransport({})
    service = make_service([container("jackett", ports=[published(9117, 9117)])], transport)

    assert service.snapshot()["services"] == []
    assert transport.requests == []


def test_one_failing_service_does_not_hide_the_others():
    transport = FakeTransport(
        {
            "/Sessions": HttpResponse(500, {}, b"boom"),
            "/api/v3/queue": ok({"totalRecords": 1, "records": []}),
        }
    )
    service = make_service(
        [
            container("jellyfin", ports=[published(8096, 8096)]),
            container("sonarr", ports=[published(8989, 8989)]),
        ],
        transport,
    )

    snapshot = service.snapshot()
    reachable = {item["name"]: item for item in snapshot["services"]}
    assert reachable["jellyfin"]["reachable"] is False
    assert "did not respond" in reachable["jellyfin"]["detail"]
    assert reachable["sonarr"]["reachable"] is True
    assert snapshot["totals"]["queued"] == 1


def test_an_unreadable_credential_is_explained_without_leaking_it():
    def refuse(root):
        raise CredentialUnavailable("Unreadable Servarr config at /srv/config/config.xml")

    transport = FakeTransport({})
    service = make_service(
        [container("sonarr", ports=[published(8989, 8989)])],
        transport,
        readers={"arr": refuse},
    )

    snapshot = service.snapshot()
    assert snapshot["services"][0]["reachable"] is False
    assert snapshot["services"][0]["detail"].startswith("Unreadable Servarr config")
    assert transport.requests == []


def test_stopped_and_unrelated_containers_are_ignored():
    transport = FakeTransport({})
    service = make_service(
        [
            container("jellyfin", status="exited", ports=[published(8096, 8096)]),
            container("postgres", image="postgres:16", ports=[published(5432, 5432)]),
        ],
        transport,
    )

    assert service.snapshot()["services"] == []


def test_a_container_without_a_config_mount_says_so():
    transport = FakeTransport({})
    service = make_service(
        [container("sabnzbd", ports=[published(8080, 8085)])],
        transport,
        mounts=[{"type": "bind", "source": "/mnt/downloads", "destination": "/downloads"}],
        readers={"sabnzbd": lambda root: "unused"},
    )

    detail = service.snapshot()["services"][0]["detail"]
    assert "no /config mount" in detail


def test_the_snapshot_is_cached_between_calls():
    transport = FakeTransport({"/api/v3/queue": ok({"totalRecords": 0, "records": []})})
    service = ActivityService(
        container_provider=lambda: [container("sonarr", ports=[published(8989, 8989)])],
        inspect_reader=lambda container_id: {
            "mounts": [{"source": "/srv/config", "destination": "/config"}]
        },
        transport=transport,
        credential_readers={"arr": lambda root: "arr-key"},
        wall_clock=lambda: NOW,
        ttl_seconds=30.0,
        clock=lambda: 100.0,
    )

    service.snapshot()
    service.snapshot()
    assert len(transport.requests) == 1
