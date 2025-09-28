from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Optional

from flask import Request, current_app, g, has_request_context, request

from app.logging import current_request_id


def _resolve_log_path() -> Path:
    try:
        configured = current_app.config.get('APPROVAL_AUDIT_LOG')  # type: ignore[attr-defined]
    except RuntimeError:
        configured = None
    path = str(configured or os.getenv('APPROVAL_AUDIT_LOG', 'logs/ops_copilot_approvals.log'))
    return Path(path)


def _ensure_parent(path: Path) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def _safe_request() -> Optional[Request]:
    if not has_request_context():
        return None
    return request


def record_approval_event(action_id: str, status: str, payload: Mapping[str, Any]) -> None:
    """Append an approval event as a JSON line for lightweight auditing."""

    path = _resolve_log_path()
    _ensure_parent(path)

    request_obj = _safe_request()
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action_id": action_id,
        "status": status,
        "request_id": current_request_id(),
        "remote_addr": getattr(request_obj, 'remote_addr', None),
        "endpoint": getattr(request_obj, 'path', None),
        "payload": dict(payload),
    }

    actor = None
    try:
        actor = getattr(g, 'current_user', None)
    except RuntimeError:
        actor = None
    if actor is not None:
        entry['actor'] = str(actor)

    try:
        with path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=True))
            fh.write('\n')
    except Exception as exc:  # pragma: no cover - best effort logging
        current_app.logger.error(
            "failed to write approval audit entry",
            extra={"action_id": action_id, "status": status},
            exc_info=(type(exc), exc, exc.__traceback__),
        )
