from host_prerequisites import (
    JOURNAL_CAP,
    MEMORY_CGROUP,
    HostPrerequisiteService,
    is_journal_capped,
    is_memory_cgroup_enabled,
)


CAPPED = ["[Journal]\nSystemMaxUse=200M\n"]
UNCAPPED = ["[Journal]\n#SystemMaxUse=\n"]


class FakeHelper:
    """Returns a scripted per-prerequisite response from the repair command."""

    def __init__(self, results=None, error=None, success=True, failure=None):
        self.results = results
        self.error = error
        self.success = success
        self.failure = failure
        self.calls = []

    def call(self, command, params=None):
        self.calls.append((command, params))
        if self.error:
            raise self.error
        if not self.success:
            return {"success": False, "error": self.failure or "boom"}
        return {"success": True, "results": self.results or []}


def make_service(controllers, *, journal=CAPPED, helper=None):
    return HostPrerequisiteService(
        helper=helper,
        controller_reader=lambda: set(controllers),
        journal_config_reader=lambda: list(journal),
    )


def requirement(status, prerequisite_id):
    return next(item for item in status["requirements"] if item["id"] == prerequisite_id)


# --- detection ---------------------------------------------------------------


def test_a_correctly_configured_host_satisfies_everything():
    status = make_service(["cpuset", "cpu", "io", "memory", "pids"]).status()

    assert status["satisfied"] is True
    assert status["reboot_required"] is False


def test_a_missing_memory_controller_is_reported_with_its_remedy():
    status = make_service(["cpuset", "cpu", "io", "pids"]).status()

    assert status["satisfied"] is False
    assert status["reboot_required"] is True
    assert requirement(status, MEMORY_CGROUP)["satisfied"] is False
    assert "cgroup_enable=memory" in requirement(status, MEMORY_CGROUP)["remedy"]


def test_an_uncapped_journal_is_reported_without_asking_for_a_reboot():
    status = make_service(["memory"], journal=UNCAPPED).status()

    assert status["satisfied"] is False
    # Journald reloads on restart; nothing here waits on a boot.
    assert status["reboot_required"] is False
    assert requirement(status, JOURNAL_CAP)["satisfied"] is False
    assert requirement(status, JOURNAL_CAP)["requires_reboot"] is False


def test_an_unreadable_controller_list_reports_unknown_not_broken():
    # cgroup v1 has no cgroup.controllers file; claiming a fault there is a guess.
    status = make_service([]).status()

    assert requirement(status, MEMORY_CGROUP)["satisfied"] is None
    assert status["satisfied"] is True


def test_is_memory_cgroup_enabled_distinguishes_absent_from_unreadable():
    assert is_memory_cgroup_enabled(lambda: {"cpu", "memory"}) is True
    assert is_memory_cgroup_enabled(lambda: {"cpu", "pids"}) is False
    assert is_memory_cgroup_enabled(lambda: set()) is None


def test_any_existing_journal_cap_counts_as_satisfied():
    """An operator who chose 500M has already made this decision."""
    assert is_journal_capped(lambda: ["[Journal]\nSystemMaxUse=500M\n"]) is True
    assert is_journal_capped(lambda: ["[Journal]\n# SystemMaxUse=200M\n"]) is False
    assert is_journal_capped(lambda: []) is None


def test_a_cap_set_in_any_source_counts():
    sources = ["[Journal]\n#SystemMaxUse=\n", "[Journal]\nSystemMaxUse=200M\n"]

    assert is_journal_capped(lambda: sources) is True


# --- repair ------------------------------------------------------------------


def test_apply_repairs_both_settings_and_asks_for_the_reboot_one_needs():
    helper = FakeHelper(
        [
            {"id": MEMORY_CGROUP, "changed": True, "supported": True},
            {"id": JOURNAL_CAP, "changed": True, "supported": True},
        ]
    )
    result = make_service(["cpuset"], journal=UNCAPPED, helper=helper).apply()

    assert helper.calls == [("host_prerequisites_apply", {})]
    assert result["changed"] is True
    assert sorted(result["applied"]) == sorted([JOURNAL_CAP, MEMORY_CGROUP])
    assert result["reboot_required"] is True
    assert result["errors"] == []


def test_capping_the_journal_alone_asks_for_no_reboot():
    helper = FakeHelper([{"id": JOURNAL_CAP, "changed": True, "supported": True}])
    result = make_service(["memory"], journal=UNCAPPED, helper=helper).apply()

    assert result["applied"] == [JOURNAL_CAP]
    assert result["reboot_required"] is False


def test_apply_leaves_a_satisfied_host_alone():
    helper = FakeHelper()
    result = make_service(["memory"], helper=helper).apply()

    assert helper.calls == []
    assert result == {"changed": False, "reboot_required": False, "applied": [], "errors": []}


def test_a_boot_file_already_configured_still_asks_for_the_reboot():
    """Configured on disk, absent from the running kernel: the reboot is still owed."""
    helper = FakeHelper([{"id": MEMORY_CGROUP, "changed": False, "supported": True}])
    result = make_service(["cpuset"], helper=helper).apply()

    assert result["changed"] is False
    assert result["reboot_required"] is True
    assert result["applied"] == []


def test_a_host_that_does_not_boot_from_cmdline_asks_for_nothing():
    helper = FakeHelper([{"id": MEMORY_CGROUP, "changed": False, "supported": False}])
    result = make_service(["cpuset"], helper=helper).apply()

    assert result["changed"] is False
    assert result["reboot_required"] is False


def test_one_failed_setting_is_named_while_the_other_still_applies():
    helper = FakeHelper(
        [
            {"id": MEMORY_CGROUP, "error": "read-only file system"},
            {"id": JOURNAL_CAP, "changed": True, "supported": True},
        ]
    )
    result = make_service(["cpuset"], journal=UNCAPPED, helper=helper).apply()

    assert result["applied"] == [JOURNAL_CAP]
    assert result["reboot_required"] is False
    assert result["errors"] == ["Container memory accounting: read-only file system"]


def test_results_for_settings_this_host_already_had_are_ignored():
    helper = FakeHelper(
        [
            {"id": MEMORY_CGROUP, "changed": True, "supported": True},
            {"id": JOURNAL_CAP, "changed": True, "supported": True},
        ]
    )
    # Only the cgroup was unsatisfied, so only it may be reported as applied.
    result = make_service(["cpuset"], journal=CAPPED, helper=helper).apply()

    assert result["applied"] == [MEMORY_CGROUP]


def test_an_unknown_result_id_is_ignored():
    helper = FakeHelper([{"id": "something_else", "changed": True, "supported": True}])
    result = make_service(["cpuset"], helper=helper).apply()

    assert result["applied"] == []
    assert result["changed"] is False


def test_a_helper_failure_is_reported_without_claiming_a_change():
    helper = FakeHelper(success=False, failure="helper refused")
    result = make_service(["cpuset"], helper=helper).apply()

    assert result["changed"] is False
    assert result["errors"] == ["helper refused"]


def test_a_helper_transport_error_is_caught():
    helper = FakeHelper(error=RuntimeError("helper socket missing"))
    result = make_service(["cpuset"], helper=helper).apply()

    assert result["changed"] is False
    assert "helper socket missing" in result["errors"][0]


def test_apply_without_a_helper_reports_why_it_cannot_repair():
    result = make_service(["cpuset"]).apply()

    assert result["changed"] is False
    assert result["errors"] == ["The privileged helper is unavailable"]
