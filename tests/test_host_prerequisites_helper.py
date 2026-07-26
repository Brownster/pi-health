from __future__ import annotations

import pytest

import pihealth_helper as helper


BASE_CMDLINE = (
    "console=serial0,115200 console=tty1 root=PARTUUID=6dbeb0a9-02 "
    "rootfstype=ext4 fsck.repair=yes rootwait"
)


@pytest.fixture
def cmdline(monkeypatch, tmp_path):
    path = tmp_path / "cmdline.txt"
    path.write_text(BASE_CMDLINE + "\n")
    monkeypatch.setattr(helper, "KERNEL_CMDLINE_PATHS", (str(path),))
    return path


def test_missing_parameters_are_appended_with_a_backup(cmdline, tmp_path):
    result = helper.cmd_host_prerequisites_apply({})

    assert result["success"] is True
    assert result["changed"] is True
    assert result["added"] == ["cgroup_enable=memory", "cgroup_memory=1"]

    written = cmdline.read_text()
    assert "cgroup_enable=memory cgroup_memory=1" in written
    assert written.startswith(BASE_CMDLINE)

    backup = tmp_path / result["backup"].split("/")[-1]
    assert backup.read_text() == BASE_CMDLINE + "\n"


def test_the_result_stays_a_single_line(cmdline):
    """A second line in cmdline.txt stops a Raspberry Pi from booting."""
    helper.cmd_host_prerequisites_apply({})

    content = cmdline.read_text()
    assert content.endswith("\n")
    assert content.count("\n") == 1


def test_existing_boot_parameters_are_preserved(cmdline):
    helper.cmd_host_prerequisites_apply({})

    parameters = cmdline.read_text().split()
    assert "root=PARTUUID=6dbeb0a9-02" in parameters
    assert "rootwait" in parameters
    assert parameters[: len(BASE_CMDLINE.split())] == BASE_CMDLINE.split()


def test_applying_twice_changes_nothing_the_second_time(cmdline):
    helper.cmd_host_prerequisites_apply({})
    first = cmdline.read_text()

    second_result = helper.cmd_host_prerequisites_apply({})

    assert second_result["changed"] is False
    assert cmdline.read_text() == first


def test_a_partially_configured_line_gains_only_what_is_missing(cmdline):
    cmdline.write_text(BASE_CMDLINE + " cgroup_enable=memory\n")

    result = helper.cmd_host_prerequisites_apply({})

    assert result["added"] == ["cgroup_memory=1"]
    assert cmdline.read_text().split().count("cgroup_enable=memory") == 1


def test_a_host_without_a_cmdline_file_is_reported_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "KERNEL_CMDLINE_PATHS", (str(tmp_path / "absent.txt"),))

    result = helper.cmd_host_prerequisites_apply({})

    assert result["success"] is True
    assert result["changed"] is False
    assert result["supported"] is False


def test_the_command_ignores_caller_supplied_paths(monkeypatch, tmp_path):
    """The helper picks the boot file; a caller must never be able to aim it."""
    path = tmp_path / "cmdline.txt"
    path.write_text(BASE_CMDLINE + "\n")
    monkeypatch.setattr(helper, "KERNEL_CMDLINE_PATHS", (str(path),))
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n")

    result = helper.cmd_host_prerequisites_apply(
        {"path": str(victim), "cmdline_path": str(victim), "parameters": ["init=/bin/sh"]}
    )

    assert result["path"] == str(path)
    assert victim.read_text() == "untouched\n"
    assert "init=/bin/sh" not in path.read_text()


def test_the_command_is_registered_as_mutating(monkeypatch):
    assert helper.COMMANDS["host_prerequisites_apply"] is helper.cmd_host_prerequisites_apply
    assert "host_prerequisites_apply" in helper._MUTATING_COMMANDS
