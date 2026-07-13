# AI Agents Integration: Provider-Neutral Mattermost Assistant

Date: 2026-07-12  
Status: AA-000 complete; implementation contracts accepted
First provider: Claude Code CLI  
First transport: Mattermost

## Goal

Add a separate AI Agents integration to LimeOS. Users mention one provider-neutral
`@limeos` identity in Mattermost to request a read-only investigation. The gateway
invokes an authenticated Claude Code CLI process on demand and exposes only bounded,
redacted LimeOS operations.

The first release is mention-triggered and read-only. It does not run scheduled jobs,
change configuration, restart services, or provide arbitrary shell or filesystem
access.

## Current Baseline

The Mattermost integration is operational on the target Pi. It installs and manages:

- Postgres and Mattermost
- The `limeos` team and `limeos-alerts` channel
- Incoming-webhook alert delivery
- The native alert daemon, alert policy, and silences

This completes the chat and alert prerequisites described as B1/B2 in
`Docs/AGENT_INVESTIGATE_MVP.md` and LA-006 in
`Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`.

The backend service boundary and legacy UI removal are signed off. No `limeops` CLI,
agent gateway, provider adapter, or Mattermost mention listener exists yet.

## Product Decisions

1. Mattermost and AI Agents are separate top-level cards on the Integrations page.
2. Mattermost owns chat infrastructure, alert delivery, and alert policy.
3. AI Agents owns the bot, providers, conversations, permissions, limits, and audit.
4. Mattermost is a dependency of the first AI Agents transport, not part of the agent
   runtime.
5. Users interact with one provider-neutral `@limeos` bot.
6. Claude Code CLI is the first provider adapter because the initial deployment uses
   an existing subscription rather than metered API access.
7. Provider selection is configuration behind one gateway contract. Codex CLI,
   Anthropic API, OpenAI API, and local providers remain future adapters.
8. Alerts never invoke a model automatically. A user must mention `@limeos`.
9. The first release permits read-only investigation only.
10. Scheduled housekeeping, multiple agent profiles, approvals, and mutations are
    deferred.

## Integration Model

The Integrations page presents independent product capabilities:

### Mattermost

Owns installation, service health, channels, webhooks, alert policy, silences, and test
delivery. It remains useful when AI Agents is disabled or uninstalled.

### AI Agents

Depends on a healthy Mattermost connection for its first transport. It owns:

- Bot bootstrap and connection health
- Provider installation and authentication state
- The default provider and model settings
- Invocation, concurrency, and daily limits
- Conversation and thread state
- Read-only tool policy
- Usage and audit history
- Disable and repair controls

Provider connections appear as cards inside AI Agents. Claude is available first.
Codex and API providers can be added without creating new bots or authorization paths.

## Architecture

```text
Mattermost alert thread
        |
        | explicit @limeos mention
        v
Mattermost listener -----> agent gateway -----> Claude Code adapter
        |                       |                       |
        |                       |                       v
        |                       +-----------------> provider process
        |                                               |
        |                                               v
        +<---------------- bounded response <------- limeops
                                                        |
                                                        v
                                              policy and redaction
                                                        |
                                                        v
                                              LimeOS domain services
```

The Mattermost listener is a transport adapter. It cannot authorize operations. The
provider adapter translates gateway turns to Claude Code CLI invocations. It cannot
grant tools. `limeops` is the only route from a model to LimeOS state.

## Components

### `limeops` Read Boundary

Create a versioned command contract with JSON output, stable errors, bounded results,
explicit actor identity, and an audit ID. Initial operations are:

```text
limeops context
limeops system status
limeops container list
limeops container status <name>
limeops container logs <name> --lines <20..500>
limeops stack list
limeops stack status <name>
limeops stack inspect <name>
limeops service status <allowlisted-service>
limeops service logs <allowlisted-service> --lines <20..500>
limeops disk health
limeops mount status
limeops snapraid status
limeops network check <allowlisted-target>
limeops installation inventory
```

`stack inspect` and `installation inventory` expose structured, redacted views. They do
not give the model raw access to Compose directories, `/etc`, the source checkout, home
directories, or arbitrary paths.

### Agent Gateway

The gateway owns provider-neutral messages, thread mappings, locks, cancellation,
timeouts, usage records, tool-loop limits, and audit correlation. One Mattermost root
post maps to one conversation. Turns in one conversation are serialized. Provider-native
session files are disposable implementation details rather than the source of truth.

### Claude Code Adapter

The first adapter launches one headless Claude Code turn for an explicit mention. It
runs under a dedicated `lime-agent` service identity with a restricted home directory
for authentication and provider state.

The operating-system sandbox denies Docker, the privileged helper, source writes,
system configuration, secrets, and unrelated user data. Provider tool restrictions are
defence in depth; `limeops` enforces the server-side boundary.

### Mattermost Listener

The listener uses a least-privileged bot restricted to configured teams and channels.
It ignores its own posts, responds only to explicit mentions, deduplicates events by ID,
reconnects after failure, and posts the final answer in the originating thread.

The listener stores no Mattermost administrator password. Setup uses write-only admin
credentials to create or repair the bot and stores only the resulting bot secret.

## Runtime Data

Use the existing LimeOS runtime ownership contract:

| Path | Contents | Mode/owner |
| --- | --- | --- |
| `/etc/limeos/integrations/agents.json` | Non-secret settings and policy | Service-readable |
| `/etc/limeos/integrations/agents.env` | Mattermost bot secret and provider references | `0600` |
| `/var/lib/lime-agent/state/` | Thread mapping, deduplication, summaries, usage | `lime-agent` writable |
| `/var/log/limeos/agent-audit.jsonl` | Actor, provider, tools, policy, result, duration | Append-only service log |
| Dedicated agent home | Claude authentication and provider state | `lime-agent` only |

No API response, progress event, Mattermost message, provider prompt, or audit payload may
contain a token, password, webhook URL, private key, authorization header, or database
connection string.

## User Workflow

1. An administrator opens the AI Agents integration card.
2. LimeOS verifies that Mattermost is connected.
3. Setup installs the restricted agent service and creates the `@limeos` bot.
4. The administrator completes Claude Code authentication under the agent identity.
5. LimeOS runs a provider health check and a Mattermost mention test.
6. A user mentions `@limeos` in a normal or alert thread.
7. The listener records and deduplicates the event, then opens or resumes the thread
   conversation.
8. Claude receives canonical LimeOS context and may call only allowed `limeops` reads.
9. The gateway posts a bounded response in the same thread and records usage and audit
   events.

## Interface

The AI Agents card has these states: Not installed, Setup required, Authenticating,
Connected, Degraded, Disabled, and Disconnected.

The detail view contains:

- **Overview:** gateway, bot, provider, last successful turn, and repair controls
- **Providers:** Claude card with installation, authentication, health, and limits
- **Permissions:** visible read operations and denied capability groups
- **Usage:** turns, failures, duration, and provider-reported usage when available
- **Audit:** recent requests, actors, tools, policy decisions, and outcomes

The UI must never imply that choosing a provider changes permissions. Permission policy
belongs to the agent profile and gateway.

## Limits and Failure Handling

The first release enforces:

- Explicit-mention triggering
- One active turn per Mattermost thread
- A small global concurrency limit
- Per-turn timeout and tool-loop limit
- Input and output size limits
- A configurable daily invocation limit
- An immediate disable switch

Provider timeout, authentication expiry, malformed output, listener disconnect, duplicate
events, unavailable LimeOS services, and Mattermost delivery failure produce distinct,
non-secret errors. A failed turn cannot leave a background process running or mark an
operation successful. Restarting the gateway preserves thread mappings and event
deduplication.

## Work Packages

| ID | Package | Depends on | Parallel group | Deliverable |
| --- | --- | --- | --- | --- |
| AA-000 | Re-baseline and contracts | Mattermost live | Complete | Accepted in `Docs/LIMEOS_AI_AGENTS_AA000_BASELINE.md` |
| AA-001 | `limeops` envelope and policy | AA-000 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA001_LIMEOPS_CONTRACT.md` |
| AA-002 | Read-only diagnostic operations | AA-001 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA002_DIAGNOSTIC_OPERATIONS.md` |
| AA-003 | Gateway domain and persistence | AA-000 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA003_GATEWAY_DOMAIN.md` |
| AA-004 | Claude Code adapter and sandbox | AA-001, AA-003 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA004_CLAUDE_ADAPTER.md` |
| AA-005 | Mattermost bot and listener | AA-003 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA005_MATTERMOST_TRANSPORT.md` |
| AA-006 | AI Agents integration service/API | AA-003..AA-005 | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA006_INTEGRATION_API.md` |
| AA-007 | AI Agents frontend | AA-006 contract | Complete | Implemented in `Docs/LIMEOS_AI_AGENTS_AA007_FRONTEND.md` |
| AA-008 | Security and recovery suite | AA-001..AA-007 | Complete | Verified in `Docs/LIMEOS_AI_AGENTS_AA008_SECURITY_RECOVERY.md` |
| AA-009 | Target-Pi signoff | AA-008 | Release | Install, authenticate, mention, alert-thread investigation, disable, repair, and rollback evidence |

### Suggested Assignment

After AA-000 fixes the contracts, these streams can proceed independently:

- **Core stream:** AA-001 and AA-002
- **Gateway/provider stream:** AA-003 and AA-004
- **Transport stream:** AA-005, using mocked gateway contracts until AA-003 lands
- **Frontend stream:** AA-007, using fixtures after the AA-006 API contract is agreed
- **Verification stream:** prepare AA-008 fixtures and threat cases alongside implementation

AA-006 integrates the streams. AA-009 remains a single release signoff on Holly before any
second host deployment.

## Release Acceptance

The first release is complete when:

1. An administrator can install, authenticate, disable, and repair AI Agents without
   changing the Mattermost alert installation.
2. `@limeos` answers an explicit mention in the same Mattermost thread.
3. An alert thread can be investigated with bounded status and redacted logs.
4. Removing provider-side restrictions does not bypass the `limeops` policy.
5. The agent identity cannot read secrets, use Docker/helper sockets, write source or
   configuration, or execute arbitrary shell commands.
6. Duplicate events cannot duplicate turns or replies.
7. Provider, gateway, listener, and host restarts preserve a coherent conversation.
8. Every request records the Mattermost actor, provider, tool calls, policy results,
   duration, outcome, and correlation ID.
9. Full backend, frontend, browser, security, and target-Pi tests pass.

## Deferred Work

- Codex CLI, Anthropic API, OpenAI API, and local provider adapters
- Scheduled and out-of-hours housekeeping jobs
- Multiple agent profiles or visible bot identities
- Automatic provider failover
- API cost projection and billing controls
- Media additions, container restarts, and approval workflows
- Autonomous remediation
- General file browsing, file writes, shell, Compose lifecycle, updates, mounts, storage
  mutation, and SnapRAID write operations
- A native LimeOS chat screen

Scheduled housekeeping is the preferred next increment after the read-only release. It
will reuse the same gateway and permissions, run only configured read operations, and post
reports to a selected Mattermost channel.

## Relationship to Earlier Plans

This design replaces the temporary provider lock in `Docs/AGENT_INVESTIGATE_MVP.md` with
the provider-neutral gateway from `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`, while retaining
Claude Code as the first adapter. It implements the read-only subset of LA-001 through
LA-004, LA-007, LA-008, and LA-009.

It also supersedes the reserved AI-agent tab in
`docs/plans/2026-07-10-mattermost-integrations-design.md`. AI Agents now has a separate
top-level integration card. Mattermost remains its first transport dependency.
