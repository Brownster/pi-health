# LimeOS Integration Lifecycle IL-005 API

Date: 2026-07-21

Status: Complete; lifecycle mutations are ready for the shared UI foundation

Scope: IL-005 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `67d545c`

## Outcome

LimeOS now exposes the six frozen Mattermost and AI Agents lifecycle mutations as
authenticated, CSRF-protected, administrator-authorized background operations. Every
accepted request returns `202` with an operation identifier and owner-bound SSE URL.

The existing AI Agents disable action uses the same streamed contract. Its current UI
client and committed production bundle were updated in the implementation commit, so a
Pi without npm does not receive a client that expects the removed synchronous response.

## Route Contract

The fixed routes are:

```text
POST /api/integrations/agents/disable
POST /api/integrations/agents/uninstall
POST /api/integrations/mattermost/disable
POST /api/integrations/mattermost/enable
POST /api/integrations/mattermost/uninstall
POST /api/integrations/mattermost/purge
```

Disable and enable accept exactly `{}`. Mattermost uninstall requires the exact typed
confirmation `Mattermost`. Purge additionally requires an explicit Boolean data-loss
acknowledgement. AI Agents uninstall requires the exact typed confirmation `AI Agents`,
fresh Mattermost administrator credentials, and one Boolean Claude removal choice.
Unknown fields, malformed objects, incorrect types, and incorrect confirmations fail
before status dispatch or lifecycle service execution.

The server status allowlist decides whether an action is currently available. Clients
cannot infer or force actions from display state. Dependency blocks and stale requests
return a stable `409`. When a tombstone exposes `retry_cleanup`, the route matching the
recorded cleanup action resumes that operation instead of creating a separate public
retry route. Agent retry accepts fresh credentials but retains the tombstone's original
Claude removal choice.

## Operation And Security Boundary

All six mutations require `extensions.admin`. Missing or unavailable authorization
policy fails closed before lifecycle status or service dispatch. Global CSRF protection
runs before route authorization.

The operation registry now supports generated-operation-ID producer factories and a
per-integration conflict key. A second active lifecycle mutation for the same integration
returns stable `409`; operation-capacity exhaustion returns stable `429`. Mattermost and
AI Agents may use their separate operation slots, and SSE replay remains bound to the
creating session owner.

Only bounded lifecycle step, line, error, completion, and frozen warning fields enter
operation history or SSE. Unknown fields are dropped. Text containing paths, URLs,
credential labels, tokens, webhooks, DSNs, API keys, environment assignments, control
characters, or excessive length is replaced with a stable public message. Unexpected
producer exceptions also become the fixed integration lifecycle failure message.

Lifecycle audit records contain only actor, permission, integration, action, decision,
outcome, stable code, and optional operation identifier. Accepted, rejected, succeeded,
warning, and failed outcomes are recorded without request values or exception text.

## Compatibility And Deployment

No database, runtime-state, helper-policy, Compose, or one-time migration is required.
Deploying `67d545c` restarts the application through the normal updater; the committed
`static/v2` bundle supports devices where npm is absent.

The API compatibility change is intentional: `POST /api/integrations/agents/disable`
no longer accepts an absent request body or returns `{ "state": "disabled" }`. Callers
must send `{}` and follow the returned operation stream. The shipped client already does
so. Other setup, repair, authentication, alert, usage, audit, and policy routes are
unchanged.

Rollback is straightforward before a lifecycle action starts. After an action creates a
tombstone, complete or retry it with lifecycle-aware code before rolling back to a
release that does not understand lifecycle state.

## Verification

Focused lifecycle API, operation registry, and compatibility tests:

```text
53 passed in 18.09s
```

Targeted streamed-disable browser test:

```text
1 passed in 2.43s
```

The mandatory implementation commit gate passed:

```text
1849 passed, 1 skipped, 141 deselected in 103.65s
141 Playwright tests passed in 235.43s
tox -e all: OK
```

The production TypeScript check and Vite build passed. The committed bundle digest is
fresh, repository Ruff `E9,F`, focused Ruff, and `git diff --check` passed. Coverage
includes all six routes, authentication, CSRF, administrator denial, unavailable policy,
strict request shapes, stale and malformed status, dependency blocks, cleanup retry,
fresh credential custody, concurrent mutation, operation capacity, SSE ownership,
bounded output, secret redaction, and terminal audit outcomes.

## Remaining Work

- IL-006 adds the shared lifecycle dialog, action filtering, and cross-card invalidation.
- IL-007 adds the complete AI Agents disable, uninstall, warning, and cleanup-retry UI.
- IL-008 adds Mattermost dependency-blocked, disable, enable, retained-data uninstall,
  cleanup-retry, and release-gated purge UI.
- Purge remains absent from `allowed_actions` under the default-off server release policy
  until IL-010 records destructive-target evidence and explicitly enables it.
