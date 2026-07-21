# LimeOS Integration Lifecycle IL-007 AI Agents UI

Date: 2026-07-21

Status: Complete; AI Agents lifecycle management is available from Integrations

Scope: IL-007 in
`docs/plans/2026-07-20-integration-lifecycle-delivery-plan.md`

Implementation commit: `53f6825`

## Outcome

The AI Agents card now exposes one compact **Manage AI Agents** menu whose actions come
only from the normalized server `allowed_actions` response. Administrators can disable,
enable and repair, uninstall, or retry cleanup when the corresponding action is
authorized. Viewers do not receive lifecycle controls.

Setup, provider authentication, repair, test delivery, and detail tabs remain separate
from destructive lifecycle actions. The persistent card distinguishes connected,
disabled, cleanup-required, and not-installed states. Mattermost and alert delivery
remain visible and operational after agent disable or uninstall.

## Lifecycle Workflows

Disable uses the shared streamed lifecycle dialog and preserves configuration,
conversation history, usage, audit history, Mattermost, and alerts. A disabled agent
offers **Enable and repair**, which reuses the existing streamed repair operation and
refreshes both integration cards through the shared page invalidation contract.

Uninstall states the exact removal boundary. It removes managed assistant services, bot
credentials, runtime configuration, provider state, conversations, usage records, and
local agent data. It preserves Mattermost, alert delivery, channels, messages, other
integrations, and the LimeOps security audit log.

The uninstall confirmation:

- requests a Mattermost administrator username and write-only password;
- enables **Remove Claude Code from this device** by default;
- explains the LimeOS-managed package, hold, repository, and signing-key removal; and
- requires typing `AI Agents` before submission.

Successful local cleanup with failed remote bot removal remains a warning completion.
The bounded warning persists on the not-installed card after the dialog closes.

## Credential Custody And Recovery

The password is held only in component memory while the confirmation form is active.
The client clears both its state and the request object immediately after operation
creation, and clears again on failure, completion, cancel, and close. It is never placed
in storage, URLs, progress output, notices, or status data.

A failed secret-bearing uninstall retains progress but its **Retry** action returns to a
fresh confirmation form with empty password and typed-confirmation fields. After a page
refresh, `cleanup_required` presents the same fresh-credential recovery path. LimeOS
retains the original Claude removal choice in the server tombstone; the retry UI cannot
change it. Disable retry contains no secret and may resume the existing fixed executor.

Cleanup operation records are runtime-filtered. Unknown actions, non-retryable records,
and actions without a fixed local route do not produce a retry control.

## Accessibility And Responsive Behavior

The shared menu retains keyboard navigation and focus restoration. Dialog focus returns
to the menu trigger when it remains present, or to the stable `#ai-agents` card after
uninstall removes that trigger. Running operations cannot be closed, status changes are
announced, long progress output wraps, and destructive controls remain usable without
horizontal overflow on phone, tablet, and desktop viewports.

## Compatibility And Deployment

No database, runtime-state, helper-policy, Compose, dependency, or one-time migration is
required. Deploying `53f6825` through the normal updater is sufficient. The production
`static/v2` bundle is committed for devices where npm is absent.

Existing lifecycle tombstones created by IL-001 through IL-005 remain compatible. If an
agent operation is already `cleanup_required`, the updated UI reads its recorded action
and offers the appropriate recovery form. IL-007 changes no backend route or helper
contract.

## Verification

Focused lifecycle contract tests:

```text
6 passed
```

The complete Integrations browser module passed, including three viewport variants of
the uninstall confirmation:

```text
17 passed
```

The full release gate passed outside the managed sandbox because its real Unix
socketpair protocol tests require OS capabilities blocked by that sandbox:

```text
1849 passed, 1 skipped, 151 deselected in 99.20s
151 Playwright tests passed in 248.74s
tox -e all: OK
```

The production TypeScript check, Vite build, bundle publication, repository Ruff
`E9,F`, and `git diff --check` passed. Browser coverage includes server-authorized menu
actions, viewer visibility, disable, enable/repair, uninstall payload shape, default
Claude removal, password clearing on cancel and operation creation, fresh-secret retry,
warning completion, cleanup recovery after refresh, cross-card invalidation, persistent
not-installed state, focus restoration, and responsive overflow.

## Remaining Work

- IL-008 adds the Mattermost dependency-blocked, disable, enable, retained-data
  uninstall, cleanup retry, and release-gated purge interface.
- IL-009 performs cross-domain failure, security, accessibility, responsive, and target
  hardening after both integration workflows are present.
