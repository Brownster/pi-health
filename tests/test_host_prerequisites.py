from host_prerequisites import (
    MEMORY_CGROUP,
    HostPrerequisiteService,
    is_memory_cgroup_enabled,
)


class FakeHelper:
    def __init__(self, response=None, error=None):
        self.response = response or {"success": True, "changed": True, "backup": "/boot/bak"}
        self.error = error
        self.calls = []

    def call(self, command, params=None):
        self.calls.append((command, params))
        if self.error:
            raise self.error
        return self.response


def make_service(controllers, helper=None):
    return HostPrerequisiteService(helper=helper, controller_reader=lambda: set(controllers))


def test_memory_controller_present_satisfies_the_requirement():
    status = make_service(["cpuset", "cpu", "io", "memory", "pids"]).status()

    assert status["satisfied"] is True
    assert status["reboot_required"] is False
    assert status["requirements"][0]["id"] == MEMORY_CGROUP


def test_memory_controller_absent_is_reported_with_its_remedy():
    status = make_service(["cpuset", "cpu", "io", "pids"]).status()

    requirement = status["requirements"][0]
    assert status["satisfied"] is False
    assert status["reboot_required"] is True
    assert requirement["satisfied"] is False
    assert "cgroup_enable=memory" in requirement["remedy"]


def test_an_unreadable_controller_list_reports_unknown_not_broken():
    # cgroup v1 has no cgroup.controllers file; claiming a fault there would be a guess.
    status = make_service([]).status()

    assert status["requirements"][0]["satisfied"] is None
    assert status["satisfied"] is True
    assert status["reboot_required"] is False


def test_is_memory_cgroup_enabled_distinguishes_absent_from_unreadable():
    assert is_memory_cgroup_enabled(lambda: {"cpu", "memory"}) is True
    assert is_memory_cgroup_enabled(lambda: {"cpu", "pids"}) is False
    assert is_memory_cgroup_enabled(lambda: set()) is None


def test_apply_repairs_an_unsatisfied_host_and_asks_for_a_reboot():
    helper = FakeHelper()
    result = make_service(["cpuset", "cpu"], helper).apply()

    assert helper.calls == [("host_prerequisites_apply", {})]
    assert result["changed"] is True
    assert result["reboot_required"] is True
    assert result["applied"] == [MEMORY_CGROUP]
    assert result["errors"] == []


def test_apply_leaves_a_satisfied_host_alone():
    helper = FakeHelper()
    result = make_service(["memory", "cpu"], helper).apply()

    assert helper.calls == []
    assert result == {"changed": False, "reboot_required": False, "applied": [], "errors": []}


def test_a_boot_file_already_configured_still_asks_for_the_reboot():
    """Configured on disk, absent from the running kernel: the reboot is still owed."""
    helper = FakeHelper({"success": True, "changed": False, "supported": True})
    result = make_service(["cpuset"], helper).apply()

    assert result["changed"] is False
    assert result["reboot_required"] is True
    assert result["applied"] == []


def test_a_host_that_does_not_boot_from_cmdline_asks_for_nothing():
    helper = FakeHelper({"success": True, "changed": False, "supported": False})
    result = make_service(["cpuset"], helper).apply()

    assert result["changed"] is False
    assert result["reboot_required"] is False


def test_a_helper_failure_is_reported_without_claiming_a_change():
    helper = FakeHelper({"success": False, "error": "read-only file system"})
    result = make_service(["cpuset"], helper).apply()

    assert result["changed"] is False
    assert result["reboot_required"] is False
    assert result["errors"] == ["read-only file system"]


def test_a_helper_transport_error_is_caught():
    helper = FakeHelper(error=RuntimeError("helper socket missing"))
    result = make_service(["cpuset"], helper).apply()

    assert result["changed"] is False
    assert "helper socket missing" in result["errors"][0]


def test_apply_without_a_helper_reports_why_it_cannot_repair():
    result = make_service(["cpuset"]).apply()

    assert result["changed"] is False
    assert result["errors"] == ["The privileged helper is unavailable"]
