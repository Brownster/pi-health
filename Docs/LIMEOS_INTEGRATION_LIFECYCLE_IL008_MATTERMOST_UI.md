# LimeOS Integration Lifecycle IL-008 Mattermost UI

Date: 2026-07-21

Status: Complete; Mattermost lifecycle management is available from Integrations

Scope: IL-008 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `2be73c1`

## Outcome

The Mattermost card now exposes one compact **Manage Mattermost** menu whose actions
come only from the normalized server `allowed_actions` response. Administrators can
disable, enable, uninstall, retry cleanup, or delete retained data when the corresponding
action is authorized. Viewers do not receive lifecycle controls.

The existing setup, alert policy, test delivery, incident summary, and Mattermost link
remain separate from destructive lifecycle actions. The persistent card distinguishes
connected, disabled, cleanup-required, retained-data, and not-installed states.

## Dependency And Lifecycle Workflows

When AI Agents blocks Mattermost disable or uninstall, the Manage menu preserves the
server-provided blocked action. Its dialog names AI Agents, states whether disable or
uninstall is required, and offers **Go to AI Agents**. That action accepts only the
canonical lifecycle navigation target, scrolls to the stable `#ai-agents` anchor, and
moves keyboard focus to the card.

Disable stops the complete Mattermost, Postgres, and alert-delivery stack while
preserving configuration and chat data. Enable restarts the complete stack. The disabled
card hides live test and open-site controls because the service is intentionally down.

Uninstall requires typing `Mattermost` and states the exact boundary:

- Mattermost, Postgres, and alert containers, alert delivery, and LimeOS connection
  configuration are removed.
- Database records, messages, uploads, plugins, and retained logs are preserved for
  reinstall.

After uninstall, a persistent retained-data card offers **Set up again**. It does not
infer permanent deletion from retained data. **Delete data** and the purge menu item are
absent unless the server explicitly includes `purge` in `allowed_actions`.

When released by the server, purge requires typing `Mattermost` and selecting a separate
irreversible-data-loss acknowledgement. The dialog names database records, messages,
uploads, plugins, retained logs, and recovery metadata as permanently removed.

## Recovery, Permissions, And Invalidation

`cleanup_required` replaces normal installed and retained-data views with the recorded
operation, recovery state, last update, and **Retry cleanup**. Retry dispatches only the
normalized recorded disable, enable, uninstall, or purge action through its fixed local
route. Uninstall and purge retries return to typed confirmation before continuing.

Lifecycle controls require the existing `extensions.admin` permission in addition to a
server-authorized action. Unknown actions, malformed cleanup records, unrecognized
blocked routes, and unreleased purge actions remain inert or hidden.

Every operation completion or failure uses the shared Integrations invalidation key, so
Mattermost, AI Agents, stack notifications, and package updates refresh from server
state together. Dialog focus returns to the stable `#mattermost-integration` card when
the triggering menu no longer exists after uninstall or purge.

## Accessibility And Responsive Behavior

The shared menu retains keyboard navigation. Running dialogs cannot close, operation
status is announced, progress output wraps, destructive controls require explicit user
input, and blocker navigation restores a visible and keyboard-operable destination.
Mattermost uninstall was exercised without horizontal overflow at phone, tablet, and
desktop widths.

## Compatibility And Deployment

No database, helper-policy, Compose, dependency, runtime-state, or one-time migration is
required. Deploying `2be73c1` through the normal updater is sufficient. The production
`static/v2` bundle is committed for devices where npm is absent.

Existing connected, disabled, retained-data, and cleanup tombstones from IL-001 through
IL-005 remain compatible. The purge server policy remains default-off, so normal Holly
upgrades do not expose data deletion.

## Verification

Focused Mattermost lifecycle browser coverage:

```text
9 passed, 19 deselected
```

The complete Integrations browser module passed, including three viewport variants of
the Mattermost uninstall confirmation:

```text
28 passed
```

The full release gate passed outside the managed sandbox because its real Unix
socketpair protocol tests require OS capabilities blocked by that sandbox:

```text
1849 passed, 1 skipped, 158 deselected in 97.85s
158 Playwright tests passed in 259.79s
tox -e all: OK
```

The production TypeScript check, Vite build, bundle publication, lifecycle contract
test, repository Ruff `E9,F`, and `git diff --check` passed. Browser coverage includes
server-authorized actions, viewer visibility, dependency guidance and focus, disable,
enable, uninstall payload shape, retained-data persistence, purge release gating,
typed confirmation, irreversible acknowledgement, cleanup recovery after refresh,
stable focus restoration, and responsive overflow.

The optional route-size report still flags the pre-existing dynamic
`performance-history` chunk at 103.75 kB against its 100 kB target. Its baseline was
already 103.75 kB before IL-008; the Mattermost entry bundle remains within its 200 kB
initial JavaScript budget. IL-009 will carry the route-budget exception as release
hardening work.

## Remaining Work

- IL-009 performs cross-domain failure, security, startup, package reconciliation,
  accessibility, responsive, existing-workflow, and target hardening.
- IL-010 runs the Holly canary and records upgrade, retention, rollback, and GO/NO-GO
  evidence before any purge release decision.
