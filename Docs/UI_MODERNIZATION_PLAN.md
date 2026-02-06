# UI Modernization Plan (Shadcn-Based)

## Vision

Build a modern UI that is:

- DRY: shared components and shared data-fetch layer.
- Modular: page features isolated by domain.
- Easy to extend: predictable conventions for new pages and APIs.

## Current state summary

- Flask serves static pages directly from `static/*.html`.
- Shared scripts exist in `static/js/api.js`, `static/js/nav.js`, `static/js/theme.js`.
- Per-page logic is mostly inline script in each HTML file.
- Tailwind is loaded via CDN (no typed component system, no build pipeline for UI source).

## Target architecture

Use a hybrid rollout to avoid breaking backend routes:

1. Keep Flask API routes intact.
2. Introduce a new frontend app (React + TypeScript + Tailwind + shadcn/ui).
3. Mount one migrated page at a time while legacy pages remain available.
4. Move shared behavior to reusable modules:
   - `ui/lib/api-client.ts`
   - `ui/lib/auth.ts`
   - `ui/lib/theme.ts`
   - `ui/components/layout/*`
   - `ui/components/domain/*`

## Design direction

Direction name: **Operational Clarity**

- Density: medium-dense for dashboard workflows.
- Surfaces: soft contrast panels with clear section boundaries.
- Typography: strong numeric readability for metrics and logs.
- Color: neutral base + functional semantic colors for state.
- Motion: minimal, purpose-driven transitions only for load/state changes.

## Technical standards

- TypeScript strict mode for UI code.
- Zod schemas for API response validation at boundaries.
- React Query (or equivalent) for cache and polling behavior.
- shadcn/ui primitives as base; compose domain components on top.
- No inline JS in HTML pages for migrated routes.
- No duplicate API calls across sibling components.

## Page migration order

Order is based on risk and shared-component yield.

1. `login.html` (small, isolated, auth baseline)
2. `index.html` (dashboard shell and navigation)
3. `system.html` (metrics cards establish reusable status components)
4. `containers.html` (table/actions patterns)
5. `stacks.html` (forms + logs patterns)
6. `apps.html` (catalog cards/search/filter patterns)
7. `settings.html` (settings form system)
8. storage/network/tools pages (`pools`, `mounts`, `shares`, `plugins`, `disks`, `network`, `tailscale`, `tools`)

## Definition of done (per page)

- Pixel-consistent with chosen design system.
- Existing API behavior preserved.
- Error/loading/empty states implemented.
- Mobile breakpoint verified.
- Keyboard accessibility and focus states verified.
- Old page route either replaced or redirected intentionally.

## PR slicing strategy

- PR 1: UI tooling bootstrap + shell layout + login migration.
- PR 2: dashboard (`index`) migration.
- PR 3: system metrics migration.
- PR 4+: one page per PR, plus shared components when needed.

Each PR includes:

- before/after screenshots
- route impact
- reused vs new components
- test notes

## Risks and mitigations

- Risk: duplicated logic between legacy and new pages.
  - Mitigation: move API/auth/theme logic first into shared UI libs.
- Risk: theming drift across pages.
  - Mitigation: central design tokens and component variants.
- Risk: long-lived migration branch.
  - Mitigation: small PRs merged continuously into `main`.
