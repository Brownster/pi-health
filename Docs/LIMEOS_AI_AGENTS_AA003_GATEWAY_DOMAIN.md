# LimeOS AI Agents AA-003 Gateway Domain and Persistence

Date: 2026-07-12

Status: Complete

Predecessor: `Docs/LIMEOS_AI_AGENTS_AA000_BASELINE.md`

Successors: AA-004 Claude Code adapter (implements the provider contract frozen here);
AA-006 integration API (consumes usage totals, records, and the disable switch).

## Outcome

AA-003 implements the provider-neutral gateway: it fulfils the frozen AA-005
`TurnHandler` contract on one side and freezes the provider contract that AA-004
implements on the other. The AA-005 listener now has a real gateway underneath it with
no listener changes, exactly as the baseline's mocked-contract plan intended.

- **Provider contract** (`agent_gateway/provider.py`): one invocation receives the
  canonical non-secret context plus bounded conversation messages and returns either a
  `FinalAnswer` or exactly one typed `ToolCall` — the baseline's structured-turn shape.
  Typed provider errors (timeout, authentication, malformed, unavailable) never carry
  credential material.
- **Tool loop**: the gateway validates each `ToolCall` (operation name pattern plus a
  read-only allowlist mirroring the AA-001 default policy) and executes it through an
  injected `limeops` executor with the broker's frozen actor shape
  (`{type: mattermost, id, username}`); the per-turn correlation id and the broker
  `audit_id` returned by each tool call are recorded together in the usage ledger, so
  AA-006 can join gateway turns to broker audit records. The bounded envelope summary
  (16 KiB cap) is appended to the conversation and the provider is invoked again, up to
  6 rounds. *(Corrected during AA-002 integration: the original actor shape carried
  `kind`/`correlation_id` fields the broker rejects.)* Disallowed operations are refused without
  reaching the broker; broker failures become bounded tool results, never prompt-visible
  internals. The broker's policy remains authoritative — the gateway allowlist is
  defence in depth.
- **Limits** (baseline table): 1 concurrent turn globally and per conversation
  (non-blocking locks -> `TurnBusyError`), 300-second wall-clock turn deadline enforced
  across rounds, 6 tool rounds per turn, a configurable 20-invocation daily cap checked
  before every provider call (`TurnLimitError`), and the 32 KiB output ceiling applied to
  final answers.
- **Persistence**: a bounded provider-neutral conversation store (one atomic JSON file
  per conversation; provider-native session files stay disposable) and a usage ledger
  that records user turns and provider invocations separately, with UTC-midnight daily
  rollover and JSONL turn records for the AA-006 usage/audit views. Both survive restart.
- **Failure contract**: every failure maps to a typed AA-005 `TurnError` safe to post
  in-thread; a failed turn is always recorded as failed and can never be reported
  successful; the immediate disable switch fails new turns fast and aborts a running
  turn between rounds.

## Source Layout

| Path | Responsibility |
| --- | --- |
| `agent_gateway/provider.py` | Frozen provider contract: context, `FinalAnswer`/`ToolCall`, typed errors |
| `agent_gateway/conversation.py` | Bounded, atomic, provider-neutral conversation persistence |
| `agent_gateway/usage.py` | Turn and invocation counters, daily rollover, JSONL turn records |
| `agent_gateway/gateway.py` | `TurnHandler` implementation: locks, tool loop, limits, disable switch, error mapping, `limeops_client_executor` adapter |

Wiring on the target: `AgentGateway(state_dir=/var/lib/limeos/integrations/agents,
provider=<AA-004 adapter>, limeops_executor=limeops_client_executor(LimeOpsClient()))`
handed to the AA-005 `MentionListener` as its gateway.

## Evidence

`tests/test_agent_gateway.py` — 16 tests: conversation bounding/persistence and id
validation; invocation counting, daily rollover, and restart persistence; final-answer
turns with context and usage assertions; the tool loop feeding bounded broker results
back to the provider with actor + correlation id; disallowed-operation refusal without
broker contact; broker failure as a bounded, redacted tool result; round exhaustion;
the daily cap; the cross-round deadline; provider-error mapping; failed-turn recording;
the disable switch (fail-fast and between-rounds abort, then re-enable); global busy
under a concurrent turn; and the output ceiling.

Gates: full ruff clean on the package; gateway + transport suites 39 passed; full unit
suite green on the closing commit.

## Deferred within AA-003 scope

- Conversation summarization (the store bounds raw history instead; a summarizer slots
  into `ConversationStore` without contract changes).
- The canonical context document itself (`context_provider` is injected; AA-002's
  `context` operation and the AA-003 wiring on the target supply the real content).
