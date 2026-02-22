# Phase 1 Decision Gate Record (PH1-001)

Date: 2026-02-22  
Status: Approved (GO)  
Owner: Pi-Health maintainers

## Scope
This record closes the mandatory Decision Gate defined in `Docs/UI_MODERNIZATION_PLAN_phase2.md` after Phase 0 completion.

## Inputs Reviewed
1. `Docs/UI_PHASE0_RELEASE_SIGNOFF.md` (Phase 0 release validation and QA evidence).
2. `Docs/UI_MODERNIZATION_PLAN_phase2.md` (reconciled scope, risks, and phased strategy).
3. User/reviewer requirement that mobile pain relief and React migration remain separated.

## Decision
Proceed with Phase 1 Foundation work (`PH1-002` onward), while preserving the standalone Phase 0 hotfix release path.

## Decision Rationale
1. Phase 0 exit criteria are met with phone/tablet/desktop automated evidence.
2. React migration remains scoped as incremental and reversible (no big-bang cutover).
3. The highest hidden dependencies (Flask + Vite integration and route-mode contract) are now explicitly ticketed before page migration.

## Runtime Contract (Binding for Phase 1+)
1. Runtime mode variable: `PIHEALTH_UI_MODE=legacy|hybrid|v2`.
2. Route selection variable: `PIHEALTH_UI_V2_PAGES=<comma-separated legacy route keys>`.
3. Default mode requirement: if `PIHEALTH_UI_MODE` is unset or invalid, behavior must default to `legacy`.
4. `legacy` mode:
   - Serve existing legacy UI routes only.
   - No v2 route exposure required for normal operation.
5. `hybrid` mode:
   - Serve legacy UI by default.
   - Redirect only routes listed in `PIHEALTH_UI_V2_PAGES` to v2 equivalents.
6. `v2` mode:
   - Prefer v2 UI routes broadly.
   - Preserve backend API endpoints and auth/session behavior.
7. Rollback contract:
   - Switching mode to `legacy` must disable v2 route exposure without code changes or rebuild.
8. Non-negotiable guardrail:
   - No backend API contract changes in Phase 1.

## Pilot Confirmation
Phase 2 first parity pilot remains: `containers`.

## Record of Approval
1. Gate question: "Should Phase 0 be treated as standalone and React migration as a separate long-term initiative?"
   - Answer: Yes.
2. Gate question: "Should the project proceed into Phase 1 Foundation now?"
   - Answer: Yes.
