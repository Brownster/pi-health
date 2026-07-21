"""Operation registry for the separately permissioned action broker."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from agent_actions.actuator import ActionActuator
from limeops.broker import OperationDefinition


_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _execute_params(params: Mapping[str, Any]) -> Mapping[str, Any]:
    if set(params) != {"action_id"}:
        raise ValueError("Action execution accepts only an action ID")
    action_id = params.get("action_id")
    if not isinstance(action_id, str) or not _ACTION_ID_RE.fullmatch(action_id):
        raise ValueError("Action ID is invalid")
    return {"action_id": action_id}


def build_actuator_operations(
    actuator: ActionActuator,
) -> dict[str, OperationDefinition]:
    return {
        "action.execute": OperationDefinition(
            validate_params=_execute_params,
            handler=lambda params, context: actuator.execute(
                params["action_id"], audit_id=context.audit_id
            ),
        )
    }
