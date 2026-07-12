# LimeOS AI Agents AA-006 Integration Service and API

Date: 2026-07-12

Status: Complete

Predecessors: AA-002 diagnostic operations, AA-003 gateway, AA-004 Claude adapter and
sandbox, and AA-005 Mattermost transport

Successors: AA-007 frontend, AA-008 security and recovery suite, and AA-009 target
signoff

## Outcome

AA-006 joins the completed agent components behind one framework-neutral integration
service and an authenticated Flask API. The browser process orchestrates fixed helper
operations. It never reads provider credentials, the Mattermost bot token, agent state,
or the LimeOps audit file directly.

The slice includes:

- Typed public integration states for the AA-007 card and detail views
- Owner-bound streamed install, repair, and Claude authentication operations
- Mattermost bot bootstrap and token rotation through the AA-005 contract
- Per-host container and stack allowlists applied to the AA-001 policy
- Provider, permissions, usage, and audit read endpoints
- Immediate disable, repair, and threaded-delivery test actions
- Fixed helper calls for settings, secrets, health, service control, usage, and audit
- Ephemeral authorization URL replay that is redacted when authentication ends
- Bounded helper timeouts, JSONL reads, query limits, and public errors

## Public States

`GET /api/integrations/agents` returns one lowercase state:

| State | Meaning |
| --- | --- |
| `not_installed` | The agent runtime has not been provisioned |
| `setup_required` | Mattermost, configuration, a compatible provider, or provider authentication is missing |
| `authenticating` | A guided Claude login is active |
| `connected` | Mattermost, LimeOps, Claude, and the gateway are healthy |
| `degraded` | A required component is starting or failed while configuration remains present |
| `disabled` | The administrator disabled the agent service |
| `disconnected` | A configured runtime cannot reach Mattermost or its owned services |

The response includes non-secret Mattermost, gateway, broker, and provider summaries plus
the last successful turn when available. It never returns credential paths, token IDs,
tokens, passwords, provider output, environment values, or raw helper errors.

## Route Contract

Every route requires an authenticated LimeOS session. Every mutation requires CSRF.

```text
GET  /api/integrations/agents
POST /api/integrations/agents/install
GET  /api/integrations/agents/operations/<operation-id>/stream
POST /api/integrations/agents/disable
POST /api/integrations/agents/repair
GET  /api/integrations/agents/providers
POST /api/integrations/agents/providers/claude/auth
POST /api/integrations/agents/test
GET  /api/integrations/agents/permissions
GET  /api/integrations/agents/usage?limit=50
GET  /api/integrations/agents/audit?limit=50
```

Usage and audit limits accept integers from 1 through 200. Records are newest-tail
results returned in chronological order. The helper reads at most 512 KiB from a JSONL
file and caps the encoded public records below the helper frame limit.

## Install and Repair

Install accepts exactly:

```json
{
  "admin_username": "admin",
  "admin_password": "write-only-value",
  "limits": {
    "turn_timeout_seconds": 300,
    "tool_rounds_per_turn": 6,
    "invocations_per_day": 20
  }
}
```

`limits` is optional. Unknown fields fail before the background operation starts. The
Mattermost administrator password remains only in the operation closure and is never
included in events or retained operation state.

Install performs these fixed steps:

1. Require the existing Mattermost integration to be connected or degraded.
2. Install Claude Code from the signed stable repository.
3. Provision the isolated runtime and hardened units.
4. Resolve the configured Mattermost team and channel.
5. Create or repair `@limeos`, rotate its token, and store the new token through the
   fixed helper destination.
6. Generate exact container and stack resource allowlists from the current host.
7. Validate and write the runtime settings and read-only LimeOps policy.
8. Start the service when Claude is already authenticated. Otherwise return
   `requires_auth: true` and leave the agent stopped.

Repair with administrator credentials repeats the full setup and bot repair. Repair
with `{}` reinstalls the signed provider and isolated runtime, preserves settings,
secrets, conversations, usage, provider state, Mattermost, Postgres, and alerts, then
starts the service only when configuration and authentication pass.

Provider and runtime setup use `helper_call(..., timeout=1200)`. Other helper calls keep
the ordinary 30-second deadline.

## Guided Claude Authentication

Start authentication with:

```json
{"action": "start"}
```

The route returns an owner-bound operation and SSE URL. Stream events can contain the
fixed provider operation ID, a filtered HTTPS authorization URL, a request for the
authorization response, public status text, and one terminal result.

Submit the response with:

```json
{
  "action": "submit",
  "operation_id": "provider-operation-id",
  "code": "authorization-response"
}
```

Cancel with:

```json
{"action": "cancel", "operation_id": "provider-operation-id"}
```

The service independently accepts authorization URLs only when they use HTTPS and the
host is `claude.ai` or `console.anthropic.com`. The SSE registry strips its internal
ephemeral marker from live output. When the operation ends, it replaces retained URLs
with `{"expired": true}` while preserving event IDs. Completed operation replay cannot
recover the URL.

After successful authentication, the operation starts `limeos-agent.service`. A start
failure becomes a bounded terminal error and cannot be reported as success.

## Permissions

`GET /api/integrations/agents/permissions` exposes one provider-neutral `read_only`
profile. It lists enabled LimeOps operations, exact configured resources, and explicit
denied capability groups. Provider selection does not change permissions.

The integration service accepts resource names matching the existing bounded identifier
contract. Invalid Docker or stack names are omitted. The helper validates the full
policy again and requires its operation set to match the checked-in default profile.

## Helper Boundary

AA-006 adds these fixed helper operations:

| Command | Purpose |
| --- | --- |
| `agent_bot_secret_write` | Atomically replace only the Mattermost bot-token file |
| `agent_configure` | Validate and write only the fixed settings and policy paths |
| `agent_runtime_start` | Require valid configuration and Claude authentication, then start the owned unit |
| `agent_usage_read` | Return bounded allowlisted usage counters and records |
| `agent_audit_read` | Return bounded allowlisted LimeOps audit fields |
| `agent_delivery_test` | Post a root message and threaded reply with the stored bot identity |

`agent_runtime_status` now checks the minimum Claude version, runs `claude auth status`
under `lime-agent` with an empty environment, validates stored settings, and returns only
non-secret booleans, IDs, versions, and unit states.

Disable updates the non-secret enabled flag and disables only `limeos-agent.service`.
It leaves Mattermost, Postgres, alerts, provider state, conversations, usage, and audit
records intact.

## AA-007 Handoff

AA-007 can build the separate AI Agents card and its Overview, Providers, Permissions,
Usage, and Audit views directly from these routes. It should:

1. Treat the public state as authoritative for card actions and banners.
2. Use the existing operation-stream client for install, repair, and auth start.
3. Show the authorization URL only while the auth operation is active.
4. Submit or cancel authentication through the same Claude auth route.
5. Never cache the authorization URL in browser storage.
6. Present permissions as provider-neutral and read-only.
7. Keep Mattermost alert controls on the existing Mattermost card.

## Verification

Focused coverage proves state derivation, secret-free setup events, Mattermost
prerequisites, signed install and repair sequencing, bot bootstrap and rotation,
resource-policy generation, guided auth filtering and submission, URL replay redaction,
disable and delivery testing, bounded usage and audit reads, route authentication, CSRF,
stream ownership, strict payloads, and public error mapping.

The full backend suite passes. AA-009 still owns target-side helper regeneration,
systemd verification, real Claude login, Mattermost mention, alert-thread investigation,
disable, repair, and rollback evidence on Holly.
