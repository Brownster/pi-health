# UI Migration Tracker

## Ground rules

- One page-focused branch at a time.
- Keep legacy route available until replacement is validated.
- Merge only when page definition of done is met.

## Shared foundation checklist

- [x] Choose final UI stack (Flask + static HTML + vanilla ES modules + shared CSS tokens).
- [x] Establish design tokens (color, spacing, radius, typography).
- [x] Create shared API client baseline (`static/js/lib/http.js`).
- [x] Create shared layout shell (header/nav/content/footer).
- [x] Create reusable shared state components (`LoadingState`, `ErrorState`, `EmptyState`).
- [ ] Add UI smoke tests for core routes.

## Page checklist

### 1) Login (`static/login.html`)
- [x] Build new login screen with modern reusable form controls.
- [x] Preserve session/auth behavior.
- [x] Validate invalid credentials path.
- [ ] Validate logout redirect path.

### 2) Dashboard (`static/index.html`)
- [x] Build dashboard service-card grid with reusable card patterns.
- [x] Preserve service icon mapping behavior.
- [x] Preserve launch/open actions.

### 3) System (`static/system.html`)
- [x] Build metric cards with shared metric styling patterns.
- [x] Preserve refresh cadence and rate calculations.
- [x] Preserve system action controls (shutdown/reboot/network tests).

### 4) Containers (`static/containers.html`)
- [x] Build container table/list with status badges.
- [x] Preserve start/stop/restart/log actions.
- [x] Preserve stats polling behavior.

### 5) Stacks (`static/stacks.html`)
- [x] Build stack list/details view.
- [x] Preserve deploy/update/remove behavior.
- [x] Preserve log and error handling.

### 6) Apps (`static/apps.html`)
- [x] Build catalog browser with search/filter/sort.
- [x] Preserve app install flow and status feedback.

### 7) Settings (`static/settings.html`)
- [x] Build settings sections with reusable field groups.
- [x] Preserve save/reset and plugin toggles.

### 8) Storage/Network/Tools pages
- [x] Migrate `pools`.
- [x] Migrate `mounts`.
- [x] Migrate `shares`.
- [ ] Migrate `plugins`.
- [ ] Migrate `disks`, `network`, `tailscale`, `tools`.
- [ ] Backfill already-migrated pages that still use page-local shell/state markup instead of shared primitives.
- [ ] Validate plugin-specific edge cases.

## Release readiness

- [ ] All legacy pages replaced or intentionally kept.
- [ ] Theming parity validated.
- [ ] Mobile and desktop smoke checks completed.
- [ ] Documentation updated.
