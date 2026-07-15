"""Framework-neutral aggregation for the LimeOS Overview dashboard."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit


MAX_APPLICATIONS = 128
MAX_ACTIVE_INCIDENTS = 50
MAX_RECENT_RECOVERIES = 5
MAX_ISSUES = 100
MAX_WARNINGS = 50

METRIC_RULES = {
    "cpu": (60.0, 85.0, "CPU usage", "%"),
    "memory": (70.0, 90.0, "Memory usage", "%"),
    "temperature": (65.0, 80.0, "Temperature", " C"),
    "disk": (75.0, 90.0, "Storage usage", "%"),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _number(value) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _text(value, default: str = "", limit: int = 512) -> str:
    return (value.strip() if isinstance(value, str) else default)[:limit]


def _issue(code: str, severity: str, label: str, detail: str, path: str) -> dict:
    return {
        "code": code,
        "severity": severity,
        "label": label,
        "detail": detail,
        "path": path,
    }


class OverviewService:
    """Compose a bounded dashboard snapshot from existing read services."""

    def __init__(
        self,
        *,
        system_stats_provider: Callable[[], Mapping],
        container_provider: Callable[[], list[dict]],
        stack_provider: Callable[[], tuple[list[dict], str | None]],
        alert_status_provider: Callable[[], Mapping],
        recent_recoveries_provider: Callable[[], list[dict]] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._system_stats_provider = system_stats_provider
        self._container_provider = container_provider
        self._stack_provider = stack_provider
        self._alert_status_provider = alert_status_provider
        self._recent_recoveries_provider = recent_recoveries_provider or (lambda: [])
        self._clock = clock

    def snapshot(self) -> dict:
        warnings: list[dict] = []
        stats = self._read_mapping(
            "system", "System metrics are unavailable", self._system_stats_provider, warnings
        )
        containers = self._read_containers(warnings)
        stacks = self._read_stacks(warnings)
        alert_status = self._read_mapping(
            "alerts", "Alert status is unavailable", self._alert_status_provider, warnings
        )
        recoveries = self._read_recoveries(warnings)

        metrics = self._metrics(stats)
        container_counts, container_issues = self._container_health(containers)
        stack_counts, stack_issues = self._stack_health(stacks)
        active, alert_issues = self._alert_health(alert_status)
        issues = [
            *self._metric_issues(metrics),
            *container_issues,
            *stack_issues,
            *alert_issues,
            *self._source_issues(warnings),
        ]
        issues.sort(key=self._issue_sort_key)
        health_state = self._health_state(issues)
        if len(issues) > MAX_ISSUES:
            warnings.append(
                {
                    "code": "result_truncated",
                    "source": "health",
                    "message": f"Health issues are limited to {MAX_ISSUES}",
                }
            )
        issues = issues[:MAX_ISSUES]

        for warning in stats.get("warnings", []) if isinstance(stats, Mapping) else []:
            if not isinstance(warning, Mapping):
                continue
            warnings.append(
                {
                    "code": _text(warning.get("code"), "source_unavailable"),
                    "source": _text(warning.get("source"), "system"),
                    "message": _text(warning.get("message"), "System metric unavailable"),
                }
            )

        return {
            "health": {"state": health_state, "issues": issues},
            "metrics": metrics,
            "workloads": {"containers": container_counts, "stacks": stack_counts},
            "alerts": {"active": active, "recent_recoveries": recoveries},
            "applications": self._applications(containers, warnings),
            "warnings": warnings[:MAX_WARNINGS],
            "collected_at": self._timestamp(),
        }

    @staticmethod
    def _read_mapping(source, message, provider, warnings) -> Mapping:
        try:
            value = provider()
            if not isinstance(value, Mapping):
                raise TypeError("provider returned a non-mapping value")
            return value
        except Exception:
            warnings.append({"code": "source_unavailable", "source": source, "message": message})
            return {}

    def _read_containers(self, warnings: list[dict]) -> list[dict]:
        try:
            containers = self._container_provider()
            if not isinstance(containers, list):
                raise TypeError("container provider returned a non-list value")
        except Exception:
            warnings.append(
                {
                    "code": "source_unavailable",
                    "source": "containers",
                    "message": "Container status is unavailable",
                }
            )
            return []
        if len(containers) == 1 and containers[0].get("id") in {
            "docker-not-available",
            "error-listing",
        }:
            warnings.append(
                {
                    "code": "source_unavailable",
                    "source": "containers",
                    "message": "Container status is unavailable",
                }
            )
            return []
        return [item for item in containers if isinstance(item, dict)]

    def _read_stacks(self, warnings: list[dict]) -> list[dict]:
        try:
            stacks, error = self._stack_provider()
            if error or not isinstance(stacks, list):
                raise RuntimeError("stack status unavailable")
            return [item for item in stacks if isinstance(item, dict)]
        except Exception:
            warnings.append(
                {
                    "code": "source_unavailable",
                    "source": "stacks",
                    "message": "Stack status is unavailable",
                }
            )
            return []

    def _read_recoveries(self, warnings: list[dict]) -> list[dict]:
        try:
            records = self._recent_recoveries_provider()
            if not isinstance(records, list):
                raise TypeError("recovery provider returned a non-list value")
            normalized = [
                self._alert_record(record)
                for record in records
                if isinstance(record, Mapping) and record.get("event") == "recovery"
            ]
            valid = [record for record in normalized if record is not None]
            valid.sort(key=lambda item: item["at"], reverse=True)
            return valid[:MAX_RECENT_RECOVERIES]
        except Exception:
            warnings.append(
                {
                    "code": "source_unavailable",
                    "source": "alert_history",
                    "message": "Recent alert history is unavailable",
                }
            )
            return []

    @staticmethod
    def _metrics(stats: Mapping) -> dict:
        memory = (
            stats.get("memory_usage")
            if isinstance(stats.get("memory_usage"), Mapping)
            else {}
        )
        disk = stats.get("disk_usage") if isinstance(stats.get("disk_usage"), Mapping) else {}
        return {
            "cpu_percent": _number(stats.get("cpu_usage_percent")),
            "memory_percent": _number(memory.get("percent")),
            "memory_used": _number(memory.get("used")),
            "memory_total": _number(memory.get("total")),
            "temperature_celsius": _number(stats.get("temperature_celsius")),
            "disk_percent": _number(disk.get("percent")),
            "disk_used": _number(disk.get("used")),
            "disk_total": _number(disk.get("total")),
        }

    @staticmethod
    def _metric_issues(metrics: Mapping) -> list[dict]:
        values = {
            "cpu": metrics.get("cpu_percent"),
            "memory": metrics.get("memory_percent"),
            "temperature": metrics.get("temperature_celsius"),
            "disk": metrics.get("disk_percent"),
        }
        issues = []
        for name, value in values.items():
            warning_at, critical_at, label, suffix = METRIC_RULES[name]
            if value is None:
                issues.append(
                    _issue(
                        f"metric.{name}.unavailable",
                        "unknown",
                        f"{label} unavailable",
                        "No current reading is available",
                        "/system",
                    )
                )
            elif value >= critical_at:
                issues.append(
                    _issue(
                        f"metric.{name}.critical",
                        "critical",
                        f"{label} is critical",
                        f"Current value: {value:.1f}{suffix}",
                        "/system",
                    )
                )
            elif value >= warning_at:
                issues.append(
                    _issue(
                        f"metric.{name}.warning",
                        "attention",
                        f"{label} needs attention",
                        f"Current value: {value:.1f}{suffix}",
                        "/system",
                    )
                )
        return issues

    @staticmethod
    def _container_health(containers: list[dict]) -> tuple[dict, list[dict]]:
        counts = {"total": len(containers), "running": 0, "unhealthy": 0, "stopped": 0}
        issues = []
        for container in containers:
            name = _text(container.get("name"), "Unknown container")
            status = _text(container.get("status"), "unknown").lower()
            health = _text(container.get("health")).lower()
            restart_policy = _text(container.get("restart_policy")).lower()
            if status == "running":
                counts["running"] += 1
            else:
                counts["stopped"] += 1
            if health == "unhealthy":
                counts["unhealthy"] += 1
                issues.append(
                    _issue(
                        f"container.{name}.unhealthy",
                        "critical",
                        f"{name} is unhealthy",
                        "The container health check is failing",
                        "/containers",
                    )
                )
            elif status != "running" and restart_policy not in {"", "no", "none"}:
                issues.append(
                    _issue(
                        f"container.{name}.stopped",
                        "attention",
                        f"{name} is stopped",
                        f"Restart policy: {restart_policy}",
                        "/containers",
                    )
                )
        return counts, issues

    @staticmethod
    def _stack_health(stacks: list[dict]) -> tuple[dict, list[dict]]:
        counts = {"total": len(stacks), "healthy": 0, "partial": 0, "down": 0, "unknown": 0}
        issues = []
        for stack in stacks:
            name = _text(stack.get("name"), "Unknown stack")
            status = _text(stack.get("status"), "unknown").lower()
            if status == "running":
                counts["healthy"] += 1
            elif status == "partial":
                counts["partial"] += 1
                issues.append(
                    _issue(
                        f"stack.{name}.partial",
                        "attention",
                        f"{name} is partially running",
                        "Some stack containers are stopped",
                        "/stacks",
                    )
                )
            elif status in {"stopped", "down", "conflict", "error"}:
                counts["down"] += 1
                issues.append(
                    _issue(
                        f"stack.{name}.down",
                        "critical",
                        f"{name} is down",
                        "No stack containers are running",
                        "/stacks",
                    )
                )
            else:
                counts["unknown"] += 1
                issues.append(
                    _issue(
                        f"stack.{name}.unknown",
                        "unknown",
                        f"{name} status is unavailable",
                        "The stack could not be checked",
                        "/stacks",
                    )
                )
        return counts, issues

    def _alert_health(self, status: Mapping) -> tuple[list[dict], list[dict]]:
        incidents = status.get("incidents") if isinstance(status.get("incidents"), list) else []
        active = [
            self._alert_record({**record, "event": "incident"})
            for record in incidents
            if isinstance(record, Mapping)
        ]
        active = [record for record in active if record is not None]
        active.sort(key=lambda item: (item["severity"] != "critical", item["at"]))
        active = active[:MAX_ACTIVE_INCIDENTS]
        active_keys = {record["key"] for record in active}
        issues = [
            _issue(
                f"alert.{record['key']}",
                "critical" if record["severity"] == "critical" else "attention",
                record["summary"] or record["key"],
                f"Active {record['kind']} incident",
                "/integrations",
            )
            for record in active
        ]

        resources = status.get("resources") if isinstance(status.get("resources"), list) else []
        for resource in resources:
            if not isinstance(resource, Mapping) or resource.get("ok") is not False:
                continue
            key = _text(resource.get("key"), "unknown")
            if key in active_keys:
                continue
            severity = _text(resource.get("severity"), "warning").lower()
            summary = _text(resource.get("summary"), key)
            kind = _text(resource.get("kind"), "resource")
            issues.append(
                _issue(
                    f"resource.{key}",
                    "critical" if severity == "critical" else "attention",
                    summary,
                    f"Current {kind} check is failing",
                    "/integrations",
                )
            )

        if status.get("installed") is True and status.get("state") in {
            "degraded",
            "disconnected",
            "unavailable",
        }:
            issues.append(
                _issue(
                    "integration.mattermost.degraded",
                    "attention",
                    "Mattermost integration needs attention",
                    "Alert delivery or a managed service is degraded",
                    "/integrations",
                )
            )
        return active, issues

    @staticmethod
    def _source_issues(warnings: list[dict]) -> list[dict]:
        labels = {
            "containers": ("Container status unavailable", "/containers"),
            "stacks": ("Stack status unavailable", "/stacks"),
            "alerts": ("Alert status unavailable", "/integrations"),
        }
        return [
            _issue(
                f"source.{warning['source']}.unavailable",
                "unknown",
                labels[warning["source"]][0],
                warning["message"],
                labels[warning["source"]][1],
            )
            for warning in warnings
            if warning.get("source") in labels
        ]

    @staticmethod
    def _alert_record(record: Mapping) -> dict | None:
        key = _text(record.get("key"))
        if not key:
            return None
        at = _text(record.get("at")) or _text(record.get("opened_at"))
        return {
            "event": _text(record.get("event"), "incident"),
            "key": key,
            "kind": _text(record.get("kind"), "generic"),
            "severity": _text(record.get("severity"), "warning"),
            "summary": _text(record.get("summary"), key),
            "at": at,
        }

    @staticmethod
    def _applications(containers: list[dict], warnings: list[dict]) -> list[dict]:
        applications = []
        for container in containers:
            explicit_url = OverviewService._safe_web_url(container.get("web_url"))
            port = OverviewService._web_port(container.get("ports"))
            if explicit_url is None and port is None:
                continue
            applications.append(
                {
                    "id": _text(container.get("id"), "unknown-container"),
                    "name": _text(container.get("name"), "Unnamed"),
                    "status": _text(container.get("status"), "unknown"),
                    "image": _text(container.get("image"), "unknown"),
                    "port": port,
                    "web_url": explicit_url,
                    "web_scheme": _text(container.get("web_scheme"))
                    if container.get("web_scheme") in {"http", "https"}
                    else None,
                }
            )
        applications.sort(key=lambda item: (item["status"] != "running", item["name"].lower()))
        if len(applications) > MAX_APPLICATIONS:
            warnings.append(
                {
                    "code": "result_truncated",
                    "source": "applications",
                    "message": f"Application links are limited to {MAX_APPLICATIONS}",
                }
            )
        return applications[:MAX_APPLICATIONS]

    @staticmethod
    def _safe_web_url(value) -> str | None:
        if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
            return None
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        return value

    @staticmethod
    def _web_port(value) -> int | None:
        ports = (
            [port for port in value if isinstance(port, Mapping)]
            if isinstance(value, list)
            else []
        )

        def valid(candidate) -> bool:
            return (
                isinstance(candidate, int)
                and not isinstance(candidate, bool)
                and 0 < candidate <= 65535
            )

        tcp = [port for port in ports if port.get("protocol") != "udp"]
        candidates = (
            next((port.get("host_port") for port in tcp if valid(port.get("host_port"))), None),
            next((port.get("host_port") for port in ports if valid(port.get("host_port"))), None),
            next((port.get("container_port") for port in tcp if valid(port.get("container_port"))), None),
            next((port.get("container_port") for port in ports if valid(port.get("container_port"))), None),
        )
        return next((candidate for candidate in candidates if valid(candidate)), None)

    def _timestamp(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _health_state(issues: list[dict]) -> str:
        severities = {issue.get("severity") for issue in issues}
        if "critical" in severities:
            return "critical"
        if "attention" in severities:
            return "attention"
        if "unknown" in severities:
            return "unknown"
        return "healthy"

    @staticmethod
    def _issue_sort_key(issue: Mapping) -> tuple[int, str]:
        rank = {"critical": 0, "attention": 1, "unknown": 2}
        return rank.get(issue.get("severity"), 3), _text(issue.get("code"))
