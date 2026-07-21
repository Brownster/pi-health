"""Framework-neutral proposal and approval orchestration."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_actions.capability import (
    ActionActor,
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    TriggerType,
    canonical_hash,
)
from agent_actions.ledger import (
    ActionLedger,
    ActionLedgerError,
    ActionState,
    NewAction,
)
from agent_actions.policy import ActionPolicy, ActionPolicyError


_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_EVIDENCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class AgentActionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AgentActionService:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        policy_provider: Callable[[], ActionPolicy],
        ledger: ActionLedger,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._policy_provider = policy_provider
        self._ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def propose(
        self,
        *,
        operation: str,
        params: Any,
        actor: Any,
        trigger: str = "interactive",
        reason: str,
        evidence_ids: Sequence[str] = (),
        idempotency_key: str,
    ) -> tuple[dict[str, Any], bool]:
        try:
            capability = self._registry.require(operation)
            source_actor = ActionActor.from_mapping(actor)
            trigger_type = TriggerType(trigger)
            normalized = capability.normalize(params)
            target = capability.target(normalized)
            policy = self._policy_provider()
            mode = policy.mode_for(operation, target, trigger_type)
            if mode == AuthorityMode.OBSERVE:
                raise AgentActionError("observe_only", "Capability is observe-only")
            if mode not in capability.eligible_modes:
                raise AgentActionError(
                    "ineligible_mode", "Capability cannot use the configured authority mode"
                )
            reason = self._reason(reason)
            evidence = self._evidence(evidence_ids)
            if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_RE.fullmatch(
                idempotency_key
            ):
                raise AgentActionError("invalid_input", "Idempotency key is invalid")
            precondition_hash = canonical_hash(capability.precondition(normalized))
            payload = {
                "operation": operation,
                "capability_version": capability.version,
                "target": target,
                "params": normalized,
                "trigger": trigger_type.value,
                "evidence_ids": evidence,
            }
            payload_hash = canonical_hash(payload)
            now = self._aware_now()
            if mode in {AuthorityMode.SUPERVISED, AuthorityMode.AUTONOMOUS}:
                policy.require_execution_enabled()
                state = ActionState.AUTHORISED
            elif mode == AuthorityMode.APPROVAL:
                state = ActionState.AWAITING_APPROVAL
            else:
                state = ActionState.PROPOSED
            action, created = self._ledger.create(
                NewAction(
                    action_id=self._id_factory(),
                    idempotency_key=idempotency_key,
                    operation=operation,
                    capability_version=capability.version,
                    target=target,
                    risk=capability.risk.value,
                    trigger=trigger_type.value,
                    authority_mode=mode.value,
                    params=normalized,
                    evidence_ids=evidence,
                    payload_hash=payload_hash,
                    reason=reason,
                    impact=capability.impact(normalized),
                    precondition_hash=precondition_hash,
                    actor_type=source_actor.type,
                    actor_id=source_actor.id,
                    actor_username=source_actor.username,
                    state=state,
                    created_at=now.isoformat(),
                    expires_at=(
                        now + timedelta(seconds=policy.proposal_ttl_seconds)
                    ).isoformat(),
                )
            )
            return action.public_dict(), created
        except AgentActionError:
            raise
        except (CapabilityError, ActionPolicyError, ActionLedgerError, ValueError) as exc:
            raise self._public_error(exc) from exc

    def approve(self, action_id: str, *, approver: Any) -> dict[str, Any]:
        try:
            actor = ActionActor.from_mapping(approver)
            action = self._ledger.get(action_id)
            policy = self._policy_provider()
            policy.require_execution_enabled()
            trigger = TriggerType(action.trigger)
            mode = policy.mode_for(action.operation, action.target, trigger)
            if mode != AuthorityMode.APPROVAL or action.authority_mode != mode.value:
                raise AgentActionError(
                    "policy_changed", "Action authority changed after proposal"
                )
            policy.require_approver(action.operation, actor)
            now = self._aware_now()
            if self._parse_time(action.expires_at) <= now:
                self._ledger.expire(action_id)
                raise AgentActionError("expired", "Action approval has expired")
            capability = self._registry.require(action.operation)
            if capability.version != action.capability_version:
                raise AgentActionError(
                    "contract_changed", "Capability changed after proposal"
                )
            current_precondition = canonical_hash(capability.precondition(action.params))
            if current_precondition != action.precondition_hash:
                self._ledger.invalidate_precondition(action_id)
                raise AgentActionError(
                    "precondition_changed", "Target changed after proposal"
                )
            return self._ledger.approve(
                action_id,
                payload_hash=action.payload_hash,
                approver_type=actor.type,
                approver_id=actor.id,
                approver_username=actor.username,
                approved_at=now.isoformat(),
            ).public_dict()
        except AgentActionError:
            raise
        except (CapabilityError, ActionPolicyError, ActionLedgerError, ValueError) as exc:
            raise self._public_error(exc) from exc

    def reject(self, action_id: str) -> dict[str, Any]:
        try:
            now = self._aware_now().isoformat()
            return self._ledger.reject(action_id, rejected_at=now).public_dict()
        except ActionLedgerError as exc:
            raise self._public_error(exc) from exc

    def get(self, action_id: str) -> dict[str, Any]:
        try:
            return self._ledger.get(action_id).public_dict()
        except ActionLedgerError as exc:
            raise self._public_error(exc) from exc

    def list(self, *, limit: int = 50) -> dict[str, Any]:
        try:
            return {
                "actions": [record.public_dict() for record in self._ledger.list(limit=limit)]
            }
        except ActionLedgerError as exc:
            raise self._public_error(exc) from exc

    @staticmethod
    def _reason(value: Any) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 1000
            or any(character in value for character in "\x00\r")
        ):
            raise AgentActionError("invalid_input", "Action reason is invalid")
        return value.strip()

    @staticmethod
    def _evidence(value: Sequence[str]) -> list[str]:
        if isinstance(value, (str, bytes)) or len(value) > 16:
            raise AgentActionError("invalid_input", "Action evidence is invalid")
        evidence = []
        for item in value:
            if not isinstance(item, str) or not _EVIDENCE_RE.fullmatch(item):
                raise AgentActionError("invalid_input", "Action evidence is invalid")
            if item in evidence:
                raise AgentActionError("invalid_input", "Action evidence is duplicated")
            evidence.append(item)
        return evidence

    def _aware_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AgentActionError("clock_failure", "Action clock is unavailable")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise AgentActionError("corrupt_store", "Action expiry is invalid") from exc
        if parsed.tzinfo is None:
            raise AgentActionError("corrupt_store", "Action expiry is invalid")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _public_error(exc: Exception) -> AgentActionError:
        code = getattr(exc, "code", "action_failure")
        public = {
            "invalid_policy": "Action policy is invalid",
            "denied_operation": "Action operation is disabled",
            "denied_target": "Action target is not allowlisted",
            "denied_approver": "Actor cannot approve this action",
            "kill_switch": "Agent actions are disabled",
            "not_found": "Action was not found",
            "invalid_state": "Action state has changed",
            "idempotency_conflict": "Idempotency key belongs to another payload",
            "payload_changed": "Action payload has changed",
            "conflict": "Action changed concurrently",
        }.get(code, str(exc) or "Agent action failed")
        return AgentActionError(code, public)
