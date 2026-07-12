"""BF-004 characterization: the SSE operation transport (operation_sse).

Locks in the reconnect and ownership invariants of ``stream_operation_response``:
session->owner mapping, Last-Event-ID cursor math, SSE framing, keep-alives, and
stream termination on completion or lost ownership. Uses a fake registry so no
threads or sockets are involved; failures here mean a transport invariant moved
even if a payload still looks valid.
"""

from flask import Flask

from operation_manager import OperationEvent, OperationEventBatch
from operation_sse import stream_operation_response

OWNER_TOKEN = "owner-token"
KIND = "catalog-install"
OP_ID = "op-1"


class FakeRegistry:
    def __init__(self, *, is_owner=True, batches=None):
        self._is_owner = is_owner
        self._batches = list(batches or [])
        self.is_owner_calls = []
        self.events_since_calls = []

    def is_owner(self, operation_id, *, expected_kind, owner):
        self.is_owner_calls.append(
            {"operation_id": operation_id, "expected_kind": expected_kind, "owner": owner}
        )
        return self._is_owner

    def events_since(self, operation_id, *, expected_kind, owner, cursor, wait_timeout):
        self.events_since_calls.append(
            {"cursor": cursor, "owner": owner, "expected_kind": expected_kind}
        )
        if self._batches:
            return self._batches.pop(0)
        return None


def _event(event_id, payload):
    return OperationEvent(event_id=event_id, payload=payload)


def _batch(events=(), *, next_cursor=0, complete=False):
    return OperationEventBatch(events=tuple(events), next_cursor=next_cursor, complete=complete)


def _client(registry, *, owner=OWNER_TOKEN):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"

    @app.route("/stream")
    def stream():
        return stream_operation_response(registry, OP_ID, KIND)

    client = app.test_client()
    if owner is not None:
        with client.session_transaction() as sess:
            sess["csrf_token"] = owner
    return client


# --- Ownership ---------------------------------------------------------------

def test_non_owner_gets_404():
    registry = FakeRegistry(is_owner=False)
    response = _client(registry).get("/stream")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Operation not found"}


def test_ownership_check_uses_session_token_and_expected_kind():
    registry = FakeRegistry(is_owner=False)
    _client(registry, owner="my-token").get("/stream")
    call = registry.is_owner_calls[0]
    assert call["owner"] == "my-token"
    assert call["expected_kind"] == KIND
    assert call["operation_id"] == OP_ID


def test_missing_session_token_is_treated_as_non_owner():
    # A request with no session csrf_token maps owner to None; the registry must reject it.
    registry = FakeRegistry(is_owner=False)
    response = _client(registry, owner=None).get("/stream")
    assert response.status_code == 404
    assert registry.is_owner_calls[0]["owner"] is None


# --- SSE framing and completion ---------------------------------------------

def test_streams_events_as_sse_frames_and_completes():
    registry = FakeRegistry(
        batches=[_batch([_event(1, {"line": "hello"})], next_cursor=2, complete=True)]
    )
    response = _client(registry).get("/stream")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    assert "id: 1\n" in body
    assert 'data: {"line": "hello"}' in body


def test_stream_hides_ephemeral_control_marker():
    registry = FakeRegistry(
        batches=[
            _batch(
                [
                    _event(
                        1,
                        {
                            "authorization_url": "https://claude.ai/login",
                            "_ephemeral": True,
                        },
                    )
                ],
                next_cursor=2,
                complete=True,
            )
        ]
    )
    body = _client(registry).get("/stream").get_data(as_text=True)
    assert "https://claude.ai/login" in body
    assert "_ephemeral" not in body


def test_sets_no_buffering_headers():
    registry = FakeRegistry(batches=[_batch([], next_cursor=0, complete=True)])
    response = _client(registry).get("/stream")
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"


def test_emits_keep_alive_when_no_events_yet():
    registry = FakeRegistry(
        batches=[
            _batch([], next_cursor=0, complete=False),
            _batch([_event(1, {"done": True})], next_cursor=2, complete=True),
        ]
    )
    body = _client(registry).get("/stream").get_data(as_text=True)
    assert ": keep-alive\n\n" in body
    assert '"done"' in body


def test_stream_ends_when_ownership_lost_midway():
    # events_since returning None (ownership revoked / gone) terminates the stream.
    registry = FakeRegistry(batches=[])  # first events_since returns None
    response = _client(registry).get("/stream")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == ""


# --- Last-Event-ID reconnect cursor -----------------------------------------

def test_last_event_id_resumes_after_given_id():
    registry = FakeRegistry(batches=[_batch([], next_cursor=0, complete=True)])
    _client(registry).get("/stream", headers={"Last-Event-ID": "4"}).get_data()
    assert registry.events_since_calls[0]["cursor"] == 5


def test_missing_last_event_id_starts_at_zero():
    registry = FakeRegistry(batches=[_batch([], next_cursor=0, complete=True)])
    _client(registry).get("/stream").get_data()
    assert registry.events_since_calls[0]["cursor"] == 0


def test_non_integer_last_event_id_starts_at_zero():
    registry = FakeRegistry(batches=[_batch([], next_cursor=0, complete=True)])
    _client(registry).get("/stream", headers={"Last-Event-ID": "not-a-number"}).get_data()
    assert registry.events_since_calls[0]["cursor"] == 0


def test_negative_last_event_id_is_clamped_to_zero():
    registry = FakeRegistry(batches=[_batch([], next_cursor=0, complete=True)])
    # "-5" + 1 = -4, clamped up to 0.
    _client(registry).get("/stream", headers={"Last-Event-ID": "-5"}).get_data()
    assert registry.events_since_calls[0]["cursor"] == 0


def test_cursor_advances_across_batches():
    registry = FakeRegistry(
        batches=[
            _batch([_event(1, {"line": "a"})], next_cursor=2, complete=False),
            _batch([_event(2, {"done": True})], next_cursor=3, complete=True),
        ]
    )
    _client(registry).get("/stream").get_data()
    assert registry.events_since_calls[0]["cursor"] == 0
    assert registry.events_since_calls[1]["cursor"] == 2
