# V2 Legacy UI Removal Signoff

Date: 2026-06-30
Status: Complete
Scope: LR-001 through LR-007

## Decision

LimeOS now serves the React v2 interface exclusively. The repository no longer contains the v1
pages, their JavaScript modules, the legacy theme package, or runtime mode selection. The retained
`login.html` and `login.js` files provide the authentication entry point used by the v2 app.

The backend still uses Flask for API and static-file delivery. This signoff removes the
Flask-rendered v1 UI; it does not satisfy any separate requirement to replace Flask as the API
server.

## Removed Surface

| Surface | Result |
|---|---|
| Legacy HTML pages | Removed; `login.html` retained |
| Legacy JavaScript | Removed; `pages/login.js` retained |
| Legacy theme system | Loader, routes, assets, and guides removed |
| UI mode selection | `legacy`, `hybrid`, and per-page selection removed |
| Legacy browser suites | Removed after v2 parity coverage was retained |
| Legacy URL behavior | Supported URLs redirect to their v2 equivalents |

## Runtime Contract

- `/` and `/v2/*` serve the v2 SPA.
- `/login.html` remains public and independent of the removed theme system.
- Supported `*.html` bookmarks redirect to current v2 routes.
- `PIHEALTH_UI_MODE`, `PIHEALTH_UI_V2_PAGES`, and `THEME` have no runtime effect.
- New migrations from `/etc/pi-health.env` omit those retired variables.
- The v2 appearance control continues to support light, dark, and system modes.

## Validation Matrix

| Gate | Evidence | Result |
|---|---|---|
| Python lint | `tox -e lint` | Pass |
| Unit suite | `tox -e all` | 698 passed, 1 skipped |
| Browser suite | `tox -e all` | 97 passed |
| Frontend checks | `npm --prefix frontend run check` | Pass |
| Production frontend | `npm --prefix frontend run build:publish` | Pass |
| Bundle budget | `node scripts/check_frontend_bundle_budget.mjs` | Pass |
| Compose configuration | `docker compose config --quiet` | Pass |
| Patch hygiene | `git diff --check` | Pass |

Browser coverage includes desktop, phone, and tablet viewports. It covers authentication,
navigation, compatibility redirects, responsive overflow, dialogs, lifecycle actions, settings,
storage, shares, networking, disks, stacks, containers, system metrics, and the app catalog.

## Deployment Check

Before release, verify these items on the target Pi:

1. Back up `/etc/limeos`, `/var/lib/limeos`, and the active deployment revision.
2. Remove `PIHEALTH_UI_MODE`, `PIHEALTH_UI_V2_PAGES`, and `THEME` from the service environment.
3. Restart `pi-health.service` and confirm `/login.html`, `/`, and the main v2 routes load.
4. Confirm login, one read-only API view, and one reversible container action.
5. Confirm legacy bookmarks redirect to their documented v2 destinations.

## Rollback

Environment-variable rollback no longer exists. Restore the pre-removal revision or release and
redeploy its matching frontend assets. Commit `67e591a` is the final repository revision before
the LR-004 deletion work in this branch and can anchor a pre-removal tag. Restore runtime data only
if the deployment changed its schema or contents; UI removal alone does not require a data restore.

Do not attempt rollback by setting `PIHEALTH_UI_MODE=legacy`. Current code ignores that variable,
and the legacy files are absent.

## Follow-up Gate

The v1 UI removal portion of the LimeOS agent automation entry gate is complete. The automation
sprint remains blocked on its separate requirement to replace or formally accept the Flask API
backend, plus every other gate listed in `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md`.
