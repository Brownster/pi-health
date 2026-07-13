# LimeOS AI Agents AA-004 Claude Code Adapter and Sandbox

Date: 2026-07-12

Status: Complete

Predecessors: AA-001 LimeOps contract, AA-002 diagnostic operations, AA-003 gateway
domain, and AA-005 Mattermost transport

Successors: AA-006 integration API and AA-009 target signoff

## Outcome

AA-004 supplies the first provider adapter and the production service boundary. Claude
Code implements the provider-neutral AA-003 contract. It receives bounded conversation
context and returns either one final answer or one typed LimeOps request. The gateway,
not Claude, executes diagnostic operations.

The slice includes:

- A tool-free Claude Code adapter with strict structured-output parsing
- A bounded subprocess runner that terminates the whole process group on timeout or
  output overflow
- Non-secret version and subscription-authentication health checks
- A short-lived guided login manager for SSH and LAN deployments
- A production runtime that wires AA-002 through AA-005
- Fixed privileged-helper operations for identities, files, package installation,
  guided authentication, status, and disable
- Hardened `limeopsd.service` and `limeos-agent.service` templates
- An isolated agent runtime outside the writable source checkout
- Default non-secret agent settings and the websocket runtime dependency

## Provider Contract

`agent_provider/claude.py` invokes Claude Code with the security-equivalent command:

```text
claude --safe-mode
  --tools ""
  --strict-mcp-config
  --disable-slash-commands
  --permission-mode dontAsk
  --max-turns 1
  --output-format json
  --json-schema <gateway-turn-schema>
  --no-session-persistence
  --no-chrome
  -p
```

The prompt travels over stdin. It does not appear in the process list. The child receives
a fixed minimal environment containing `HOME`, locale, `PATH`, and `CLAUDE_CONFIG_DIR`.
It does not inherit `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`CLAUDE_CODE_OAUTH_TOKEN`, cloud-provider selectors, or the LimeOS credential file.

The outer response must contain Claude Code's `structured_output`. The inner object must
match exactly one of these shapes:

```json
{"type": "final", "text": "..."}
```

```json
{"type": "tool", "operation": "system.status", "params": {}}
```

Unknown fields, unstructured output, invalid JSON, oversized prompts, oversized process
output, non-zero exits, and timeouts fail through the typed AA-003 provider errors.
Provider stderr never enters a Mattermost reply or API response.

The implementation requires Claude Code 2.1.205 or newer. It follows the current
[Claude Code CLI reference](https://code.claude.com/docs/en/cli-usage),
[headless output contract](https://code.claude.com/docs/en/headless), and
[Linux authentication storage contract](https://code.claude.com/docs/en/authentication).

## Guided Authentication

`agent_provider/auth.py` owns one `claude auth login` process at a time. The privileged
helper launches it as `lime-agent` with an empty environment and the dedicated Claude
configuration directory.

Raw output is discarded after filtering. The browser-facing stream can contain only:

- An HTTPS authorization URL on the `claude.ai` or `console.anthropic.com` host
- A fixed request for the authorization response
- A fixed completed, failed, cancelled, or timed-out status

The submitted authorization response is length-bounded and rejects NUL, CR, and LF. It
is written to the child once and is never logged or persisted. Authorization URLs remain
in memory only and are removed when the operation ends. Successful Linux credentials
remain under `/var/lib/lime-agent/.claude/` with mode `0600`.

AA-006 should map its owner-bound streamed operation to these fixed helper commands:

| Helper command | Accepted parameters |
| --- | --- |
| `agent_provider_auth_start` | none |
| `agent_provider_auth_status` | `operation_id`, `cursor` |
| `agent_provider_auth_submit` | `operation_id`, `code` |
| `agent_provider_auth_cancel` | `operation_id` |

## Runtime Boundary

The agent service runs as `lime-agent:lime-agent` with only the `limeops-client`
supplementary group. Its code and minimal virtual environment are installed at fixed
locations:

| Path | Owner and mode | Purpose |
| --- | --- | --- |
| `/usr/lib/limeos-agent/` | `root:root`, read-only | Installed gateway, provider, transport, and LimeOps client packages |
| `/var/lib/lime-agent/venv/` | `lime-agent:lime-agent` | Minimal Python runtime with `websocket-client` |
| `/var/lib/lime-agent/.claude/` | `lime-agent:lime-agent`, `0700` | Claude settings and credentials |
| `/var/lib/lime-agent/state/` | `lime-agent:lime-agent`, `0750` | Conversations, usage, deduplication, and thread mapping |

The source checkout, Docker socket, privileged-helper socket, root home, and global LimeOS
credential file are inaccessible in the agent unit. The service loads non-secret settings
through a systemd credential snapshot and loads only the dedicated Mattermost bot token
from `agents.env`.

`limeopsd` runs separately as `limeops`, with the `docker` and `pihealth` groups. It owns
the broker socket and audit file. The AA-001 policy and AA-002 validators remain the
authorization boundary.

## Fixed Provisioning

The privileged helper accepts no caller-controlled path, user, package, repository, unit
text, or shell command. AA-006 can call these fixed operations:

| Helper command | Effect |
| --- | --- |
| `agent_runtime_install` | Create fixed identities and paths, install isolated runtime packages, preserve settings and secrets, install units, and start LimeOps |
| `agent_provider_install` | Verify Anthropic's published signing-key fingerprint, configure the stable signed apt repository, and install `claude-code` |
| `agent_runtime_status` | Return non-secret unit, version, and credential-presence state |
| `agent_runtime_disable` | Stop and disable only `limeos-agent.service` |

Provider installation uses Anthropic's signed apt repository and checks fingerprint
`31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE` before trusting the key. It rejects
Claude Code versions older than 2.1.205.

Repair preserves the existing policy, product settings, bot token, conversations, usage,
provider state, Mattermost, Postgres, and alert delivery. Bot-token rotation uses an
atomic replacement without leaving secret backup files.

## Production Wiring

`python -m agent_runtime` loads strict version-1 settings, checks provider health, and
wires:

```text
Mattermost websocket -> MentionListener -> AgentGateway -> ClaudeCodeProvider
                                           |
                                           +-> LimeOpsClient -> limeopsd
```

The canonical context call uses a fixed system actor. User-requested tools retain the
Mattermost actor supplied by AA-003. The runtime rejects credential-bearing Mattermost
URLs, unknown configuration fields, unsafe identifiers, invalid limits, and multiline
bot tokens.

## AA-006 Handoff

AA-006 still owns the authenticated browser API and operation orchestration. It must:

1. Run provider installation and runtime installation through the fixed helper calls.
2. Complete AA-005 bot setup and store the bot token with the fixed secret writer.
3. Write validated non-secret settings and per-host LimeOps resource allowlists.
4. Drive the guided authentication start, status, submit, and cancel flow.
5. Start `limeos-agent.service` only after bot setup and Claude health pass.
6. Expose disable, repair, provider status, usage, and audit without returning secrets.

Provider and runtime installation can exceed the ordinary 30-second helper deadline.
AA-006 must call those two fixed operations with the bounded setup timeout supported by
`helper_call(..., timeout=1200)`.

The existing target helper unit must be regenerated from the updated `setup.sh` before
agent provisioning. The new fixed operations need write access to identity files, the
signed package repository, the isolated runtime directories, and the owned units.

## Verification

Focused coverage proves the exact tool-free arguments, minimal environment, strict reply
shapes, error mapping, prompt/output bounds, process-group timeout cleanup, health
mapping, authorization filtering, guided-code submission, URL disposal, auth timeout,
fixed helper inputs, signing-repository installation, repair preservation, atomic secret
rotation, unit hardening, strict runtime settings, and end-to-end in-process wiring.

The full backend suite passes. `bash -n setup.sh`, Ruff, JSON parsing, and diff checks also
pass. This development container blocks the systemd user/credential lookup sockets, so
`systemd-analyze verify` must run on Holly during AA-009 target signoff.
