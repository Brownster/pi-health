# LimeOS Capability Providers CP-010 Disk Summary Contract

Date: 2026-07-18

Status: Implemented

Scope: CP-010 in
`docs/plans/2026-07-16-capability-providers-storage-delivery-plan.md`

## Summary Contract

The authenticated `GET /api/disks/summary` endpoint provides one bounded read model for
the CP-011 disk interface. It reports:

- Physical-device totals and healthy, warning, failing, and unknown counts
- Mounted and unmounted device counts
- Assigned, unassigned, and unused device counts when provider data is complete
- Mounted total, used, and available bytes with aggregate usage percentage
- Per-device health, temperature, mounted capacity, and provider assignments
- Source availability, bounded warnings, overall state, and collection time

The existing `/api/disks` contract remains compatible. It now includes an additive
`configured_mountpoint` field so an offline filesystem can still be matched to a provider
through its `fstab` entry.

## Provider Assignments

The first assignment adapter reads existing `mergerfs.json` and `snapraid.json`
configuration from the owned storage-plugin configuration directory. It does not import
or execute provider code.

MergerFS branch paths map to `storage.pooling` assignments. SnapRAID UUIDs and paths map
to `storage.protection` data or parity assignments. Each assignment includes its provider,
capability, role, configured resource, matched device path, and future owning-page link.

Reads are size- and count-bounded. Unsafe paths and malformed records are ignored.
Malformed configuration for one provider produces a warning without hiding assignments
from the other provider.

## Partial Failure Semantics

Inventory is the required source. If the helper or block-device inventory is unavailable,
the endpoint returns an `unavailable` state with an empty bounded contract instead of
raising an unhandled error.

SMART and provider assignments are optional sources:

- Missing SMART data marks affected health as unknown.
- Unavailable assignment data leaves assigned, unassigned, and unused counts as `null`;
  it never reports a false zero.
- Partially readable provider configuration reports known assignments but leaves inferred
  unassigned and unused counts as `null`.
- Internal exception text is replaced by stable public warning messages.

The frontend client normalizes malformed fields to unknown or unavailable states. It
cannot turn an invalid response into an all-clear display.

## Performance Boundary

CP-010 adds no polling, background jobs, cache, database, or startup reads. The summary is
assembled only when its endpoint is requested. The current Disks page retains its existing
inventory-first loading behavior; CP-011 will consume this contract while preserving that
non-blocking user experience.

## Existing-Instance Deployment

No manual migration is required for Holly or another existing installation:

1. Use the normal LimeOS update workflow.
2. Allow the updater to restart the application and helper services.
3. Confirm `/api/disks` and the current Disks page still load.
4. Confirm `/api/disks/summary` returns the expected device, capacity, and source states.
5. Check configured MergerFS branches and SnapRAID data/parity disks appear as assignments.

There is no database, manifest, provider configuration, or API migration. Existing
MergerFS and SnapRAID files are read in place and never rewritten. The committed production
bundle means the target Pi does not need npm.

## Verification

- Focused disk, provider assignment, API, inventory, and manager suite: 93 passed
- Frontend summary normalization tests: 2 passed
- Full non-browser suite: 1,673 passed, 1 skipped
- Full browser parity suite: 134 passed
- Ruff, TypeScript, production bundle freshness, and `git diff --check`: passed

No visual redesign is included in CP-010. Disk summary presentation and card layout remain
owned by CP-011.
