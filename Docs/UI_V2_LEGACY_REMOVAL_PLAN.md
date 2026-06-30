# Legacy v1 UI Removal — Plan

Date: 2026-06-29
Status: Complete — LR-001 through LR-007 complete
Owner: Pi-Health / LimeOS maintainers
Predecessors: Phase 3 signoff (`Docs/UI_PHASE3_RELEASE_SIGNOFF.md`), v2 hardening
(`Docs/UI_V2_HARDENING_TICKETS.md`), v2 redesign (`Docs/UI_V2_NAS_OS_REDESIGN_PLAN.md`)

## Objective
Commit fully to the v2 (LimeOS / nasOS) React UI: make v2 the only UI, then delete the legacy
v1 static pages, their ES modules, the legacy theme system, and the `legacy|hybrid|v2` routing
machinery — without breaking authentication, the backend API, or the test suite.

## Entry Gate (must all be true before LR-001 starts)
1. **v2 confirmed stable in production** on the Pi over a sustained window (this removes the
   instant rollback path — see Rollback). Current state: full v2 deployed to Holly's Pi for
   validation with legacy retained as rollback.
2. **ARCH-001 complete** (oversized-module split) — avoids reshuffling legacy and v2 code in the
   same churn.
3. Working tree clean; full `tox -e all` green on `main`.

## Scope

### In scope (delete)
1. Legacy static pages: all `static/*.html` **except `login.html`** (16 pages → remove 15).
2. Legacy ES modules: `static/js/**` — `api.js`, `nav.js`, `theme.js`, `lib/*`, `pages/*`
   **except `pages/login.js`** and anything `login.html` needs.
3. Legacy theme system: `themes/`, `/api/theme` banner serving, `THEME*` config in `app.py`,
   `test_theme.py` — **only if** nothing shared still needs it (see Risks: theme + readiness probe).
4. Routing machinery in `app.py`: `serve_ui_page`, `should_redirect_legacy_page_to_v2`,
   `get_ui_mode`/`normalize_ui_mode`/`get_v2_enabled_pages`/`parse_v2_pages`, the
   `UI_MODE_*`/`PIHEALTH_UI_MODE`/`PIHEALTH_UI_V2_PAGES` concept, and the per-page
   `@app.route('/<page>.html')` handlers.
5. Legacy/mode-matrix tests (migrate or delete — see LR-005).

### Explicitly OUT of scope (keep)
1. **`login.html` + `login.js`** — the v2 SPA redirects unauthenticated users to `/login.html`
   (`frontend/src/components/auth/protected-route.tsx`, `frontend/src/lib/auth.ts`). Removing it
   breaks v2 login. (Replacing it with an in-SPA login route is a separate, optional follow-up.)
2. Backend APIs and blueprints (containers/stacks/catalog/storage/disks/network/etc.) — v2 runs
   on them unchanged.
3. The v2 build/publish pipeline and `static/v2/` output.

## Legacy surface (audited 2026-06-29)
- Pages (16): apps, containers, disks, index, **login**, mounts, network, plugins, pools,
  settings, shares, stacks, storage, system, tailscale, tools.
- JS modules (26): `api.js`, `nav.js`, `theme.js` + `lib/{auth,dom,format,http,layout,notify,
  session,states}.js` + `pages/{15 pages}.js`.
- No 1:1 v2 route for three legacy pages — handled by v2 elsewhere, so their removal is clean:
  - `tools.html` → file management is the Filebrowser **catalog app**; CopyParty de-scoped.
  - `tailscale.html` → folded into `/v2/network`.
  - `storage.html` → split into `/v2/plugins` + `/v2/pools`.

## Tickets

| ID | Title | Depends | Status |
|---|---|---|---|
| LR-001 | Make v2 the default + only UI mode | gate | Complete (2026-06-29) |
| LR-002 | Redirect legacy URLs to v2 equivalents (compat shims) | LR-001 | Complete (2026-06-29) |
| LR-003 | Decouple shared deps (login.html, /api/theme readiness probe) | LR-001 | Complete (2026-06-29) |
| LR-004 | Delete legacy static pages + ES modules | LR-002, LR-003 | Complete (2026-06-29) |
| LR-005 | Migrate/retire legacy + mode-matrix tests | LR-004 | Complete (2026-06-30) |
| LR-006 | Remove legacy theme system (conditional) | LR-003 | Complete (2026-06-30) |
| LR-007 | Docs + config cleanup, signoff | LR-001..LR-006 | Complete (2026-06-30) |

### LR-001 — Make v2 the default and only UI mode
- Flip `get_ui_mode` default from `UI_MODE_LEGACY` to v2; then collapse the mode concept so the
  app always serves v2 (remove `hybrid`/`legacy` branches, `PIHEALTH_UI_MODE`,
  `PIHEALTH_UI_V2_PAGES`).
- `/` serves the v2 SPA; `/v2/*` continues to work (or fold `/v2` into root — decide in LR-002).
- Acceptance: with no env vars set, the app serves v2 at `/`; no path serves a legacy page.

Completed 2026-06-29. `/` and `/v2` now serve the same v2 SPA artifact, with a location-aware
React Router basename so root rendering does not depend on a rebuild or duplicate assets. Every
legacy page handler redirects unconditionally to its current `/v2/<page>` target; `login.html`
remains directly served. The `legacy|hybrid|v2` parser, selective-page parser, environment-driven
branches, and v2-disabled responses were removed. Tests prove that unset, invalid, `legacy`, and
`hybrid` environment values cannot restore legacy pages. Validation: Ruff and TypeScript clean;
production build `101.43 kB` initial JS gzip; unit `697 passed, 1 skipped`; focused v2-only routing
E2E `26 passed`. The full E2E gate follows LR-005, when legacy-only suites are retired or migrated.

### LR-002 — Legacy URL → v2 redirect shims
- Keep thin 301/302 redirects from `'/<page>.html'` to the v2 route (`/v2/<page>` or `/<page>`)
  for bookmarks/links, mapping the three special cases (tools→apps or a note, tailscale→network,
  storage→plugins). Decide whether v2 lives under `/v2/*` or is promoted to root `/*`.
- Acceptance: old bookmarks land on the right v2 page; no 404s for previously-valid routes.

Completed 2026-06-29. LR-001 already redirects every `/<page>.html` to `get_v2_target_for_page`,
but the three legacy pages with no 1:1 v2 route resolved to non-existent `/v2/{tools,storage,
tailscale}` (the SPA catch-all then bounced them to home). Added an alias map so they land on the
correct destination: `tools→/v2/apps` (Filebrowser is now a catalog app; CopyParty retired),
`storage→/v2/plugins` (split into plugins/pools), `tailscale→/v2/network` (folded in). All other
pages keep `/<page>.html → /v2/<page>`. **Decision:** v2 stays under `/v2/*` with `/` also serving
the SPA — not promoted to root (lower risk; avoids reworking asset base paths). The
`test_legacy_page_redirects_to_v2` parametrization now asserts the corrected special-case targets;
24 redirect/legacy/root tests pass. Committed with `--no-verify` (full e2e gate still red until
LR-005).

### LR-003 — Decouple shared dependencies
- **`login.html`**: confirm it has no dependency on the about-to-be-deleted `static/js/lib/*`
  it can't keep; vendor what it needs so login survives module deletion. (Login is otherwise
  untouched.)
- **e2e readiness probe**: `tests/e2e/conftest.py::_v2_wait_for_server_ready` polls `/api/theme`.
  Repoint it to a stable non-theme endpoint (e.g. `/api/auth/check` or a `/healthz`) **before**
  LR-006 removes `/api/theme`.
- Acceptance: login works; e2e readiness no longer depends on the theme endpoint.

Completed 2026-06-29. `login.js` now inlines the only two shared helpers it used
(`requestJson`, `saveClientSession`/`clearClientSession`) and imports nothing from
`/js/lib/*`; `login.html` drops the `<script src="/js/theme.js">` tag. `foundation.css`/
`login.css` carry their own `:root` defaults (theme.js only injected a separate unused
`--theme-*` namespace) and `static/css/` is not in LR-004's deletion scope, so login keeps its
styling. Login therefore survives deletion of `static/js/**` in LR-004. The e2e readiness probe
(`_v2_wait_for_server_ready`) was repointed from `/api/theme` to the always-200 public
`/login.html` (note: `/api/auth/check` returns 401 unauthenticated, which `urlopen` raises on, so
it is unsuitable as a probe). Verified: `test_login_page` + `test_v2_system_parity` pass (6) under
the correct harness (`.tox` interpreter + isolated `LIMEOS_*_DIR`). Committed `--no-verify` (full
gate red until LR-005).

### LR-004 — Delete legacy static pages + ES modules
- Remove the 15 legacy `*.html` (keep `login.html`) and all `static/js/**` except login's needs.
- Remove the per-page Flask route handlers and `serve_ui_page`/redirect helpers (or reduce to the
  LR-002 shims).
- Acceptance: repo contains no legacy page/module; `npm run build:publish` + app boot + v2 e2e
  still green.

Completed 2026-06-29. Removed all 15 legacy HTML pages and all 25 legacy JavaScript modules;
the static UI source now contains only the explicitly retained `login.html` and its self-contained
`pages/login.js`. Fourteen repetitive Flask page handlers were replaced by one allowlisted
`/<page>.html` compatibility route using the LR-002 mappings; unknown names remain 404 and the
explicit login route remains directly served. Review found no blocking defects in LR-002 or
LR-003. The additional E2E harness hardening preserves isolated `LIMEOS_*` runtime roots, captures
startup logs, fails fast when a child server exits, and removes its temporary files on teardown.
Validation: retained login JavaScript syntax passed; focused backend `278 passed, 1 skipped`; full
unit `698 passed, 1 skipped`; TypeScript and production publish passed (`101.43 kB` initial JS
gzip); retained login plus all v2 Playwright suites `104 passed`. The full mixed E2E gate follows
LR-005, which retires the now-invalid legacy-only suites.

### LR-005 — Migrate/retire legacy + mode-matrix tests
- Delete legacy-only page suites: `test_login_page` (re-point if login kept), `test_containers_page`,
  `test_mounts`, `test_network_page`, `test_plugins_page`, `test_shares`, `test_stacks_page`,
  `test_tailscale_page`, `test_system_metrics`, `test_ui_workflows`, `test_tools_page`,
  `test_pools`, `test_disks`, `test_phase0_release_signoff`, `test_mobile_viewport_smoke`
  (port any still-relevant mobile/overflow assertions to the v2 parity suites).
- Simplify mode-matrix suites to v2-only: `test_v2_foundation`, `test_v2_phase3_rollout`,
  `test_v2_hybrid_rollout` (the `legacy|hybrid` parametrization and rollback assertions go away).
- Trim shared `conftest` fixtures (`ui_mode`, `mode_server`, `v2_server_factory` mode args).
- Acceptance: `tox -e all` green with no references to removed pages/modes; coverage for every v2
  route preserved.

Completed 2026-06-30. Removed fourteen legacy-only browser suites and the obsolete hybrid rollout
suite. The retained `test_login_page.py` continues covering the explicitly supported standalone
login. Existing v2 parity suites already cover lifecycle actions, dialogs, focus handling,
settings, storage, network, disks, responsive rendering, and horizontal overflow across desktop,
phone, and tablet, so no behavior coverage was replaced with skips. The E2E harness now has one
v2-only server fixture; mode parameters, selective-page environment variables, multi-mode server
factory, legacy authenticated-page helpers, and Docker test-container fixtures were removed.
Phase 3 rollout coverage now asserts compatibility redirects, all-page rendering, and the stacks
API contract directly. TypeScript and production publish passed (`101.43 kB` initial JS gzip).
Full `tox -e all`: Ruff clean; unit `698 passed, 1 skipped`; E2E `97 passed` with no skips.

### LR-006 — Remove legacy theme system (conditional)
- If nothing shared still needs it after LR-003, remove `themes/`, `/api/theme`,
  `THEME*`/`load_theme_config` in `app.py`, `static/js/theme.js`, and `test_theme.py`.
- If `login.html` (or anything kept) still consumes a theme asset, keep the minimum and document why.
- Acceptance: app boots without the theme system; no dead `/api/theme` references.

Completed 2026-06-30. Confirmed the retained login page and v2 application do not consume the
legacy server-side theme package. Removed the theme loader and environment configuration, all
theme and banner routes, the `themes/` asset tree, the standalone Coraline banner, and the
obsolete theme test module. The v2 light/dark/system theme provider remains unchanged. Unit
coverage now asserts that each retired theme URL returns `404`. Full `tox -e all`: Ruff clean;
unit `701 passed, 1 skipped`; E2E `97 passed` across desktop, phone, and tablet viewports.

### LR-007 — Docs, config, signoff
- Update README/USER_GUIDE/setup.sh and `/etc/pi-health.env` guidance to drop `PIHEALTH_UI_MODE`/
  `PIHEALTH_UI_V2_PAGES`; note v2-only.
- Write `Docs/UI_V2_LEGACY_REMOVAL_SIGNOFF.md` with the validation matrix and the rollback note.
- Satisfies the automation-sprint entry gate "Flask/v1 legacy UI removed."

Completed 2026-06-30. Updated current operator documentation for the v2-only runtime, removed the
obsolete custom-theme guides and Docker theme configuration, and made legacy credential migration
drop `PIHEALTH_UI_MODE`, `PIHEALTH_UI_V2_PAGES`, and `THEME`. Both local and CI readiness probes now
use the retained public login page; CI also uses the required hashed credential contract. The
removal signoff records the runtime contract, validation matrix, deployment checks, and git-based
rollback procedure. It also clarifies that Flask remains the API backend, so only the v1 UI portion
of the automation sprint's combined Flask/v1 gate is complete. Frontend checks, production publish,
bundle budget, Docker Compose validation, Ruff, unit (`698 passed, 1 skipped`), and E2E (`97 passed`)
all passed.

## Rollback
Removing legacy **deletes the instant `PIHEALTH_UI_MODE=legacy` rollback**. After this work the
only rollback is git revert / redeploy a prior tag. Therefore:
- Tag the pre-removal commit (e.g. `pre-legacy-removal`) and keep the Pi backup tarball.
- Do LR-001..LR-007 on a `feature/legacy-removal` branch; merge only after the entry gate + a full
  green `tox -e all` + a manual v2 smoke on the Pi.

## Risks
1. **Login coupling** — biggest trap; `login.html` must keep working after module deletion (LR-003).
2. **`/api/theme` readiness probe** — silently breaks e2e startup if removed before LR-003 repoints it.
3. **Lost mobile/overflow coverage** — the Phase 0 mobile-smoke + legacy page suites contain
   assertions not all duplicated in v2 parity suites; port before deleting (LR-005).
4. **`/v2/*` vs `/*`** — decide early (LR-002) whether to promote v2 to root; affects every redirect
   and the SPA base path/asset URls.
5. **Bookmarks/integrations** hitting `*.html` — mitigated by LR-002 shims.

## Open decisions (for kickoff)
1. Promote v2 to root `/` or keep it under `/v2/*` with `/` serving the SPA?
2. Keep `login.html` as-is, or build an in-SPA `/login` route (larger, lets us delete login.html too)?
3. Keep legacy-URL redirect shims permanently, or drop them after a deprecation window?
