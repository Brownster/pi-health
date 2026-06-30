"""Flask transport adapter for replayable background-operation events."""

import json

from flask import Response, jsonify, request, session


def stream_operation_response(registry, operation_id, expected_kind):
    """Stream one session-owned operation as SSE with replay support."""
    owner = session.get("csrf_token")
    if not registry.is_owner(
        operation_id,
        expected_kind=expected_kind,
        owner=owner,
    ):
        return jsonify({"error": "Operation not found"}), 404

    try:
        cursor = int(request.headers.get("Last-Event-ID", "-1")) + 1
    except ValueError:
        cursor = 0
    cursor = max(0, cursor)

    def generate():
        nonlocal cursor
        while True:
            batch = registry.events_since(
                operation_id,
                expected_kind=expected_kind,
                owner=owner,
                cursor=cursor,
                wait_timeout=15,
            )
            if batch is None:
                break
            if not batch.events and not batch.complete:
                yield ": keep-alive\n\n"
                continue
            for event in batch.events:
                yield f"id: {event.event_id}\ndata: {json.dumps(event.payload)}\n\n"
            cursor = batch.next_cursor
            if batch.complete:
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
