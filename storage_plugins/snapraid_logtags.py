"""
Parse SnapRAID log tags into structured data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


KNOWN_TAG_PREFIXES = {
    "summary",
    "scan",
    "run",
    "msg",
    "conf",
    "blocksize",
    "data",
    "mode",
    "pool",
    "share",
    "autosave",
    "filter",
    "content",
    "version",
    "unixtime",
    "time",
    "command",
    "argv",
    "memory",
    "thermal",
}


def _unescape(value: str) -> str:
    return (
        value.replace("\\d", ":")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\\\", "\\")
    )


def _is_tag_name(name: str) -> bool:
    if name in KNOWN_TAG_PREFIXES:
        return True
    if name.endswith("parity"):
        return True
    return False


@dataclass
class LogTagParseResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    scan_counts: dict[str, int] = field(default_factory=dict)
    run_progress: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "summary": self.summary,
            "scan_counts": self.scan_counts,
            "run_progress": self.run_progress,
            "messages": self.messages,
        }


def parse_log_tags(text: str) -> LogTagParseResult:
    result = LogTagParseResult()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue

        parts = line.split(":")
        name = parts[0]
        if not _is_tag_name(name):
            continue

        values = [_unescape(part) for part in parts[1:]]
        result.events.append({"name": name, "values": values})

        if name == "summary" and len(values) >= 2:
            key = values[0]
            if key == "exit":
                result.summary["exit"] = values[1]
            else:
                try:
                    result.summary[key] = int(values[1])
                except ValueError:
                    result.summary[key] = values[1]
            continue

        if name == "scan" and values:
            scan_key = values[0]
            result.scan_counts[scan_key] = result.scan_counts.get(scan_key, 0) + 1
            continue

        if name == "run" and values and values[0] == "pos":
            fields = values[1:]
            if len(fields) >= 8:
                try:
                    result.run_progress = {
                        "blockpos": int(fields[0]),
                        "countpos": int(fields[1]),
                        "countsize": int(fields[2]),
                        "percent": int(fields[3]),
                        "eta": int(fields[4]),
                        "size_speed": float(fields[5]),
                        "cpu": float(fields[6]),
                        "elapsed": int(fields[7]),
                    }
                except ValueError:
                    result.run_progress = {"raw": fields}
            continue

        if name == "msg" and len(values) >= 2:
            result.messages.append({"level": values[0], "message": values[1]})

    return result
