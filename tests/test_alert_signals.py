from types import SimpleNamespace

from alert_daemon import (
    build_live_provider,
    collect_signals,
    config_from_env,
    container_records,
    mounts_present,
    run_once,
    smart_passed,
)
from alert_evaluator import AlertEvaluator, AlertEvaluatorConfig
from alert_notifier import RecordingNotifier
from alert_signals import (
    ContainerRecord,
    DiskHealth,
    container_signals,
    mount_signals,
    smart_signals,
    snapraid_signals,
)


# -- pure providers ----------------------------------------------------------
def test_container_signals_only_watch_long_running_and_flag_down_or_unhealthy():
    records = [
        ContainerRecord("jellyfin", running=True, health="healthy", restart_policy="unless-stopped"),
        ContainerRecord("sonarr", running=False, health=None, restart_policy="always"),
        ContainerRecord("radarr", running=True, health="unhealthy", restart_policy="always"),
        ContainerRecord("backup-job", running=False, health=None, restart_policy="no"),  # one-shot: ignored
    ]
    signals = {s.key: s for s in container_signals(records)}
    assert "container:backup-job" not in signals  # one-shot never pages
    assert signals["container:jellyfin"].ok is True
    assert signals["container:sonarr"].ok is False and "not running" in signals["container:sonarr"].summary
    assert signals["container:radarr"].ok is False and "healthcheck" in signals["container:radarr"].summary
    assert signals["container:sonarr"].severity == "warning"


def test_smart_signals_unknown_assessment_is_silent_critical_on_fail():
    signals = smart_signals([
        DiskHealth("/dev/sda", passed=True),
        DiskHealth("/dev/sdb", passed=False, summary="SMART FAILING"),
        DiskHealth("/dev/sdc", passed=None),  # unknown -> no signal
    ])
    by_key = {s.key: s for s in signals}
    assert "smart:/dev/sdc" not in by_key
    assert by_key["smart:/dev/sda"].ok is True
    assert by_key["smart:/dev/sdb"].ok is False
    assert by_key["smart:/dev/sdb"].severity == "critical"


def test_mount_signals_required_missing_is_critical():
    signals = {s.key: s for s in mount_signals({"/mnt/disk1"}, ["/mnt/disk1", "/mnt/parity"])}
    assert signals["mount:/mnt/disk1"].ok is True
    assert signals["mount:/mnt/parity"].ok is False
    assert signals["mount:/mnt/parity"].severity == "critical"


def test_snapraid_signals_map_status_to_severity():
    assert snapraid_signals({"status": "unconfigured"}) == []
    assert snapraid_signals(None) == []
    error = snapraid_signals({"status": "error", "message": "Configuration not applied"})
    assert error[0].ok is False and error[0].severity == "critical"
    degraded = snapraid_signals({"status": "degraded", "message": "Sync required"})
    assert degraded[0].ok is False and degraded[0].severity == "warning"
    assert snapraid_signals({"status": "healthy"})[0].ok is True


# -- extraction helpers ------------------------------------------------------
def test_smart_passed_reads_bool_and_string_assessments():
    assert smart_passed({"passed": True}) is True
    assert smart_passed({"smart_status": "PASSED"}) is True
    assert smart_passed({"assessment": "FAILED"}) is False
    assert smart_passed({"error_message": "no data"}) is None
    assert smart_passed({}) is None


def test_container_records_from_docker_attrs():
    container = SimpleNamespace(
        name="jellyfin",
        status="running",
        attrs={
            "State": {"Health": {"Status": "unhealthy"}},
            "HostConfig": {"RestartPolicy": {"Name": "always"}},
        },
    )
    records = container_records([container])
    assert records == [ContainerRecord("jellyfin", running=True, health="unhealthy", restart_policy="always")]


def test_mounts_present_parses_proc_mounts():
    text = "proc /proc proc rw 0 0\n/dev/sda1 /mnt/disk1 ext4 rw 0 0\n"
    assert mounts_present(text) == {"/proc", "/mnt/disk1"}


# -- orchestration -----------------------------------------------------------
def test_collect_signals_isolates_a_failing_source():
    def good():
        return container_signals([ContainerRecord("a", True, None, "always")])

    def broken():
        raise RuntimeError("subsystem down")

    signals = collect_signals([broken, good])
    assert [s.key for s in signals] == ["container:a"]


def test_run_once_evaluates_and_delivers(tmp_path):
    evaluator = AlertEvaluator(
        state_path=tmp_path / "alerts.json",
        config=AlertEvaluatorConfig(fail_threshold=1),
    )
    notifier = RecordingNotifier()

    def provider():
        return mount_signals(set(), ["/mnt/parity"])  # missing -> incident

    notifications = run_once(provider, evaluator, notifier)
    assert [n.event for n in notifications] == ["incident"]
    assert [n.key for n in notifier.sent] == ["mount:/mnt/parity"]


def test_config_from_env_parses_and_defaults():
    config = config_from_env({
        "LIMEOS_ALERT_MATTERMOST_WEBHOOK": "https://mm/hook",
        "LIMEOS_ALERT_POLL_SECONDS": "30",
        "LIMEOS_ALERT_REQUIRED_MOUNTS": "/mnt/disk1, /mnt/parity",
    })
    assert config.webhook_url == "https://mm/hook"
    assert config.poll_seconds == 30
    assert config.fail_threshold == 2  # default
    assert config.required_mounts == ("/mnt/disk1", "/mnt/parity")


def test_build_live_provider_combines_sources():
    provider = build_live_provider(
        list_containers=lambda: [
            SimpleNamespace(name="jellyfin", status="running",
                            attrs={"State": {}, "HostConfig": {"RestartPolicy": {"Name": "always"}}})
        ],
        smart_devices=lambda: {"disks": [{"device": "/dev/sda", "data": {"smart_status": "FAILED"}}]},
        snapraid_status=lambda: {"status": "healthy"},
        read_proc_mounts=lambda: "/dev/sda1 /mnt/disk1 ext4 rw 0 0\n",
        required_mounts=["/mnt/parity"],
    )
    keys = {s.key for s in provider()}
    assert keys == {"container:jellyfin", "smart:/dev/sda", "mount:/mnt/parity", "snapraid:status"}
