# UI Modernization Plan

## Final stack decision

For this migration wave, the UI stack is:

- Flask-served HTML routes in `static/*.html`
- Page modules in vanilla ES modules (`static/js/pages/*`)
- Shared browser utilities in `static/js/lib/*`
- Shared design tokens/components in CSS (`static/css/foundation.css` + page CSS)
- Tailwind utility classes where useful

`shadcn/ui` remains a future option that requires a React build pipeline. It is explicitly out of scope for the current parity-focused migration.

## Goals

- DRY: shared auth, API, and state rendering helpers.
- Modular: one module per page, shared helpers in `static/js/lib`.
- Easy to extend: predictable structure for new pages and low-coupling page logic.

## Current implementation baseline

- Login, Dashboard, System, and Containers are migrated to module-based page scripts.
- Shared auth/session helpers exist in `static/js/lib/auth.js` and `static/js/lib/session.js`.
- Shared HTTP helper exists in `static/js/lib/http.js`.
- Shared layout helper exists in `static/js/lib/layout.js`.
- Shared state components exist in `static/js/lib/states.js`.
- All migrated routes now rely on page modules and shared libs; legacy `static/js/api.js` is no longer loaded by page HTML.
- Dashboard (`index.html`) keeps its custom hero markup but now initializes `ensureDashboardShell` for shared nav/notification primitives.

## Standards for migrated pages

- Use `requestJson` from `static/js/lib/http.js` for API calls.
- Do not interpolate API/user data into `innerHTML` without escaping.
- Keep all behavior in page modules; no inline `<script>` blocks for migrated routes.
- Preserve route behavior and API compatibility.

## Migration order

1. `login.html`
2. `index.html`
3. `system.html`
4. `containers.html`
5. `stacks.html`
6. `apps.html`
7. `settings.html`
8. storage/network/tools pages (`pools`, `mounts`, `shares`, `plugins`, `disks`, `network`, `tailscale`, `tools`)

## Definition of done per page

- Existing API behavior preserved.
- Loading/error/empty states handled.
- Keyboard and focus behavior verified.
- Mobile layout checked.
- Shared utilities used instead of duplicated fetch/auth logic.

## PR strategy

- One page-focused PR at a time on top of migration foundation.
- Keep PRs small and composable.
- Include route impact and test notes in each PR.

## Future phase: React + shadcn evaluation

After page parity is complete and stable:

- Evaluate introducing a React + TypeScript frontend app.
- Evaluate `shadcn/ui` for component primitives.
- Migrate from static route-by-route only if it reduces complexity and maintenance burden.
