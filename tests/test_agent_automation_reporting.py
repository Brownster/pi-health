from agent_automation.reporting import MattermostReportDelivery, render_mattermost_report


def report(status="healthy"):
    return {
        "schedule_id": "schedule-1",
        "schedule_name": "Morning health report",
        "occurrence_id": "occurrence-1",
        "scheduled_for": "2026-07-22T07:00:00+00:00",
        "generated_at": "2026-07-22T07:00:02+00:00",
        "status": status,
        "counts": {"healthy": 1, "attention": 0, "failed": 0},
        "checks": [
            {
                "operation": "service.status",
                "target": "limeopsd",
                "outcome": "healthy",
                "summary": '{"active_state":"active"}',
                "audit_id": "audit-1",
                "error_code": None,
            }
        ],
    }


def test_report_renderer_is_bounded_and_distinguishes_attention():
    healthy = render_mattermost_report(report())
    attention = render_mattermost_report(report("partial"))

    assert healthy["attachments"][0]["color"] == "#3a7bd5"
    assert "Scheduled report" in healthy["attachments"][0]["title"]
    assert attention["attachments"][0]["color"] == "#e0a13b"
    assert "service.status" in healthy["attachments"][0]["text"]
    assert "audit-1" not in healthy["attachments"][0]["text"]


def test_delivery_reads_only_named_webhook_and_posts_rendered_report(tmp_path):
    secrets = tmp_path / "mattermost.env"
    secrets.write_text(
        "POSTGRES_PASSWORD=private\n"
        "LIMEOS_ALERT_MATTERMOST_WEBHOOK=https://mm.example/hooks/report\n"
    )
    calls = []
    delivery = MattermostReportDelivery(
        secrets_path=secrets,
        poster=lambda url, payload: calls.append((url, payload)),
    )

    delivery(report())

    assert calls[0][0] == "https://mm.example/hooks/report"
    assert "private" not in str(calls[0][1])


def test_delivery_fails_closed_without_webhook(tmp_path):
    delivery = MattermostReportDelivery(
        secrets_path=tmp_path / "missing.env",
        poster=lambda _url, _payload: None,
    )

    try:
        delivery(report())
    except RuntimeError as exc:
        assert str(exc) == "Mattermost report delivery is unavailable"
    else:
        raise AssertionError("missing webhook must fail")
