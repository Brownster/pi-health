"""Policy-bound creation of one supervised repair action."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from agent_actions.canary import CanaryGateError, CanaryGateService
from agent_actions.capability import (
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    CapabilitySpec,
    TriggerType,
    canonical_hash,
)
from agent_actions.ledger import (
    ActionLedger,
    ActionLedgerError,
    ActionState,
    NewAction,
    NewSupervisionAuthorization,
)
from agent_actions.policy import ActionPolicy, ActionPolicyError
from agent_supervision.service import (
    ACTION_DEADLINE_SECONDS,
    ASSESSMENT_INTERVAL_SECONDS,
    SupervisionError,
    SupervisionStore,
)


class SupervisionAuthorizationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def maintenance_window(
    schedule: Mapping[str, Any], at: datetime
) -> dict[str, Any] | None:
    """Return the open cron window containing an aware point in time."""

    if not isinstance(at, datetime) or at.tzinfo is None:
        raise SupervisionAuthorizationError(
            "clock_failure", "Supervision clock is unavailable"
        )
    try:
        window = schedule["window"]
        duration = timedelta(minutes=window["duration_minutes"])
        zone = ZoneInfo(window["timezone"])
        trigger = CronTrigger.from_crontab(window["cron"], timezone=zone)
    except (KeyError, TypeError, ValueError) as exc:
        raise SupervisionAuthorizationError(
            "schedule_changed", "Supervision schedule window is invalid"
        ) from exc
    now = at.astimezone(timezone.utc)
    search_from = now - duration
    candidate = trigger.get_next_fire_time(None, search_from)
    window_start = None
    iterations = 0
    while candidate is not None and candidate <= now:
        window_start = candidate.astimezone(timezone.utc)
        candidate = trigger.get_next_fire_time(candidate, candidate)
        iterations += 1
        if iterations > 1500:
            raise SupervisionAuthorizationError(
                "schedule_changed", "Supervision schedule window is too frequent"
            )
    if window_start is None:
        return None
    deadline = window_start + duration
    if now >= deadline:
        return None
    digest = hashlib.sha256(
        (
            f"{schedule['id']}\x00{schedule['revision']}\x00"
            f"{window_start.isoformat()}"
        ).encode("utf-8")
    ).hexdigest()
    return {
        "key": f"window-{digest[:32]}",
        "start": window_start,
        "deadline": deadline,
    }


class SupervisionAuthorizer:
    """Recheck every safety gate and atomically create one scheduled action."""

    def __init__(
        self,
        *,
        store: SupervisionStore,
        ledger: ActionLedger,
        registry: CapabilityRegistry,
        policy_provider: Callable[[], ActionPolicy],
        canary_gate: CanaryGateService,
        clock: Callable[[], datetime],
        precondition_provider: (
            Callable[[str, Mapping[str, Any]], Mapping[str, Any]] | None
        ) = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._registry = registry
        self._policy_provider = policy_provider
        self._canary_gate = canary_gate
        self._clock = clock
        self._precondition_provider = precondition_provider
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)

    def authorize(
        self, schedule_id: str, incident_id: str
    ) -> tuple[dict[str, Any], bool]:
        try:
            now = self._now()
            schedule = self._store.get_schedule(schedule_id)
            if not schedule["enabled"]:
                raise SupervisionAuthorizationError(
                    "schedule_disabled", "Supervision schedule is disabled"
                )
            incident = self._store.get_incident(incident_id)
            if (
                incident["schedule_id"] != schedule_id
                or incident["operation"] != schedule["operation"]
                or incident["target"] != schedule["target"]
                or incident["state"] != "confirmed"
                or incident["resolved_at"] is not None
            ):
                raise SupervisionAuthorizationError(
                    "incident_changed", "Supervision incident is not confirmed"
                )
            assessments = self._store.list_assessments(schedule_id, limit=1)
            if (
                not assessments
                or assessments[0]["id"] != incident["last_assessment_id"]
                or assessments[0]["outcome"] != "failed"
            ):
                raise SupervisionAuthorizationError(
                    "assessment_changed", "Fresh failed assessment is unavailable"
                )
            assessment = assessments[0]
            assessed_for = self._time(
                assessment["assessed_for"], "Assessment time"
            )
            if (
                assessed_for > now
                or (now - assessed_for).total_seconds()
                >= ASSESSMENT_INTERVAL_SECONDS
            ):
                raise SupervisionAuthorizationError(
                    "assessment_stale", "Failed assessment is no longer fresh"
                )
            window = maintenance_window(schedule, now)
            if window is None or assessed_for < window["start"]:
                raise SupervisionAuthorizationError(
                    "window_closed", "Supervised repair window is closed"
                )

            capability = self._registry.require(schedule["operation"])
            params = capability.normalize(schedule["params"])
            target = capability.target(params)
            if (
                target != schedule["target"]
                or capability.version != schedule["capability_version"]
                or capability.risk.value != schedule["risk"]
                or AuthorityMode.SUPERVISED not in capability.eligible_modes
            ):
                raise SupervisionAuthorizationError(
                    "contract_changed", "Supervised repair contract changed"
                )
            policy = self._policy_provider()
            policy.require_execution_enabled()
            mode = policy.mode_for(
                schedule["operation"], target, TriggerType.SCHEDULED
            )
            if mode != AuthorityMode.SUPERVISED:
                raise SupervisionAuthorizationError(
                    "policy_changed", "Scheduled supervised authority is unavailable"
                )
            if self._ledger.active_demotion(
                operation=schedule["operation"], target=target
            ) is not None:
                raise SupervisionAuthorizationError(
                    "demoted",
                    "Supervised authority is demoted to approval",
                )
            canary = self._canary_gate.require_supervised(
                operation=schedule["operation"],
                target=target,
                trigger=TriggerType.SCHEDULED,
                mode=mode,
            )
            audit_id = assessment["audit_id"]
            if not isinstance(audit_id, str) or not audit_id:
                raise SupervisionAuthorizationError(
                    "audit_failure", "Assessment audit evidence is unavailable"
                )

            action_id = self._id_factory()
            occurrence_key = self._stable_id(
                "occurrence", schedule_id, assessment["id"]
            )
            authorization_id = self._stable_id(
                "authorization", occurrence_key
            )
            expires = min(
                now + timedelta(seconds=ACTION_DEADLINE_SECONDS),
                window["deadline"],
            )
            evidence = [assessment["id"], audit_id]
            payload_hash = canonical_hash(
                {
                    "operation": schedule["operation"],
                    "capability_version": capability.version,
                    "target": target,
                    "params": params,
                    "trigger": TriggerType.SCHEDULED.value,
                    "evidence_ids": evidence,
                }
            )
            precondition_hash = self._precondition_hash(
                capability=capability,
                operation=schedule["operation"],
                params=params,
                target=target,
            )
            action = NewAction(
                action_id=action_id,
                idempotency_key=occurrence_key,
                operation=schedule["operation"],
                capability_version=capability.version,
                target=target,
                risk=capability.risk.value,
                trigger=TriggerType.SCHEDULED.value,
                authority_mode=AuthorityMode.SUPERVISED.value,
                params=params,
                evidence_ids=evidence,
                payload_hash=payload_hash,
                reason=(
                    f"Code-owned health assessment failed twice for {target}."
                ),
                impact=capability.impact(params),
                precondition_hash=precondition_hash,
                actor_type="system",
                actor_id="limeops-supervisor",
                actor_username=None,
                state=ActionState.AUTHORISED,
                created_at=now.isoformat(),
                expires_at=expires.isoformat(),
            )
            authorization = NewSupervisionAuthorization(
                authorization_id=authorization_id,
                occurrence_key=occurrence_key,
                schedule_id=schedule_id,
                schedule_revision=schedule["revision"],
                incident_id=incident_id,
                assessment_id=assessment["id"],
                assessed_for=assessment["assessed_for"],
                window_key=window["key"],
                window_start=window["start"].isoformat(),
                window_deadline=window["deadline"].isoformat(),
                release_commit=canary["release_commit"],
                authorized_at=now.isoformat(),
                expires_at=expires.isoformat(),
            )
            created_action, created_authorization, created = (
                self._ledger.create_supervised_action(
                    action,
                    authorization,
                    supervision_path=self._store.path,
                )
            )
            return {
                "action": created_action.public_dict(),
                "authorization": created_authorization.public_dict(),
            }, created
        except SupervisionAuthorizationError:
            raise
        except CanaryGateError as exc:
            raise SupervisionAuthorizationError(exc.code, str(exc)) from exc
        except (
            ActionLedgerError,
            ActionPolicyError,
            CapabilityError,
            SupervisionError,
        ) as exc:
            raise self._public_error(exc) from exc
        except Exception as exc:
            raise SupervisionAuthorizationError(
                "authorization_failure",
                "Supervised repair authorization failed",
            ) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SupervisionAuthorizationError(
                "clock_failure", "Supervision clock is unavailable"
            )
        return value.astimezone(timezone.utc)

    def _precondition_hash(
        self,
        *,
        capability: CapabilitySpec,
        operation: str,
        params: Mapping[str, Any],
        target: str,
    ) -> str:
        if self._precondition_provider is None:
            return canonical_hash(capability.precondition(params))
        value = self._precondition_provider(operation, params)
        if not isinstance(value, Mapping) or not value:
            raise SupervisionAuthorizationError(
                "precondition_unavailable",
                "Trusted action precondition is unavailable",
            )
        expected_keys = {
            "operation",
            "capability_version",
            "target",
            "params",
            "precondition_hash",
        }
        if (
            set(value) != expected_keys
            or value.get("operation") != operation
            or value.get("capability_version") != capability.version
            or value.get("target") != target
            or value.get("params") != dict(params)
        ):
            raise SupervisionAuthorizationError(
                "contract_changed",
                "Trusted action precondition contract changed",
            )
        precondition_hash = value.get("precondition_hash")
        if (
            not isinstance(precondition_hash, str)
            or len(precondition_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in precondition_hash
            )
        ):
            raise SupervisionAuthorizationError(
                "precondition_unavailable",
                "Trusted action precondition is unavailable",
            )
        return precondition_hash

    @staticmethod
    def _time(value: Any, label: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise SupervisionAuthorizationError(
                "corrupt_store", f"{label} is invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise SupervisionAuthorizationError(
                "corrupt_store", f"{label} is invalid"
            )
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _stable_id(kind: str, *parts: str) -> str:
        digest = hashlib.sha256(
            "\x00".join((kind, *parts)).encode("utf-8")
        ).hexdigest()
        return f"{kind}-{digest[:32]}"

    @staticmethod
    def _public_error(exc: Exception) -> SupervisionAuthorizationError:
        code = getattr(exc, "code", "authorization_failure")
        messages = {
            "schedule_changed": "Supervision schedule changed before authorization",
            "incident_changed": "Supervision incident is not confirmed",
            "assessment_changed": "Fresh failed assessment is unavailable",
            "target_busy": "Another action is active for this exact target",
            "window_budget_exhausted": (
                "Repair budget for this maintenance window is exhausted"
            ),
            "cooldown_active": "Repair target is inside its rolling cooldown",
            "demoted": "Supervised authority is demoted to approval",
            "canary_required": "A current repair canary is required",
        }
        return SupervisionAuthorizationError(
            code, messages.get(code, str(exc) or "Authorization failed")
        )
