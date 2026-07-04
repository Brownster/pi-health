# LimeOS Backend Decoupling Signoff

Date: 2026-07-04
Status: Accepted (hardware smoke pending — see Validation Evidence)
Owner: Pi-Health / LimeOS maintainers
Predecessor: `Docs/LIMEOS_BACKEND_MIGRATION_SPRINT.md`
Successor: `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`

## Purpose

Close out ticket BF-005 of the backend decoupling sprint. This document records the
framework-neutral service inventory, the dependency direction that keeps the core free of Flask
transport state, the behavior that intentionally remains Flask-only, the validation evidence, and the
target-Pi smoke procedure. It also signs off entry gate 2 of
`Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`.

## Decision

The domain behavior of every web route now lives in a framework-neutral service. Flask remains the
human UI's HTTP transport. Web routes are thin adapters: they parse transport input, establish the
authenticated identity, call one service operation, and map the result (or a typed neutral exception)
to HTTP. Outbound infrastructure — the Docker client, config/state repositories, schedulers, the
operation registry, and the privileged-helper client — is injected through ports.

Flask removal was not a goal and did not happen. A later transport project may replace Flask if typed
request models, generated OpenAPI, or async transport justify the cost.

## Service Inventory

All services live at the repository root as `*_service.py`. Each receives its infrastructure through
constructor-injected ports and providers; none reads Flask request, session, response, or application
state.

| Service | Responsibility | Key injected dependencies |
|---|---|---|
| `system_service` | System metrics / read-only telemetry | CPU, disk, and Pi metric readers |
| `container_inventory_service` | Container read model + telemetry | Docker port, stats reader, update-status reader |
| `container_operations_service` | Lifecycle, image updates, Compose recreate, logs | Docker port, process runner, update-state writer |
| `network_diagnostics_service` | Host/container connectivity + health detail | Docker, subprocess, socket, HTTP adapters |
| `network_group_service` | VPN topology discovery + coordinated recreate | Docker, IP readers, process execution |
| `stack_read_service` | Stack discovery, status, detail, backups, artifacts | stacks-path provider, command runner |
| `stack_mutation_service` | Compose/`.env` save, backup/restore, create/delete | path, lock, backup, validation, atomic-write adapters |
| `stack_operations_service` | Compose lifecycle + streaming operations | path, lock, process factory, operation registry |
| `disk_inventory_service` | Block-device inventory assembly | privileged helper port |
| `disk_mount_service` | fstab mutation, mount/unmount, dependency checks | helper port, dependency inspector |
| `disk_suggestion_service` | Suggested mount placement policy | disk-inventory snapshot |
| `media_paths_service` | Media paths + startup-service management | helper port, config repository |
| `seedbox_service` | Seedbox configuration + credentials | helper port, config repository |
| `smart_service` | SMART health + self-tests | helper port, smartctl parser |
| `storage_read_service` | Storage-plugin reads, status, logs | dynamic plugin registry provider |
| `update_service` | Auto-update config, schedule, pull/recreate run | config repo, scheduler, stack lister, compose runner, trigger factory, clock |
| `backup_service` | Backup config, schedule, run, restore | config repo, scheduler, helper, source/stack providers, trigger factory, clock |
| `catalog_service` | Catalog reads, install, remove (locking + streaming) | catalog dir + media providers, compose I/O, stack ops, operation registry (per call) |
| `tools_service` | CopyParty config + privileged status/install/configure | config repo, helper call |

Shared ports and neutral infrastructure live in `ports.py` (`HelperPort`/`HelperClientAdapter`,
`DockerPort`/`DockerClientAdapter`, `SchedulerPort`/`ApschedulerAdapter`, `ConfigRepository`/
`JsonFileRepository`, `AuditPort`/`FileAuditWriter`, and the clock convention) and
`operation_manager.py` (`OperationRegistry`, process-scoped exactly-once background operations with
opaque ownership and cursor replay).

## Dependency Direction

The dependency-direction audit is verifiable and was run as part of this signoff:

- **No service imports Flask.** `grep -nE "^\s*(from flask|import flask)" *_service.py` returns
  nothing. The only three matches for `request`/`session`/`current_app`/`jsonify` in service modules
  are the word "request" inside three docstrings ("... configuration or request is invalid").
- **No service imports a Flask-bearing blueprint module** (`stack_manager`, `disk_manager`,
  `catalog_manager`, `backup_scheduler`, `update_scheduler`, `tools_manager`, `setup_manager`,
  `app`). Services depend only on `ports` and neutral infrastructure (`operation_manager`,
  `helper_client`, `compose_yaml`, `container_helpers`, `system_stats`, `mount_dependencies`,
  `fstab_presets`, `runtime_paths`), all confirmed Flask-free.
- **Identity and audit enter as explicit inputs.** Services never read the session. Actor identity is
  passed in by the caller (for example, `catalog_service.install` takes `owner` and `username`; the
  operation registry stores the opaque owner and compares it with `hmac.compare_digest`). Audit is an
  injected `AuditPort`. The web adapter derives identity from the authenticated session and CSRF
  token; a future `limeops` caller derives it from its own policy/approval/identity boundary.

Direction: `web adapter -> core services -> ports`, and (future) `agent/CLI -> limeops policy ->
core services -> ports`. Nothing in the core points back at a transport.

## Remaining Flask-only Behavior

The following intentionally stay in the transport layer and are out of scope for the core:

- **Authentication, CSRF, and session identity** — `auth_utils.py` (`login_required`, `csrf_protect`,
  CSRF token lifecycle, `LoginRateLimiter`) and the login/logout routes in `app.py`. This is the only
  first-party module besides the blueprints that imports Flask.
- **SSE transport** — `operation_sse.py` maps a session owner to the neutral registry, parses
  `Last-Event-ID`, and frames events. The registry itself is neutral; only the adapter is Flask-aware.
- **HTTP routing and mapping** — the `*_manager` blueprints, the `backup_scheduler`/`update_scheduler`
  blueprints, `storage_plugins`, and the `core_api` routes in `app.py`. Each parses input, resolves
  the factory-injected service, and maps results or typed neutral exceptions to status codes.
- **Application factory** — `create_app`/`AppDependencies` in `app.py` constructs the services, wires
  ports, registers blueprints, and starts schedulers.

Module-level compatibility shims in the scheduler/tools/catalog transports (for example
`load_config`, `run_backup_job`, `_load_stack_compose`, patchable `helper_call`/`CATALOG_DIR`) delegate
to the resolved service and exist only to preserve internal callers and the existing test surface;
they carry no domain logic.

## Agent / CLI Policy Boundary

The core provides the behavior an initial `limeops` command set needs (system status, container and
stack lifecycle, disk/mount/storage reads, backups, catalog, tools) but it does **not** by itself
enforce authorization. Two properties keep the agent path from bypassing policy:

1. Services accept actor identity as an explicit argument and never read ambient session state, so an
   agent caller cannot inherit a browser session's authority by accident. The caller must supply an
   identity, and `limeops` is where that identity, its approvals, and its audit record are produced.
2. Mutation services preserve validation, locking, atomic writes, and typed rejection independent of
   transport, so policy cannot be weakened by choosing a different client.

Per `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`, agent and CLI callers must pass through the `limeops`
policy/approval/identity/audit boundary and must never call unrestricted mutation services directly.
The web adapter may expose operations authorized by browser sessions and CSRF controls. This signoff
does not implement `limeops`; it certifies that the core is ready to sit behind it.

## Validation Evidence

Run from a clean checkout on 2026-07-04 (`tox` environments; frontend via `npm`):

| Gate | Command / evidence | Result |
|---|---|---|
| Python lint | `ruff check --select E9,F63,F7,F82 .` | Pass (clean) |
| Backend unit tests | `pytest tests/ -m 'not e2e'` | `976 passed, 1 skipped` |
| End-to-end suite | `pytest tests/e2e/` | `97 passed` |
| Full regression | pre-commit `tox -e all` (lint + unit + e2e) | Pass on every commit of the sprint |
| Frontend type check | `npm --prefix frontend run check` | Pass (no errors) |
| Bundle budget | `node scripts/check_frontend_bundle_budget.mjs` | Pass (JS 99.06 kB / 200 kB, CSS 6.32 kB / 80 kB) |
| Dependency audit | Core modules contain no Flask transport imports | Pass (see Dependency Direction) |
| Hardware smoke | Login, primary views, one reversible mutation on the target Pi | **Pending** (see below) |

The one E2E caveat carried from the sprint: two legacy `tests/test_login_page.py` checks require an
app served at `localhost:8002`; the pre-commit gate provisions this via `scripts/run-e2e.sh`, and the
suite reports `97 passed` there. The Playwright Chromium blocker recorded during the 2026-07-02 slices
was resolved on 2026-07-03.

## Hardware Smoke (pending operator)

The one gate that cannot be run off the target Pi. Before flipping this signoff's status to fully
Accepted, the operator should, on the Pi with a current backup of `/etc/limeos` and `/var/lib/limeos`:

1. Log in through the v2 UI and confirm the session + CSRF flow.
2. Load the primary views: system, containers, stacks, disks/mounts, storage, settings.
3. Perform one reversible mutation (for example, save an auto-update config change or toggle a
   share) and confirm the audit/last-run record updates.
4. Trigger one streaming operation (a stack `up` or catalog install with start) and confirm SSE
   replay and reconnect via `Last-Event-ID`.
5. Roll back by redeploying the preceding revision if any step regresses; service extraction requires
   no runtime data rollback.

## Entry Gate Signoff

`Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md` entry gate 2 ("the framework-neutral service boundary is
signed off; Flask may remain as the human UI transport, but agent and CLI paths must not depend on
Flask state") is satisfied by the service inventory and dependency-direction audit above, pending the
hardware smoke. The remaining agent-sprint entry gates (security hardening signoff, v1 UI removal, v2
API contract stability, secret-storage contracts, and Mattermost/provider decisions) are tracked
separately and are unaffected by this signoff.
