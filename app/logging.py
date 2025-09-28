from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict

from flask import Flask, g, request
from flask.signals import got_request_exception


class JsonRequestFormatter(logging.Formatter):
    """Render log records as JSON lines with request metadata when available."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - base class contract
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, self.default_time_format),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None)
        if request_id is None:
            try:
                request_id = getattr(g, "request_id", None)
            except RuntimeError:
                request_id = None
        if request_id:
            payload["request_id"] = request_id

        if hasattr(record, "method"):
            payload["method"] = record.method
        if hasattr(record, "path"):
            payload["path"] = record.path
        if hasattr(record, "status_code"):
            payload["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            payload["duration_ms"] = record.duration_ms

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)


def init_logging(app: Flask) -> None:
    """Configure JSON logging and request ID middleware for the Flask app."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonRequestFormatter())

    # Reset Flask's default handlers to avoid duplicate logs.
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    @app.before_request
    def _inject_request_id() -> None:  # pragma: no cover - flask runtime hook
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.request_id = request_id
        g.request_started = time.time()

    @app.after_request
    def _log_request(response):  # pragma: no cover - flask runtime hook
        try:
            request_id = getattr(g, "request_id", None)
        except RuntimeError:
            request_id = None
        if request_id:
            response.headers["X-Request-ID"] = request_id

        started = getattr(g, "request_started", None)
        duration_ms = None
        if isinstance(started, (int, float)):
            duration_ms = round((time.time() - started) * 1000, 2)

        extra = {
            "request_id": request_id,
            "method": request.method,
            "path": request.path,
            "status_code": response.status_code,
        }
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms

        app.logger.info("request complete", extra=extra)
        return response

    @got_request_exception.connect_via(app)
    def _log_exception(sender, exception, **kwargs):  # pragma: no cover - runtime hook
        try:
            request_id = getattr(g, "request_id", None)
        except RuntimeError:
            request_id = None
        extra = {
            "request_id": request_id,
            "method": getattr(request, "method", None),
            "path": getattr(request, "path", None),
        }
        exc_info = (type(exception), exception, exception.__traceback__)
        app.logger.error("request error", exc_info=exc_info, extra=extra)


def current_request_id() -> str | None:
    """Return the request ID for the active request context if present."""

    try:
        return getattr(g, "request_id", None)
    except RuntimeError:
        return None
