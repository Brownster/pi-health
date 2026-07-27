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


@pytest.fixture
def journald(monkeypatch, tmp_path):
    """Point the journal cap at a temporary drop-in and stub the systemd calls."""
    dropin = tmp_path / "journald.conf.d" / "limeos.conf"
    monkeypatch.setattr(helper, "JOURNALD_DROPIN_PATH", str(dropin))
    commands = []
    monkeypatch.setattr(
        helper, "run_command", lambda cmd, **kwargs: commands.append(cmd) or {"returncode": 0}
    )
    monkeypatch.setattr(helper, "_journal_cap_is_set", lambda: False)
    return dropin, commands


# --- kernel command line -----------------------------------------------------


def test_missing_parameters_are_appended_with_a_backup(cmdline, tmp_path):
    result = helper._apply_memory_cgroup()

    assert result["changed"] is True
    assert result["added"] == ["cgroup_enable=memory", "cgroup_memory=1"]

    written = cmdline.read_text()
    assert "cgroup_enable=memory cgroup_memory=1" in written
    assert written.startswith(BASE_CMDLINE)

    backup = tmp_path / result["backup"].split("/")[-1]
    assert backup.read_text() == BASE_CMDLINE + "\n"


def test_the_result_stays_a_single_line(cmdline):
    """A second line in cmdline.txt stops a Raspberry Pi from booting."""
    helper._apply_memory_cgroup()

    content = cmdline.read_text()
    assert content.endswith("\n")
    assert content.count("\n") == 1


def test_existing_boot_parameters_are_preserved(cmdline):
    helper._apply_memory_cgroup()

    parameters = cmdline.read_text().split()
    assert "root=PARTUUID=6dbeb0a9-02" in parameters
    assert "rootwait" in parameters
    assert parameters[: len(BASE_CMDLINE.split())] == BASE_CMDLINE.split()


def test_applying_twice_changes_nothing_the_second_time(cmdline):
    helper._apply_memory_cgroup()
    first = cmdline.read_text()

    second = helper._apply_memory_cgroup()

    assert second["changed"] is False
    assert cmdline.read_text() == first


def test_a_partially_configured_line_gains_only_what_is_missing(cmdline):
    cmdline.write_text(BASE_CMDLINE + " cgroup_enable=memory\n")

    result = helper._apply_memory_cgroup()

    assert result["added"] == ["cgroup_memory=1"]
    assert cmdline.read_text().split().count("cgroup_enable=memory") == 1


def test_a_host_without_a_cmdline_file_is_reported_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "KERNEL_CMDLINE_PATHS", (str(tmp_path / "absent.txt"),))

    result = helper._apply_memory_cgroup()

    assert result["changed"] is False
    assert result["supported"] is False


# --- journal cap -------------------------------------------------------------


def test_the_journal_cap_is_written_as_a_dropin_then_reclaimed(journald):
    dropin, commands = journald

    result = helper._apply_journal_cap()

    assert result["changed"] is True
    assert result["limit"] == helper.JOURNAL_MAX_USE
    assert f"SystemMaxUse={helper.JOURNAL_MAX_USE}" in dropin.read_text()
    # The cap governs the next start; the vacuum reclaims what is already there.
    assert ["systemctl", "restart", "systemd-journald"] in commands
    assert [f"--vacuum-size={helper.JOURNAL_MAX_USE}" in " ".join(c) for c in commands].count(
        True
    ) == 1


def test_an_operator_who_set_their_own_cap_is_not_overruled(monkeypatch, tmp_path):
    dropin = tmp_path / "limeos.conf"
    monkeypatch.setattr(helper, "JOURNALD_DROPIN_PATH", str(dropin))
    monkeypatch.setattr(helper, "_journal_cap_is_set", lambda: True)

    result = helper._apply_journal_cap()

    assert result["changed"] is False
    assert not dropin.exists()


def test_an_unwritable_dropin_is_reported_rather_than_raised(monkeypatch, tmp_path):
    target = tmp_path / "nope" / "limeos.conf"
    monkeypatch.setattr(helper, "JOURNALD_DROPIN_PATH", str(target))
    monkeypatch.setattr(helper, "_journal_cap_is_set", lambda: False)
    monkeypatch.setattr(helper.os, "makedirs", _raise_permission_error)

    result = helper._apply_journal_cap()

    assert "error" in result
    assert result["id"] == "journal_cap"


def _raise_permission_error(*_args, **_kwargs):
    raise PermissionError("read-only file system")


def test_an_existing_cap_is_detected_from_a_dropin(monkeypatch, tmp_path):
    config = tmp_path / "journald.conf"
    config.write_text("[Journal]\n#SystemMaxUse=\n")
    dropin_dir = tmp_path / "journald.conf.d"
    dropin_dir.mkdir()
    (dropin_dir / "zz-operator.conf").write_text("[Journal]\nSystemMaxUse=500M\n")

    real_listdir, real_open = helper.os.listdir, open

    monkeypatch.setattr(
        helper.os,
        "listdir",
        lambda path: real_listdir(dropin_dir)
        if path == "/etc/systemd/journald.conf.d"
        else real_listdir(path),
    )
    monkeypatch.setattr(
        "builtins.open",
        lambda path, *a, **kw: real_open(
            str(path)
            .replace("/etc/systemd/journald.conf.d", str(dropin_dir))
            .replace("/etc/systemd/journald.conf", str(config)),
            *a,
            **kw,
        ),
    )

    assert helper._journal_cap_is_set() is True


# --- dispatcher --------------------------------------------------------------


def test_every_setting_is_applied_and_reported_separately(cmdline, journald):
    response = helper.cmd_host_prerequisites_apply({})

    assert response["success"] is True
    assert response["changed"] is True
    assert [item["id"] for item in response["results"]] == ["memory_cgroup", "journal_cap"]


def test_one_failing_setting_does_not_stop_the_others(monkeypatch, journald):
    monkeypatch.setattr(helper, "_apply_memory_cgroup", _raise_permission_error)

    response = helper.cmd_host_prerequisites_apply({})

    assert response["success"] is True
    results = {item["id"]: item for item in response["results"]}
    # The failure is reported against the prerequisite, not an internal function name.
    assert "read-only file system" in results["memory_cgroup"]["error"]
    assert results["journal_cap"]["changed"] is True


def test_the_command_ignores_caller_supplied_paths(monkeypatch, tmp_path, journald):
    """The helper picks the files; a caller must never be able to aim it."""
    path = tmp_path / "cmdline.txt"
    path.write_text(BASE_CMDLINE + "\n")
    monkeypatch.setattr(helper, "KERNEL_CMDLINE_PATHS", (str(path),))
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n")

    response = helper.cmd_host_prerequisites_apply(
        {"path": str(victim), "cmdline_path": str(victim), "parameters": ["init=/bin/sh"]}
    )

    assert response["results"][0]["path"] == str(path)
    assert victim.read_text() == "untouched\n"
    assert "init=/bin/sh" not in path.read_text()


def test_the_command_is_registered_as_mutating():
    assert helper.COMMANDS["host_prerequisites_apply"] is helper.cmd_host_prerequisites_apply
    assert "host_prerequisites_apply" in helper._MUTATING_COMMANDS
