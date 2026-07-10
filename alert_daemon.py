"""Alert daemon (brick B2, part 2): poll signals, evaluate, deliver to Mattermost.

Runs as its own process — deliberately outside the Flask API — so an API crash still pages.
The pure orchestration (`collect_signals`, `run_once`) and extraction helpers are unit-tested;
`main()` wires the live services and loops, and is validated on the target hardware.

Config (environment):
  LIMEOS_ALERT_MATTERMOST_WEBHOOK   incoming-webhook URL (unset => dry run, log only)
  LIMEOS_ALERT_POLL_SECONDS         evaluation interval (default 60)
  LIMEOS_ALERT_FAIL_THRESHOLD       consecutive failures before paging (default 2)
  LIMEOS_ALERT_REQUIRED_MOUNTS      comma-separated mountpoints that must be present
"""

from __future__ import annotations

import logging
import json
import os
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from alert_evaluator import AlertEvaluator, AlertEvaluatorConfig, Notification, Signal
from alert_notifier import Notifier
from alert_policy import AlertPolicy, default_alert_policy
from alert_signals import (
    ContainerRecord,
    DiskHealth,
    container_signals,
    mount_signals,
    smart_signals,
    snapraid_signals,
)

logger = logging.getLogger("limeos.alertd")

SignalSource = Callable[[], list[Signal]]


@dataclass
class DaemonConfig:
    webhook_url: str | None
    poll_seconds: int
    fail_threshold: int
    required_mounts: tuple[str, ...]
    state_path: Path
    policy_path: Path | None = None
    status_path: Path | None = None


def config_from_env(environ: dict | None = None) -> DaemonConfig:
    environ = environ if environ is not None else os.environ
    from runtime_paths import STATE_DIR

    def _int(name: str, default: int) -> int:
        try:
            return max(1, int(environ.get(name, "")))
        except (TypeError, ValueError):
            return default

    mounts = tuple(
        path.strip()
        for path in (environ.get("LIMEOS_ALERT_REQUIRED_MOUNTS", "") or "").split(",")
        if path.strip()
    )
    state_dir = Path(STATE_DIR)
    policy_value = (environ.get("LIMEOS_ALERT_POLICY_PATH") or "").strip()
    status_value = (environ.get("LIMEOS_ALERT_STATUS_PATH") or "").strip()
    return DaemonConfig(
        webhook_url=(environ.get("LIMEOS_ALERT_MATTERMOST_WEBHOOK") or "").strip() or None,
        poll_seconds=_int("LIMEOS_ALERT_POLL_SECONDS", 60),
        fail_threshold=_int("LIMEOS_ALERT_FAIL_THRESHOLD", 2),
        required_mounts=mounts,
        state_path=state_dir / "alerts.json",
        policy_path=Path(policy_value) if policy_value else None,
        status_path=Path(status_value) if status_value else state_dir / "alert-status.json",
    )


# -- orchestration (pure) ----------------------------------------------------
def collect_signals(sources: Iterable[SignalSource]) -> list[Signal]:
    """Combine signals from every source; one failing subsystem never sinks the rest."""
    signals: list[Signal] = []
    for source in sources:
        try:
            signals.extend(source())
        except Exception:  # noqa: BLE001 - a broken reader must not stop the tick
            logger.exception("alert signal source failed; skipping this source")
    return signals


def run_once(
    provider: SignalSource,
    evaluator: AlertEvaluator,
    notifier: Notifier,
    *,
    should_notify: Callable[[Signal, str], bool] | None = None,
    on_signals: Callable[[list[Signal]], None] | None = None,
    on_delivery: Callable[[Notification, Exception | None], None] | None = None,
) -> list[Notification]:
    signals = provider()
    if on_signals is not None:
        on_signals(signals)
    notifications = evaluator.evaluate(signals, should_notify=should_notify)
    for notification in notifications:
        try:
            notifier.send(notification)
            if on_delivery is not None:
                on_delivery(notification, None)
        except Exception as exc:  # noqa: BLE001 - delivery is best-effort; recovery still fires later
            logger.exception("failed to deliver notification for %s", notification.key)
            evaluator.mark_delivery_failed(notification)
            if on_delivery is not None:
                on_delivery(notification, exc)
    return notifications


# -- extraction helpers (pure) ----------------------------------------------
def smart_passed(data: dict) -> bool | None:
    """Best-effort SMART overall-health from a parsed SMART dict. None = unknown."""
    for key in ("passed", "smart_status_passed", "health_passed"):
        value = data.get(key)
        if isinstance(value, bool):
            return value
    nested_status = data.get("smart_status")
    if isinstance(nested_status, dict) and isinstance(nested_status.get("passed"), bool):
        return nested_status["passed"]
    assessment = str(
        data.get("smart_status") or data.get("assessment") or data.get("overall_health") or ""
    ).strip().upper()
    if assessment in {"PASS", "PASSED", "OK", "GOOD", "HEALTHY"}:
        return True
    if assessment in {"FAIL", "FAILED", "FAILING", "BAD"}:
        return False
    return None


def container_records(containers: Iterable) -> list[ContainerRecord]:
    records: list[ContainerRecord] = []
    for container in containers:
        attrs = getattr(container, "attrs", {}) or {}
        state = attrs.get("State") or {}
        host_config = attrs.get("HostConfig") or {}
        health = ((state.get("Health") or {}).get("Status")) or None
        policy = (host_config.get("RestartPolicy") or {}).get("Name") or "no"
        records.append(
            ContainerRecord(
                name=getattr(container, "name", "?"),
                running=getattr(container, "status", "") == "running",
                health=health,
                restart_policy=policy,
            )
        )
    return records


def mounts_present(proc_mounts_text: str) -> set[str]:
    """The set of active mountpoints from /proc/self/mounts content."""
    present: set[str] = set()
    for line in proc_mounts_text.splitlines():
        fields = line.split()
        if len(fields) >= 2:
            present.add(fields[1])
    return present


# -- live provider assembly --------------------------------------------------
def build_live_provider(
    *,
    list_containers: Callable[[], Iterable],
    smart_devices: Callable[[], dict],
    snapraid_status: Callable[[], dict],
    read_proc_mounts: Callable[[], str],
    required_mounts: Iterable[str] | Callable[[], Iterable[str]],
) -> SignalSource:
    """Assemble one signal provider from injected live readers (best-effort per subsystem)."""

    def _containers() -> list[Signal]:
        return container_signals(container_records(list_containers()))

    def _smart() -> list[Signal]:
        disks = []
        for entry in (smart_devices().get("disks") or []):
            data = entry.get("data") or {}
            disks.append(
                DiskHealth(
                    device=entry.get("device", "unknown"),
                    passed=smart_passed(data),
                    summary=str(data.get("error_message") or ""),
                )
            )
        return smart_signals(disks)

    def _mounts() -> list[Signal]:
        mounts = required_mounts() if callable(required_mounts) else required_mounts
        return mount_signals(mounts_present(read_proc_mounts()), mounts)

    def _snapraid() -> list[Signal]:
        return snapraid_signals(snapraid_status())

    sources: list[SignalSource] = [_containers, _smart, _mounts, _snapraid]

    def _provider() -> list[Signal]:
        return collect_signals(sources)

    return _provider


def main() -> int:  # pragma: no cover - integration entrypoint, validated on the Pi
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = config_from_env()

    from alert_notifier import MattermostWebhookNotifier, RecordingNotifier

    if config.webhook_url:
        notifier: Notifier = MattermostWebhookNotifier(config.webhook_url)
    else:
        logger.warning("LIMEOS_ALERT_MATTERMOST_WEBHOOK unset — running in dry mode (log only)")
        notifier = RecordingNotifier()

    evaluator = AlertEvaluator(
        state_path=config.state_path,
        config=AlertEvaluatorConfig(fail_threshold=config.fail_threshold),
    )

    policy_holder = [_load_policy(config)]
    provider = _build_live_provider_from_environment(
        config,
        required_mounts_provider=lambda: policy_holder[0].required_mounts,
    )
    latest_signals: list[Signal] = []
    delivery_status: dict = {}

    def record_signals(signals: list[Signal]) -> None:
        latest_signals[:] = signals

    def record_delivery(notification: Notification, error: Exception | None) -> None:
        delivery_status.clear()
        delivery_status.update(
            {
                "at": notification.at,
                "ok": error is None,
                "error": str(error) if error else None,
            }
        )

    logger.info("limeos alertd started (interval=%ss, mounts=%s)", config.poll_seconds, config.required_mounts)
    while True:
        try:
            policy_holder[0] = _load_policy(config)
            for note in run_once(
                provider,
                evaluator,
                notifier,
                should_notify=lambda signal, _event: policy_holder[0].allows(
                    signal.kind, signal.key
                ),
                on_signals=record_signals,
                on_delivery=record_delivery,
            ):
                logger.info("%s %s: %s", note.event, note.key, note.summary)
            _write_status(config, evaluator, latest_signals, delivery_status)
        except Exception:
            logger.exception("evaluation tick failed")
        time.sleep(config.poll_seconds)


def _build_live_provider_from_environment(
    config: DaemonConfig,
    *,
    required_mounts_provider: Callable[[], Iterable[str]] | None = None,
) -> SignalSource:  # pragma: no cover
    """Wire the live services lazily so the module imports cleanly for tests.

    Container signals use the read-only Docker socket. Host SMART, mount, and
    SnapRAID inputs use the helper's read-only health snapshot command.
    """
    try:
        import docker as docker_sdk

        client = docker_sdk.from_env()
    except Exception:
        client = None

    def list_containers():
        return client.containers.list(all=True) if client is not None else []

    snapshot_cache: dict = {"read_at": 0.0, "value": {}}

    def health_snapshot():
        now = time.monotonic()
        if now - snapshot_cache["read_at"] < 1:
            return snapshot_cache["value"]
        try:
            from helper_client import helper_call

            result = helper_call("alert_health_snapshot", {})
            value = result if result.get("success") else {}
        except Exception:
            value = {}
        snapshot_cache.update({"read_at": now, "value": value})
        return value

    def smart_devices():
        snapshot = health_snapshot()
        smart = snapshot.get("smart") or {}
        return {"disks": smart.get("devices", [])}

    def snapraid_status():
        return (health_snapshot().get("snapraid") or {})

    def read_proc_mounts():
        snapshot = health_snapshot()
        mounts = (snapshot.get("mounts") or {}).get("data")
        if isinstance(mounts, list):
            return "\n".join(
                f"{entry.get('device', '?')} {entry.get('mountpoint', '?')}"
                for entry in mounts
                if isinstance(entry, dict)
            )
        try:
            return Path("/proc/self/mounts").read_text()
        except OSError:
            return ""

    return build_live_provider(
        list_containers=list_containers,
        smart_devices=smart_devices,
        snapraid_status=snapraid_status,
        read_proc_mounts=read_proc_mounts,
        required_mounts=required_mounts_provider or config.required_mounts,
    )


def _load_policy(config: DaemonConfig) -> AlertPolicy:
    raw = None
    if config.policy_path is not None:
        try:
            raw = json.loads(config.policy_path.read_text())
            if isinstance(raw, dict) and isinstance(raw.get("policy"), dict):
                raw = raw["policy"]
        except (FileNotFoundError, OSError, ValueError):
            raw = None
    if raw is None:
        raw = default_alert_policy()
        raw["required_mounts"] = list(config.required_mounts)
    return AlertPolicy.from_mapping(raw)


def _write_status(
    config: DaemonConfig,
    evaluator: AlertEvaluator,
    signals: list[Signal],
    delivery: dict,
) -> None:
    if config.status_path is None:
        return
    config.status_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.time(),
        "resources": [asdict(signal) for signal in signals],
        "incidents": [asdict(incident) for incident in evaluator.active_incidents],
        "delivery": dict(delivery),
    }
    temporary = config.status_path.with_suffix(config.status_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, config.status_path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
