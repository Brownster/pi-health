# LimeOS AI Agents AA-002 Read-Only Diagnostic Operations

Date: 2026-07-12

Status: Complete

Predecessor: `Docs/LIMEOS_AI_AGENTS_AA001_LIMEOPS_CONTRACT.md`

Successors: AA-004 (the provider now has real diagnostics to call); AA-006 (owns
generating per-host resource allowlists at install time); AA-009 (target validation of
the wiring module).

## Outcome

AA-002 registers the read-only diagnostic handlers behind the frozen AA-001 broker —
all fifteen operations in `config/agent-policy.default.json`: `context`,
`system.status`, `container.list/status/logs`, `stack.list/status/inspect`,
`service.status/logs`, `disk.health`, `mount.status`, `snapraid.status`,
`network.check`, and `installation.inventory`.

- Every handler is a thin, bounded adapter over an injected domain reader; nothing
  constructs Docker, helper, or filesystem access itself, and nothing mutates. The
  broker remains the authorization boundary (policy, resource allowlists, timeouts,
  output limits, fail-closed audit).
- **Redaction:** log text is scrubbed of passwords/secrets/tokens/api keys, bearer
  headers, URL-embedded credentials (any scheme, including database connection
  strings), and incoming-webhook URLs — then byte-bounded below the policy output cap
  with an explicit `truncated` flag, so oversized logs come back as data rather than an
  `output_limit` error. All redaction patterns use bounded quantifiers: log content is
  attacker-influenced, and an unbounded quantifier ahead of a required literal scans
  quadratically (a redaction-time DoS found during testing — a 120 KB line took ~100 s
  before the fix, ~10 ms after).
- **`stack.inspect` never returns compose or env content.** It sanitizes to structure —
  services, images, ports, restart policy, dependencies, and environment variable
  **keys** only — because `stack_details` upstream carries raw `compose_content` and
  `env_content` (secrets).
- **Strict parameters:** unknown fields, wrong types, empty names, and out-of-range
  log lines (20–500, default 200) fail with `invalid_input` before any reader runs.
- Failing readers map to the broker's `upstream_failure` without leaking internals;
  one broken subsystem fails only its own operation.

## Contract fix found by integration

Wiring the real broker under the AA-003 gateway exposed an actor-contract mismatch:
the gateway sent `{kind, username, correlation_id}` but the broker's frozen actor shape
is `{type ∈ {local, mattermost, system}, id, username?}` — every tool call would have
been rejected on the target. The gateway now sends the frozen shape; the per-turn
correlation id stays in the gateway usage ledger, which now also records the broker
`audit_id` from every tool call so AA-006 can join gateway turns to broker audit
records. (`Docs/LIMEOS_AI_AGENTS_AA003_GATEWAY_DOMAIN.md` carries the correction note.)

## Source Layout

| Path | Responsibility |
| --- | --- |
| `limeops/operations.py` | Redaction, log bounding, stack sanitization, strict validators, `build_operations()` |
| `limeops/wiring.py` | Target integration: real readers (Docker SDK, stack read service, systemd, SMART via helper, `/proc` mounts, SnapRAID plugin, socket probes), lazily imported per call |
| `limeops/server.py` | `__main__` now serves the full diagnostic set via `default_operation_factory` |

Resource allowlists note: the default policy ships empty `resources` for
container/stack operations (deny-all until populated). Per-host lists are generated at
install time by AA-006; tests exercise populated allowlists.

## Evidence

`tests/test_limeops_operations.py` — 21 tests: secret-pattern redaction (six classes)
with ordinary lines untouched; truncation flag and byte cap; stack sanitization (env
values and raw content provably absent, keys preserved); registry-vs-default-policy
exact match and `resource_param` mapping; `context` discovery; and through the **real
broker**: success envelopes, log redaction end-to-end with default lines,
resource-denial before the handler, five invalid-parameter shapes rejected before
execution, reader failure as non-leaking `upstream_failure` — plus the full-chain test:
a scripted provider's `ToolCall` flows gateway → broker → diagnostics and the result
feeds the final answer.

Gates: full ruff clean; agent + limeops suites 135 passed in ~1 s; full unit suite
green on the closing commit.
