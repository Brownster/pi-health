# LimeOS Capability Providers CP-012 Disk Workflows

Date: 2026-07-18

Status: Implemented

Scope: CP-012 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Suggested Mounts

Suggested mounts now appear as a compact action band between the fleet summary and device
cards. Each row retains the detected device, reason, proposed mount point, and explicit
confirmation step.

Cancelling confirmation sends no request. A successful mount uses the existing API and
refreshes inventory. Structured JSON and plain-text helper errors remain visible to the
operator.

## Unmount Safety

Unmount remains in the device overflow menu introduced by CP-011. Selecting a filesystem
moves keyboard focus to the inline confirmation. Confirm and cancel remain separate, and
helper guidance such as dependent container names is preserved.

## SMART Recovery

The SMART dialog now owns its complete workflow:

- Detail failures show a bounded error and an in-place retry action.
- Successful detail reads update the corresponding device health and temperature.
- Self-tests appear only when SMART is available, enabled, and the helper is reachable.
- Self-test success or failure appears inside the dialog.
- Starting a self-test no longer triggers a disk inventory, assignment, or suggestion
  refresh.

The dialog uses an icon close action, traps focus through the existing modal component,
and remains within the viewport at desktop and phone widths.

## Refresh Failures

A failed manual refresh keeps the last successful cards and summary visible. A warning
shows the last sync time, bounded failure text, and a retry action. Initial inventory
failure retains the existing full error state because there is no safe snapshot to show.

Successful action notices dismiss automatically and also provide an explicit close action.
Error notices remain until dismissed or replaced.

## Existing-Instance Deployment

No manual migration is required. CP-012 changes frontend workflow state and the committed
production bundle only. It does not change databases, helper commands, mount configuration,
provider files, or API request shapes.

Use the normal LimeOS updater, allow the service restart to finish, and hard reload the
Disks page. The target Pi does not need npm.

## Verification

- Disk browser suite split across desktop and phone profiles: 15 passed
- Disk, API, manager, and committed-bundle checks: 88 passed
- Frontend disk summary tests: 3 passed
- TypeScript, Ruff, production build, and `git diff --check`: passed
- Manual Playwright screenshots at 1440x1000 and 390x844: no clipping, overlap, or
  horizontal overflow observed

The repository-wide commit hook exceeds the current command runner lifetime. CP-020 owns
the complete cross-domain regression gate before release signoff.
