# UI Phase 5 — Containers + Stacks Management Depth Release Signoff

Date: 2026-07-07
Decision: **GO**
Tickets: `Docs/UI_PHASE5_CONTAINERS_STACKS_TICKETS.md`
Precondition: Phase 3 signed off (`Docs/UI_PHASE3_RELEASE_SIGNOFF.md`); runs in parallel with Phase 4

## Scope delivered
Closed the gap between the backend and the v2 UI for containers and stacks: full stack lifecycle,
safer compose editing with restore preview, container operational detail + healthcheck, logs QoL,
stack↔container linking, VPN-group awareness, and a provider-safe update workflow.

| Ticket | Outcome |
|---|---|
| PH5-001 Backend additive surface (stack label, inspect, dry-run validate) | ✅ `74c4227` |
| PH5-002 Stack lifecycle UI: create / delete (typed-name + force) / scan | ✅ `2cb6a69` |
| PH5-003 Compose/env editor upgrades + restore preview + dirty guard | ✅ `ea3f90b` |
| PH5-004 Container detail drawer + healthcheck + logs QoL | ✅ `6c15cbc` |
| PH5-005 Stack↔container linking + VPN-group awareness | ✅ `f7a3042` |
| PH5-006 Update workflow: check-all + provider-safe updates | ✅ `315e50f` |
| PH5-007 E2E parity + release signoff | ✅ (this doc) |

## Security & safety posture
- **Env values never render by default.** The inspect endpoint returns environment **keys** only;
  values require an explicit per-key reveal that fetches `?env=full` on demand (guardrail 5). Verified
  in `container_inventory_service._environment` and the detail drawer.
- **Every new mutating call is CSRF-safe** — create/delete/scan/validate/recreate all go through
  `requestApi`, which attaches `X-CSRF-Token` on mutating methods.
- **Destructive/risky actions are confirm-gated:** stack delete requires typing the stack name and a
  second "Stop and delete" step on the 409 running-stack conflict; updating a VPN network provider
  opens a guard that offers to recreate the group (prevents silently orphaning
  `network_mode: service:` members — the gluetun/watchtower footgun).

## Validation matrix (2026-07-07, full `tox -e all` pre-commit gate)
- `npm --prefix frontend run check` (tsc) — pass
- `npm --prefix frontend run build:publish` — pass
- `node scripts/check_frontend_bundle_budget.mjs` — pass (initial JS **114.96 kB gz / 200 kB**, CSS 6.78 kB)
- Unit suite (`pytest -m 'not e2e'`) — **1034 passed, 1 skipped**
- e2e suite (`pytest -m e2e`) — **107 passed** across phone/tablet/desktop
- ruff gate (`E9,F`) — pass

## e2e coverage
Phase 5 coverage lives in the extended parity suites (`test_v2_containers_parity.py`,
`test_v2_stacks_parity.py`) and their mock installers rather than new files, keeping the shared
fixtures in one place:
- Stack lifecycle: create (validated) → edit (dry-run validate) → up → delete with the two-step
  force confirmation; scan.
- Restore preview (current vs backup diff) before the destructive confirm; dirty-editor guard.
- Container detail drawer incl. env key reveal; healthcheck; logs tail/auto-refresh/download.
- Group-by-stack sectioning (persisted) and VPN badges — orphaned member links to `/v2/network`.
- Check-all update summary and the provider-safe update→recreate guard.

## Rollout & rollback
Frontend against additive backend surface (`GET /api/containers/<id>` inspect, container `stack`
label, `validate_only` compose). No existing route shapes changed; standard v2 rollback (env flags /
redeploy the previous revision) applies with no data migration.

## Deferred / follow-up (per the tickets' "Out of scope")
- True log **streaming** (SSE follow) — backend is snapshot-only; 5s polling covers the need.
- Compose syntax highlighting / CodeMirror — bundle cost not justified (budget headroom preserved).
- Per-service (not per-stack) up/down/restart — needs new backend compose service-level operations
  (candidate Phase 6).
- Auto-scheduled update checks remain watchtower's job; check-all stays a manual action.

## Decision
**GO.** All seven tickets delivered with the evidence above; env-secret handling, CSRF, and the
destructive-action confirmations meet the scope guardrails; automated coverage is green across
phone/tablet/desktop and the bundle is within budget without needing the deferred route-split.
