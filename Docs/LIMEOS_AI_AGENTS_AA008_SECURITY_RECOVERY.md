# LimeOS AI Agents AA-008 Security and Recovery Suite

Date: 2026-07-13

Status: Complete

Predecessors: AA-001 through AA-007

Successor: AA-009 target-Pi signoff

## Outcome

AA-008 consolidates adversarial and interrupted-workflow coverage for the read-only AI
Agents release. The suite now proves the local contracts for provider isolation, strict
broker input, prompt boundaries, secret handling, bounded failures, restart behavior,
and administrator recovery.

The verification pass exposed and fixed these boundary defects:

- Provider and guided-auth timeouts now terminate the complete process group even when
  the direct parent has already exited.
- Unexpected agent operation failures return a fixed public error instead of raw
  exception text.
- Listener recovery logs no longer include exception strings that may contain provider,
  delivery, or database credentials.
- Mattermost websocket authentication JSON-encodes the bot token instead of interpolating
  it into a protocol frame.
- Diagnostic redaction covers Basic authorization values and complete database URL,
  connection string, and DSN assignments.
- The Claude authentication route rejects malformed JSON, missing actions, incomplete
  submissions, and unknown fields before an operation starts.

## Threat Evidence

| Threat or interruption | Enforcement and evidence |
| --- | --- |
| Prompt injection changes instructions or creates a tool call | Provider prompt is structured JSON; hostile text remains one user-message value in `test_hostile_user_text_remains_data_in_provider_prompt` |
| Unknown operation, field, argument, resource, or oversized frame reaches execution | LimeOps schema, policy, validators, protocol bounds, and pre-dispatch audit tests reject each class before the handler |
| Provider reaches Docker, source, credentials, devices, or privileged groups | The rendered agent unit has fixed inaccessible paths, an empty capability set, private devices, restricted address families, and only `limeops-client`; provisioning tests assert the boundary |
| Timeout leaves a child process running | Provider and guided-auth orphan-child marker tests prove process-group termination after the parent exits |
| Secret reaches logs, SSE, public errors, or diagnostic output | Listener logging, operation failure, setup events, ephemeral auth events, and expanded redaction tests assert secret absence |
| Bot token changes websocket frame structure | The authentication frame is parsed and compared after testing an injection-shaped token |
| Duplicate or replay repeats an agent turn | Persistent event dedup tests cover duplicate delivery, restart, and failed reply delivery |
| Listener disconnect stops future turns | Reconnect tests prove capped backoff and resumed frame consumption |
| Gateway, broker, provider, auth, or delivery failure leaks internals | Typed error and bounded-output tests cover every boundary; audit persistence failure denies execution |
| Disable interrupts Mattermost alerts or is lost on reload | Gateway disable tests abort between rounds; browser tests retain disabled state while Mattermost remains connected after reload |
| Browser retains a short-lived authorization URL | Auth completion clears the link and a reload test verifies browser storage contains no authorization URL material |
| Interrupted setup cannot be recovered | Repair can optionally rerun Mattermost bot and configuration bootstrap with write-only admin credentials; service and browser tests restore a partial configuration |

## Recovery Surface

The repair dialog now separates ordinary runtime repair from full Mattermost bot and
configuration repair. Ordinary repair preserves existing settings and credentials. The
full option asks for the Mattermost administrator credentials, rotates and stores the bot
credential through the fixed helper path, reapplies the generated read-only policy, and
clears the administrator password from browser state when the operation ends or closes.

Provider authentication and repair remain owner-bound streamed operations. Ephemeral
authorization events are removed from operation history on completion, and browser
reload uses public integration state rather than replaying the authorization URL.

## Verification

Focused verification passed 106 agent security, integration, provisioning, transport,
and redaction tests. The complete gate passed:

```text
tox -e all
```

Results: 1,349 backend tests passed, one hardware-dependent test skipped, and all 121
Playwright tests passed across desktop, phone, and tablet profiles. The production
frontend bundle was rebuilt and published to `static/v2`.

## AA-009 Handoff

AA-009 must validate claims that require Holly's real operating system and external
services:

- Install or repair the managed identities, helper, units, provider, bot, and policy.
- Run `systemd-analyze verify` and inspect the live agent process groups, filesystem
  access, supplementary groups, and Docker denial.
- Complete real Claude subscription authentication and verify expiry/re-authentication.
- Mention `@limeos` in Mattermost, run a read-only alert-thread investigation, and verify
  duplicate/reconnect behavior against the live server.
- Exercise disable, repair, service restart, and rollback while confirming Mattermost,
  Postgres, alerts, conversations, usage, and audit data remain intact as specified.
