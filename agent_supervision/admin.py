"""Administrator projections and commands for supervised repair state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_actions.capability import TriggerType
from agent_actions.defaults import read_agent_release_commit
from agent_actions.ledger import ActionLedger, ActionLedgerError
from agent_actions.policy import ActionPolicy, ActionPolicyError
from agent_supervision.authorization import maintenance_window
from agent_supervision.service import (
    MAX_ACTIONS_PER_TARGET_24H,
    MAX_ACTIONS_PER_WINDOW,
    SupervisionService,
    SupervisionStore,
)


class SupervisionAdminError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupervisionAdminService:
    """Compose private stores into bounded administrator-facing projections."""

    def __init__(
        self,
        *,
        supervision_path: str | Path,
        ledger_path: str | Path,
        policy_path: str | Path,
        release_commit_provider: Callable[[], str] = read_agent_release_commit,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.store = SupervisionStore(supervision_path)
        self._ledger = ActionLedger(ledger_path)
        self._policy_path = Path(policy_path)
        self._release_commit_provider = release_commit_provider
        self._clock = clock
        self._schedules = SupervisionService(
            store=self.store,
            clock=clock,
            id_factory=id_factory,
        )

    def create(self, values: Any, *, owner: Any) -> dict[str, Any]:
        if isinstance(values, Mapping) and values.get("enabled") is True:
            raise SupervisionAdminError(
                "confirmation_required",
                "Create the schedule disabled, then confirm enablement",
            )
        return self._schedule_projection(
            self._schedules.create(values, owner=owner)
        )

    def update(self, schedule_id: str, values: Any) -> dict[str, Any]:
        current = self._schedules.get(schedule_id)
        if (
            not current["enabled"]
            and isinstance(values, Mapping)
            and values.get("enabled") is True
        ):
            raise SupervisionAdminError(
                "confirmation_required",
                "Use the supervised repair enable confirmation",
            )
        return self._schedule_projection(
            self._schedules.update(schedule_id, values)
        )

    def enable(self, schedule_id: str, values: Any) -> dict[str, Any]:
        if not isinstance(values, Mapping) or set(values) != {
            "revision",
            "confirmation",
        }:
            raise SupervisionAdminError(
                "invalid_enablement", "Schedule enablement is invalid"
            )
        if values.get("confirmation") != "ENABLE SUPERVISION":
            raise SupervisionAdminError(
                "confirmation_required",
                "Confirm supervised repair enablement",
            )
        revision = values.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise SupervisionAdminError(
                "invalid_enablement", "Schedule revision is invalid"
            )
        current = self._schedules.get(schedule_id)
        if current["enabled"]:
            raise SupervisionAdminError(
                "already_enabled", "Schedule is already enabled"
            )
        updated = {
            field: current[field]
            for field in (
                "name",
                "enabled",
                "operation",
                "params",
                "service_priority",
                "window",
                "delivery",
            )
        }
        updated["enabled"] = True
        updated["revision"] = revision
        return self._schedule_projection(
            self._schedules.update(schedule_id, updated)
        )

    def get(self, schedule_id: str) -> dict[str, Any]:
        return self._schedule_projection(self._schedules.get(schedule_id))

    def list(self) -> dict[str, Any]:
        catalogue = self._schedules.list()
        return {
            **catalogue,
            "schedules": [
                self._schedule_projection(schedule)
                for schedule in catalogue["schedules"]
            ],
            "limits": {
                "max_actions_per_target_24h": MAX_ACTIONS_PER_TARGET_24H,
                "max_actions_per_window": MAX_ACTIONS_PER_WINDOW,
            },
        }

    def incidents(self, *, limit: int = 100) -> dict[str, Any]:
        self._limit(limit)
        incidents = self.store.list_incidents()[:limit]
        return {
            "incidents": [
                {
                    **incident,
                    "transitions": self.store.list_transitions(incident["id"]),
                }
                for incident in incidents
            ]
        }

    def incident(self, incident_id: str) -> dict[str, Any]:
        incident = self.store.get_incident(incident_id)
        schedule = self.store.get_schedule(incident["schedule_id"])
        action = self._action(incident.get("last_action_id"))
        return {
            "incident": {
                **incident,
                "schedule": schedule,
                "assessments": self.store.list_assessments(
                    schedule["id"], limit=20
                ),
                "transitions": self.store.list_transitions(incident_id),
                "last_action": action,
            }
        }

    def demotions(self, *, limit: int = 100) -> dict[str, Any]:
        self._limit(limit)
        try:
            return {
                "demotions": [
                    record.public_dict()
                    for record in self._ledger.demotions(limit=limit)
                ]
            }
        except ActionLedgerError as exc:
            raise self._error(exc) from exc

    def clear_demotion(
        self,
        demotion_id: str,
        values: Any,
        *,
        actor: Any,
    ) -> dict[str, Any]:
        if not isinstance(values, Mapping) or set(values) != {
            "revision",
            "recovery_action_id",
            "confirmation",
        }:
            raise SupervisionAdminError(
                "invalid_clearance", "Demotion clearance is invalid"
            )
        if values.get("confirmation") != "CLEAR DEMOTION":
            raise SupervisionAdminError(
                "confirmation_required",
                "Type CLEAR DEMOTION to confirm this authority change",
            )
        if (
            not isinstance(actor, Mapping)
            or set(actor) != {"type", "id", "username"}
            or actor.get("type") != "local"
        ):
            raise SupervisionAdminError(
                "denied_actor", "A local administrator is required"
            )
        now = self._now()
        try:
            record = self._ledger.clear_demotion(
                demotion_id,
                expected_revision=values.get("revision"),
                recovery_action_id=values.get("recovery_action_id"),
                release_commit=self._release_commit_provider(),
                cleared_by_type="local",
                cleared_by_id=actor.get("id"),
                cleared_by_username=actor.get("username"),
                cleared_at=now.isoformat(),
            )
            return record.public_dict()
        except ActionLedgerError as exc:
            raise self._error(exc) from exc
        except Exception as exc:
            raise SupervisionAdminError(
                "release_unavailable",
                "Deployed release identity is unavailable",
            ) from exc

    def _schedule_projection(
        self, schedule: Mapping[str, Any]
    ) -> dict[str, Any]:
        assessments = self.store.list_assessments(schedule["id"], limit=10)
        incidents = self.store.list_incidents(schedule_id=schedule["id"])
        incident = next(
            (
                candidate
                for candidate in incidents
                if candidate["resolved_at"] is None
            ),
            incidents[0] if incidents else None,
        )
        charges = self.store.list_budget_charges(schedule["id"], limit=10)
        now = self._now()
        current_window = maintenance_window(schedule, now)
        window_key = current_window["key"] if current_window else None
        window_used = sum(
            charge["window_key"] == window_key for charge in charges
        )
        last_charge = charges[0] if charges else None
        cooldown_until = (
            (
                datetime.fromisoformat(last_charge["charged_at"])
                + timedelta(hours=24)
            ).astimezone(timezone.utc).isoformat()
            if last_charge is not None
            else None
        )
        demotion = self._active_demotion(
            schedule["operation"], schedule["target"]
        )
        canary = self._canary(schedule)
        configured_authority = self._configured_authority(schedule)
        effective_authority = (
            "approval"
            if demotion is not None
            and configured_authority == "supervised"
            else configured_authority
        )
        return {
            **schedule,
            "status": {
                "assessments": assessments,
                "incident": incident,
                "last_action": self._action(
                    incident.get("last_action_id") if incident else None
                ),
                "canary": canary,
                "demotion": demotion,
                "configured_authority": configured_authority,
                "effective_authority": effective_authority,
                "maintenance_window": (
                    {
                        "key": current_window["key"],
                        "start": current_window["start"].isoformat(),
                        "deadline": current_window["deadline"].isoformat(),
                    }
                    if current_window
                    else None
                ),
                "budget": {
                    "rolling_24h": {
                        "used": sum(
                            datetime.fromisoformat(charge["charged_at"])
                            > now - timedelta(hours=24)
                            for charge in charges
                        ),
                        "limit": MAX_ACTIONS_PER_TARGET_24H,
                    },
                    "window": {
                        "used": window_used,
                        "limit": MAX_ACTIONS_PER_WINDOW,
                    },
                    "last_charge": last_charge,
                    "cooldown_until": cooldown_until,
                },
            },
        }

    def _canary(self, schedule: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            record = self._ledger.active_canary(
                operation=schedule["operation"],
                target=schedule["target"],
                trigger=TriggerType.SCHEDULED.value,
                capability_version=schedule["capability_version"],
            )
            if record is None:
                return None
            value = record.public_dict()
            try:
                value["status"] = (
                    "eligible"
                    if record.release_commit
                    == self._release_commit_provider()
                    else "stale"
                )
            except Exception:
                value["status"] = "unavailable"
            return value
        except ActionLedgerError as exc:
            raise self._error(exc) from exc

    def _active_demotion(
        self, operation: str, target: str
    ) -> dict[str, Any] | None:
        try:
            record = self._ledger.active_demotion(
                operation=operation, target=target
            )
            return record.public_dict() if record is not None else None
        except ActionLedgerError as exc:
            raise self._error(exc) from exc

    def _configured_authority(self, schedule: Mapping[str, Any]) -> str:
        try:
            policy = ActionPolicy.from_file(self._policy_path)
            return policy.mode_for(
                schedule["operation"],
                schedule["target"],
                TriggerType.SCHEDULED,
            ).value
        except ActionPolicyError as exc:
            raise SupervisionAdminError(exc.code, str(exc)) from exc

    def _action(self, action_id: str | None) -> dict[str, Any] | None:
        if action_id is None:
            return None
        try:
            action = self._ledger.get(action_id).public_dict()
            action["events"] = self._ledger.events(action_id)
            return action
        except ActionLedgerError as exc:
            raise self._error(exc) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise SupervisionAdminError(
                "clock_failure", "Supervision clock is unavailable"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _limit(limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise SupervisionAdminError(
                "invalid_limit", "Limit must be between 1 and 100"
            )

    @staticmethod
    def _error(exc: ActionLedgerError) -> SupervisionAdminError:
        return SupervisionAdminError(exc.code, str(exc))


class LazySupervisionAdminService:
    def __init__(self, factory: Callable[[], SupervisionAdminService]) -> None:
        self._factory = factory
        self._service: SupervisionAdminService | None = None

    def _get(self) -> SupervisionAdminService:
        if self._service is None:
            self._service = self._factory()
        return self._service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)
