# LimeOS Integration Lifecycle IL-006 UI Foundation

Date: 2026-07-21

Status: Complete; the shared lifecycle interface is ready for the AI Agents and
Mattermost workflow slices

Scope: IL-006 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `90db8b6`

## Outcome

LimeOS now has one lifecycle dialog and operation hook for integration state changes.
The foundation owns confirmation, acknowledgement, streamed progress, bounded warning
display, retained failure output, retry, completion, and focus restoration. The existing
AI Agents disable action uses this shared path; IL-007 and IL-008 will add the remaining
agent and Mattermost controls without creating separate dialog behavior.

The Integrations page owns one invalidation revision. Every lifecycle completion,
failure, and retry refreshes Mattermost and AI Agents together, preventing either card
from retaining a stale dependency view. Existing stack-notification and package-update
cards continue to refresh from the same page revision.

## Client Trust Boundary

The client accepts only the frozen lifecycle action catalog in a fixed display order and
filters actions by integration. Unknown, duplicated, or integration-incompatible actions
are discarded when status JSON enters the Mattermost and AI Agents clients.

Mutation URLs come from a local six-route catalog. Callers cannot supply a route, and a
cleanup retry can resolve only the recorded action when that action has a known fixed
route. Blocked-action navigation accepts only `/integrations#ai-agents`; absolute,
external, malformed, and unknown routes remain inert. Warning display accepts only the
bounded `agent_bot_cleanup_failed` result.

## Dialog And Accessibility Contract

The shared dialog:

- supports exact typed confirmation and a separate acknowledgement checkbox;
- prevents Escape, backdrop, header, or action closure while cleanup is running;
- announces running, success, warning, and error changes through live status roles;
- wraps and scrolls the last 100 bounded progress lines;
- retains failure output and exposes retry against the same fixed operation executor;
- clears local confirmation state on close; and
- restores focus to the originating control, or to the stable `#ai-agents` card when a
  refresh removes that control.

`ActionMenu` now restores focus to its trigger before dispatching an action. Existing
Containers, Stacks, and Disks menu behavior remains covered, including keyboard
navigation and Escape restoration. `ModalOverlay` retains its existing focus trap and
adds an explicit fallback for triggers removed by a lifecycle refresh.

## Compatibility And Deployment

No database, runtime-state, helper-policy, Compose, dependency, or one-time migration is
required. Deploying `90db8b6` through the normal updater is sufficient. The production
`static/v2` bundle is committed, so devices without npm receive the IL-006 interface.

The status response additions from IL-005 remain backward-compatible for existing
display paths. IL-006 does not expose uninstall, purge, or new Mattermost controls and
does not change integration service behavior.

## Verification

Focused client contract tests:

```text
5 passed
```

The complete Integrations browser module plus the shared Containers, Stacks, and Disks
menu regressions passed:

```text
16 passed
```

The full release gate passed outside the managed sandbox because its real Unix
socketpair protocol tests require OS capabilities blocked by that sandbox:

```text
1849 passed, 1 skipped, 143 deselected in 94.32s
143 Playwright tests passed in 232.95s
tox -e all: OK
```

The production TypeScript check, Vite build and bundle publication passed. Repository
Ruff `E9,F` and `git diff --check` also passed. Browser coverage proves lifecycle
success, retained progress on failure, retry, cross-card refresh, stable fallback focus,
and unchanged shared menu behavior.

## Remaining Work

- IL-007 adds the complete AI Agents disable, enable/repair, uninstall, remote warning,
  and cleanup-retry interface using this foundation.
- IL-008 adds Mattermost dependency blocks, disable, enable, retained-data uninstall,
  cleanup retry, and release-gated purge controls using the same foundation.
- IL-009 performs cross-domain failure, security, accessibility, responsive, and target
  hardening after both workflows are present.
