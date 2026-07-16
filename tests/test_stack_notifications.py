"""Stack notifications: *arr webhook normalization + Mattermost rendering."""

import pytest

from stack_notifications_service import (
    QUIET_EVENTS,
    VERBOSE_EVENTS,
    normalize,
    render_mattermost,
)


def _radarr(event, **extra):
    return {"eventType": event, "instanceName": "Radarr",
            "movie": {"title": "The Matrix", "year": 1999},
            "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}}, **extra}


def _sonarr(event, **extra):
    return {"eventType": event, "instanceName": "Sonarr",
            "series": {"title": "Severance"},
            "episodes": [{"seasonNumber": 2, "episodeNumber": 3, "title": "x"}],
            "episodeFile": {"quality": {"quality": {"name": "WEBDL-1080p"}}}, **extra}


def test_radarr_import_normalizes_with_media_and_quality():
    note = normalize(_radarr("Download"))
    assert note.source == "radarr" and note.event == "imported" and note.severity == "info"
    assert "The Matrix (1999)" in note.detail and "Bluray-1080p" in note.detail


def test_import_flagged_as_upgrade_becomes_upgraded():
    note = normalize(_radarr("Download", isUpgrade=True))
    assert note.event == "upgraded"


def test_sonarr_import_includes_episode_code():
    note = normalize(_sonarr("Download"))
    assert note.source == "sonarr" and note.event == "imported"
    assert "Severance S02E03" in note.detail and "WEBDL-1080p" in note.detail


def test_health_issue_is_a_warning_and_carries_the_message():
    note = normalize({"eventType": "HealthIssue", "instanceName": "Sonarr",
                      "level": "warning", "message": "Indexer unavailable"})
    assert note.event == "health" and note.severity == "warning"
    assert note.detail == "Indexer unavailable"


def test_health_error_level_is_critical():
    note = normalize({"eventType": "HealthIssue", "level": "error", "message": "Download client down"})
    assert note.severity == "critical"


def test_health_restored_is_info():
    note = normalize({"eventType": "HealthRestored", "message": "Indexer restored"})
    assert note.event == "health_restored" and note.severity == "info"


def test_failure_and_manual_are_warnings():
    assert normalize(_radarr("DownloadFailure")).event == "failed"
    assert normalize(_radarr("ManualInteractionRequired")).severity == "warning"


@pytest.mark.parametrize("event", ["Grab", "Rename", "MovieAdded", "ApplicationUpdate", "Test"])
def test_quiet_policy_suppresses_noise(event):
    assert normalize(_radarr(event)) is None


def test_verbose_policy_forwards_grab_but_never_test():
    assert normalize(_radarr("Grab"), events=VERBOSE_EVENTS).event == "grabbed"
    assert normalize(_radarr("Test"), events=VERBOSE_EVENTS) is None


@pytest.mark.parametrize("payload", [None, "not a dict", {}, {"eventType": "WhoKnows"}])
def test_unknown_or_malformed_payload_returns_none(payload):
    assert normalize(payload) is None


def test_source_falls_back_when_instance_name_missing():
    note = normalize({"eventType": "Download", "movie": {"title": "Dune"}}, source_default="media")
    assert note.source == "media"


def test_detail_is_length_bounded():
    note = normalize({"eventType": "HealthIssue", "message": "x" * 900})
    assert len(note.detail) <= 500


def test_render_mattermost_colours_by_severity_and_never_empty():
    payload = render_mattermost(normalize(_radarr("DownloadFailure")))
    attachment = payload["attachments"][0]
    assert attachment["color"] == "#e0a13b"  # warning
    assert "radarr" in attachment["title"] and attachment["text"]


def test_quiet_is_the_documented_default_set():
    assert QUIET_EVENTS < VERBOSE_EVENTS
    assert "grabbed" not in QUIET_EVENTS and "imported" in QUIET_EVENTS


# -- ingest service --------------------------------------------------------------
from stack_notifications_service import StackNotificationsService  # noqa: E402


def _service(config, delivered=None):
    delivered = delivered if delivered is not None else []
    return StackNotificationsService(
        config_provider=lambda: config,
        poster=lambda url, payload: delivered.append((url, payload)),
    ), delivered


CONFIG = {"enabled": True, "token": "s3cret", "webhook_url": "https://mm/hooks/x", "mode": "quiet"}


def test_ingest_forwards_a_valid_event_to_the_webhook():
    service, delivered = _service(CONFIG)
    body, status = service.ingest("s3cret", _radarr("Download"))
    assert status == 200 and body["status"] == "forwarded" and body["event"] == "imported"
    assert delivered[0][0] == "https://mm/hooks/x"


def test_ingest_rejects_a_bad_token():
    service, delivered = _service(CONFIG)
    body, status = service.ingest("wrong", _radarr("Download"))
    assert status == 401 and delivered == []


def test_ingest_returns_200_and_no_post_for_suppressed_or_test_events():
    service, delivered = _service(CONFIG)
    for event in ("Grab", "Test"):
        body, status = service.ingest("s3cret", _radarr(event))
        assert status == 200 and body["status"] == "ignored"
    assert delivered == []


def test_ingest_honours_verbose_mode():
    service, delivered = _service({**CONFIG, "mode": "verbose"})
    body, status = service.ingest("s3cret", _radarr("Grab"))
    assert status == 200 and body["event"] == "grabbed" and len(delivered) == 1


def test_ingest_404_when_disabled():
    service, _ = _service({**CONFIG, "enabled": False})
    _body, status = service.ingest("s3cret", _radarr("Download"))
    assert status == 404


def test_ingest_delivery_failure_is_non_fatal():
    service = StackNotificationsService(
        config_provider=lambda: CONFIG,
        poster=lambda url, payload: (_ for _ in ()).throw(RuntimeError("mm down")),
    )
    body, status = service.ingest("s3cret", _radarr("Download"))
    assert status == 200 and body["status"] == "delivery_failed"


def test_status_reports_config_including_token_for_the_admin():
    service, _ = _service(CONFIG)
    status = service.status()
    assert status == {
        "enabled": True,
        "configured": True,
        "mode": "quiet",
        "source_default": "stack",
        "channel_name": None,
        "token": "s3cret",
    }


def test_set_mode_persists_and_validates():
    stored = dict(CONFIG)
    service = StackNotificationsService(
        config_provider=lambda: stored,
        poster=lambda *_: None,
        config_writer=lambda config: stored.update(config),
    )
    body, status = service.set_mode("verbose")
    assert status == 200 and body["mode"] == "verbose" and stored["mode"] == "verbose"
    _body, bad = service.set_mode("loud")
    assert bad == 400


def test_set_mode_404_when_not_configured():
    service = StackNotificationsService(
        config_provider=lambda: {"enabled": False},
        poster=lambda *_: None,
        config_writer=lambda config: None,
    )
    _body, status = service.set_mode("verbose")
    assert status == 404
