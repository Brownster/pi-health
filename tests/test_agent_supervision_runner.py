from types import SimpleNamespace

from agent_supervision.runner import build_runtime


class RecordingClient:
    def __init__(self):
        self.calls = []

    def request(self, operation, params, actor):
        self.calls.append((operation, params, actor))
        return {
            "ok": True,
            "data": {
                "operation": "container.restart",
                "capability_version": "1",
                "target": "get_iplayer",
                "params": {"name": "get_iplayer"},
                "precondition_hash": "a" * 64,
            },
        }


def test_runtime_reads_trusted_action_precondition_through_broker(tmp_path):
    client = RecordingClient()
    args = SimpleNamespace(
        supervision=str(tmp_path / "supervision.sqlite3"),
        ledger=str(tmp_path / "actions.sqlite3"),
        socket=str(tmp_path / "limeops.sock"),
        policy=str(tmp_path / "action-policy.json"),
        delivery_config=str(tmp_path / "delivery.json"),
        delivery_secrets=str(tmp_path / "mattermost.env"),
    )
    runtime = build_runtime(
        args,
        scheduler=object(),
        client=client,
        delivery=lambda _context: "post-1",
    )

    result = runtime._authorizer._precondition_provider(
        "container.restart", {"name": "get_iplayer"}
    )

    assert result["precondition_hash"] == "a" * 64
    assert client.calls == [
        (
            "action.precondition",
            {
                "operation": "container.restart",
                "params": {"name": "get_iplayer"},
            },
            {"type": "system", "id": "limeops-supervisor"},
        )
    ]
