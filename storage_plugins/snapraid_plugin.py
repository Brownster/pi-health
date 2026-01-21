"""
SnapRAID storage plugin.
Manages SnapRAID configuration, sync, scrub, and recovery.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Generator, Optional

from storage_plugins.base import StoragePlugin, CommandResult, PluginStatus
from helper_client import helper_call, helper_available, HelperError
from storage_plugins.snapraid_logtags import parse_log_tags


class SnapRAIDPlugin(StoragePlugin):
    """SnapRAID parity protection plugin."""

    PLUGIN_ID = "snapraid"
    PLUGIN_NAME = "SnapRAID"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Parity-based backup for data recovery"
    PLUGIN_CATEGORY = "storage"  # UI appears on Pools page

    SNAPRAID_BIN = "/usr/bin/snapraid"
    SNAPRAID_CONF = "/etc/snapraid.conf"

    DEFAULT_EXCLUDES = [
        "*.tmp",
        "*.temp",
        "*.bak",
        "/lost+found/",
        "*.unrecoverable",
        ".Thumbs.db",
        ".DS_Store",
        "._*",
        ".fseventsd/",
        ".Spotlight-V100/",
        ".Trashes/",
        "aquota.group",
        "aquota.user",
    ]

    def __init__(self, config_dir: str):
        super().__init__(config_dir)
        self._schema = None

    def get_schema(self) -> dict:
        if self._schema is None:
            schema_path = os.path.join(
                os.path.dirname(self.config_dir),
                "schemas",
                "snapraid.schema.json"
            )
            if os.path.exists(schema_path):
                with open(schema_path) as handle:
                    self._schema = json.load(handle)
            else:
                self._schema = {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "drives": {"type": "array"},
                        "excludes": {"type": "array"},
                        "settings": {"type": "object"},
                        "thresholds": {"type": "object"},
                        "scrub": {"type": "object"},
                        "schedule": {"type": "object"}
                    }
                }
        return self._schema

    def get_config(self) -> dict:
        if os.path.exists(self.config_path):
            with open(self.config_path) as handle:
                config = json.load(handle)
        else:
            config = {}

        defaults = {
            "enabled": False,
            "drives": [],
            "excludes": self.DEFAULT_EXCLUDES.copy(),
            "settings": {
                "blocksize": 256,
                "hashsize": 16,
                "autosave": 500,
                "nohidden": False,
                "prehash": True
            },
            "thresholds": {
                "delete_threshold": 50,
                "update_threshold": 500
            },
            "scrub": {
                "enabled": True,
                "percent": 12,
                "age_days": 10
            },
            "schedule": {
                "sync_enabled": False,
                "sync_cron": "0 3 * * *",
                "scrub_enabled": False,
                "scrub_cron": "0 4 * * 0"
            }
        }

        for key, default_value in defaults.items():
            if key not in config:
                config[key] = default_value
            elif isinstance(default_value, dict):
                for inner_key, inner_value in default_value.items():
                    if inner_key not in config[key]:
                        config[key][inner_key] = inner_value

        return config

    def set_config(self, config: dict) -> CommandResult:
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            temp_path = f"{self.config_path}.tmp"
            with open(temp_path, "w") as handle:
                json.dump(config, handle, indent=2)
            os.replace(temp_path, self.config_path)
            return CommandResult(success=True, message="Configuration saved")
        except Exception as exc:
            return CommandResult(success=False, message="", error=str(exc))

    def validate_config(self, config: dict) -> list[str]:
        errors = []
        drives = config.get("drives", [])

        if not drives:
            errors.append("At least one drive must be configured")
            return errors

        data_drives = [d for d in drives if d.get("role") == "data"]
        parity_drives = [d for d in drives if d.get("role") == "parity"]
        content_drives = [d for d in drives if d.get("content", False)]

        if not data_drives:
            errors.append("At least one data drive is required")

        if not parity_drives:
            errors.append("At least one parity drive is required")

        if not content_drives:
            errors.append("At least one drive must store content files")

        names = [d.get("name") for d in drives]
        if len(names) != len(set(names)):
            errors.append("Drive names must be unique")

        for drive in drives:
            path = drive.get("path", "")
            if not path.startswith("/mnt/"):
                errors.append(f"Drive path must be under /mnt/: {path}")

        parity_levels = [d.get("parity_level", 1) for d in parity_drives]
        if parity_levels:
            for idx, level in enumerate(sorted(set(parity_levels))):
                if level != idx + 1:
                    errors.append("Parity levels must be contiguous (1, 2, 3...)")
                    break

        return errors

    def apply_config(self) -> CommandResult:
        config = self.get_config()
        errors = self.validate_config(config)
        if errors:
            return CommandResult(
                success=False,
                message="",
                error=f"Validation failed: {'; '.join(errors)}"
            )

        conf_content = self._generate_config(config)

        if helper_available():
            try:
                result = helper_call('write_snapraid_conf', {
                    'content': conf_content,
                    'path': self.SNAPRAID_CONF
                })
                if result.get('success'):
                    schedule_result = self.apply_schedule(config)
                    if schedule_result and not schedule_result.success:
                        return schedule_result
                    return CommandResult(
                        success=True,
                        message=f"Configuration written to {self.SNAPRAID_CONF}"
                    )
                return CommandResult(success=False, message="", error=result.get('error', 'Helper failed'))
            except HelperError as exc:
                return CommandResult(success=False, message="", error=str(exc))

        try:
            with open(self.SNAPRAID_CONF, "w") as handle:
                handle.write(conf_content)
            schedule_result = self.apply_schedule(config)
            if schedule_result and not schedule_result.success:
                return schedule_result
            return CommandResult(
                success=True,
                message=f"Configuration written to {self.SNAPRAID_CONF}"
            )
        except PermissionError:
            return CommandResult(
                success=False,
                message="",
                error="Permission denied. Use helper service for privileged operations."
            )
        except Exception as exc:
            return CommandResult(success=False, message="", error=str(exc))

    def apply_schedule(self, config: dict | None = None) -> CommandResult | None:
        """Apply systemd timers for SnapRAID schedule."""
        config = config or self.get_config()
        schedule = config.get("schedule", {})

        if not schedule:
            return None

        if not helper_available():
            enabled = schedule.get("sync_enabled") or schedule.get("scrub_enabled")
            if enabled:
                return CommandResult(
                    success=False,
                    message="",
                    error="Helper service required to manage systemd timers."
                )
            return None

        for job_type in ("sync", "scrub"):
            enabled = schedule.get(f"{job_type}_enabled", False)
            unit_base = f"pihealth-snapraid-{job_type}"
            service_name = f"{unit_base}.service"
            timer_name = f"{unit_base}.timer"

            if enabled:
                service_content, timer_content = self.generate_systemd_timer(job_type)
                result = helper_call('write_systemd_unit', {
                    'unit_name': service_name,
                    'content': service_content
                })
                if not result.get('success'):
                    return CommandResult(success=False, message="", error=result.get('error', 'Helper failed'))

                result = helper_call('write_systemd_unit', {
                    'unit_name': timer_name,
                    'content': timer_content
                })
                if not result.get('success'):
                    return CommandResult(success=False, message="", error=result.get('error', 'Helper failed'))

                helper_call('systemctl', {'action': 'daemon-reload'})
                helper_call('systemctl', {'action': 'enable', 'unit': timer_name})
            else:
                helper_call('systemctl', {'action': 'disable', 'unit': timer_name})

        return CommandResult(success=True, message="Schedule updated")

    def generate_systemd_timer(self, job_type: str) -> tuple[str, str]:
        """
        Generate systemd service and timer files.

        Args:
            job_type: "sync" or "scrub"

        Returns:
            (service_content, timer_content)
        """
        config = self.get_config()
        schedule = config.get("schedule", {})
        cron = schedule.get(f"{job_type}_cron", "0 3 * * *")
        on_calendar = self._cron_to_oncalendar(cron)

        service = (
            "[Unit]\n"
            f"Description=SnapRAID {job_type}\n"
            "After=local-fs.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart=/usr/bin/snapraid {job_type}\n"
            "Nice=19\n"
            "IOSchedulingClass=idle\n"
        )

        timer = (
            "[Unit]\n"
            f"Description=SnapRAID {job_type} timer\n\n"
            "[Timer]\n"
            f"OnCalendar={on_calendar}\n"
            "RandomizedDelaySec=1800\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

        return service, timer

    def _cron_to_oncalendar(self, cron: str) -> str:
        """Convert cron expression to systemd OnCalendar format."""
        parts = cron.split()
        if len(parts) != 5:
            return "*-*-* 03:00:00"

        minute, hour, day, month, dow = parts

        dow_map = {
            "0": "Sun",
            "1": "Mon",
            "2": "Tue",
            "3": "Wed",
            "4": "Thu",
            "5": "Fri",
            "6": "Sat",
            "7": "Sun"
        }

        if dow in dow_map:
            return f"{dow_map[dow]} *-*-* {hour}:{minute}:00"
        if dow == "*" and day == "*" and month == "*":
            return f"*-*-* {hour}:{minute}:00"

        return f"*-*-* {hour}:{minute}:00"

    def _generate_config(self, config: dict) -> str:
        lines = [
            "# Generated by Pi-Health",
            f"# {datetime.now().isoformat()}",
            ""
        ]

        settings = config.get("settings", {})

        if settings.get("prehash", True):
            lines.append("prehash")
        if settings.get("nohidden", False):
            lines.append("nohidden")

        blocksize = settings.get("blocksize", 256)
        if blocksize != 256:
            lines.append(f"blocksize {blocksize}")

        hashsize = settings.get("hashsize", 16)
        if hashsize != 16:
            lines.append(f"hashsize {hashsize}")

        autosave = settings.get("autosave", 0)
        if autosave > 0:
            lines.append(f"autosave {autosave}")

        lines.append("")

        drives = config.get("drives", [])

        for drive in sorted(
            [d for d in drives if d.get("role") == "parity"],
            key=lambda item: item.get("parity_level", 1)
        ):
            level = drive.get("parity_level", 1)
            path = drive["path"]
            if level == 1:
                lines.append(f"parity {path}/snapraid.parity")
            else:
                lines.append(f"{level}-parity {path}/snapraid.{level}-parity")

        lines.append("")

        for drive in drives:
            if drive.get("content", False):
                path = drive["path"]
                lines.append(f"content {path}/snapraid.content")

        lines.append("")

        for drive in [d for d in drives if d.get("role") == "data"]:
            name = drive["name"]
            path = drive["path"]
            lines.append(f"data {name} {path}")

        lines.append("")

        excludes = config.get("excludes", [])
        for pattern in excludes:
            lines.append(f"exclude {pattern}")

        return "\n".join(lines)

    def get_status(self) -> dict:
        config = self.get_config()

        if not config.get("enabled"):
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "SnapRAID is not enabled",
                "details": {}
            }

        drives = config.get("drives", [])
        if not drives:
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "No drives configured",
                "details": {}
            }

        data_drives = [d for d in drives if d.get("role") == "data"]
        parity_drives = [d for d in drives if d.get("role") == "parity"]

        details = {
            "data_drives": len(data_drives),
            "parity_drives": len(parity_drives),
            "last_sync": None,
            "last_scrub": None,
            "sync_in_progress": False
        }

        if not os.path.exists(self.SNAPRAID_CONF):
            return {
                "status": PluginStatus.ERROR.value,
                "message": "Configuration not applied",
                "details": details
            }

        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "status"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                output = result.stdout
                if "No error detected" in output:
                    return {
                        "status": PluginStatus.HEALTHY.value,
                        "message": "All data protected",
                        "details": details
                    }
                if "sync" in output.lower() and "required" in output.lower():
                    return {
                        "status": PluginStatus.DEGRADED.value,
                        "message": "Sync required",
                        "details": details
                    }
        except FileNotFoundError:
            return {
                "status": PluginStatus.ERROR.value,
                "message": "SnapRAID not installed",
                "details": details
            }
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass

        return {
            "status": PluginStatus.HEALTHY.value,
            "message": "Status unknown",
            "details": details
        }

    def get_commands(self) -> list[dict]:
        return [
            {
                "id": "status",
                "name": "Status",
                "description": "Show current SnapRAID status",
                "dangerous": False
            },
            {
                "id": "diff",
                "name": "Diff",
                "description": "Show changes since last sync",
                "dangerous": False
            },
            {
                "id": "sync",
                "name": "Sync",
                "description": "Update parity data",
                "dangerous": False
            },
            {
                "id": "scrub",
                "name": "Scrub",
                "description": "Verify data integrity",
                "dangerous": False
            },
            {
                "id": "check",
                "name": "Check",
                "description": "Verify parity without fixing",
                "dangerous": False
            },
            {
                "id": "fix",
                "name": "Fix",
                "description": "Recover damaged files from parity",
                "dangerous": True
            }
        ]

    def run_command(
        self,
        command_id: str,
        params: dict = None
    ) -> Generator[str, None, CommandResult]:
        params = params or {}
        log_tags = params.get("log_tags", True)
        log_target = params.get("log_target")
        gui = params.get("gui", True)
        conf_path = params.get("conf_path")

        cmd_map = {
            "status": ["status"],
            "diff": ["diff"],
            "sync": ["sync"],
            "scrub": ["scrub", "-p", str(params.get("percent", 12))],
            "check": ["check"],
            "fix": ["fix"]
        }

        if command_id not in cmd_map:
            yield f"Unknown command: {command_id}"
            return CommandResult(success=False, message="", error="Unknown command")

        args = cmd_map[command_id]

        if command_id == "sync" and not params.get("force", False):
            diff_check = self._check_diff_thresholds()
            if diff_check:
                yield f"WARNING: {diff_check}"
                yield "Use force=true to override"
                return CommandResult(
                    success=False,
                    message="",
                    error=diff_check
                )

        if helper_available():
            try:
                helper_params = {'command': command_id}
                if conf_path:
                    helper_params['conf_path'] = conf_path
                if log_tags:
                    helper_params['log_tags'] = True
                    helper_params['log_target'] = log_target or ">&2"
                    helper_params['gui'] = bool(gui)
                if command_id == "scrub" and 'percent' in params:
                    helper_params['percent'] = params['percent']
                if command_id == "scrub" and 'age_days' in params:
                    helper_params['age_days'] = params['age_days']
                result = helper_call('snapraid', helper_params)
                stdout = result.get('stdout', '')
                stderr = result.get('stderr', '')
                for line in stdout.splitlines():
                    yield line
                tag_data = None
                if log_tags:
                    tag_text = "\n".join([stderr, stdout])
                    tag_data = parse_log_tags(tag_text).to_dict() if tag_text else None
                if result.get('success'):
                    return CommandResult(success=True, message="Complete", data={"log_tags": tag_data})
                return CommandResult(
                    success=False,
                    message="",
                    error=result.get('stderr', 'Command failed'),
                    data={"log_tags": tag_data}
                )
            except HelperError as exc:
                yield f"ERROR: {str(exc)}"
                return CommandResult(success=False, message="", error=str(exc))

        tmp_log_path = None
        base_args = []
        if conf_path:
            base_args.extend(["-c", conf_path])
        if log_tags:
            if not log_target:
                tmp_log_path = f"/tmp/pihealth-snapraid-{command_id}-{int(time.time())}.log"
                log_target = tmp_log_path
            base_args.extend(["--log", log_target])
            if gui:
                base_args.append("--gui")

        full_args = base_args + args

        yield f"Running: snapraid {' '.join(full_args)}"
        yield ""

        try:
            process = subprocess.Popen(
                [self.SNAPRAID_BIN] + full_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            output_lines = []
            for line in iter(process.stdout.readline, ""):
                output_lines.append(line.rstrip())
                yield output_lines[-1]

            process.wait()

            tag_data = None
            if log_tags:
                tag_text = ""
                if log_target in (">&1", ">&2"):
                    tag_text = "\n".join(output_lines)
                elif log_target and os.path.exists(log_target):
                    try:
                        with open(log_target) as handle:
                            tag_text = handle.read()
                    except Exception:
                        tag_text = ""
                if tag_text:
                    tag_data = parse_log_tags(tag_text).to_dict()

            if process.returncode == 0:
                yield ""
                yield "Command completed successfully"
                return CommandResult(success=True, message="Complete", data={"log_tags": tag_data})

            yield ""
            yield f"Command failed with exit code {process.returncode}"
            return CommandResult(
                success=False,
                message="",
                error=f"Exit code {process.returncode}",
                data={"log_tags": tag_data}
            )

        except FileNotFoundError:
            yield "ERROR: SnapRAID binary not found"
            return CommandResult(
                success=False,
                message="",
                error="SnapRAID not installed"
            )
        except Exception as exc:
            yield f"ERROR: {str(exc)}"
            return CommandResult(success=False, message="", error=str(exc))
        finally:
            if tmp_log_path and os.path.exists(tmp_log_path):
                try:
                    os.remove(tmp_log_path)
                except Exception:
                    pass

    def _check_diff_thresholds(self) -> Optional[str]:
        config = self.get_config()
        thresholds = config.get("thresholds", {})
        del_threshold = thresholds.get("delete_threshold", 50)
        upd_threshold = thresholds.get("update_threshold", 500)

        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "diff"],
                capture_output=True,
                text=True,
                timeout=60
            )

            output = result.stdout
            removed_match = re.search(r"(\d+)\s+removed", output)
            updated_match = re.search(r"(\d+)\s+updated", output)

            removed = int(removed_match.group(1)) if removed_match else 0
            updated = int(updated_match.group(1)) if updated_match else 0

            if removed > del_threshold:
                return (
                    "Delete threshold exceeded: "
                    f"{removed} files removed (threshold: {del_threshold})"
                )

            if updated > upd_threshold:
                return (
                    "Update threshold exceeded: "
                    f"{updated} files changed (threshold: {upd_threshold})"
                )

        except Exception:
            pass

        return None

    def is_installed(self) -> bool:
        return os.path.exists(self.SNAPRAID_BIN)

    def get_install_instructions(self) -> str:
        return (
            "To install SnapRAID on Raspberry Pi OS:\n\n"
            "    sudo apt update\n"
            "    sudo apt install snapraid\n\n"
            "Or build from source:\n\n"
            "    wget https://github.com/amadvance/snapraid/releases/download/v12.3/snapraid-12.3.tar.gz\n"
            "    tar xzf snapraid-12.3.tar.gz\n"
            "    cd snapraid-12.3\n"
            "    ./configure\n"
            "    make\n"
            "    sudo make install\n"
        )

    def get_diff_summary(self) -> dict:
        try:
            result = subprocess.run(
                [self.SNAPRAID_BIN, "diff"],
                capture_output=True,
                text=True,
                timeout=120
            )

            summary = {
                "added": 0,
                "removed": 0,
                "updated": 0,
                "moved": 0,
                "copied": 0,
                "restored": 0
            }

            for key in summary:
                match = re.search(rf"(\d+)\s+{key}", result.stdout)
                if match:
                    summary[key] = int(match.group(1))

            return summary

        except Exception:
            return {}

    def get_recovery_status(self) -> dict:
        """
        Analyze array health and recovery options.

        Returns:
            {
                "recoverable": bool,
                "failed_drives": [...],
                "missing_files": int,
                "damaged_files": int,
                "recovery_options": [...]
            }
        """
        status = {
            "recoverable": True,
            "failed_drives": [],
            "missing_files": 0,
            "damaged_files": 0,
            "recovery_options": []
        }

        output = ""
        if helper_available():
            try:
                result = helper_call('snapraid', {'command': 'status'})
                output = result.get('stdout', '')
                if not result.get('success'):
                    status["recoverable"] = False
                    status["error"] = result.get('stderr', 'SnapRAID status failed')
                    return status
            except HelperError as exc:
                status["recoverable"] = False
                status["error"] = str(exc)
                return status
        else:
            try:
                result = subprocess.run(
                    [self.SNAPRAID_BIN, "status"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    status["recoverable"] = False
                    status["error"] = result.stderr or "SnapRAID status failed"
                    return status
                output = result.stdout
            except Exception as exc:
                status["recoverable"] = False
                status["error"] = str(exc)
                return status

        def _parse_count(label: str) -> int:
            patterns = [
                rf'{label}\s+file\s+(\d+)',
                rf'(\d+)\s+{label}'
            ]
            for pattern in patterns:
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    return int(match.group(1))
            return 0

        status["missing_files"] = _parse_count("missing")
        status["damaged_files"] = _parse_count("damaged")

        failed = []
        for line in output.splitlines():
            if "missing" in line.lower() and "disk" in line.lower():
                parts = line.split()
                failed.append(parts[-1])
        if failed:
            status["failed_drives"] = failed

        if status["missing_files"] > 0:
            status["recovery_options"].append({
                "id": "fix_missing",
                "name": "Recover Missing Files",
                "command": "fix",
                "params": {"filter": "missing"}
            })

        if status["damaged_files"] > 0:
            status["recovery_options"].append({
                "id": "fix_damaged",
                "name": "Recover Damaged Files",
                "command": "fix",
                "params": {"filter": "damaged"}
            })

        return status
