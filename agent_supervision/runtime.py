"""Dedicated model-free runtime for supervised repair assessment and scheduling."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from agent_actions.ledger import ActionLedger, ActionLedgerError, ActionState
from agent_supervision.authorization import (
    SupervisionAuthorizationError,
    SupervisionAuthorizer,
)
from agent_supervision.service import (
    SupervisionError,
    SupervisionService,
    SupervisionStore,
    assessment_bucket,
)


SYSTEM_ACTOR = {"type": "system", "id": "limeops-supervisor"}
MAX_CONCURRENT_ASSESSMENTS = 4
SUPERVISOR_POLL_SECONDS = 60

_ACTION_TRANSITIONS = {
    ActionState.AUTHORISED: ("action_authorized", "action_authorized"),
    ActionState.EXECUTING: ("action_started", "executing"),
    ActionState.VERIFYING: ("verification_started", "verifying"),
}
_FAILED_ACTION_STATES = frozenset(
    {
        ActionState.EXECUTION_FAILED,
        ActionState.VERIFICATION_FAILED,
        ActionState.ROLLBACK_FAILED,
        ActionState.ESCALATION_REQUIRED,
        ActionState.EXPIRED,
        ActionState.CANCELLED,
        ActionState.SUPERSEDED,
        ActionState.PRECONDITION_CHANGED,
    }
)
_AUTHORIZATION_TRANSITIONS = {
    "window_closed": ("window_deferred", "window_deferred"),
    "target_busy": ("active_action_deferred", "active_action_deferred"),
    "active_conflict": ("active_action_deferred", "active_action_deferred"),
    "cooldown_active": ("budget_blocked", "budget_blocked"),
    "window_budget_exhausted": ("budget_blocked", "budget_blocked"),
    "demoted": ("demoted", "demoted"),
}

logger = logging.getLogger("limeos.agent.supervisor")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupervisedRepairRuntime:
    """Run bounded health reads and create actions only through the authorizer."""

    def __init__(
        self,
        *,
        store: SupervisionStore,
        service: SupervisionService,
        authorizer: SupervisionAuthorizer,
        ledger: ActionLedger,
        scheduler: Any,
        diagnostic: Callable[
            [str, Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
        ],
        deliver: Callable[[Mapping[str, Any]], str],
        clock: Callable[[], datetime] = _utcnow,
        max_assessments: int = MAX_CONCURRENT_ASSESSMENTS,
    ) -> None:
        if (
            isinstance(max_assessments, bool)
            or not isinstance(max_assessments, int)
            or not 1 <= max_assessments <= MAX_CONCURRENT_ASSESSMENTS
        ):
            raise ValueError("Assessment concurrency is invalid")
        self.store = store
        self._service = service
        self._authorizer = authorizer
        self._ledger = ledger
        self._scheduler = scheduler
        self._diagnostic = diagnostic
        self._deliver = deliver
        self._clock = clock
        self._max_assessments = max_assessments
        self._cycle_lock = threading.Lock()

    def init_scheduler(self) -> None:
        """Recover durable work before accepting periodic cycles."""

        self.recover()
        self._scheduler.add_job(
            self.run_cycle,
            "interval",
            id="supervised-repair:cycle",
            replace_existing=True,
            seconds=SUPERVISOR_POLL_SECONDS,
            coalesce=True,
            max_instances=1,
        )
        if not self._scheduler.running:
            self._scheduler.start()
        self.run_cycle()

    def recover(self) -> None:
        """Resume occurrences and actions without replaying uncertain messages."""

        now = self._now()
        self.store.recover_deliveries(at=now.isoformat())
        self._reconcile_actions(now)
        for occurrence in self.store.incomplete_occurrences():
            try:
                self._process_occurrence(occurrence)
            except Exception:
                logger.exception(
                    "failed to recover supervision occurrence %s",
                    occurrence["id"],
                )
        self._deliver_pending()

    def run_cycle(self, *, at: datetime | None = None) -> dict[str, int]:
        """Assess each enabled schedule once in the current ten-minute bucket."""

        if not self._cycle_lock.acquire(blocking=False):
            return {"assessed": 0, "skipped": 1}
        try:
            now = self._aware(at or self._clock())
            self._reconcile_actions(now)
            schedules = [
                schedule
                for schedule in self.store.list_schedules()
                if schedule["enabled"]
            ]
            bucket = assessment_bucket(now).isoformat()
            incomplete = self.store.incomplete_occurrences()
            occurrences: list[dict[str, Any]] = []
            recovering_schedules: set[str] = set()
            for occurrence in incomplete:
                if occurrence["schedule_id"] in recovering_schedules:
                    continue
                recovering_schedules.add(occurrence["schedule_id"])
                occurrences.append(occurrence)
            for schedule in schedules:
                if schedule["id"] in recovering_schedules:
                    continue
                try:
                    occurrence, _created = self.store.begin_occurrence(
                        schedule_id=schedule["id"],
                        assessed_for=bucket,
                        started_at=now.isoformat(),
                    )
                except SupervisionError as exc:
                    if exc.code != "schedule_disabled":
                        logger.warning(
                            "failed to claim assessment for %s: %s",
                            schedule["id"],
                            exc.code,
                        )
                    continue
                if occurrence["state"] != "completed":
                    occurrences.append(occurrence)

            if occurrences:
                with ThreadPoolExecutor(
                    max_workers=self._max_assessments,
                    thread_name_prefix="limeops-supervision",
                ) as executor:
                    futures = [
                        executor.submit(self._process_occurrence, occurrence)
                        for occurrence in occurrences
                    ]
                    for future in futures:
                        try:
                            future.result()
                        except Exception:
                            logger.exception("supervised assessment failed")
            self._reconcile_actions(self._now())
            self._deliver_pending()
            return {"assessed": len(occurrences), "skipped": 0}
        finally:
            self._cycle_lock.release()

    def _process_occurrence(self, occurrence: Mapping[str, Any]) -> None:
        current = self.store.get_occurrence(str(occurrence["id"]))
        if current["state"] == "completed":
            return
        schedule = self.store.get_schedule(current["schedule_id"])
        if not schedule["enabled"]:
            self.store.finish_occurrence(
                current["id"],
                terminal_code="schedule_disabled",
                at=self._now().isoformat(),
            )
            return
        if current["state"] == "claimed":
            try:
                response = self._diagnostic(
                    schedule["assessment_operation"],
                    {"name": schedule["target"]},
                    SYSTEM_ACTOR,
                )
            except Exception:
                response = {
                    "ok": False,
                    "error": {"code": "unavailable_dependency"},
                    "audit_id": None,
                }
            result = self._service.assess(
                schedule["id"],
                response,
                assessed_at=datetime.fromisoformat(current["assessed_for"]),
            )
            current = self.store.mark_occurrence_assessed(
                current["id"],
                assessment_id=result["assessment"]["id"],
                incident_id=(
                    result["incident"]["id"]
                    if result["incident"] is not None
                    else None
                ),
                at=self._now().isoformat(),
            )

        terminal_code = "assessment_recorded"
        if current["action_id"] is not None:
            terminal_code = "action_authorized"
        elif current["incident_id"] is not None:
            incident = self.store.get_incident(current["incident_id"])
            assessment = self.store.get_assessment(current["assessment_id"])
            if (
                incident["resolved_at"] is None
                and incident["state"] == "confirmed"
                and assessment["outcome"] == "failed"
            ):
                terminal_code = self._authorize(current, incident)
        self.store.finish_occurrence(
            current["id"],
            terminal_code=terminal_code,
            at=self._now().isoformat(),
        )

    def _authorize(
        self,
        occurrence: Mapping[str, Any],
        incident: Mapping[str, Any],
    ) -> str:
        try:
            result, _created = self._authorizer.authorize(
                occurrence["schedule_id"], incident["id"]
            )
            action_id = result["action"]["id"]
            self.store.link_occurrence_action(
                occurrence["id"],
                incident_id=incident["id"],
                action_id=action_id,
                at=self._now().isoformat(),
            )
            return "action_authorized"
        except SupervisionAuthorizationError as exc:
            transition, state = _AUTHORIZATION_TRANSITIONS.get(
                exc.code, ("supervision_blocked", "supervision_blocked")
            )
            self.store.record_incident_event(
                incident["id"],
                transition_key=(
                    f"authorization:{incident['id']}:{transition}:{exc.code}"
                ),
                transition_type=transition,
                details={"code": exc.code},
                state=state,
                terminal_code=None,
                resolved=False,
                at=self._now().isoformat(),
            )
            return exc.code

    def _reconcile_actions(self, now: datetime) -> None:
        for incident in self.store.list_incidents():
            action_id = incident.get("last_action_id")
            if incident["resolved_at"] is not None or action_id is None:
                continue
            try:
                action = self._ledger.get(action_id)
            except ActionLedgerError:
                self._record_blocked_action(
                    incident, action_id, "action_unavailable", now
                )
                continue
            if action.state == ActionState.SUCCEEDED:
                self.store.record_incident_event(
                    incident["id"],
                    transition_key=f"action:{action_id}:succeeded",
                    transition_type="recovered_after_action",
                    details={
                        "action_id": action_id,
                        "terminal_code": action.terminal_code or "verified",
                    },
                    state="recovered",
                    terminal_code=action.terminal_code or "verified",
                    resolved=True,
                    at=now.isoformat(),
                )
                continue
            if (
                action.state == ActionState.CANCELLED
                and action.terminal_code == "integration_disabled"
            ):
                self.store.record_incident_event(
                    incident["id"],
                    transition_key=f"action:{action_id}:integration-disabled",
                    transition_type="supervision_blocked",
                    details={
                        "action_id": action_id,
                        "code": "integration_disabled",
                    },
                    state="supervision_blocked",
                    terminal_code="integration_disabled",
                    resolved=False,
                    at=now.isoformat(),
                )
                continue
            if action.state in _FAILED_ACTION_STATES:
                self.store.record_incident_event(
                    incident["id"],
                    transition_key=(
                        f"action:{action_id}:failed:{action.state.value}"
                    ),
                    transition_type="escalated",
                    details={
                        "action_id": action_id,
                        "action_state": action.state.value,
                        "terminal_code": action.terminal_code or action.state.value,
                    },
                    state="escalated",
                    terminal_code=action.terminal_code or action.state.value,
                    resolved=False,
                    at=now.isoformat(),
                )
                demotion = self._ledger.active_demotion(
                    operation=action.operation, target=action.target
                )
                if demotion is not None:
                    self.store.record_incident_event(
                        incident["id"],
                        transition_key=f"action:{action_id}:demoted",
                        transition_type="demoted",
                        details={
                            "action_id": action_id,
                            "cause": demotion.cause,
                        },
                        state="demoted",
                        terminal_code=demotion.cause,
                        resolved=False,
                        at=now.isoformat(),
                    )
                continue
            transition = _ACTION_TRANSITIONS.get(action.state)
            if transition is not None:
                transition_type, state = transition
                self.store.record_incident_event(
                    incident["id"],
                    transition_key=(
                        f"action:{action_id}:{action.state.value}"
                    ),
                    transition_type=transition_type,
                    details={
                        "action_id": action_id,
                        "action_state": action.state.value,
                    },
                    state=state,
                    terminal_code=None,
                    resolved=False,
                    at=now.isoformat(),
                )

    def _record_blocked_action(
        self,
        incident: Mapping[str, Any],
        action_id: str,
        code: str,
        now: datetime,
    ) -> None:
        self.store.record_incident_event(
            incident["id"],
            transition_key=f"action:{action_id}:unavailable",
            transition_type="supervision_blocked",
            details={"action_id": action_id, "code": code},
            state="supervision_blocked",
            terminal_code=None,
            resolved=False,
            at=now.isoformat(),
        )

    def _deliver_pending(self) -> None:
        for pending in self.store.pending_deliveries():
            try:
                delivery = self.store.claim_delivery(
                    pending["id"], at=self._now().isoformat()
                )
            except SupervisionError as exc:
                if exc.code == "thread_unavailable":
                    break
                logger.warning(
                    "failed to claim incident delivery %s: %s",
                    pending["id"],
                    exc.code,
                )
                continue
            transition = self.store.get_transition(delivery["transition_id"])
            incident = self.store.get_incident(delivery["incident_id"])
            message = {
                "delivery": delivery,
                "incident": incident,
                "transition": transition,
                "schedule": self.store.get_schedule(incident["schedule_id"]),
            }
            try:
                post_id = self._deliver(message)
                self.store.finish_delivery(
                    delivery["id"],
                    delivered=True,
                    post_id=post_id,
                    at=self._now().isoformat(),
                )
            except Exception:
                logger.exception(
                    "failed to deliver supervision incident %s",
                    delivery["incident_id"],
                )
                self.store.finish_delivery(
                    delivery["id"],
                    delivered=False,
                    post_id=None,
                    at=self._now().isoformat(),
                )

    def _now(self) -> datetime:
        return self._aware(self._clock())

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SupervisionError(
                "clock_failure", "Supervision clock is unavailable"
            )
        return value.astimezone(timezone.utc)
