# LimeOS AI Agents AA-005 Mattermost Bot and Listener

Date: 2026-07-12

Status: Complete against mocked gateway contracts (per the AA-000 decision); target
Mattermost settings change and live websocket verification remain deployment steps.

Predecessor: `Docs/LIMEOS_AI_AGENTS_AA000_BASELINE.md`

Dependencies: AA-003 agent gateway (mocked here through the frozen `TurnHandler`
contract); AA-004/AA-006 own installation, the agent identity, and secret-file placement.

## Outcome

AA-005 implements the Mattermost transport: bot bootstrap, the mention listener, thread
mapping, event deduplication, reconnect, and threaded reply delivery. The transport talks
to the gateway only through a frozen turn contract, so AA-003 can land underneath it
without listener changes.

- Explicit-mention triggering only; the bot never responds to its own posts; an optional
  channel allowlist restricts where it listens.
- One Mattermost root post maps to one persistent conversation id; duplicate websocket
  deliveries are dropped by a bounded, persisted dedup store. Both survive restart.
- Turns run strictly sequentially, satisfying the baseline limits of one concurrent turn
  globally and one per thread.
- Input is truncated to 32 KiB; replies are capped at 32 KiB and chunked below
  Mattermost's smallest common per-post limit.
- Turn failures post typed, non-secret messages in the originating thread; internal
  exception text never reaches Mattermost. Transport failures reconnect with capped
  backoff.
- A crash mid-turn cannot double-run a mention after restart (the event is marked seen
  before execution; losing one reply is safer than acting twice).

Bot bootstrap follows the AA-000 transport prerequisites: the administrator password is
write-only (one login, never persisted, never in the report); bot-account creation and
user access tokens are enabled through the config API; the `limeos` bot is created or
found and added only to the configured team and channel; its access token is created —
rotating and revoking a previously recorded token — and handed only to an injected secret
writer. The setup report is non-secret and safe to stream to the browser. The incoming
alert webhook stays owned by the Mattermost integration and is not reused as the bot
credential.

## Source Layout

| Path | Responsibility |
| --- | --- |
| `agent_transport/gateway_contract.py` | Frozen `TurnRequest`/`TurnResult`/`TurnHandler` + typed public errors and the 32 KiB turn limits |
| `agent_transport/events.py` | Websocket frame -> `MentionEvent` (mention detection, own-post and allowlist filtering) |
| `agent_transport/state.py` | Persisted, bounded event dedup and root-post -> conversation mapping |
| `agent_transport/bot_client.py` | Mattermost v4 API surface (admin bootstrap calls + bot posting), stdlib urllib with injected opener |
| `agent_transport/bot_setup.py` | AA-005 setup flow and threaded-delivery verification |
| `agent_transport/listener.py` | The run loop: frames -> dedup -> thread map -> gateway turn -> chunked threaded replies; reconnect with capped backoff |

The live websocket transport (`websocket_frames`) is a thin lazy-import adapter; the
`websocket-client` package is installed into the agent environment by the AA-004/AA-006
provisioning work, keeping the application's dependency set unchanged.

## Evidence

`tests/test_agent_transport.py` — 23 tests covering: mention parsing (strip, thread-root
fallback, own-post/allowlist/malformed-frame rejection), dedup and thread-map restart
persistence and bounding, the full bot bootstrap (config patch issued, existing-bot 400
path, token to the secret writer only, previous-token revocation, no secret or admin
password in the report), threaded-delivery verification, typed API errors, turn execution
and threaded reply, duplicate-frame suppression, stable conversation ids per thread,
typed public error posting, internal-error redaction, reply chunking, input truncation,
reconnect backoff, and the output ceiling.

Gates: full ruff (not just `E9,F`) clean on the package; transport suite 23 passed; full
unit suite green on the closing commit.

## Remaining for the target (tracked under AA-006/AA-009)

1. Run bot setup against Holly's Mattermost (its server currently has bot creation and
   user access tokens disabled — the bootstrap enables both) via the AA-006 API.
2. Install `websocket-client` into the `lime-agent` environment and run the listener as
   the sandboxed unit (AA-004 provisioning).
3. Live verification: websocket events received, threaded reply delivered, reconnect
   after a Mattermost restart, and dedup across a listener restart.
