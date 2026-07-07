# Phase 5 Containers + Stacks - Management Depth Tickets (Draft)

Date: 2026-07-05
Branch: `feature/ui-phase5-containers-stacks` (recommended)
Source: audit of v2 containers/stacks vs available backend routes (below)
Precondition signoff: `Docs/UI_PHASE3_RELEASE_SIGNOFF.md`
Related: `Docs/UI_PHASE4_POOLS_TICKETS.md` (independent — the two phases share no files
beyond `routes.tsx`/e2e fixtures and can run in parallel)

## Objective
Close the gap between what the backend already supports and what the v2 UI exposes:
full stack lifecycle (create / delete / scan), safer compose editing, container
health + detail visibility, stack<->container linking, and a workable image-update
workflow that respects VPN network groups.

## Where we are (2026-07-05 audit)

Containers v2 (`frontend/src/pages/containers-page.tsx`, `container-list.tsx`) is mature:
list with stats polling, start/stop/restart, per-container update check + badge, logs
snapshot modal, per-container network test, web-URL launch. Stacks v2
(`frontend/src/pages/stacks-page.tsx`) has cards with running counts, up/down/restart/pull
via SSE operations, compose/env textarea editors, backups list + restore, logs snapshot.

Backend routes that exist but are **unused or under-used by the v2 UI**:
- `GET /api/containers/<id>/health` — healthcheck state + last probe output. Never called.
- `POST /api/stacks/<name>` (create), `DELETE /api/stacks/<name>` (delete, with
  conflict/force semantics via `StackDeleteConflictError` / `StackForceConfirmationError`),
  `POST /api/stacks/scan` — no UI for any of them; stacks can only be created by the
  catalog or SSH today.
- `GET /api/stacks/<name>` (`stack_details`: compose + env + status in one payload) — the
  editor modal makes two separate calls instead.
- `GET /api/stacks/<name>/backups/<backup_name>` (backup content) — restore is blind; no
  preview/diff.

Structural gaps:
- `ContainerSummary` has no stack/compose-project field and the backend inventory does not
  emit one, so containers cannot be grouped by stack and a stack cannot list its containers.
- Container logs and stack logs are one-shot `tail` snapshots — no refresh, tail-size
  choice, or download.
- Update checks are strictly per-row; no "check all" and no awareness that updating a VPN
  provider container orphans its `network_mode: service:` members (the network-groups
  remedy exists on the Network page but is not linked from containers).
- No container detail view (image, created/uptime, restart policy, mounts, networks, env).

## Scope Guardrails
1. API changes are **additive only**; no changes to existing route shapes.
2. Reuse Phase 2/3 primitives (page shell, modals with focus handling, `role=status`
   notices, single-flight pending state, SSE operation streaming and its e2e mocks).
3. Preserve the mobile baseline: no horizontal overflow at 390px, touch targets >= 44px.
4. Destructive actions (stack delete, container update on a network provider) get explicit
   confirms; stack delete requires typing the stack name.
5. Never render container env **values** by default — env vars routinely hold secrets.
   Keys only, with per-variable reveal.
6. Bundle budget from PH3 applies (JS <= 200 kB gz); if Phase 5 breaches it, do the
   route-level code splitting deferred since PH2 as part of PH5-007.

## Execution Order and Dependencies
| Order | Ticket | Depends On | Critical Path | Status |
|---|---|---|---|---|
| 1 | PH5-001 Backend additive surface (stack label, inspect, dry-run validate) | — | Yes | Complete (2026-07-07) |
| 2 | PH5-002 Stack lifecycle UI: create / delete / scan | — | Yes | Complete (2026-07-07) |
| 3 | PH5-003 Compose/env editor upgrades + restore preview | PH5-001 | Yes | Complete (2026-07-07) |
| 4 | PH5-004 Container detail drawer + healthcheck + logs QoL | PH5-001 | Yes | Complete (2026-07-07) |
| 5 | PH5-005 Stack<->container linking + VPN-group awareness | PH5-001 | No | Complete (2026-07-07) |
| 6 | PH5-006 Update workflow: check-all + provider-safe updates | PH5-005 | No | Planned |
| 7 | PH5-007 E2E parity + release signoff | all | Yes | Planned |

PH5-002 has no backend dependency and can start immediately alongside PH5-001.

---

## PH5-001 - Backend additive surface (P0)
Estimate: 1 day

### Files
- `container_inventory_service.py`, `container_helpers.py`
- `app.py` (new inspect route), `stack_manager.py` (dry-run validate)
- `frontend/src/lib/containers.ts`, `frontend/src/lib/stacks.ts` (types only)
- `tests/test_containers.py`, `tests/test_stacks.py`

### Tasks
1. Add `stack` (compose project) to each container summary, read from the
   `com.docker.compose.project` label (null when absent). Cheap: labels are already in the
   container attrs the inventory reads.
2. New `GET /api/containers/<id>` inspect endpoint: image (+ digest/tag), created,
   restart policy, uptime/started_at, mounts (source -> destination, ro/rw), networks,
   command, and env **keys only** plus a `?env=full` opt-in that returns values (still
   behind login + CSRF-exempt GET; document the secrets caveat in the docstring).
3. `POST /api/stacks/<name>/compose?validate_only=true` (or `{"validate_only": true}` in
   the body): run the existing validation without writing, returning the same error shape
   as save. Reuses `StackComposeValidationError` — no new validation logic.
4. Unit tests for all three (label present/absent; inspect on running/stopped/missing;
   validate-only does not touch the file and holds no stack lock longer than needed).

### Acceptance Criteria
1. Existing container/stack tests pass unchanged.
2. New payloads covered by unit tests; env values absent unless explicitly requested.

Completed 2026-07-07 in `74c4227`. Container summaries now expose the Compose project label;
the authenticated inspect endpoint returns image, lifecycle, restart, mount, network, command, and
environment-key details, with values available only through explicit `?env=full`; and compose
validation can run without a file read, write, backup, or stack lock. Frontend types cover the new
additive payloads. Validation: Ruff clean, focused backend `180 passed`, full backend `1034 passed,
1 skipped`, and frontend TypeScript checks pass.

---

## PH5-002 - Stack lifecycle UI: create / delete / scan (P0)
Estimate: 1-1.5 days

### Files
- `frontend/src/pages/stacks-page.tsx`
- `frontend/src/components/stacks/stack-create-modal.tsx` (new)
- `frontend/src/lib/stacks.ts` (`createStack`, `deleteStack`, `scanStacks`)

### Tasks
1. "New stack" action: modal with name field (validate client-side against the server rule
   `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`, no leading dot), compose textarea seeded with a minimal
   template, optional `.env` textarea. Surface 400 validation and 409 already-exists errors
   inline. On success, refresh the list and open the new stack.
2. Delete: overflow/menu action on the stack card -> confirm dialog that requires typing
   the stack name. Handle the backend's conflict semantics: if the API answers 409 with a
   force-confirmation requirement (running containers), show what is still running and a
   second explicit "Stop and delete" step that retries with the force flag.
3. "Scan" button on the page header calling `/api/stacks/scan`, reporting
   discovered/adopted stacks in a `role=status` notice, then refreshing.
4. Read the exact create/delete/force request shapes from `stack_manager.py`
   (`api_create_stack`, `api_delete_stack`) rather than guessing — the delete force flow
   already exists server-side.

### Acceptance Criteria
1. A stack can be created, brought up, and deleted entirely from `/v2/stacks`.
2. Deleting a running stack requires the two-step force confirmation.
3. Invalid compose on create shows the server's validation message inline, not a toast.

Completed 2026-07-07 in `2cb6a69`. The stacks page now provides a validated create modal with
Compose and optional environment content, directory scanning with an accessible result notice,
and typed-name deletion. A `409` shutdown conflict keeps the dialog open and requires a second
explicit “Stop and delete” action using the backend's `force` plus `confirm_name` contract. New
stacks refresh the list and open in the editor. Validation: frontend TypeScript and production
build pass, initial JS is `110.54 kB` gzip (within budget), and the existing stacks E2E suite is
`7 passed` across desktop, phone, and tablet.

---

## PH5-003 - Compose/env editor upgrades + restore preview (P0)
Estimate: 1 day

### Files
- `frontend/src/pages/stacks-page.tsx` (editor + backups modals)
- `frontend/src/lib/stacks.ts` (`validateStackCompose`, `fetchStackBackupContent`)

### Tasks
1. "Validate" button in the compose editor using the PH5-001 dry-run endpoint; show
   errors inline above the Save button. Optionally auto-validate on a 1s debounce after
   typing stops (keep it manual if the endpoint proves too chatty).
2. Unsaved-changes guard: closing the editor modal (or switching compose/env tab) with
   dirty content asks for confirmation.
3. Restore preview: before restoring a backup, fetch its content
   (`GET /api/stacks/<name>/backups/<backup_name>`) and show it side-by-side (or stacked on
   mobile) with the current compose, with a simple line-diff highlight. Restore stays a
   confirm action.
4. Use `GET /api/stacks/<name>` (stack_details) to load compose+env in one request when
   opening the editor (replaces the current two parallel calls).
5. Keep textareas (no CodeMirror — bundle budget); `spellCheck=false`, monospace, and a
   line/column in validation errors when the server provides one.

### Acceptance Criteria
1. Invalid YAML/compose is flagged before saving; save still enforces server-side.
2. Restore shows what will change before it happens.
3. Dirty editors cannot be dismissed silently.

Completed 2026-07-07 in `ea3f90b`. The editor now loads compose, environment, filename, and status
through one stack-details request; Compose has an explicit dry-run Validate action with inline
server errors; and dirty close or tab changes require confirmation. Backup restore fetches content
first and renders current/backup panes with changed lines highlighted before the destructive
confirmation. Validation: TypeScript and production build pass, initial JS is `111.24 kB` gzip,
and the updated stacks E2E suite is `7 passed` across desktop, phone, and tablet.

---

## PH5-004 - Container detail drawer + healthcheck + logs QoL (P0)
Estimate: 1-1.5 days

### Files
- `frontend/src/components/containers/container-detail.tsx` (new)
- `frontend/src/pages/containers-page.tsx`
- `frontend/src/lib/containers.ts` (`fetchContainerInspect`, `fetchContainerHealth`)

### Tasks
1. Detail drawer/modal from the container name (or a "Details" action): PH5-001 inspect
   payload — image + tag, created/uptime, restart policy, mounts, networks, ports, env
   keys with per-key reveal button (`?env=full` fetched only on first reveal).
2. Healthcheck section using the existing `GET /api/containers/<id>/health`: current
   state (healthy/unhealthy/starting/none), failing streak, and the last probe output in a
   `<pre>`. Add a compact health dot next to the status badge in the list for containers
   that have a healthcheck.
3. Logs modal QoL: tail-size selector (100/200/500/1000 — backend `tail` param already
   exists), manual refresh + auto-refresh toggle (5s polling while open; no backend
   change), and a "Download" button (client-side blob of the current text).
4. Same tail/refresh/download treatment for the stack logs modal (same endpoint pattern).

### Acceptance Criteria
1. Unhealthy containers are visible at a glance in the list and explained in the drawer.
2. Env values never appear without an explicit per-key reveal.
3. Logs can be tailed at 1000 lines, auto-refreshed, and downloaded on phone and desktop.

Completed 2026-07-07 in `6c15cbc`. Container names now open a responsive operational-detail
dialog with image/lifecycle/restart metadata, mounts, networks, healthcheck state and output, and
environment keys. Values require an explicit per-key reveal, and the full environment payload is
fetched only on first reveal. Health dots surface configured healthchecks in the list. A shared
container/stack log viewer adds 100/200/500/1000-line tails, manual refresh, five-second
auto-refresh, and client-side download. Validation: TypeScript and production build pass, initial
JS is `113.17 kB` gzip, and focused container plus stack E2E is `21 passed` across all viewports.

---

## PH5-005 - Stack<->container linking + VPN-group awareness (P1)
Estimate: 1 day

### Files
- `frontend/src/pages/containers-page.tsx`, `container-list.tsx`
- `frontend/src/pages/stacks-page.tsx`
- `frontend/src/lib/network.ts` (reuse `fetchNetworkGroups`)

### Tasks
1. Containers page: optional "Group by stack" toggle using the new `stack` field —
   grouped section headers with the stack name linking to `/v2/stacks` (unlabelled
   containers under "Standalone").
2. Stack cards (or an expanded stack row): list the stack's containers by matching the
   `stack` field from the containers API, with status dots and a jump to the container's
   detail drawer. One containers fetch shared per page load — no per-stack calls.
3. VPN-group badges: fetch network groups once and badge provider containers ("VPN
   provider") and members ("via <provider>"); orphaned members get a warning badge whose
   click navigates to the Network page recreate flow (do not duplicate the recreate UI).
4. Persist the group-by preference in `localStorage`.

### Acceptance Criteria
1. A stack's containers are reachable from its card; a container's stack is one tap away.
2. Orphaned VPN-group members are visibly flagged on the containers page.

---

## PH5-006 - Update workflow: check-all + provider-safe updates (P1)
Estimate: 1 day

### Files
- `frontend/src/pages/containers-page.tsx`
- `frontend/src/lib/containers.ts`

### Tasks
1. "Check all for updates" header action: run the existing per-container `check_update`
   sequentially (2-3 concurrent max — each check pulls image metadata), with a progress
   notice ("checked 7/23") and a completion summary listing updatable containers.
2. Update badges already render; add an "Updates available (n)" filter chip when n > 0.
3. Provider-safe update guard: before running `update` on a container that is a VPN
   network provider (from PH5-005's group data), warn that its members will be orphaned
   and offer "Update, then recreate group" — run the update, then call the existing
   `/api/network-groups/<provider>/recreate`. Members of a group get a note that updating
   them individually may re-pin to a dead namespace (recommend the group recreate path).
4. Do not auto-schedule checks; this stays a manual action (watchtower already exists for
   automation, and unattended checks would hammer registries).

### Acceptance Criteria
1. One tap surfaces every updatable container without leaving the page.
2. Updating a gluetun-style provider from the UI cannot silently orphan its members.

---

## PH5-007 - E2E parity + release signoff (P0)
Estimate: 1 day

### Files
- `tests/e2e/test_v2_stacks_lifecycle.py`, `tests/e2e/test_v2_container_detail.py` (new)
- e2e mock fixtures (extend the existing containers/stacks mock installers)
- `Docs/UI_PHASE5_RELEASE_SIGNOFF.md` (new, at completion)

### Tasks
1. Mocks: stack create/delete (incl. 409 force flow), scan, validate-only errors, backup
   content, container inspect, health states (healthy/unhealthy/none), network groups with
   an orphaned member, sequential update checks.
2. E2E across phone/tablet/desktop: create -> edit(validate) -> up -> delete force flow;
   detail drawer incl. env reveal; logs tail/auto-refresh; group-by-stack; check-all;
   provider update guard.
3. `npm run check`, `build:publish`, bundle budget; if over budget, implement route-level
   dynamic chunks (deferred from PH2) and re-measure.
4. Full unit + e2e suites green; write the signoff doc in the PH0-PH3 format.

### Acceptance Criteria
1. New e2e suites green in `tox -e e2e` alongside existing v2 suites.
2. Bundle within budget (with or without the chunk split), recorded in the signoff.

---

## Out of scope (deferred)
- True log **streaming** (SSE follow) for containers/stacks — backend is snapshot-only
  today; polling covers the need. Revisit if 5s polling proves inadequate.
- Compose syntax highlighting / CodeMirror — bundle cost not justified yet.
- Per-service (not per-stack) up/down/restart controls — needs new backend compose
  service-level operations; candidate Phase 6.
- Container resource limit editing, image pruning, and registry credential management.
- Auto-scheduled update checks (watchtower remains the automation path).
