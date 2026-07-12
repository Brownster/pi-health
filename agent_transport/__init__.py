"""AA-005 Mattermost transport: bot bootstrap, mention listener, thread mapping.

The transport stream from `docs/plans/2026-07-12-ai-agents-integration-design.md`. It talks
to the agent gateway only through the frozen contract in `gateway_contract` (mocked until
AA-003 lands) and never touches Docker, the helper, or provider credentials itself.
"""

from agent_transport.gateway_contract import TurnHandler, TurnRequest, TurnResult

__all__ = ["TurnHandler", "TurnRequest", "TurnResult"]
