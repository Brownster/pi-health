# LimeOS AI Agents AA-000 Baseline and Contract Signoff

Date: 2026-07-12

Status: Accepted for the read-only release

Scope: AA-000 in `docs/plans/2026-07-12-ai-agents-integration-design.md`

Target: Holly (`192.168.0.45`, hostname `wybie`)

## Decision

Proceed with AA-001, AA-003, and mocked AA-005 work against the contracts in this
document. The current backend, Mattermost deployment, and target Pi support a
mention-triggered, read-only assistant.

This signoff does not authorize mutation, scheduled model invocation, arbitrary file
access, shell access, or approval-gated actions. Those features remain behind a later
security and identity review.

## Evidence Baseline

Repository baseline: `04e47e8` (`docs: agents: define provider-neutral Mattermost
assistant`). The commit hook passed 1,146 backend tests and 114 browser tests. A focused
AA-000 run passed 106 security, helper, runtime-path, operation-registry, and port tests.
No framework-neutral `*_service.py` module imports Flask.

The target Pi reported:

| Property | Evidence | Result |
| --- | --- | --- |
| Platform | Debian 12, Linux 6.12, `aarch64` | Supported |
| Memory | 7.9 GiB total, 5.1 GiB available | Supported; start with concurrency one |
| Root disk | 116 GiB total, 75 GiB available | Supported |
| LimeOS | `pi-health.service` active; API health OK | Ready |
| Helper | `pihealth-helper.service` active; typed socket API | Ready |
| Docker | Active | Ready for the privileged broker |
| Mattermost | 11.8.3 ARM64, healthy; API ping OK | Ready |
| Alert delivery | Mattermost, Postgres, and `limeos-alertd` running | Ready |
| Claude Code | Not installed | AA-004 install work |
| Agent identity | `lime-agent` absent | AA-004 install work |
| Mattermost bot settings | Bot creation and user access tokens disabled | AA-005 setup work |

The target has no Node or npm installation. This is not a blocker. Anthropic's native
Claude Code package supports Debian on ARM64 and does not require a project Node runtime.

## Entry-Gate Review

| Gate from the automation sprint | Evidence | AA-000 result |
| --- | --- | --- |
| Security hardening | CSRF, persistent secret key, helper validation, runtime relocation, and credential tests are present and green | Conditional pass for read-only operations; mutation remains blocked |
| Framework-neutral core | `Docs/LIMEOS_BACKEND_DECOUPLING_SIGNOFF.md`; no service imports Flask | Pass |
| Legacy UI removal | `Docs/UI_V2_LEGACY_REMOVAL_SIGNOFF.md` | Pass |
| Stable v2 contracts | Phase 3-5 signoffs and current browser suite | Pass; AI Agents uses an additive API namespace |
| Authentication and operation ownership | Login, CSRF, owner-bound operation registry, and secret modes covered by tests | Pass for browser setup; agent identity contract is frozen below |
| Typed privileged helper | Fixed command allowlist and parameter validation; focused tests pass | Pass |
| Mattermost and provider decisions | Mattermost live; provider-neutral gateway; Claude Code first | Pass with AA-004/AA-005 installation work |

The repository does not contain one prior document that signs off every security and
secret-storage gate together. This AA-000 decision therefore applies only to the
read-only release. AA-008 must produce the consolidated adversarial evidence before
AA-009 can declare release readiness.

## Frozen Ownership Boundary

### Browser Service

`pi-health.service` remains the authenticated browser transport. Existing Mattermost
routes and data are unchanged. The target currently runs this service as `holly`, which
has Docker access; the agent provider must never inherit this identity.

### `limeops` Broker

AA-001 creates a local `limeopsd` broker and a small `limeops` client. The broker owns
access to the Docker and helper ports and calls the existing framework-neutral domain
services. The CLI never imports or constructs privileged ports.

The broker contract is:

- Dedicated `limeops` service identity
- Membership only in the groups needed for Docker and the LimeOS helper
- No login shell and no reusable interactive credentials
- Unix socket at `/run/limeos/limeops.sock`
- Socket mode `0660`, owned by `limeops:limeops-client`
- Peer UID captured with Unix peer credentials
- Length-framed, versioned JSON requests and responses
- Maximum request size 64 KiB
- Maximum response size 1 MiB before operation-specific limits
- Server-side timeouts, policy validation, redaction, and audit
- No TCP listener

The broker is the authorization boundary. It must reject unknown operations and fields
before calling a domain service.

### Agent Service

The gateway and provider run as `lime-agent`:

- No `sudo`, Docker, `pihealth`, or privileged-helper group membership
- Member of `limeops-client` only
- Home at `/var/lib/lime-agent`
- No access to `/home/holly`, the LimeOS checkout, stack directories, credential files,
  Docker socket, or helper socket
- Writable access only to its provider home and agent conversation state
- Systemd filesystem, process, device, capability, and network restrictions

The read-only broker may accept an asserted Mattermost actor from the gateway, but it
also records the peer UID. Policy cannot depend on the asserted actor in the first
release. Any future mutation requires a separate, non-forgeable capability and approval
contract.

## `limeops` Envelope

AA-001 freezes this response envelope as schema version `1`:

```json
{
  "schema_version": "1",
  "request_id": "opaque-request-id",
  "ok": true,
  "operation": "container.status",
  "data": {},
  "warnings": [],
  "error": null,
  "audit_id": "opaque-audit-id"
}
```

Errors use stable codes for invalid input, denied operation, missing resource,
unavailable dependency, timeout, output limit, upstream failure, and audit failure.
Machine output goes to stdout. Human diagnostics go to stderr. A request does not run if
the initial audit record cannot be persisted.

The first policy contains read operations only. Browser mutation services are not
registered with the broker.

## Data and Secret Paths

| Path | Owner and mode | Contract |
| --- | --- | --- |
| `/etc/limeos/integrations/agents.json` | `root:limeops`, `0640` | Non-secret product settings |
| `/etc/limeos/integrations/agents.env` | `root:lime-agent`, `0640` | Mattermost bot secret references only |
| `/etc/limeos/agent-policy.json` | `root:limeops`, `0640` | Operation, resource, argument, and output limits |
| `/var/lib/lime-agent/state/` | `lime-agent:lime-agent`, `0750` | Conversations, deduplication, summaries, usage |
| `/var/lib/lime-agent/.claude/` | `lime-agent:lime-agent`, `0700` | Claude configuration and mode-`0600` credentials |
| `/var/log/limeos/agent-audit.jsonl` | `limeops:limeops`, `0640` | Broker decisions and tool results |
| `/run/limeos/limeops.sock` | `limeops:limeops-client`, `0660` | Local typed broker transport |

Do not reuse the target's generic `/var/lib/limeos/integrations` ownership for agent
state. Setup must create the child directory with the ownership above.

API responses, operation events, prompts, model output, Mattermost posts, and audit
records never expose passwords, tokens, webhook URLs, credential paths, authorization
headers, environment values, or database connection strings.

## Claude Code Provider Contract

The provider adapter uses Anthropic's signed Linux package on the stable channel. Setup
must verify ARM64 support and required CLI features after installation. The minimum
feature baseline is Claude Code 2.1.205 because the release uses structured output and
bounded turn behavior documented at that version.

Authentication runs as `lime-agent` with `CLAUDE_CONFIG_DIR` below the dedicated home.
The first release uses `claude auth login` with a Claude Pro or Max subscription. Linux
credentials remain in `.credentials.json` with mode `0600`. The service environment must
not contain `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or cloud-provider selectors,
because those credentials take precedence over subscription login.

The agent unit does not load the global `/etc/limeos/credentials.env`. It receives only
its dedicated configuration and Mattermost bot credential.

Provider health uses `claude auth status`, which returns JSON and a non-zero exit status
when logged out. Setup and status must report an expiring or invalid login without
printing credential material.

Each model invocation uses the equivalent of:

```text
claude --safe-mode -p <prompt>
  --tools ""
  --strict-mcp-config
  --disable-slash-commands
  --permission-mode dontAsk
  --max-turns 1
  --output-format json
  --json-schema <gateway-turn-schema>
  --no-session-persistence
```

Do not use `--bare`: official documentation states that bare mode still exposes Bash,
file-read, and file-edit tools, and it does not read `CLAUDE_CODE_OAUTH_TOKEN`. The
gateway stores provider-neutral context and invokes Claude with no built-in tools or MCP
servers.

The structured result is either a final answer or one typed `limeops` request. The
gateway validates and executes the request, appends the bounded result to conversation
context, and starts another single-turn invocation. This keeps tool execution in the
provider-neutral gateway rather than exposing Bash to Claude.

## Initial Limits

| Limit | Default |
| --- | ---: |
| Concurrent user turns | 1 globally and 1 per thread |
| Provider process timeout | 300 seconds |
| Tool rounds per user turn | 6 |
| Provider invocations per day | 20, configurable |
| Mattermost input retained per turn | 32 KiB |
| Final Mattermost response | 32 KiB before transport chunking |
| Container/service log lines | 20-500; default 200 |
| Log bytes returned by one operation | 128 KiB |
| Broker request | 64 KiB |
| Broker response | 1 MiB, with smaller operation caps |

The gateway records user turns and provider invocations separately so later API cost
estimates use real workload data.

## Provisioning Contract

The authenticated browser service orchestrates setup but does not gain general root
authority. AA-004 and AA-005 add fixed helper operations for agent provisioning. The
helper owns templates and allowlists for:

- Creating the `limeops`, `lime-agent`, and `limeops-client` identities
- Creating runtime directories with the modes in this document
- Installing or upgrading the signed Claude Code package from the configured channel
- Installing, enabling, disabling, and removing owned systemd units
- Writing or rotating the agent secret file without returning its contents
- Reporting non-secret installation, version, unit, and credential-presence status

The helper does not accept arbitrary usernames, package names, apt repositories, unit
contents, paths, commands, environment keys, or secret destinations. The web process
does not call `sudo`, edit `/etc/systemd`, or copy Claude credentials.

Removal disables the agent units and removes bot/provider credentials. Mattermost,
Postgres, alert delivery, conversations, and provider state are retained unless the
administrator explicitly selects their separate deletion options.

## Browser API Namespace

AI Agents uses additive routes under `/api/integrations/agents`. Existing Mattermost
routes remain unchanged.

The v1 route set is:

```text
GET  /api/integrations/agents
POST /api/integrations/agents/install
GET  /api/integrations/agents/operations/<operation-id>/stream
POST /api/integrations/agents/disable
POST /api/integrations/agents/repair
GET  /api/integrations/agents/providers
POST /api/integrations/agents/providers/claude/auth
POST /api/integrations/agents/test
GET  /api/integrations/agents/usage
GET  /api/integrations/agents/audit
```

Every route requires an authenticated LimeOS session. Every mutation requires CSRF.
Install, repair, and authentication use owner-bound streamed operations. Responses use
typed public states and never return provider or Mattermost secrets.

Provider authentication is a guided operation. It runs `claude auth login` under the
agent identity and filters provider output through an explicit allowlist before streaming
it to the browser. The short-lived authorization URL is shown only to the authenticated
administrator. It is never persisted in operation history, logs, audit records, or API
responses after the authentication operation completes.

## Mattermost Transport Prerequisites

The live Mattermost server currently reports bot-account creation and user access tokens
disabled. AA-005 setup must:

1. Accept the Mattermost administrator password as a write-only value.
2. Enable the required bot and token settings through a supported administrative path.
3. Create or find the `limeos` bot and add it only to configured teams/channels.
4. Create or rotate its token and store it in the agent secret file.
5. Verify websocket events and threaded reply delivery.
6. Never persist the administrator password.

The incoming alert webhook remains owned by the Mattermost integration and is not reused
as the bot credential.

## Package Readiness

| Package | Decision after AA-000 |
| --- | --- |
| AA-001 `limeops` envelope and policy | Ready |
| AA-002 diagnostic operations | Ready after AA-001 skeleton |
| AA-003 gateway domain and persistence | Ready |
| AA-004 Claude adapter and sandbox | Ready after AA-001/AA-003 contracts; target install required |
| AA-005 Mattermost bot and listener | Ready for mocks/contracts; target settings change required |
| AA-006 integration API | Route namespace frozen; waits for AA-003..AA-005 |
| AA-007 frontend | May begin fixtures from the frozen public states and routes |
| AA-008 security suite | Threat cases may begin now |
| AA-009 target signoff | Blocked until AA-008 passes |

## Required Follow-Up Evidence

AA-008 and AA-009 must prove:

- The provider cannot reach Docker, helper, credentials, stacks, source, or user homes.
- Unknown broker operations, arguments, fields, paths, and oversized payloads fail
  before service execution.
- Prompt injection cannot turn a structured tool request into shell or file access.
- Authentication expiry, provider timeout, duplicate Mattermost events, gateway restart,
  and broker failure produce bounded, non-secret outcomes.
- Audit failure denies tool execution.
- The provider can be disabled without interrupting Mattermost alerts.
- Rollback removes agent services and credentials without removing Mattermost data.

## External References

- Claude Code setup and requirements: `https://code.claude.com/docs/en/setup`
- Claude Code authentication and credential precedence:
  `https://code.claude.com/docs/en/authentication`
- Claude Code programmatic use: `https://code.claude.com/docs/en/headless`
- Claude Code CLI flags: `https://code.claude.com/docs/en/cli-reference`
