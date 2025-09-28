"""Lightweight Model Context Protocol (MCP) helpers."""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional


class BaseMCPTool:
    """Minimal interface for MCP-style tools."""

    tool_id: str = "base"

    def should_run(self, message: str) -> bool:
        """Return True when the tool should be invoked for the given message."""
        return True

    def collect(self, message: str) -> Dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        """Return a plain-text summary suitable for prompt injection."""
        raise NotImplementedError

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Optional structured signals that downstream logic can inspect."""
        return {}


class SystemStatsTool(BaseMCPTool):
    """Expose host system metrics collected via ``get_system_stats``."""

    tool_id = "system_stats"

    def __init__(self, fetch_stats: Callable[[], Dict[str, Any]]) -> None:
        self._fetch_stats = fetch_stats

    def should_run(self, message: str) -> bool:
        lowered = message.lower()
        keywords = [
            "status",
            "health",
            "system",
            "cpu",
            "memory",
            "temperature",
            "disk",
            "queue",
            "slow",
            "issue",
        ]
        return any(keyword in lowered for keyword in keywords)

    def collect(self, message: str) -> Dict[str, Any]:
        stats = self._fetch_stats()
        summary = self._summarise(stats)
        return {
            "tool": self.tool_id,
            "stats": stats,
            "summary": summary,
        }

    def render_for_prompt(self, payload: Dict[str, Any]) -> str:
        return payload.get("summary", "")

    def derive_signals(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        stats = payload.get("stats") or {}
        cpu = stats.get("cpu_usage_percent")
        temp = stats.get("temperature_celsius")
        disk = (stats.get("disk_usage") or {}).get("percent")

        signals: Dict[str, Any] = {}
        if isinstance(cpu, (int, float)) and cpu >= 85:
            signals["high_cpu"] = round(cpu, 1)
        if isinstance(temp, (int, float)) and temp >= 72:
            signals["hot_system"] = round(temp, 1)
        if isinstance(disk, (int, float)) and disk >= 85:
            signals["disk_pressure"] = round(disk, 1)
        return signals

    @staticmethod
    def _summarise(stats: Dict[str, Any]) -> str:
        sections = []
        cpu = stats.get("cpu_usage_percent")
        if isinstance(cpu, (int, float)):
            sections.append(f"CPU load: {cpu:.1f}%")

        memory = stats.get("memory_usage") or {}
        mem_summary = SystemStatsTool._memory_summary(memory)
        if mem_summary:
            sections.append(mem_summary)

        disk = stats.get("disk_usage") or {}
        disk_summary = SystemStatsTool._disk_summary(disk)
        if disk_summary:
            sections.append(f"Primary disk: {disk_summary}")

        disk2 = stats.get("disk_usage_2") or {}
        disk2_summary = SystemStatsTool._disk_summary(disk2)
        if disk2_summary:
            sections.append(f"Secondary disk: {disk2_summary}")

        temp = stats.get("temperature_celsius")
        if isinstance(temp, (int, float)):
            sections.append(f"Board temperature: {temp:.1f}°C")

        network = stats.get("network_usage") or {}
        sent = network.get("bytes_sent")
        recv = network.get("bytes_recv")
        traffic = []
        if isinstance(sent, (int, float)):
            traffic.append(f"sent {SystemStatsTool._format_bytes(sent)}")
        if isinstance(recv, (int, float)):
            traffic.append(f"received {SystemStatsTool._format_bytes(recv)}")
        if traffic:
            sections.append("Network traffic " + " / ".join(traffic))

        return "\n".join(section for section in sections if section)

    @staticmethod
    def _memory_summary(memory: Dict[str, Any]) -> Optional[str]:
        total = memory.get("total")
        used = memory.get("used")
        percent = memory.get("percent")
        if not all(isinstance(value, (int, float)) for value in [total, used, percent]):
            return None
        return (
            f"Memory usage: {SystemStatsTool._format_bytes(used)} of "
            f"{SystemStatsTool._format_bytes(total)} ({percent:.0f}% utilised)"
        )

    @staticmethod
    def _disk_summary(disk: Dict[str, Any]) -> Optional[str]:
        total = disk.get("total")
        used = disk.get("used")
        percent = disk.get("percent")
        if not all(isinstance(value, (int, float)) for value in [total, used, percent]):
            return None
        return (
            f"{SystemStatsTool._format_bytes(used)} of {SystemStatsTool._format_bytes(total)} used "
            f"({percent:.0f}% capacity)"
        )

    @staticmethod
    def _format_bytes(value: float) -> str:
        if not isinstance(value, (int, float)) or value < 0:
            return "n/a"
        if value == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        exponent = min(int(math.log(value, 1024)), len(units) - 1)
        scaled = value / (1024 ** exponent)
        return f"{scaled:.1f} {units[exponent]}"
