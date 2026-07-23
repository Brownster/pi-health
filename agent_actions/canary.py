"""Durable evidence gate for supervised R1 agent repairs."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from agent_actions.capability import (
    RESOURCE_RE,
    ActionActor,
    AuthorityMode,
    CapabilityError,
    CapabilityRegistry,
    RiskClass,
    TriggerType,
)
from agent_actions.ledger import ActionLedger, ActionLedgerError, ActionState


_RELEASE_COMMIT_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_LEDGER_PUBLIC_CODES = {
    "active_conflict",
    "already_revoked",
    "ineligible_source",
    "not_found",
    "store_failure",
    "unverified_source",
}


class CanaryGateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class CanaryGateService:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        ledger: ActionLedger,
        release_commit_provider: Callable[[], str],
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._registry = registry
        self._ledger = ledger
        self._release_commit_provider = release_commit_provider
        self._clock = clock
        self._id_factory = id_factory

    def attest(
        self,
        source_action_id: str,
        *,
        actor: Mapping[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        administrator = self._local_actor(actor)
        if (
            not isinstance(source_action_id, str)
            or not RESOURCE_RE.fullmatch(source_action_id)
        ):
            raise CanaryGateError("invalid_input", "Source action ID is invalid")
        try:
            existing = self._ledger.canary_for_source(source_action_id)
            if existing is not None:
                return existing.public_dict(), False
            action = self._ledger.get(source_action_id)
            if (
                action.state != ActionState.SUCCEEDED
                or action.terminal_code != "verified"
                or action.risk != RiskClass.REVERSIBLE.value
                or action.trigger != TriggerType.INTERACTIVE.value
                or action.authority_mode != AuthorityMode.APPROVAL.value
            ):
                raise CanaryGateError(
                    "ineligible_source", "Source action is not eligible for a canary"
                )
            capability = self._registry.require(action.operation)
            if (
                capability.version != action.capability_version
                or capability.risk.value != action.risk
            ):
                raise CanaryGateError(
                    "stale_capability", "Source action capability is no longer current"
                )
            if AuthorityMode.SUPERVISED not in capability.eligible_modes:
                raise CanaryGateError(
                    "ineligible_capability",
                    "Capability does not permit supervised authority",
                )
            if not RESOURCE_RE.fullmatch(action.target):
                raise CanaryGateError(
                    "ineligible_source", "Source action target is invalid"
                )

            release_commit = self._release_commit_provider()
            if (
                not isinstance(release_commit, str)
                or not _RELEASE_COMMIT_RE.fullmatch(release_commit)
            ):
                raise CanaryGateError(
                    "release_unavailable", "Deployed release identity is unavailable"
                )
            attestation_id = self._id_factory()
            if (
                not isinstance(attestation_id, str)
                or not RESOURCE_RE.fullmatch(attestation_id)
            ):
                raise CanaryGateError(
                    "gate_unavailable", "Canary gate identity is unavailable"
                )
            attested_at = self._clock().isoformat()
            record, created = self._ledger.attest_canary(
                attestation_id=attestation_id,
                source_action_id=source_action_id,
                operation=action.operation,
                target=action.target,
                capability_version=action.capability_version,
                risk=action.risk,
                release_commit=release_commit,
                attested_by_type=administrator.type,
                attested_by_id=administrator.id,
                attested_by_username=administrator.username,
                attested_at=attested_at,
            )
            return record.public_dict(), created
        except CanaryGateError:
            raise
        except CapabilityError as exc:
            raise CanaryGateError(
                "stale_capability", "Source action capability is no longer current"
            ) from exc
        except ActionLedgerError as exc:
            raise self._ledger_error(exc) from exc
        except Exception as exc:
            raise CanaryGateError(
                "gate_unavailable", "Canary gate is unavailable"
            ) from exc

    def revoke(
        self,
        attestation_id: str,
        *,
        actor: Mapping[str, Any],
    ) -> dict[str, Any]:
        administrator = self._local_actor(actor)
        if (
            not isinstance(attestation_id, str)
            or not RESOURCE_RE.fullmatch(attestation_id)
        ):
            raise CanaryGateError("invalid_input", "Canary attestation ID is invalid")
        try:
            record = self._ledger.revoke_canary(
                attestation_id,
                revoked_by_type=administrator.type,
                revoked_by_id=administrator.id,
                revoked_by_username=administrator.username,
                revoked_at=self._clock().isoformat(),
            )
            return record.public_dict()
        except ActionLedgerError as exc:
            raise self._ledger_error(exc) from exc
        except Exception as exc:
            raise CanaryGateError(
                "gate_unavailable", "Canary gate is unavailable"
            ) from exc

    def list(self, *, limit: int = 200) -> list[dict[str, Any]]:
        try:
            return [record.public_dict() for record in self._ledger.canaries(limit=limit)]
        except ActionLedgerError as exc:
            raise self._ledger_error(exc) from exc
        except Exception as exc:
            raise CanaryGateError(
                "gate_unavailable", "Canary gate is unavailable"
            ) from exc

    def snapshot(self, *, limit: int = 200) -> dict[str, Any]:
        canaries = self.list(limit=limit)
        eligible_count = 0
        for canary in canaries:
            status = "revoked"
            if canary["revoked_at"] is None:
                status = "stale"
                try:
                    capability = self._registry.require(canary["operation"])
                    if (
                        capability.version == canary["capability_version"]
                        and capability.risk.value == canary["risk"]
                        and AuthorityMode.SUPERVISED in capability.eligible_modes
                    ):
                        status = "eligible"
                        eligible_count += 1
                except CapabilityError:
                    pass
            canary["status"] = status
        return {
            "canaries": canaries,
            "gate": {
                "supervised": "canary_required",
                "autonomous": "unavailable",
                "eligible_count": eligible_count,
            },
        }

    def require_supervised(
        self,
        *,
        operation: str,
        target: str,
        trigger: TriggerType,
        mode: AuthorityMode,
    ) -> dict[str, Any]:
        if mode == AuthorityMode.AUTONOMOUS:
            raise CanaryGateError(
                "autonomous_unavailable", "Autonomous authority is unavailable"
            )
        if mode != AuthorityMode.SUPERVISED:
            raise CanaryGateError(
                "invalid_authority", "Canary gate requires supervised authority"
            )
        if trigger != TriggerType.SCHEDULED:
            raise CanaryGateError(
                "scheduled_only", "Supervised authority requires a scheduled trigger"
            )
        if not isinstance(target, str) or not RESOURCE_RE.fullmatch(target):
            raise CanaryGateError("invalid_target", "Canary target is invalid")
        try:
            capability = self._registry.require(operation)
            if (
                capability.risk != RiskClass.REVERSIBLE
                or AuthorityMode.SUPERVISED not in capability.eligible_modes
            ):
                raise CanaryGateError(
                    "ineligible_capability",
                    "Capability does not permit supervised authority",
                )
            record = self._ledger.active_canary(
                operation=operation,
                target=target,
                trigger=trigger.value,
                capability_version=capability.version,
            )
            if record is None or record.risk != capability.risk.value:
                raise CanaryGateError(
                    "canary_required",
                    "A current repair canary is required for supervised authority",
                )
            return record.public_dict()
        except CanaryGateError:
            raise
        except CapabilityError as exc:
            raise CanaryGateError(
                "unknown_capability", "Capability is not registered"
            ) from exc
        except ActionLedgerError as exc:
            raise self._ledger_error(exc) from exc
        except Exception as exc:
            raise CanaryGateError(
                "gate_unavailable", "Canary gate is unavailable"
            ) from exc

    @staticmethod
    def _local_actor(value: Mapping[str, Any]) -> ActionActor:
        try:
            actor = ActionActor.from_mapping(value)
        except (CapabilityError, TypeError) as exc:
            raise CanaryGateError(
                "denied_actor", "A local administrator is required"
            ) from exc
        if actor.type != "local":
            raise CanaryGateError(
                "denied_actor", "A local administrator is required"
            )
        return actor

    @staticmethod
    def _ledger_error(error: ActionLedgerError) -> CanaryGateError:
        code = error.code if error.code in _LEDGER_PUBLIC_CODES else "store_failure"
        messages = {
            "active_conflict": "An active canary already exists",
            "already_revoked": "Canary attestation is already revoked",
            "ineligible_source": "Source action is not eligible for a canary",
            "not_found": "Canary evidence was not found",
            "store_failure": "Canary evidence could not be persisted",
            "unverified_source": "Source action has no verification evidence",
        }
        return CanaryGateError(code, messages[code])
