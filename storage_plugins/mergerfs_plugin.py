"""
MergerFS storage plugin.
Manages MergerFS pools for combining multiple drives.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Generator

from storage_plugins.base import StoragePlugin, CommandResult, PluginStatus
from helper_client import helper_call, helper_available, HelperError


POLICIES = {
    "epmfs": "Existing path, most free space - Write to drive with most free space that already has the parent directory",
    "eplfs": "Existing path, least free space - Write to drive with least free space that has the parent directory",
    "eplus": "Existing path, least used space - Write to drive with least used space that has the parent directory",
    "mfs": "Most free space - Write to drive with most free space",
    "lfs": "Least free space - Write to drive with least free space",
    "lus": "Least used space - Write to drive with least used space",
    "rand": "Random - Randomly select a drive",
    "pfrd": "Percentage free random distribution - Weighted random by free space",
    "ff": "First found - Write to first drive with enough space"
}


class MergerFSPlugin(StoragePlugin):
    """MergerFS pool management plugin."""

    PLUGIN_ID = "mergerfs"
    PLUGIN_NAME = "MergerFS"
    PLUGIN_VERSION = "1.0.0"
    PLUGIN_DESCRIPTION = "Combine multiple drives into a single unified pool"
    PLUGIN_CATEGORY = "storage"  # UI appears on Pools page

    MERGERFS_BIN = "/usr/bin/mergerfs"
    FSTAB_PATH = "/etc/fstab"

    def __init__(self, config_dir: str):
        super().__init__(config_dir)
        self._schema = None

    def get_schema(self) -> dict:
        if self._schema is None:
            schema_path = os.path.join(
                os.path.dirname(self.config_dir),
                "schemas",
                "mergerfs.schema.json"
            )
            if os.path.exists(schema_path):
                with open(schema_path) as handle:
                    self._schema = json.load(handle)
            else:
                self._schema = {
                    "type": "object",
                    "properties": {
                        "pools": {"type": "array"}
                    }
                }
        return self._schema

    def get_config(self) -> dict:
        if os.path.exists(self.config_path):
            with open(self.config_path) as handle:
                return json.load(handle)
        return {"pools": []}

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
        pools = config.get("pools", [])

        names = []
        mount_points = []
        all_branches = []

        for pool in pools:
            name = pool.get("name", "")
            branches = pool.get("branches", [])
            mount_point = pool.get("mount_point", "")

            if name in names:
                errors.append(f"Duplicate pool name: {name}")
            names.append(name)

            if len(branches) < 2:
                errors.append(f"Pool '{name}' needs at least 2 branches")

            if mount_point in mount_points:
                errors.append(f"Duplicate mount point: {mount_point}")
            mount_points.append(mount_point)

            for branch in branches:
                if branch in all_branches:
                    errors.append(f"Branch used in multiple pools: {branch}")
                all_branches.append(branch)

            if not mount_point.startswith("/mnt/"):
                errors.append(f"Mount point must be under /mnt/: {mount_point}")

            policy = pool.get("create_policy", "epmfs")
            if policy not in POLICIES:
                errors.append(f"Invalid create policy: {policy}")

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

        try:
            pools = config.get("pools", [])
            enabled_pools = [pool for pool in pools if pool.get("enabled", True)]
            lines = self._build_fstab_lines(enabled_pools)

            if helper_available():
                try:
                    result = helper_call('fstab_set_section', {
                        'marker': 'mergerfs',
                        'lines': lines
                    })
                    if not result.get('success'):
                        return CommandResult(success=False, message="", error=result.get('error', 'Helper failed'))
                    return CommandResult(
                        success=True,
                        message=self._apply_message(enabled_pools)
                    )
                except HelperError as exc:
                    return CommandResult(success=False, message="", error=str(exc))

            self._write_fstab_section(lines)
            return CommandResult(success=True, message=self._apply_message(enabled_pools))
        except Exception as exc:
            return CommandResult(success=False, message="", error=str(exc))

    def _apply_message(self, enabled_pools: list[dict]) -> str:
        if not enabled_pools:
            return "MergerFS entries removed from fstab"
        return f"MergerFS entries updated for {len(enabled_pools)} pool(s)"

    def _generate_fstab_entry(self, pool: dict) -> str:
        branches = ":".join(pool["branches"])
        mount_point = pool["mount_point"]
        policy = pool.get("create_policy", "epmfs")
        min_free = pool.get("min_free_space", "4G")
        options = pool.get("options", "")

        opts = [
            "defaults",
            "allow_other",
            "use_ino",
            f"category.create={policy}",
            f"minfreespace={min_free}",
            "cache.files=off",
            "dropcacheonclose=true",
            "fsname=mergerfs"
        ]

        if options:
            for opt in options.split(","):
                opt = opt.strip()
                if not opt:
                    continue
                key = opt.split("=")[0]
                if not any(key == existing.split("=")[0] for existing in opts):
                    opts.append(opt)

        opts_str = ",".join(opts)
        return f"{branches} {mount_point} fuse.mergerfs {opts_str} 0 0"

    def _build_fstab_lines(self, pools: list[dict]) -> list[str]:
        lines: list[str] = []
        for pool in pools:
            name = pool.get("name") or "unnamed"
            lines.append(f"# mergerfs pool: {name}")
            lines.append(self._generate_fstab_entry(pool))
        return lines

    def _write_fstab_section(self, lines: list[str]) -> None:
        start = "# pi-health mergerfs start"
        end = "# pi-health mergerfs end"
        path = self.FSTAB_PATH

        existing = []
        if os.path.exists(path):
            with open(path) as handle:
                existing = handle.read().splitlines()

        updated = []
        in_section = False
        for line in existing:
            if line.strip() == start:
                in_section = True
                continue
            if in_section:
                if line.strip() == end:
                    in_section = False
                continue
            updated.append(line.rstrip('\n'))

        cleaned_lines = [line.rstrip('\n') for line in lines if str(line).strip()]
        if cleaned_lines:
            if updated and updated[-1].strip():
                updated.append("")
            updated.append(start)
            updated.extend(cleaned_lines)
            updated.append(end)
            updated.append("")

        content = "\n".join(updated).rstrip("\n") + "\n"
        with open(path, "w") as handle:
            handle.write(content)

    def get_status(self) -> dict:
        config = self.get_config()
        pools = config.get("pools", [])

        if not pools:
            return {
                "status": PluginStatus.UNCONFIGURED.value,
                "message": "No pools configured",
                "details": {"pools": []}
            }

        pool_status = []
        all_healthy = True

        for pool in pools:
            mount_point = pool.get("mount_point", "")
            is_mounted = os.path.ismount(mount_point)

            status = {
                "name": pool.get("name"),
                "mount_point": mount_point,
                "mounted": is_mounted,
                "branches": len(pool.get("branches", []))
            }

            if is_mounted:
                try:
                    stat = os.statvfs(mount_point)
                    status["total_bytes"] = stat.f_blocks * stat.f_frsize
                    status["free_bytes"] = stat.f_bavail * stat.f_frsize
                    status["used_percent"] = round(
                        (1 - stat.f_bavail / stat.f_blocks) * 100, 1
                    ) if stat.f_blocks > 0 else 0
                except Exception:
                    pass
            else:
                all_healthy = False

            pool_status.append(status)

        return {
            "status": PluginStatus.HEALTHY.value if all_healthy else PluginStatus.DEGRADED.value,
            "message": f"{len(pools)} pool(s) configured",
            "details": {"pools": pool_status}
        }

    def get_commands(self) -> list[dict]:
        return [
            {
                "id": "mount",
                "name": "Mount Pool",
                "description": "Mount a MergerFS pool",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "unmount",
                "name": "Unmount Pool",
                "description": "Unmount a MergerFS pool",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "balance",
                "name": "Balance",
                "description": "Rebalance files across branches",
                "dangerous": False,
                "params": ["pool_name"]
            },
            {
                "id": "status",
                "name": "Status",
                "description": "Show pool status",
                "dangerous": False
            }
        ]

    def run_command(
        self,
        command_id: str,
        params: dict = None
    ) -> Generator[str, None, CommandResult]:
        params = params or {}

        if command_id == "status":
            yield from self._cmd_status()
            return CommandResult(success=True, message="Complete")

        if command_id == "mount":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_mount(pool_name)
            return CommandResult(success=True, message="Mounted")

        if command_id == "unmount":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_unmount(pool_name)
            return CommandResult(success=True, message="Unmounted")

        if command_id == "balance":
            pool_name = params.get("pool_name")
            if not pool_name:
                yield "ERROR: pool_name required"
                return CommandResult(success=False, message="", error="pool_name required")
            yield from self._cmd_balance(pool_name)
            return CommandResult(success=True, message="Complete")

        yield f"Unknown command: {command_id}"
        return CommandResult(success=False, message="", error="Unknown command")

    def _cmd_status(self) -> Generator[str, None, None]:
        config = self.get_config()
        pools = config.get("pools", [])

        if not pools:
            yield "No pools configured"
            return

        for pool in pools:
            name = pool.get("name")
            mount_point = pool.get("mount_point")
            branches = pool.get("branches", [])

            yield f"\n=== Pool: {name} ==="
            yield f"Mount: {mount_point}"
            yield f"Branches: {len(branches)}"

            for branch in branches:
                if os.path.exists(branch):
                    try:
                        stat = os.statvfs(branch)
                        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
                        yield f"  {branch}: {free_gb:.1f} GB free"
                    except Exception:
                        yield f"  {branch}: (cannot read)"
                else:
                    yield f"  {branch}: NOT FOUND"

            if os.path.ismount(mount_point):
                yield "Status: MOUNTED"
            else:
                yield "Status: NOT MOUNTED"

    def _cmd_mount(self, pool_name: str) -> Generator[str, None, None]:
        config = self.get_config()
        pool = next(
            (item for item in config.get("pools", []) if item.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        if os.path.ismount(mount_point):
            yield f"Pool already mounted at {mount_point}"
            return

        branches = ":".join(pool["branches"])
        policy = pool.get("create_policy", "epmfs")
        min_free = pool.get("min_free_space", "4G")
        opts = f"category.create={policy},minfreespace={min_free},allow_other,use_ino"

        yield f"Mounting {pool_name}..."
        yield f"  Source: {branches}"
        yield f"  Target: {mount_point}"

        if helper_available():
            try:
                result = helper_call('mergerfs_mount', {
                    'branches': branches,
                    'mount_point': mount_point,
                    'options': opts
                })
                if result.get('success'):
                    yield "Mount successful"
                else:
                    yield f"Mount failed: {result.get('error', 'unknown error')}"
                return
            except HelperError as exc:
                yield f"ERROR: {exc}"
                return

        os.makedirs(mount_point, exist_ok=True)

        try:
            result = subprocess.run(
                [self.MERGERFS_BIN, "-o", opts, branches, mount_point],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                yield "Mount successful"
            else:
                yield f"Mount failed: {result.stderr}"
        except FileNotFoundError:
            yield "ERROR: mergerfs not installed"
        except Exception as exc:
            yield f"ERROR: {exc}"

    def _cmd_unmount(self, pool_name: str) -> Generator[str, None, None]:
        config = self.get_config()
        pool = next(
            (item for item in config.get("pools", []) if item.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        if not os.path.ismount(mount_point):
            yield f"Pool not mounted: {mount_point}"
            return

        yield f"Unmounting {pool_name}..."

        if helper_available():
            try:
                result = helper_call('mergerfs_umount', {'mount_point': mount_point})
                if result.get('success'):
                    yield "Unmount successful"
                else:
                    yield f"Unmount failed: {result.get('error', 'unknown error')}"
                    yield "Try: umount -l for lazy unmount"
                return
            except HelperError as exc:
                yield f"ERROR: {exc}"
                return

        try:
            result = subprocess.run(
                ["umount", mount_point],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                yield "Unmount successful"
            else:
                yield f"Unmount failed: {result.stderr}"
                yield "Try: umount -l for lazy unmount"
        except Exception as exc:
            yield f"ERROR: {exc}"

    def _cmd_balance(self, pool_name: str) -> Generator[str, None, None]:
        yield f"Balancing pool: {pool_name}"
        yield "NOTE: mergerfs.balance tool required"
        yield "Install with: apt install mergerfs-tools"

        config = self.get_config()
        pool = next(
            (item for item in config.get("pools", []) if item.get("name") == pool_name),
            None
        )

        if not pool:
            yield f"Pool not found: {pool_name}"
            return

        mount_point = pool.get("mount_point")

        try:
            process = subprocess.Popen(
                ["mergerfs.balance", mount_point],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )

            for line in iter(process.stdout.readline, ""):
                yield line.rstrip()

            process.wait()
        except FileNotFoundError:
            yield "mergerfs.balance not found"
            yield "Install mergerfs-tools package"
        except Exception as exc:
            yield f"ERROR: {exc}"

    def is_installed(self) -> bool:
        return os.path.exists(self.MERGERFS_BIN)

    def get_install_instructions(self) -> str:
        return (
            "To install MergerFS on Raspberry Pi OS:\n\n"
            "    sudo apt update\n"
            "    sudo apt install mergerfs\n\n"
            "For tools (balance, dedup):\n\n"
            "    sudo apt install mergerfs-tools\n"
        )

    def get_policies(self) -> dict:
        return POLICIES
