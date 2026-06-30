# LimeOS Agent Automation and Mattermost MVP Sprint

Date: 2026-06-28  
Status: Deferred - do not start until every entry gate passes  
Planning estimate: 12-15 engineering days  
First usable release: Mattermost maintenance assistant

## Objective

Build a provider-neutral LimeOS operations layer that Claude Code and Codex can use from the CLI,
then ship the first user-facing assistant through Mattermost. The assistant diagnoses LimeOS,
searches the media catalog automatically, and performs a small set of approved actions through a
typed policy boundary.

The sprint must not depend on Flask, legacy UI routes, raw shell access, direct Docker socket
access, or provider-specific tool formats.

## Entry Gates

All gates require recorded evidence before `LA-001` starts.

1. Security hardening is complete and signed off, including the remaining configuration/state
   relocation and privileged-helper boundary work.
2. The v1 UI is removed, and the framework-neutral service boundary is signed off. Flask may
   remain as the human UI transport, but agent and CLI paths must not depend on Flask state.
3. The replacement LimeOS backend and v2 API contracts are stable and documented.
4. Authentication, CSRF, operation ownership, audit identity, and secret storage have production
   contracts that the agent gateway can reuse.
5. The privileged helper accepts typed parameters and contains its own templates; it does not
   accept arbitrary executable content.
6. Full backend, frontend, and end-to-end suites pass after legacy removal.
7. Mattermost bot deployment, provider authentication, and usage/cost constraints are decided.

If an entry gate changes the expected backend boundary, re-estimate this sprint before work starts.

## Product Decisions

1. `limeops` is the stable tool contract. Agents never receive raw shell, Docker socket, helper
   socket, or media-service credentials.
2. Claude Code and Codex are interchangeable clients, not sources of authorization policy.
3. `Docs/LIMEOS_AGENT_CONTEXT.md` is the canonical agent context. `CLAUDE.md` and `AGENTS.md` are
   thin adapters that direct each client to the same context and commands.
4. MCP is deferred. A future MCP server may wrap `limeops` without changing policy or operations.
5. LimeOS owns alert detection. Uptime Kuma is not required for the first release.
6. Alerts do not invoke a model automatically. They create Mattermost incidents that a user can
   ask the assistant to diagnose.
7. Diagnostics and media searches run automatically. Adding media and restarting an allowlisted
   container require explicit approval.
8. Compose lifecycle changes, image pulls, storage mutation, SnapRAID write operations, system
   updates, and configuration edits remain blocked.
9. A future LimeOS chat screen will use the same gateway as Mattermost.

## Architecture

```text
Claude Code ----\
                 +--> limeops --> policy --> LimeOS service/helper
Codex CLI -------/

LimeOS alertd --> Mattermost webhook --> incident thread
                                           |
                                           v
                                LimeOS agent gateway
                              /          |          \
                     Claude adapter  Codex adapter  approvals/audit
                              \          |          /
                                       limeops

Future LimeOS chat UI ------------------> agent gateway
```

The CLI foundation is an internal milestone. Mattermost integration is the release boundary.

## Permission Model

| Operation | Initial policy | Approval |
|---|---|---|
| Read system/container/stack status | Allow | None |
| Read bounded, redacted logs | Allow | None |
| Read disk, mount, SMART, and SnapRAID status | Allow | None |
| Run bounded connectivity diagnostics | Allow | None |
| Search movies and series | Allow | None |
| Add a selected movie or series | Allow with confirmation | Single-use approval |
| Restart an allowlisted container | Allow with confirmation | Single-use approval |
| Compose `pull`, `up`, `down`, or stack delete | Deny | No override in MVP |
| SnapRAID `sync`, `scrub`, `check`, or `fix` | Deny | No override in MVP |
| Mount, unmount, format, partition, or power control | Deny | No override in MVP |
| Edit configuration, source, or system files | Deny | No override in MVP |
| Run arbitrary shell or API requests | Deny | No override in MVP |

Approvals expire, bind to one actor and operation payload, and cannot be replayed. A changed payload
requires a new approval.

## Delivery Plan

| Order | Ticket | Depends on | Estimate | Release critical |
|---|---|---|---:|---|
| 0 | LA-000 Entry-gate signoff and backend re-baseline | Legacy removal | 0.5 day | Yes |
| 1 | LA-001 `limeops` command and JSON contract | LA-000 | 1.0 day | Yes |
| 2 | LA-002 Agent identity, policy, and execution boundary | LA-001 | 1.5 days | Yes |
| 3 | LA-003 Canonical agent context and provider adapters | LA-001 | 0.5 day | Yes |
| 4 | LA-004 Diagnostic operations | LA-002 | 2.0 days | Yes |
| 5 | LA-005 Media search and approved add operations | LA-002 | 1.5 days | Yes |
| 6 | LA-006 Native alert evaluator and Mattermost notifications | LA-000 | 1.5 days | Yes |
| 7 | LA-007 Provider-neutral agent gateway | LA-003, LA-004 | 2.0 days | Yes |
| 8 | LA-008 Mattermost threaded bot and approval workflow | LA-005, LA-006, LA-007 | 2.0 days | Yes |
| 9 | LA-009 Security, failure, and recovery test suite | LA-002..LA-008 | 1.5 days | Yes |
| 10 | LA-010 Mattermost MVP release signoff | LA-009 | 0.5 day | Yes |

## LA-000 - Entry-Gate Signoff and Backend Re-Baseline

### Tasks

1. Record the security-hardening and legacy-removal signoff commits.
2. Inventory the final backend modules, service boundaries, API routes, authentication flow,
   privileged operations, state directories, and deployment units.
3. Identify which operations `limeops` can call through an unprivileged API and which require the
   typed helper.
4. Confirm Mattermost connectivity and the supported provider authentication method.
5. Replace provisional file references in this document with final paths.

### Acceptance Criteria

1. No production or test dependency imports Flask or serves v1 assets/routes.
2. Every entry gate has linked evidence.
3. The sprint estimate is accepted against the final architecture.

## LA-001 - `limeops` Contract

### Tasks

1. Create one executable entry point with structured subcommands and `--json` output.
2. Define a versioned response envelope:

   ```json
   {
     "schema_version": "1",
     "request_id": "...",
     "ok": true,
     "operation": "container.logs",
     "data": {},
     "warnings": [],
     "error": null,
     "audit_id": "..."
   }
   ```

3. Define stable exit codes for success, invalid input, denied action, unavailable dependency,
   timeout, and upstream failure.
4. Keep machine output on stdout and bounded diagnostic output on stderr.
5. Publish command help and examples without credentials or deployment secrets.

### Acceptance Criteria

1. Claude Code and Codex can invoke the same commands and parse the same responses.
2. Invalid parameters never reach LimeOS services or the helper.
3. Contract tests lock the JSON schema and exit-code behavior.

## LA-002 - Agent Identity, Policy, and Execution Boundary

### Tasks

1. Create a dedicated `lime-agent` service identity with no Docker-group membership.
2. Deny direct access to the Docker socket, privileged-helper socket, secrets, mount contents,
   stack files, system configuration, and source writes.
3. Store a root-owned agent policy containing operation, resource, and argument allowlists.
4. Route privileged requests through typed LimeOS operations that revalidate policy server-side.
5. Add bounded timeouts, output limits, concurrency limits, rate limits, and secret redaction.
6. Write immutable audit events for request, actor, provider, policy decision, approval, result,
   duration, and correlation ID.

### Acceptance Criteria

1. Compromising either model client does not grant shell, Docker, helper, or filesystem authority.
2. Shell metacharacters, path traversal, symlinks, oversized input, and unknown resources fail
   before execution.
3. Client-side instructions and hooks are defence in depth; removing them does not bypass policy.

## LA-003 - Canonical Context and Provider Adapters

### Tasks

1. Add `Docs/LIMEOS_AGENT_CONTEXT.md` with architecture, ownership, storage invariants, runbooks,
   terminology, forbidden actions, and escalation rules.
2. Add a small `CLAUDE.md` adapter for Claude Code.
3. Add a small `AGENTS.md` adapter for Codex.
4. Add `limeops context --json` for current, non-secret inventory and capability discovery.
5. Test the context for stale paths, secret patterns, and contradictory instructions.

### Acceptance Criteria

1. Both clients receive equivalent stable guidance and current inventory.
2. Context files contain no tokens, passwords, private keys, webhook URLs, or API keys.
3. Authorization remains correct when context files are missing or maliciously changed.

## LA-004 - Diagnostic Operations

### Initial Commands

```text
limeops context
limeops system status
limeops container list
limeops container status <name>
limeops container logs <name> --lines <20..500>
limeops stack status <name>
limeops service status <allowlisted-service>
limeops service logs <allowlisted-service> --lines <20..500>
limeops disk health
limeops mount status
limeops snapraid status
limeops snapraid diff
limeops network check <allowlisted-target>
```

### Tasks

1. Reuse LimeOS domain services rather than parsing human UI output.
2. Enforce resource allowlists and bounded output at the service boundary.
3. Redact credentials, authorization headers, environment secrets, and sensitive query values.
4. Return partial results with scoped warnings when one subsystem is unavailable.

### Acceptance Criteria

1. Read operations cannot mutate host state.
2. Logs remain useful after redaction and truncation.
3. Disk or mount failure does not prevent unrelated diagnostics from returning.

## LA-005 - Media Search and Approved Add Operations

### Initial Commands

```text
limeops media search movie <query>
limeops media search series <query>
limeops media add movie <provider-id> --approval <token>
limeops media add series <provider-id> --approval <token>
limeops container restart <allowlisted-name> --approval <token>
```

### Tasks

1. Keep Sonarr, Radarr, and related API credentials inside LimeOS credential storage.
2. Normalize search results into stable IDs, title, year, media type, availability, and duplicate
   state.
3. Require the user to select one exact result before approval.
4. Bind each approval to the normalized operation payload and actor.
5. Make retries idempotent so gateway reconnects cannot add media or restart twice.

### Acceptance Criteria

1. Ambiguous searches cannot add media.
2. Existing library items return a non-destructive duplicate result.
3. Expired, replayed, wrong-user, or modified approvals fail closed.

## LA-006 - Native Alert Evaluator

### Initial Signals

1. Container stopped, restarting, unhealthy, or health check repeatedly failing.
2. Configured connectivity check repeatedly failing.
3. Required mount missing or source identity changed.
4. SMART status degraded or failed.
5. SnapRAID scheduled operation failed or safety preflight blocked it.
6. LimeOS service recovered after restart.

### Tasks

> Mattermost webhook/incident posting may follow the transport patterns referenced in
> Prior Art and References.

1. Run alert evaluation outside the main API process so an API crash can still produce a service
   failure notification.
2. Require consecutive failures, deduplicate active incidents, apply cooldowns, and emit recovery
   notifications.
3. Persist alert state across process and host restarts.
4. Post structured incidents through a secret-managed Mattermost webhook.
5. Keep model invocation out of the alert path.

### Acceptance Criteria

1. One continuing fault creates one incident and one recovery event, not repeated noise.
2. A reboot does not reopen resolved incidents or lose active incident state.
3. A complete host, power, router, or Internet outage is documented as undetectable from the same
   machine; external monitoring remains separate future scope.

## LA-007 - Provider-Neutral Agent Gateway

### Tasks

1. Define a provider interface for conversation input, streamed text, tool requests, tool results,
   cancellation, usage, and errors.
2. Implement Claude and Codex/OpenAI adapters behind that interface.
3. Store provider-neutral conversation messages, summaries, tool events, approvals, and audit IDs.
4. Treat provider-native session state as disposable. Switching provider starts from the canonical
   context, a bounded conversation summary, and recent structured events.
5. Restrict gateway tool execution to `limeops` operations.

### Acceptance Criteria

1. Provider selection is configuration, not a code fork.
2. Switching provider preserves understandable conversation context without claiming native session
   compatibility.
3. Provider outage, timeout, malformed tool request, or cancellation cannot leave an action pending
   or execute it twice.

## LA-008 - Mattermost Threaded Bot and Approvals

### Tasks

> Base the Mattermost transport (thread mapping, event dedup, reconnect, bot-account setup,
> reaction approve/reject UX) on the patterns in Prior Art and References. Approval semantics and
> tool restriction are enforced in the gateway/`limeops`, never in the client.

1. Use a least-privileged bot account restricted to approved teams and channels.
2. Map each Mattermost root post to one gateway conversation.
3. Respond to explicit mentions or commands and ignore the bot's own posts.
4. Deduplicate Mattermost events by post/event ID and survive gateway restarts.
5. Support diagnostic requests inside alert threads.
6. Render action proposals with exact target, impact, expiry, and approve/reject controls.
7. Restrict approvals to configured Mattermost users and record the approver identity.
8. Return clear partial-failure and provider-unavailable responses without exposing internals.

### Acceptance Criteria

1. Users can diagnose a LimeOS alert in its original thread.
2. Automatic diagnostics and searches require no approval.
3. Media additions and allowlisted restarts require a valid single-use approval.
4. Duplicate webhook or websocket delivery cannot duplicate replies or actions.
5. Unapproved operations remain impossible even if a user or log contains prompt-injection text.

## LA-009 - Security, Failure, and Recovery Suite

### Required Coverage

1. Command and path injection, shell operators, traversal, symlink escape, and malformed JSON.
2. Direct Docker/helper/socket access attempts from the agent identity.
3. Secrets embedded in logs, errors, environment values, URLs, and upstream API responses.
4. Prompt injection in Mattermost posts, alert text, media metadata, and logs.
5. Approval expiry, actor mismatch, payload change, replay, concurrent approval, and cancellation.
6. Provider timeout, rate limit, malformed response, tool-loop limit, and mid-stream disconnect.
7. Mattermost duplicate delivery, reconnect, token rotation, and unavailable server.
8. Gateway, alert evaluator, and host restart recovery.
9. Container, storage, media API, and connectivity failure simulations.
10. Claude and Codex contract parity against the same operation fixtures.

### Acceptance Criteria

1. Every denied operation has a deterministic policy reason and audit event.
2. No failure path executes a mutating operation more than once.
3. Full project tests and the new security/integration suites pass from a clean environment.

## LA-010 - Mattermost MVP Release Signoff

### Signoff Checklist

1. Entry-gate evidence remains valid against the release commit.
2. Claude and Codex both complete the supported diagnostic and media-search scenarios.
3. Approval tests pass for media additions and allowlisted container restarts.
4. Blocked-operation tests pass for Compose, storage, SnapRAID writes, configuration, shell, and
   filesystem mutation.
5. Alert deduplication, recovery, restart, and Mattermost thread workflows pass.
6. Audit records identify the Mattermost actor, provider, request, approval, operation, and result.
7. Deployment, rollback, token rotation, incident response, and disable-switch procedures are
   documented and exercised.

Release decision: `GO` only when every item has evidence.

## Demonstration Scenarios

1. Stop an allowlisted test container. LimeOS posts one Mattermost incident. In the thread, ask the
   assistant to diagnose it; the reply includes bounded status and logs.
2. Ask for a movie with an ambiguous title. The assistant returns selectable results and adds
   nothing until one result is selected and approved.
3. Approve one media addition, resend the approval event, and verify only one library item exists.
4. Request a Plex restart. The assistant shows target and impact, then executes only after an
   authorized user approves.
5. Request `docker compose down`, SnapRAID sync, mount removal, source editing, and arbitrary shell.
   Every request is denied and audited.
6. Place hostile instructions in a container log and Mattermost message. The assistant may quote or
   explain them but cannot expand its capabilities.
7. Restart the gateway during a conversation and the host during an active alert. Thread mapping,
   alert state, and completed-operation idempotency survive.

## Prior Art and References

`claude-threads` (https://github.com/anneschuth/claude-threads) is a proven Mattermost/Slack bot
that streams chat threads to a model. Use it as a **reference for the Mattermost transport mechanics
only** (LA-006 posting and LA-008 bot), not as an execution model.

Lift (transport patterns):

1. Mattermost root-post ↔ conversation/thread mapping.
2. Event/post-ID deduplication and websocket reconnect that survives restarts.
3. Least-privileged bot-account setup and mention-only triggering (ignore the bot's own posts).
4. Webhook posting of structured incidents (LA-006) and reaction/button approve-reject controls (UX).

Reject (does not fit our threat model):

1. Its trust model — `default`/`auto`/`bypass` permission modes put authority in the model client.
   LimeOS keeps authority server-side at `limeops` + the gateway (LA-002/LA-007); client-side
   prompts are defence-in-depth only.
2. Its general execution surface — Claude Code CLI with shell, repo writes, worktrees, and file
   attachments. The production assistant is restricted to `limeops`; general coding/shell is
   deferred and denied.
3. Provider lock — it is Claude-Code-CLI-specific; LA-007 requires a provider-neutral gateway
   (Claude and Codex). Borrow only its reaction-approval UX, not its approval semantics, which are
   weaker than the single-use, payload-bound, actor-bound, replay-proof model in this sprint.

It is also TypeScript/Node; any reused transport service is a separately hardened runtime on the Pi.

## Deferred Scope

1. LimeOS in-app chat UI.
2. MCP wrapper around `limeops`.
3. External host/power/Internet outage monitoring.
4. Autonomous remediation.
5. Compose deployment, image updates, or stack editing through chat.
6. Storage, filesystem, SMART-test, or SnapRAID write operations through chat.
7. General coding or repository modification from the production assistant.
8. Voice, image, file-upload, and multi-host workflows.

## Future LimeOS UI Contract

The future chat UI must call the agent gateway rather than a model provider directly. It may add
conversation browsing, provider selection, streaming output, approval controls, alert linking, and
audit views without changing `limeops`, policy, or operation semantics.
