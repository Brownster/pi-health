"""Versioned lifecycle state and recovery-custody contracts for integrations."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator, FormatChecker

from ports import JsonFileRepository
from runtime_paths import (
    AGENT_LIFECYCLE_PATH,
    INTEGRATION_LIFECYCLE_POLICY_PATH,
    INTEGRATION_LIFECYCLE_TOMBSTONE_SCHEMA_PATH,
)


_CORRUPT_OPERATION_TIME = "1970-01-01T00:00:00+00:00"


class LifecycleStateError(RuntimeError):
    """A bounded lifecycle state failure that must fail closed."""


class RecoveryCredentialError(RuntimeError):
    """A bounded recovery credential custody failure."""


def load_lifecycle_policy(path: str | Path = INTEGRATION_LIFECYCLE_POLICY_PATH) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LifecycleStateError("Integration lifecycle policy is unavailable") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1":
        raise LifecycleStateError("Integration lifecycle policy is incompatible")
    return value


class LifecycleStateRepository:
    """Read and atomically write one application-owned lifecycle tombstone."""

    def __init__(
        self,
        path: str | Path,
        integration: str,
        *,
        repository: JsonFileRepository | None = None,
        schema_path: str | Path = INTEGRATION_LIFECYCLE_TOMBSTONE_SCHEMA_PATH,
        expected_uid: int | None = None,
        expected_gid: int | None = None,
    ) -> None:
        if integration not in {"mattermost", "agents"}:
            raise ValueError("unsupported integration lifecycle repository")
        self.path = Path(path)
        self.integration = integration
        self._repository = repository or JsonFileRepository()
        self._expected_uid = os.geteuid() if expected_uid is None else expected_uid
        self._expected_gid = os.getegid() if expected_gid is None else expected_gid
        try:
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            self._validator = Draft7Validator(schema, format_checker=FormatChecker())
        except (OSError, ValueError) as exc:
            raise LifecycleStateError("Integration lifecycle schema is unavailable") from exc

    def read(self) -> dict[str, Any] | None:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            if os.path.lexists(self.path.parent):
                self._validate_parent()
            return None
        except OSError as exc:
            raise LifecycleStateError("Integration lifecycle state is unavailable") from exc
        self._validate_parent()
        self._validate_metadata(metadata)
        try:
            with self.path.open(encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, ValueError) as exc:
            raise LifecycleStateError("Integration lifecycle state is invalid") from exc
        self._validate_record(value)
        return dict(value)

    def write(self, record: Mapping[str, Any]) -> None:
        value = dict(record)
        self._validate_record(value)
        try:
            if os.path.lexists(self.path):
                self._validate_metadata(self.path.lstat())
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            self._validate_parent()
            self._repository.write_json(self.path, value, mode=0o640)
            self.path.chmod(0o640)
            self._validate_metadata(self.path.lstat())
        except LifecycleStateError:
            raise
        except OSError as exc:
            raise LifecycleStateError("Integration lifecycle state could not be saved") from exc

    def delete(self) -> None:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise LifecycleStateError("Integration lifecycle state is unavailable") from exc
        self._validate_parent()
        self._validate_metadata(metadata)
        try:
            self.path.unlink()
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise LifecycleStateError("Integration lifecycle state could not be removed") from exc

    def _validate_record(self, value: Any) -> None:
        if not isinstance(value, dict) or value.get("integration") != self.integration:
            raise LifecycleStateError("Integration lifecycle state is invalid")
        if next(self._validator.iter_errors(value), None) is not None:
            raise LifecycleStateError("Integration lifecycle state is invalid")

    def _validate_metadata(self, metadata: os.stat_result) -> None:
        if not stat.S_ISREG(metadata.st_mode):
            raise LifecycleStateError("Integration lifecycle state is invalid")
        if stat.S_IMODE(metadata.st_mode) != 0o640:
            raise LifecycleStateError("Integration lifecycle state has unsafe permissions")
        if metadata.st_uid != self._expected_uid:
            raise LifecycleStateError("Integration lifecycle state has invalid ownership")
        if metadata.st_gid != self._expected_gid:
            raise LifecycleStateError("Integration lifecycle state has invalid ownership")

    def _validate_parent(self) -> None:
        try:
            metadata = self.path.parent.lstat()
        except OSError as exc:
            raise LifecycleStateError("Integration lifecycle state is unavailable") from exc
        mode = stat.S_IMODE(metadata.st_mode)
        if not stat.S_ISDIR(metadata.st_mode) or mode & 0o027:
            raise LifecycleStateError("Integration lifecycle directory is unsafe")
        if metadata.st_uid != self._expected_uid or metadata.st_gid != self._expected_gid:
            raise LifecycleStateError("Integration lifecycle directory has invalid ownership")


class IntegrationLifecycleResolver:
    """Merge legacy integration status with an optional lifecycle record."""

    def __init__(
        self,
        repository: LifecycleStateRepository,
        *,
        policy: Mapping[str, Any] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = dict(policy or load_lifecycle_policy())

    def status(self, legacy: Mapping[str, Any]) -> dict[str, Any]:
        public = dict(legacy)
        authoritative = self.authoritative_status(public)
        return authoritative if authoritative is not None else self._legacy(public)

    def authoritative_status(
        self, legacy: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Return tombstone-owned status, or None when legacy facts remain authoritative."""
        public = dict(legacy)
        try:
            record = self._repository.read()
        except LifecycleStateError:
            return self._cleanup_required(public, None)
        if record is None:
            return None
        phase = record["phase"]
        if phase in {"running", "cleanup_required"}:
            return self._cleanup_required(public, record)

        target = record["target_state"]
        if target == "disabled":
            public.update(state="disabled", installed=True, retained_data=False)
        elif target == "retained_data":
            public.update(state="retained_data", installed=False, retained_data=True)
        elif target == "not_installed":
            public.update(state="not_installed", installed=False, retained_data=False)
        elif target == "connected":
            return None
        public.update(
            cleanup_required=False,
            cleanup_operation=None,
            warnings=self._warnings(record),
        )
        public["allowed_actions"] = self._actions(public["state"])
        public.setdefault("blocked_actions", [])
        return public

    def apply_mattermost_dependencies(
        self,
        status: Mapping[str, Any],
        agent_snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Remove unsafe Mattermost actions and publish their fixed blockers."""
        public = dict(status)
        allowed = list(public.get("allowed_actions") or [])
        blocked = []
        installed = bool(agent_snapshot.get("installed"))
        enabled = bool(agent_snapshot.get("enabled"))
        definitions = self._policy["blocked_actions"]
        if (
            installed
            and enabled
            and "disable" in allowed
            and public.get("state") != "cleanup_required"
        ):
            blocked.append(
                {
                    "dependency_code": "agents_must_be_disabled",
                    **definitions["agents_must_be_disabled"],
                }
            )
            allowed = [action for action in allowed if action != "disable"]
        if (
            installed
            and "uninstall" in allowed
            and public.get("state") != "cleanup_required"
        ):
            blocked.append(
                {
                    "dependency_code": "agents_must_be_uninstalled",
                    **definitions["agents_must_be_uninstalled"],
                }
            )
            allowed = [action for action in allowed if action != "uninstall"]
        public["allowed_actions"] = allowed
        public["blocked_actions"] = blocked
        return public

    def _legacy(self, public: dict[str, Any]) -> dict[str, Any]:
        public.update(
            retained_data=False,
            cleanup_required=False,
            cleanup_operation=None,
            warnings=[],
        )
        public["allowed_actions"] = self._actions(str(public.get("state") or "not_installed"))
        public.setdefault("blocked_actions", [])
        return public

    def _cleanup_required(
        self,
        public: dict[str, Any],
        record: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        action = str(record.get("action")) if record else "retry_cleanup"
        operation_id = str(record.get("operation_id")) if record else "lifecycle-state"
        phase = str(record.get("phase")) if record else "running"
        started_at = str(record.get("started_at")) if record else _CORRUPT_OPERATION_TIME
        updated_at = str(record.get("updated_at")) if record else _CORRUPT_OPERATION_TIME
        public.update(
            state="cleanup_required",
            cleanup_required=True,
            retained_data=bool(record and record.get("retained_data")),
            allowed_actions=["retry_cleanup"],
            blocked_actions=[],
            cleanup_operation={
                "id": operation_id,
                "action": action,
                "state": "failed" if phase == "cleanup_required" else "interrupted",
                "started_at": started_at,
                "updated_at": updated_at,
                "retryable": True,
            },
            warnings=self._warnings(record or {}),
        )
        return public

    def _actions(self, state: str) -> list[str]:
        integration = self._repository.integration
        if state == "cleanup_required":
            actions = ["retry_cleanup"]
        elif state == "retained_data":
            actions = ["setup"]
            if self._policy.get("release_policy", {}).get("mattermost_purge_enabled"):
                actions.append("purge")
        elif state == "not_installed":
            actions = ["setup"]
        elif state == "disabled":
            actions = ["enable", "uninstall"]
        elif state == "authenticating":
            actions = []
        elif state == "setup_required":
            actions = ["repair", "disable", "uninstall"]
            if integration == "agents":
                actions.insert(1, "authenticate")
        elif state in {"degraded", "disconnected"}:
            actions = ["repair", "disable", "uninstall"]
        else:
            actions = ["disable", "uninstall"]
        supported = self._policy["integrations"][integration]["allowed_actions"]
        return [
            action
            for action in self._policy["action_order"]
            if action in actions and action in supported
        ]

    def _warnings(self, record: Mapping[str, Any]) -> list[dict[str, str]]:
        catalog = self._policy.get("warnings", {})
        return [
            {"code": code, "message": catalog[code]}
            for code in record.get("warning_codes", [])
            if code in catalog
        ]


class AgentLifecycleSnapshotService:
    """Read agent dependency state without consulting Mattermost."""

    def __init__(
        self,
        *,
        lifecycle_repository: LifecycleStateRepository,
        config_path: str | Path,
        agent_unit_path: str | Path,
        broker_unit_path: str | Path,
    ) -> None:
        self._repository = lifecycle_repository
        self._config_path = Path(config_path)
        self._agent_unit_path = Path(agent_unit_path)
        self._broker_unit_path = Path(broker_unit_path)

    def status(self) -> dict[str, Any]:
        try:
            record = self._repository.read()
        except LifecycleStateError:
            return self._cleanup_required()
        if record is not None:
            if record["phase"] != "complete":
                return self._cleanup_required()
            target = record["target_state"]
            if target == "disabled":
                return {"state": "disabled", "installed": True, "enabled": False}
            if target == "not_installed":
                return {"state": "not_installed", "installed": False, "enabled": False}

        agent_unit = self._agent_unit_path.is_file()
        broker_unit = self._broker_unit_path.is_file()
        if not agent_unit and not broker_unit and not self._config_path.exists():
            return {"state": "not_installed", "installed": False, "enabled": False}
        if not agent_unit or not broker_unit:
            return self._cleanup_required()
        try:
            config = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._cleanup_required()
        if not isinstance(config, dict):
            return self._cleanup_required()
        enabled = bool(config.get("enabled"))
        return {
            "state": "enabled" if enabled else "disabled",
            "installed": True,
            "enabled": enabled,
        }

    def package_feature_state(self) -> dict[str, Any]:
        """Expose the server-owned feature input consumed by package reconciliation."""
        status = self.status()
        state = status["state"]
        return {
            "feature": "ai_agents",
            "state": state,
            "managed": state in {"enabled", "disabled"},
            "reconcile_allowed": state in {"enabled", "disabled"},
        }

    @staticmethod
    def _cleanup_required() -> dict[str, Any]:
        return {"state": "cleanup_required", "installed": True, "enabled": True}


def default_agent_lifecycle_snapshot() -> AgentLifecycleSnapshotService:
    from agent_provider.provisioning import (
        AGENT_CONFIG_PATH,
        AGENT_UNIT_PATH,
        LIMEOPS_UNIT_PATH,
    )

    return AgentLifecycleSnapshotService(
        lifecycle_repository=LifecycleStateRepository(AGENT_LIFECYCLE_PATH, "agents"),
        config_path=AGENT_CONFIG_PATH,
        agent_unit_path=AGENT_UNIT_PATH,
        broker_unit_path=LIMEOPS_UNIT_PATH,
    )


class RecoveryCredentialCustody:
    """Invoke fixed helper commands without reading or transporting the credential."""

    _COMMANDS = {
        "retain": "mattermost_recovery_credential_retain",
        "restore": "mattermost_recovery_credential_restore",
        "discard": "mattermost_recovery_credential_discard",
    }

    def __init__(self, helper_call: Callable[..., dict]) -> None:
        self._helper_call = helper_call

    def retain(self) -> dict[str, bool]:
        return self._call("retain", "credential_retained")

    def restore(self) -> dict[str, bool]:
        return self._call("restore", "credential_restored")

    def discard(self) -> dict[str, bool]:
        return self._call("discard", "credential_discarded")

    def _call(self, action: str, result_field: str) -> dict[str, bool]:
        try:
            result = self._helper_call(self._COMMANDS[action], {})
        except Exception as exc:
            raise RecoveryCredentialError(
                "Mattermost recovery credential operation failed"
            ) from exc
        if not isinstance(result, dict) or not result.get("success"):
            raise RecoveryCredentialError("Mattermost recovery credential operation failed")
        return {"success": True, result_field: bool(result.get(result_field))}
