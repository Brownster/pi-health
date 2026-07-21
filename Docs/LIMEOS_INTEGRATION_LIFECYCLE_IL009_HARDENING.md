# LimeOS Integration Lifecycle IL-009 Cross-Domain Hardening

Date: 2026-07-21

Status: Complete; ready for the IL-010 Holly canary

Scope: IL-009 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commits: `9c59558`, `40d8408`

## Outcome

IL-009 audited Mattermost and AI Agents as one lifecycle boundary and closed the
remaining recovery, authorization, accessibility, and release-budget gaps. Existing
Mattermost alert delivery, agent isolation, package notifications, Extensions, storage,
mounts, shares, and updater workflows remain covered by the complete release suite.

The audit found and corrected these concrete gaps:

- stable server decisions such as forbidden, invalid confirmation, invalid parameters,
  and unavailable actions no longer offer a misleading Retry action;
- Mattermost cleanup retry dispatches only the operation's fixed recorded action;
- uninstall failure requires a fresh typed confirmation before retry, and retained-data
  reinstall returns the card to connected operation;
- viewer setup controls remain hidden even if a malformed response claims setup is
  allowed;
- stale Mattermost failures invalidate both integration cards and restore focus to the
  persistent Mattermost anchor;
- Mattermost tabs now have roving keyboard focus and complete tab/panel relationships;
- setup and authentication dialogs restore focus to persistent card anchors when their
  original trigger disappears;
- the alert-silence dialog has a stable accessible name; and
- the lifecycle interaction scan now fails on browser console or page errors.

## Failure, Security, And Recovery Matrix

The release gate covers injected failure at every Mattermost disable, enable, uninstall,
and purge step, interrupted-operation recovery, cleanup retry, process restart, retained
storage ownership, and purge default-off behavior. Agent coverage includes setup,
disable, enable, repair, uninstall, remote bot warnings, Claude authentication recovery,
helper startup, and persisted operation reconciliation.

Lifecycle APIs remain authenticated, CSRF-protected, administrator-owned, strict about
payload fields and confirmation values, bounded to fixed local actions, redacted, and
audited. Cleanup retry does not accept a client-selected operation type. Agent host
diagnostics remain read-only by default, and Mattermost alert delivery remains
independent when the agent is disabled or unavailable.

Startup and package coverage verifies stale operation reconciliation, scheduled and
manual package reconciliation, package notification behavior, agent helper recovery,
and provisioned service state after restart. Partial failure in one integration does not
erase or reinterpret the other integration's state.

## Accessibility And Responsive Behavior

The complete browser suite exercises lifecycle menus, confirmations, progress, cleanup,
retained-data reinstall, blockers, tab navigation, focus restoration, and existing
workflows at desktop, phone, and tablet widths. No horizontal-overflow assertions or
interaction console scans failed.

The System Health history chart now uses a small native SVG implementation instead of
Recharts. It preserves missing-sample gaps, pointer inspection, keyboard sample
navigation, summaries, and the 24-hour, 7-day, and 30-day ranges. This removes 38
transitive frontend packages and closes the route-budget exception carried from IL-008.

## Compatibility And Deployment

No database, lifecycle-state, helper-policy, Compose, provider, package-management, or
one-time runtime migration is required. Existing connected, disabled, cleanup-required,
retained-data, and not-installed records remain compatible.

Deploy the IL-009 commit range through the normal updater and restart LimeOS. The
production `static/v2` bundle is committed and source-digest checked, so Holly and other
targets without npm use the new UI directly. Removing Recharts changes only the frontend
build dependency graph; it does not require npm or dependency installation on the target.

Rollback is a normal code rollback to the previous committed bundle. Do not delete or
recreate Mattermost data, agent audit data, lifecycle state, or provider configuration.
IL-010 will record the target upgrade and rollback evidence.

Permanent Mattermost purge remains server-disabled and unreleased. It requires separate
destructive evidence against disposable data or a proven backup/restore path before any
release decision.

## Verification

The complete release gate passed outside the managed sandbox because its real Unix
socketpair protocol tests require OS capabilities blocked by that sandbox:

```text
1853 passed, 1 skipped, 163 deselected in 96.60s
163 Playwright tests passed in 269.95s
tox -e all: OK
```

The named capability, lifecycle, security, startup-helper, package-reconciliation, and
provisioning subset passed:

```text
278 passed in 19.49s
```

Focused browser verification passed for all 33 Integrations cases and all four System
Health cases. The latter includes desktop, phone, and tablet chart rendering, keyboard
inspection, missing-data gaps, range switching, summaries, and overflow checks.

The production TypeScript check, Vite build, bundle publication, source digest, and
`git diff --check` passed. Production budget results:

```text
Initial JavaScript: 163.17 kB gzip / 200 kB
Initial CSS: 9.09 kB gzip / 80 kB
Performance history route: 3.05 kB gzip / 100 kB
```

The performance-history route was 103.75 kB gzip before IL-009. All configured frontend
bundle budgets now pass.

## Remaining Work

IL-010 performs the Holly canary: preflight capture, normal upgrade, dependency blocks,
disable/enable, agent uninstall, retained-data Mattermost uninstall/reinstall, recovery,
rollback, data-retention checks, purge disposition, and final GO/NO-GO evidence.
