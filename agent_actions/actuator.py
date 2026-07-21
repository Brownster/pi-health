"""Trusted action execution with execution-time revalidation and verification."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_actions.capability import (
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    TriggerType,
    canonical_hash,
)
from agent_actions.ledger import ActionLedger, ActionLedgerError, ActionState
from agent_actions.policy import ActionPolicy, ActionPolicyError
from agent_actions.defaults import safe_stack_precondition


_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ActionActuatorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionSpec:
    operation: str
    version: str
    execute: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    verify: Callable[
        [Mapping[str, Any], Mapping[str, Any]], tuple[bool, Mapping[str, Any]]
    ]
    no_rollback_reason: str


class ActionActuator:
    """Execute one previously authorised action ID; never accept mutation params."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        executors: Mapping[str, ExecutionSpec],
        policy_provider: Callable[[], ActionPolicy],
        ledger: ActionLedger,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._executors = dict(executors)
        self._policy_provider = policy_provider
        self._ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def execute(self, action_id: str, *, audit_id: str) -> dict[str, Any]:
        if not isinstance(action_id, str) or not _ACTION_ID_RE.fullmatch(action_id):
            raise ActionActuatorError("invalid_input", "Action ID is invalid")
        if not isinstance(audit_id, str) or not _ACTION_ID_RE.fullmatch(audit_id):
            raise ActionActuatorError("invalid_input", "Action audit ID is invalid")
        try:
            now = self._now()
            action = self._ledger.get(action_id)
            if action.state != ActionState.AUTHORISED:
                raise ActionActuatorError("invalid_state", "Action is not authorised")
            if self._parse_time(action.expires_at) <= now:
                self._ledger.expire(action_id)
                raise ActionActuatorError("expired", "Action has expired")

            capability = self._registry.require(action.operation)
            executor = self._executors.get(action.operation)
            if executor is None:
                raise ActionActuatorError("unavailable_executor", "Executor is unavailable")
            if (
                capability.version != action.capability_version
                or executor.version != action.capability_version
            ):
                raise ActionActuatorError("contract_changed", "Action contract has changed")

            params = capability.normalize(action.params)
            target = capability.target(params)
            if target != action.target:
                raise ActionActuatorError("payload_changed", "Action target has changed")
            expected_payload_hash = canonical_hash(
                {
                    "operation": action.operation,
                    "capability_version": action.capability_version,
                    "target": target,
                    "params": params,
                    "trigger": action.trigger,
                    "evidence_ids": action.evidence_ids,
                }
            )
            if expected_payload_hash != action.payload_hash:
                raise ActionActuatorError("payload_changed", "Action payload has changed")

            policy = self._policy_provider()
            policy.require_execution_enabled()
            trigger = TriggerType(action.trigger)
            mode = policy.mode_for(action.operation, target, trigger)
            if mode.value != action.authority_mode or mode not in {
                AuthorityMode.APPROVAL,
                AuthorityMode.SUPERVISED,
                AuthorityMode.AUTONOMOUS,
            }:
                raise ActionActuatorError("policy_changed", "Action authority has changed")
            if mode not in capability.eligible_modes:
                raise ActionActuatorError("ineligible_mode", "Action authority is ineligible")

            before = dict(capability.precondition(params))
            if canonical_hash(before) != action.precondition_hash:
                self._ledger.invalidate_precondition(action_id)
                raise ActionActuatorError(
                    "precondition_changed", "Target changed before execution"
                )

            claimed_at = now.isoformat()
            claimed = self._ledger.claim_execution(
                action_id,
                payload_hash=action.payload_hash,
                approval_required=mode == AuthorityMode.APPROVAL,
                claimed_at=claimed_at,
            )
            self._ledger.record_event(
                action_id,
                phase="execution_started",
                created_at=claimed_at,
                details={"action_audit_id": audit_id, "before": before},
            )

            result = executor.execute(params)
            if not isinstance(result, Mapping) or result.get("error"):
                failed = self._ledger.finish_execution(
                    action_id,
                    state=ActionState.EXECUTION_FAILED,
                    terminal_code="executor_failed",
                )
                self._record_outcome(
                    action_id,
                    "execution_failed",
                    {"action_audit_id": audit_id, "code": "executor_failed"},
                )
                return failed.public_dict()

            self._ledger.begin_verification(action_id)
            verified, after = executor.verify(params, before)
            if not isinstance(after, Mapping):
                raise ActionActuatorError(
                    "verification_failure", "Verification returned invalid data"
                )
            safe_after = dict(after)
            if not verified:
                failed = self._ledger.finish_execution(
                    action_id,
                    state=ActionState.VERIFICATION_FAILED,
                    terminal_code="verification_failed:no_safe_rollback",
                )
                self._record_outcome(
                    action_id,
                    "verification_failed",
                    {
                        "action_audit_id": audit_id,
                        "after": safe_after,
                        "rollback": executor.no_rollback_reason,
                    },
                )
                return failed.public_dict()

            succeeded = self._ledger.finish_execution(
                action_id,
                state=ActionState.SUCCEEDED,
                terminal_code="verified",
            )
            self._record_outcome(
                action_id,
                "succeeded",
                {"action_audit_id": audit_id, "after": safe_after},
            )
            response = succeeded.public_dict()
            response["verification"] = safe_after
            response["approval_consumed"] = claimed.approval_used_at is not None
            return response
        except ActionActuatorError:
            raise
        except (CapabilityError, ActionPolicyError, ActionLedgerError, ValueError) as exc:
            raise self._public_error(exc) from exc
        except Exception as exc:
            # Executor and status-reader details can contain host data. Keep them out of
            # the response and ledger while closing any already-claimed action.
            try:
                current = self._ledger.get(action_id)
                if current.state == ActionState.EXECUTING:
                    self._ledger.finish_execution(
                        action_id,
                        state=ActionState.EXECUTION_FAILED,
                        terminal_code="executor_exception",
                    )
                elif current.state == ActionState.VERIFYING:
                    self._ledger.finish_execution(
                        action_id,
                        state=ActionState.VERIFICATION_FAILED,
                        terminal_code="verification_exception:no_safe_rollback",
                    )
            except Exception:
                pass
            raise ActionActuatorError("execution_failure", "Action execution failed") from exc

    def _record_outcome(self, action_id: str, phase: str, details: dict[str, Any]) -> None:
        self._ledger.record_event(
            action_id,
            phase=phase,
            created_at=self._now().isoformat(),
            details=details,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ActionActuatorError("clock_failure", "Action clock is unavailable")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ActionActuatorError("corrupt_store", "Action expiry is invalid") from exc
        if parsed.tzinfo is None:
            raise ActionActuatorError("corrupt_store", "Action expiry is invalid")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _public_error(exc: Exception) -> ActionActuatorError:
        code = getattr(exc, "code", "execution_failure")
        message = {
            "kill_switch": "Agent actions are disabled",
            "denied_operation": "Action operation is disabled",
            "denied_target": "Action target is not allowlisted",
            "invalid_state": "Action state has changed",
            "invalid_approval": "Action approval is not executable",
            "payload_changed": "Action payload has changed",
            "not_found": "Action was not found",
        }.get(code, "Action execution was denied")
        return ActionActuatorError(code, message)


def build_container_executors(
    *,
    control: Callable[[str, str], Mapping[str, Any]],
    status_reader: Callable[[str], Mapping[str, Any]],
    attempts: int = 6,
    interval_seconds: float = 2,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, ExecutionSpec]:
    """Build the first R1 repair executors around trusted container adapters."""

    def executor(operation: str, action: str) -> ExecutionSpec:
        def execute(params: Mapping[str, Any]) -> Mapping[str, Any]:
            return control(params["name"], action)

        def verify(
            params: Mapping[str, Any], before: Mapping[str, Any]
        ) -> tuple[bool, Mapping[str, Any]]:
            after: Mapping[str, Any] = {"name": params["name"], "status": "unknown"}
            for attempt in range(attempts):
                after = status_reader(params["name"])
                running = str(after.get("status") or "").lower() == "running"
                healthy = str(after.get("health") or "").lower() != "unhealthy"
                restarted = (
                    action != "restart"
                    or not before.get("started_at")
                    or after.get("started_at") != before.get("started_at")
                )
                if running and healthy and restarted:
                    return True, after
                if attempt + 1 < attempts:
                    sleeper(interval_seconds)
            return False, after

        return ExecutionSpec(
            operation=operation,
            version="1",
            execute=execute,
            verify=verify,
            no_rollback_reason=(
                "Container stop is outside the initial repair allowlist; escalate for review."
            ),
        )

    return {
        "container.start": executor("container.start", "start"),
        "container.restart": executor("container.restart", "restart"),
    }


def build_stack_executors(
    *,
    reconcile: Callable[[str], Mapping[str, Any]],
    status_reader: Callable[[str], Mapping[str, Any]],
    attempts: int = 6,
    interval_seconds: float = 2,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, ExecutionSpec]:
    """Reconcile one existing stack and verify every declared service."""

    def execute(params: Mapping[str, Any]) -> Mapping[str, Any]:
        return reconcile(params["name"])

    def verify(
        params: Mapping[str, Any], before: Mapping[str, Any]
    ) -> tuple[bool, Mapping[str, Any]]:
        after: Mapping[str, Any] = {
            "name": params["name"],
            "status": "unknown",
            "expected_services": before.get("expected_services", []),
            "containers": [],
        }
        expected = set(before.get("expected_services") or [])
        for attempt in range(attempts):
            after = safe_stack_precondition(status_reader, params["name"])
            containers = after.get("containers") or []
            running_services = {
                item.get("service")
                for item in containers
                if str(item.get("status") or "").lower() == "running"
                and str(item.get("health") or "").lower() != "unhealthy"
            }
            unhealthy = any(
                str(item.get("health") or "").lower() == "unhealthy"
                for item in containers
            )
            definition_unchanged = set(after.get("expected_services") or []) == expected
            if expected and expected <= running_services and not unhealthy and definition_unchanged:
                return True, after
            if attempt + 1 < attempts:
                sleeper(interval_seconds)
        return False, after

    return {
        "stack.reconcile": ExecutionSpec(
            operation="stack.reconcile",
            version="1",
            execute=execute,
            verify=verify,
            no_rollback_reason=(
                "The prior runtime state cannot be restored safely without stopping "
                "services; escalate for review."
            ),
        )
    }
