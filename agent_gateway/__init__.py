"""AA-003 agent gateway: provider-neutral turn orchestration and persistence.

Implements the frozen `agent_transport.gateway_contract.TurnHandler` boundary for the
Mattermost listener (AA-005) and defines the frozen provider contract that the Claude
Code adapter (AA-004) implements. Tool execution is restricted to `limeops` operations
through an injected executor — the gateway never touches Docker, the helper, or
provider credentials itself.
"""

from agent_gateway.gateway import AgentGateway, GatewayConfig
from agent_gateway.provider import FinalAnswer, Provider, ProviderContext, ToolCall

__all__ = [
    "AgentGateway",
    "GatewayConfig",
    "FinalAnswer",
    "Provider",
    "ProviderContext",
    "ToolCall",
]
