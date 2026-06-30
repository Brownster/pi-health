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
| BF-002 | Define service ports and shared adapters | BF-001 | In progress (BF-002A complete) |
| BF-003 | Extract domain services in bounded slices | BF-002 | Pending |
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
