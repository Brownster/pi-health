import json

import pytest

from limeops.cli import EXIT_DENIED, EXIT_OK, main


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, operation, params, actor):
        self.calls.append((operation, params, actor))
        return self.response


def success(data=None):
    return {
        "schema_version": "1",
        "request_id": "request-1",
        "ok": True,
        "operation": "system.status",
        "data": data or {"healthy": True},
        "warnings": [],
        "error": None,
        "audit_id": "audit-1",
    }


def test_cli_maps_nested_command_to_operation_and_prints_json(capsys):
    client = FakeClient(success())
    code = main(
        ["--json", "system", "status"],
        client_factory=lambda **_kwargs: client,
    )
    assert code == EXIT_OK
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert client.calls[0][0:2] == ("system.status", {})
    assert client.calls[0][2]["type"] == "local"


def test_cli_maps_resource_and_bounded_lines(capsys):
    client = FakeClient(success({"logs": "hello"}))
    code = main(
        ["--json", "container", "logs", "jellyfin", "--lines", "250"],
        client_factory=lambda **_kwargs: client,
    )
    assert code == EXIT_OK
    assert client.calls[0][0:2] == (
        "container.logs",
        {"name": "jellyfin", "lines": 250},
    )
    assert json.loads(capsys.readouterr().out)["data"] == {"logs": "hello"}


def test_cli_prints_human_data_without_json_flag(capsys):
    client = FakeClient(success({"healthy": True}))
    assert main(["system", "status"], client_factory=lambda **_kwargs: client) == EXIT_OK
    output = capsys.readouterr()
    assert '"healthy": true' in output.out
    assert output.err == ""


def test_cli_maps_stable_error_to_exit_code_and_stderr(capsys):
    client = FakeClient(
        {
            **success(),
            "ok": False,
            "data": None,
            "error": {"code": "denied_operation", "message": "Operation is denied"},
        }
    )
    code = main(["stack", "inspect", "media"], client_factory=lambda **_kwargs: client)
    output = capsys.readouterr()
    assert code == EXIT_DENIED
    assert output.out == ""
    assert output.err == "error: Operation is denied\n"


def test_cli_json_error_stays_on_stdout(capsys):
    response = {
        **success(),
        "ok": False,
        "data": None,
        "error": {"code": "denied_operation", "message": "Operation is denied"},
    }
    code = main(
        ["--json", "stack", "inspect", "media"],
        client_factory=lambda **_kwargs: FakeClient(response),
    )
    output = capsys.readouterr()
    assert code == EXIT_DENIED
    assert json.loads(output.out)["error"]["code"] == "denied_operation"
    assert output.err == ""


@pytest.mark.parametrize(
    "args,operation,params",
    [
        (["context"], "context", {}),
        (["container", "list"], "container.list", {}),
        (["container", "status", "plex"], "container.status", {"name": "plex"}),
        (["stack", "list"], "stack.list", {}),
        (["stack", "status", "media"], "stack.status", {"name": "media"}),
        (["service", "status", "docker"], "service.status", {"name": "docker"}),
        (["disk", "health"], "disk.health", {}),
        (["mount", "status"], "mount.status", {}),
        (["snapraid", "status"], "snapraid.status", {}),
        (["network", "check", "internet"], "network.check", {"target": "internet"}),
        (["installation", "inventory"], "installation.inventory", {}),
    ],
)
def test_cli_operation_mapping(args, operation, params, capsys):
    client = FakeClient(success())
    assert main(args, client_factory=lambda **_kwargs: client) == EXIT_OK
    assert client.calls[0][0:2] == (operation, params)
    capsys.readouterr()


def test_cli_rejects_out_of_range_log_lines_before_client(capsys):
    with pytest.raises(SystemExit) as error:
        main(
            ["container", "logs", "plex", "--lines", "501"],
            client_factory=lambda **_kwargs: FakeClient(success()),
        )
    assert error.value.code == 2
    assert "between 20 and 500" in capsys.readouterr().err


def test_cli_help_is_available(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "Read LimeOS operational state" in output
    assert "container" in output
