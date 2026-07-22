"""Bounded Mattermost rendering and delivery for scheduled reports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from limeops.operations import redact_text


MAX_REPORT_TEXT_CHARS = 7000
MAX_CHECK_TEXT_CHARS = 500
_COLORS = {"healthy": "#3a7bd5", "attention": "#e0a13b", "partial": "#e0a13b"}


def render_mattermost_report(report: Mapping[str, Any]) -> dict[str, Any]:
    status = str(report.get("status") or "partial")
    name = redact_text(str(report.get("schedule_name") or "Scheduled diagnosis"))[:120]
    counts = report.get("counts") if isinstance(report.get("counts"), Mapping) else {}
    lines = [
        (
            f"{int(counts.get('healthy') or 0)} healthy · "
            f"{int(counts.get('attention') or 0)} attention · "
            f"{int(counts.get('failed') or 0)} failed"
        )
    ]
    checks = report.get("checks")
    if isinstance(checks, list):
        for check in checks[:12]:
            if not isinstance(check, Mapping):
                continue
            operation = redact_text(str(check.get("operation") or "unknown"))[:128]
            target = redact_text(str(check.get("target") or "host"))[:128]
            outcome = redact_text(str(check.get("outcome") or "failed"))[:32]
            summary = redact_text(str(check.get("summary") or "No summary"))[
                :MAX_CHECK_TEXT_CHARS
            ]
            lines.append(f"- `{operation}` · `{target}` · **{outcome}** — {summary}")
    text = "\n".join(lines)[:MAX_REPORT_TEXT_CHARS]
    warning = status != "healthy"
    return {
        "attachments": [
            {
                "color": _COLORS.get(status, _COLORS["partial"]),
                "title": f"{'⚠️' if warning else '📋'} Scheduled report: {name}",
                "text": text,
                "fields": [
                    {"short": True, "title": "Status", "value": status},
                    {
                        "short": True,
                        "title": "Scheduled for",
                        "value": str(report.get("scheduled_for") or "unknown")[:64],
                    },
                ],
            }
        ]
    }


class MattermostReportDelivery:
    def __init__(
        self,
        *,
        secrets_path: str | Path,
        poster: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._secrets_path = Path(secrets_path)
        self._poster = poster or _post

    def __call__(self, report: Mapping[str, Any]) -> None:
        webhook = self._read_webhook()
        if webhook is None:
            raise RuntimeError("Mattermost report delivery is unavailable")
        self._poster(webhook, render_mattermost_report(report))

    def _read_webhook(self) -> str | None:
        try:
            if self._secrets_path.is_symlink():
                return None
            lines = self._secrets_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        prefix = "LIMEOS_ALERT_MATTERMOST_WEBHOOK="
        for line in lines:
            if line.startswith(prefix):
                value = line[len(prefix) :].strip()
                if value.startswith(("https://", "http://")) and len(value) <= 2048:
                    return value
                return None
        return None


def _post(url: str, payload: dict[str, Any]) -> None:  # pragma: no cover - network adapter
    import requests

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
