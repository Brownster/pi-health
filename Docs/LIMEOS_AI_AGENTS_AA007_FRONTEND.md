# LimeOS AI Agents AA-007 Frontend

Date: 2026-07-13

Status: Complete

Predecessor: AA-006 integration service and API

Successors: AA-008 security and recovery suite and AA-009 target signoff

## Outcome

AA-007 adds AI Agents as a separate top-level card on the LimeOS Integrations page.
Mattermost continues to own chat delivery and alert policy. AI Agents owns the assistant
identity, provider connection, permissions, usage, audit history, and lifecycle controls.

The card exposes five views:

- **Overview** shows the `@limeos` identity, Mattermost channel, gateway and broker state,
  last successful turn, delivery test, disable, and repair actions.
- **Providers** shows provider-neutral connection state with Claude Code as the first
  adapter.
- **Permissions** shows the enforced read-only LimeOps profile, exact resource
  restrictions, and explicitly denied capabilities.
- **Usage** shows user turns, provider invocations, daily invocations, and bounded recent
  turn records.
- **Audit** shows bounded recent LimeOps decisions with actor, operation, phase, result,
  and duration.

The published `static/v2` production bundle includes the new control surface.

## Lifecycle Workflows

Setup asks only for the existing Mattermost administrator username and password. Advanced
controls expose the AA-006 turn timeout, tool-round, and daily invocation limits. The
dialog streams provider, isolated-runtime, bot, policy, and service progress through the
existing owner-bound operation client.

When setup finishes without Claude authentication, the dialog offers the next required
action instead of reporting the integration as connected. Connected installations can
send a threaded delivery test, repair the provider and runtime, or disable only the
assistant. Disable copy states that Mattermost, alert delivery, conversations, usage, and
audit data remain in place.

The public AA-006 state controls every badge, warning, and available action. Mattermost
must be connected or degraded before setup becomes available.

## Guided Authentication

The Claude dialog starts an owner-bound authentication stream, opens only the filtered
authorization URL returned by AA-006, accepts the authorization response, and supports
cancellation. It keeps the authorization URL and response only in React memory. It clears
the URL on completion, failure, cancellation, and dialog close and never writes it to
browser storage.

The setup dialog also clears the Mattermost administrator password from React state when
an operation ends or the dialog closes.

## Responsive Behavior

The two integration cards share the existing compact LimeOS visual language. Tabs and
record tables scroll inside their own bounds on narrow screens. Full-page Playwright
captures at desktop, tablet, and 375-pixel phone widths showed no page-level horizontal
overflow, overlapping controls, or clipped card content.

## Verification

AA-007 adds browser coverage for:

- Separate Mattermost and AI Agents cards
- Provider, permissions, usage, and audit data
- Desktop, tablet, and phone overflow behavior
- Streamed setup progress and the required Claude authentication state
- Disabling AI Agents without disconnecting Mattermost

Verification completed with:

```text
npm run check
tox -e all
```

Results: 1,337 backend tests passed, one skipped, and 119 browser tests passed.

## AA-008 Handoff

AA-008 should exercise hostile and interrupted versions of the completed workflows:
authorization URL redaction and replay, malformed authentication responses, duplicate
events, stream reconnects, timeout cleanup, provider and broker failure, runtime restart,
disable during a turn, repair after partial setup, and browser recovery after reload.
AA-009 remains responsible for real Claude authentication and Mattermost mention testing
on Holly.
