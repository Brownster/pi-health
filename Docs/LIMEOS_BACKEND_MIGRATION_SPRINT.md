# LimeOS Backend Decoupling Sprint

Date: 2026-06-30
Status: Planned
Owner: Pi-Health / LimeOS maintainers
Predecessor: `Docs/UI_V2_LEGACY_REMOVAL_SIGNOFF.md`
Successor: `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`

## Decision

Keep Flask as the human UI's HTTP transport. First create an application factory, then move domain
behavior into a framework-neutral core. The agent and CLI layers will use that core through the
`limeops` policy, approval, identity, and audit boundary.

Flask removal is not a goal of this sprint. A later transport project may replace Flask with
FastAPI if typed request models, generated OpenAPI, or async transport justify the work.

## Objective

Establish a ports-and-adapters architecture without changing hardened stateful or privileged
behavior. Web routes become adapters over explicit services. The Docker client, repositories,
scheduler, operation registry, and privileged-helper client become injected outbound adapters.

The application factory and service extraction provide the foundation required by the agent
automation sprint. They improve test isolation and dependency control without a framework swap.

## Non-Goals

1. Removing Flask or rewriting every HTTP route.
2. Freezing the current HTTP contract indefinitely.
3. Generating golden fixtures for every response.
4. Preserving an endpoint shape when coordinated frontend and backend changes produce a cleaner
   model.
5. Moving privileged work into the web or agent process.
6. Replacing Python domain logic, storage plugins, schedulers, or the helper protocol.

## Architecture

```text
React v2 --------------------> Flask web adapter
                                      |
                                      v
                              core services / ports
                                      ^
                                      |
Agent or CLI --> limeops policy / approval / identity / audit adapter
                                      |
                                      v
                 Docker adapter · repositories · scheduler
                 operation registry · privileged-helper client
```

The web adapter may expose operations authorized by browser sessions and CSRF controls. Agent and
CLI callers must pass through `limeops`; they must never call unrestricted mutation services
directly.

## Constraints

1. Preserve authentication, CSRF, operation ownership, audit identity, validation, locking, atomic
   writes, and helper policy.
2. Preserve the in-process operation registry's thread and SSE replay semantics.
3. Preserve per-stack process locks and thread-local reentrancy.
4. Preserve scheduler behavior, Docker calls, and SnapRAID and MergerFS safety checks.
5. Keep privileged actions behind the typed `pihealth_helper.py` socket protocol.
6. Keep each refactor slice deployable and covered by the full regression suite.
7. Coordinate frontend and backend changes when an HTTP model changes; do not maintain unused
   compatibility layers.

## Entry Gate

Start implementation only when:

1. LR-001 through LR-007 are committed and the legacy-removal signoff is accepted.
2. The full backend, frontend, and E2E suites pass from a clean checkout.
3. A release or tag provides a tested rollback point.
4. The target Pi has a current backup of `/etc/limeos` and `/var/lib/limeos`.

## Tickets

| ID | Title | Depends | Status |
|---|---|---|---|
| BF-001 | Introduce an application factory | Entry gate | Complete (2026-06-30) |
| BF-002 | Define service ports and shared adapters | BF-001 | Complete (2026-06-30) |
| BF-003 | Extract domain services in bounded slices | BF-002 | In progress (storage plugin reads implemented; E2E pending) |
| BF-004 | Characterize security and stateful behavior | BF-001 | Pending |
| BF-005 | Sign off the core boundary and agent handoff | BF-003, BF-004 | Pending |

## BF-001 - Introduce an application factory

Create `create_app(config=None, dependencies=None)` and move route registration, blueprints,
extensions, authentication state, and runtime configuration into explicit initialization. Keep a
small production entry point for the existing systemd command.

Acceptance:

- Importing application modules performs no Docker connection, file migration, server startup, or
  credential loading.
- Tests create isolated app instances with temporary runtime paths and injected dependencies.
- Existing production routes and startup behavior remain stable.
- The full suite passes without tests depending on a module-global Flask application.

Completed 2026-06-30. `app.py` now exposes a `core_api` blueprint and
`create_app(config=None, dependencies=None)`. Credential loading, Docker connection, plugin
registration, and scheduler startup occur only during factory execution. `AppDependencies`
injects users, the login rate limiter, and the Docker client. Eleven duplicated client fixtures
were replaced by shared factory-backed fixtures, including common authenticated identity and CSRF
setup. Importing `app` without credentials is side-effect free; calling the production factory
without credentials still fails closed. Full `tox -e all`: Ruff clean; unit `700 passed, 1
skipped`; E2E `97 passed` across desktop, phone, and tablet viewports.

## BF-002 - Define service ports and shared adapters

Define narrow interfaces for repositories, Docker operations, the privileged helper, scheduler,
clock, audit writer, and operation registry. Wrap existing implementations before moving domain
logic so extraction does not also rewrite infrastructure.

Acceptance:

- Ports use framework-neutral inputs and results.
- Adapters preserve current timeouts, error classification, locking, and audit behavior.
- Tests can inject fakes without patching Flask globals or opening system sockets.
- The operation registry remains single-process and its ownership is explicit.

BF-002A completed 2026-06-30. `OperationRegistry` now owns process-scoped operation creation,
worker execution, opaque ownership, bounded retention, event trimming, and cursor-based replay
without importing Flask. `operation_sse.py` is the transport adapter for session ownership,
`Last-Event-ID`, keep-alives, and SSE response formatting. The app factory injects one registry per
application process, and the class documents that injection does not provide multi-process safety.
Deterministic tests cover ownership, expiry, capacity, trim IDs, producer failures, and missing
terminal events. Full `tox -e all`: Ruff clean; unit `706 passed, 1 skipped`; E2E `97 passed`.

Reviewed 2026-06-30: confirmed the registry has zero `flask`/`session`/`request` imports;
`operation_sse.py` is the sole Flask-aware transport (session→opaque-owner mapping, `Last-Event-ID`
parsing, SSE framing); ownership is an opaque string compared with `hmac.compare_digest`; and
`expected_kind` isolation, exactly-once producer execution, and the `first_event_id` trim/replay
math are preserved. The neutral registry now runs as a standalone unit test (no Flask, no server),
which is the decoupling proof. Retention bounds are injectable, so the BF-002B `clock` port should
be wired into the registry next to make expiry/pruning deterministic without `sleep`.

BF-002B completed 2026-06-30. `ports.py` defines framework-neutral Protocols and thin adapters for
the privileged helper (`HelperClientAdapter` → `helper_call`, preserving `HelperError`), Docker
(`DockerClientAdapter`, None-safe when unavailable), scheduler (`ApschedulerAdapter`), audit
(`FileAuditWriter`, append-only timestamped JSON groundwork), config repository (`JsonFileRepository`,
read-with-default + durable atomic write preserving mode), and the clock (callable convention from
BF-002A). All six are wired through `AppDependencies`/`create_app` and exposed on `app.extensions`;
one shared `clock` now drives both `OperationRegistry` and `LoginRateLimiter`. Call-site migration is
deferred to BF-003 (service extraction); only the clock has a real consumer migration here. New unit
tests inject fakes without Flask globals or sockets. Validation: gate ruff clean; unit
`715 passed, 1 skipped`.

## BF-003 - Extract domain services in bounded slices

Move behavior from route handlers into services one domain at a time. Route handlers should parse
transport input, establish authenticated identity, call one service operation, and map the result
to HTTP.

Recommended order:

1. System metrics and read-only inventory.
2. Containers and network diagnostics.
3. Stacks and catalog operations.
4. Disks, mounts, shares, and storage plugins.
5. Settings, backups, updates, streams, and scheduler operations.

Acceptance:

- Service modules do not import Flask request, session, response, or application globals.
- Services receive ports and adapters explicitly.
- Mutation services preserve validation, authorization context, locks, atomic writes, and audit
  records.
- Focused tests cover success, rejection, dependency failure, and partial-data behavior.
- The full frontend and E2E suites pass after every domain slice.

System metrics completed 2026-06-30. `SystemService` composes the existing neutral telemetry
collectors through injected CPU, disk, and Pi metric readers. The app factory owns service
construction, while `/api/stats` performs only authentication, one service call, and JSON mapping.
Existing resilience behavior and response fields remain unchanged. Service-level fake-reader tests
and a route delegation test cover the new boundary. Full `tox -e all`: Ruff clean; unit `717
passed, 1 skipped`; E2E `97 passed`. One initial Playwright login navigation timed out; an unchanged
full rerun passed, while all system parity tests passed in both runs.

Read-only container inventory completed 2026-06-30. `ContainerInventoryService` builds the
container read model through the injected `DockerPort`, stats reader, and update-status reader.
Port inheritance moved into the framework-neutral container helpers and accepts Docker lookup as
an explicit callback. The `/api/containers` route now parses the `stats` query, calls one service
operation, and maps the result to JSON. Focused tests cover metadata and telemetry composition,
stats suppression, Docker unavailability, list failures, and route delegation. Full `tox -e all`:
Ruff clean; unit `722 passed, 1 skipped`; E2E `97 passed`.

Container operations completed 2026-06-30. `ContainerOperationsService` owns lifecycle actions,
image update checks, Compose recreation, and log retrieval through the injected `DockerPort`,
process runner, and update-state writer. `DockerPort` now includes image pulling, and the existing
adapter delegates that call to Docker without exposing the SDK client to the service. The control
and logs routes now parse transport input and call the injected service directly. Focused tests
cover lifecycle dispatch, invalid actions, Docker failures, image comparison, update-state writes,
Compose invocation, untagged images, log decoding, and route delegation. Full `tox -e all`: Ruff
clean; unit `732 passed, 1 skipped`; E2E `97 passed`.

Container health and network diagnostics completed 2026-06-30. `NetworkDiagnosticsService` owns
host connectivity tests, container probes, and health-detail lookup through injected Docker,
subprocess, socket, and HTTP adapters. Framework-neutral exceptions distinguish Docker
unavailability from missing containers so Flask can preserve the existing `503` and `404`
responses. Probe parsing and fallback helpers moved out of `app.py`; compatibility exports retain
their focused test surface. Tests cover host ping and socket fallback, container lookup and probe
results, bounded health output, error classification, and route delegation. Full `tox -e all`:
Ruff clean; unit `741 passed, 1 skipped`; E2E `97 passed`.

VPN network groups completed 2026-07-01. `NetworkGroupService` owns topology discovery, optional
public-IP leak probing, and coordinated Compose recreation through injected Docker, IP readers,
and process execution. Discovery preserves degraded, unhealthy, and orphan classification;
recreation validates Compose metadata and keeps the provider first in the service order. Flask
maps the framework-neutral Docker-unavailable error to the existing `503` response. Focused tests
cover orphan and leak detection, Docker failures, Compose metadata rejection, command construction,
and route delegation. Full `tox -e all`: Ruff clean; unit `747 passed, 1 skipped`; E2E `97 passed`.

Stack reads completed 2026-07-01. `StackReadService` owns stack discovery, compose-file conflict
reporting, per-stack Compose status parsing, and one-snapshot status aggregation. It receives a
dynamic stacks-path provider and command runner, while mutation code continues to share the same
framework-neutral compose-file validator. The list, scan, and status routes now delegate to the
factory-injected service. Focused tests cover sorting and conflicts, JSON and JSON-lines parsing,
single-snapshot aggregation, snapshot failures, and route delegation. Full `tox -e all`: Ruff
clean; unit `753 passed, 1 skipped`; E2E `97 passed`.

Stack artifact reads completed 2026-07-01. `StackReadService` now also owns stack detail, Compose,
environment, backup listing, and backup-content reads through dynamic stack and backup path
providers. Framework-neutral exceptions distinguish missing artifacts from read failures, while
Flask retains input validation and existing `404`/`500` mappings. Backup filtering still accepts
only timestamped Compose filenames. Focused tests cover detail composition, missing environments,
Compose filename selection, backup filtering and ordering, content reads, and route delegation.
Full `tox -e all`: Ruff clean; unit `758 passed, 1 skipped`; E2E `97 passed`.

Stack file mutations completed 2026-07-01. `StackMutationService` owns Compose and `.env` saves
through injected path, lock, backup, validation, and atomic-write adapters. Compose validation
runs before lock acquisition; successful saves preserve lock, backup, then atomic replacement
ordering. Environment files retain mode `0600`. Dynamic adapters keep the existing process-lock,
reentrancy, and replace-failure tests on the hardened implementations. Focused tests cover ordering,
validation, missing stacks, backup failure, private env mode, and route delegation. Full
`tox -e all`: Ruff clean; unit `766 passed, 1 skipped`; E2E `97 passed`.

Stack backup and restore mutations completed 2026-07-01. `StackMutationService` now owns
timestamped backup creation, ten-file retention, and restore. Restore checks backup existence,
locks the stack, validates restored Compose content, creates a pre-restore backup through the
reentrant lock path, and atomically replaces the live file. Compatibility callers resolve the
same process-scoped service. Focused tests cover naming, retention, missing stacks and backups,
validation-before-backup, restore ordering, and route delegation. Existing restore replacement
failure tests remain green. Full `tox -e all`: Ruff clean; unit `772 passed, 1 skipped`; E2E `97
passed`.

Synchronous stack operations completed 2026-07-01. `StackOperationsService` owns Compose
lifecycle commands and log reads through injected path, lock, process-runner, and service-name
validation adapters. Lifecycle commands preserve the per-stack lock, command arguments, and
five-minute timeout; log reads preserve their unlocked behavior and 30-second timeout. Flask
handlers now validate transport input, call the factory-injected service, and map neutral errors
to HTTP responses. The existing compatibility wrapper resolves the same service for internal
callers. Streaming operation producers remain a separate bounded slice. Focused tests cover lock
use, detached and attached `up` arguments, targeted stops, missing and unknown operations, process
errors, log output, and route delegation. Full `tox -e all`: Ruff clean; unit `778 passed, 1
skipped`; E2E `97 passed`.

Streaming stack operations completed 2026-07-01. `StackOperationsService` now owns Compose process
startup, line collection, terminal result mapping, and per-stack locking through an injected
process factory. It yields framework-neutral event dictionaries directly to the process-scoped
`OperationRegistry`; the Flask compatibility generator only formats those events as SSE. Registry
thread startup, capacity, ownership, retention, replay, and reconnect behavior remain unchanged.
Focused tests cover all four supported actions, exact Compose arguments, lock lifetime, neutral
line and terminal events, preflight failures, process failures, service delegation, replay, and
owner isolation. Full `tox -e all`: Ruff clean; unit `783 passed, 1 skipped`; E2E `97 passed`.

Stack directory lifecycle mutations completed 2026-07-01. `StackMutationService` now owns default
Compose generation, supplied Compose validation, atomic stack creation, partial-create cleanup,
force-delete confirmation, Compose shutdown, pre-delete backup, and directory removal. Typed
framework-neutral exceptions preserve the existing `400`, `404`, `409`, and `500` responses.
Deletion retains the reentrant per-stack lock while Compose shutdown and backup resolve through
the existing process-scoped adapters. Focused tests cover validation timing, private environment
files, existing stacks, rollback cleanup, shutdown ordering and failure, force confirmation,
forced deletion, and route delegation. Full `tox -e all`: Ruff clean; unit `792 passed, 1 skipped`;
E2E `97 passed`.

Disk inventory reads completed 2026-07-01. `DiskInventoryService` owns block-device inventory
assembly from the privileged helper's `lsblk`, `blkid`, `mounts_read`, `fstab_read`, and `df`
reads. The `HelperPort` gained a neutral `available()` method so the service checks helper
readiness without importing the helper module; the pure `process_device` transform (loop/rom
skipping, blkid enrichment, mount/fstab correlation, usage math, recursive partitions) moved into
the service module. `/api/disks` and the `get_disk_inventory` compatibility wrapper now resolve
the factory-injected service. Mount, unmount, media-path, seedbox, startup-service, and SMART
routes remain on the existing helper client as later bounded slices. Focused tests cover
unavailable-helper short-circuit, `lsblk` failure surfacing, full multi-read composition, virtual
device filtering, and fstab-by-UUID correlation for unmounted devices. Full `tox -e all`: Ruff
clean; unit `797 passed, 1 skipped`; E2E `97 passed`.

Disk mount and unmount operations implemented 2026-07-02. `DiskMountService` now owns filesystem
validation, fstab mutation ordering, direct-device resolution, privileged mount calls, dependency
inspection, and fail-closed unmount behavior. Typed framework-neutral exceptions preserve the
existing `400`, `409`, and `503` mappings, including partial fstab warnings and dependency detail.
The app factory injects the helper and dependency inspector, while both routes only parse input,
delegate, and map results. Focused tests cover ordering, direct mounts, validation, partial failure,
dependency blockers, inspection failure, warnings, and route delegation. Ruff is clean; backend
unit tests pass (`808 passed, 1 skipped`). Full E2E remains pending because the Python environment
upgrade selected Playwright Chromium revision 1228, which is not installed locally; the browser
download did not complete in the available environment.

Media paths and startup-service management implemented 2026-07-02. `MediaPathsService` owns
default merging, absolute-path validation, atomic JSON persistence, typed startup parameters,
helper configuration/reload/enable sequencing, and local preview fallback. The app factory injects
the existing helper and config-repository ports. Compatibility functions and the four HTTP routes
resolve the same service, leaving Flask responsible only for transport parsing and error mapping.
Focused tests cover repository failure, validation-before-write, merged updates, helper ordering,
configuration failure, privileged previews, local fallback comparison, and route delegation. Ruff
is clean; backend unit tests pass (`817 passed, 1 skipped`). The full E2E gate remains pending on
the missing Playwright Chromium revision recorded above.

Seedbox configuration implemented 2026-07-02. `SeedboxService` owns default and persisted state,
mounted-state inspection, input normalization and validation, helper availability, configure and
disable mutations, and atomic non-secret config persistence. Passwords cross only the typed helper
call and are excluded from the saved configuration and response. Typed exceptions preserve the
existing validation, unavailable-helper, helper-transport, and rejected-operation HTTP mappings.
The app factory injects the helper and config repository; compatibility functions and both routes
resolve the same service. Focused tests cover defaults, repository and mount-reader failures, every
validation branch, helper availability, credential handling, helper-before-write ordering,
rejection without persistence, and route delegation. Ruff is clean; backend unit tests pass (`831
passed, 1 skipped`). The full E2E gate remains pending on the recorded Playwright browser blocker.

Suggested mount reads implemented 2026-07-02. `DiskSuggestionService` derives recommendations from
one injected disk-inventory snapshot and owns size parsing, filesystem filtering, mounted and
identity filtering, and the existing NVMe and USB placement policy. The app factory composes it
with the same `DiskInventoryService` instance used by `/api/disks`; the suggested-mount route now
performs only authentication, one service call, and JSON/error mapping. The size parser remains a
compatibility export for focused callers. Tests cover NVMe, small and large USB media, filtering,
unpartitioned devices, unsupported transports, size units, and route delegation. Ruff is clean;
backend unit tests pass (`841 passed, 1 skipped`). The full E2E gate remains pending on the recorded
Playwright browser blocker.

Read-only storage-plugin operations implemented 2026-07-02. `StorageReadService` owns managed and
built-in inventory fallback, plugin detail composition, live status, optional recovery reads, and
latest-log lookup. Framework-neutral exceptions distinguish missing plugins, unsupported optional
capabilities, and missing log data. The app factory injects one service with a dynamic registry
provider so plugin initialization remains deferred. Five Flask routes now authenticate, delegate,
and map results; the latest-log adapter alone retains plain-text response headers. Focused tests
cover manager fallback, metadata composition, missing-plugin classification across every read,
status delegation, optional recovery and log capabilities, empty logs, neutral log records, and
route delegation. Ruff is clean; backend unit tests pass (`860 passed, 1 skipped`). The full E2E
gate remains pending on the recorded Playwright browser blocker.

SMART health and self-test operations implemented 2026-07-02. `SmartService` owns safe device-name
validation, all-device health assembly, per-device reads, smartctl result parsing, SAT passthrough,
self-test type validation, and helper rejection classification. Partial all-device results retain
per-disk error details. The app factory injects the helper and existing SMART parser; all three
routes now parse transport input, call one service operation, and map neutral validation and
operation errors. Existing route tests now patch the injected helper adapter boundary. Focused
tests cover partial data, parser delegation, helper failures, unsafe devices, SAT reads, every
supported self-test type, invalid types, rejection mapping, and route delegation. Ruff is clean;
backend unit tests pass (`851 passed, 1 skipped`). The full E2E gate remains pending on the recorded
Playwright browser blocker.

## BF-004 - Characterize security and stateful behavior

Add focused tests for behavior that must survive any transport or client change. Characterize the
current HTTP surface only where it helps prevent security, concurrency, state, or recovery
regressions. These tests document invariants rather than freeze every response field.

Required coverage:

- Authentication, CSRF, actor identity, ownership, and audit attribution.
- Operation creation, thread execution, SSE replay, terminal states, and reconnect behavior.
- Per-stack file locks, thread-local reentrancy, atomic writes, and process boundaries.
- Helper request validation, socket failures, and fail-closed privileged operations.
- Scheduler job registration, replacement, removal, and restart behavior.
- Docker, SnapRAID, MergerFS, mount, and repository failure mapping.

Acceptance:

- Tests fail when an invariant changes even if HTTP payload shapes remain valid.
- Frontend API models may change in the same slice as their backend endpoint.
- No endpoint-specific rollout flag or duplicate transport implementation is introduced.

## BF-005 - Core boundary and agent handoff signoff

Create `Docs/LIMEOS_BACKEND_DECOUPLING_SIGNOFF.md` with the service inventory, dependency direction,
remaining Flask-only behavior, validation evidence, and target-Pi smoke results. Update the agent
automation plan to consume services only through its policy boundary.

Acceptance:

- Framework-neutral services contain the behavior needed by the initial `limeops` command set.
- The core imports no Flask transport state.
- Agent and CLI architecture cannot bypass policy, approvals, identity, or audit.
- Full validation passes from a clean checkout and on the target Pi.
- The Flask-independence entry gate in `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md` is complete.

## Validation Matrix

Each BF-003 domain slice runs focused service and adapter tests. BF-005 also requires:

| Gate | Command or evidence |
|---|---|
| Python lint | `tox -e lint` |
| Backend unit tests | `tox -e unit` |
| Full regression | `tox -e all` |
| Frontend type check | `npm --prefix frontend run check` |
| Production frontend | `npm --prefix frontend run build:publish` |
| Bundle budget | `node scripts/check_frontend_bundle_budget.mjs` |
| Dependency audit | Core modules contain no Flask transport imports |
| Hardware smoke | Login, primary views, and one reversible mutation on the target Pi |

## Rollout and Rollback

Ship the factory and each service domain as separate changes. Keep Flask routes as thin adapters
throughout the sprint. Roll back a failed slice by redeploying the preceding revision; service
extraction must not require a runtime data rollback.

Do not change runtime data formats unless a ticket supplies forward and backward migration tests.

## Optional Transport Project

Evaluate a Flask-to-FastAPI change only after BF-005 and the first agent slice establish concrete
requirements. The decision should compare the value of Pydantic models, OpenAPI generation, native
async support, and SSE handling against the cost of porting the human UI transport.

If approved:

1. Use FastAPI with single-worker Uvicorn while operation and lock state remain in process.
2. Run blocking Docker, filesystem, helper, and subprocess calls in a bounded thread pool.
3. Co-evolve frontend and backend request models instead of preserving obsolete payloads.
4. Keep security and stateful invariants from BF-004 as the migration gate.
5. Move to multiple workers only after operation state, locks, and scheduling have explicit
   cross-process designs.

## Open Decisions

Resolve these during BF-001 and BF-002:

1. Which existing modules already qualify as services or outbound adapters?
2. Where should authenticated actor and audit context enter the core?
3. Which operation-registry methods form the stable port for web and `limeops` callers?
4. Which initial `limeops` commands define the minimum BF-005 service inventory?
5. Which HTTP models should be simplified while frontend and backend are changing together?
