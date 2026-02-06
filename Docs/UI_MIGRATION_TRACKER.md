# UI Migration Tracker

## Ground rules

- One page-focused branch at a time.
- Keep legacy route available until replacement is validated.
- Merge only when page Definition of Done is met.

## Shared foundation checklist

- [ ] Choose final UI stack (React + TS + Tailwind + shadcn/ui).
- [x] Establish design tokens (color, spacing, radius, typography).
- [ ] Create shared API client with typed responses.
- [ ] Create shared layout shell (header/nav/content/footer).
- [x] Create shared state components (`LoadingState`, `ErrorState`, `EmptyState`).
- [ ] Add UI smoke tests for core routes.

## Page checklist

### 1) Login (`static/login.html`)
- [x] Build new login screen with modern reusable form controls.
- [x] Preserve session/auth behavior.
- [x] Validate invalid credentials path.
- [ ] Validate logout redirect path.

### 2) Dashboard (`static/index.html`)
- [ ] Build dashboard service-card grid with reusable card component.
- [ ] Preserve service icon mapping behavior.
- [ ] Preserve launch/open actions.

### 3) System (`static/system.html`)
- [ ] Build metric cards with shared `MetricCard` component.
- [ ] Preserve refresh cadence and rate calculations.
- [ ] Preserve system action controls (shutdown/reboot/network tests).

### 4) Containers (`static/containers.html`)
- [ ] Build container table/list with status badges.
- [ ] Preserve start/stop/restart/log actions.
- [ ] Preserve stats polling behavior.

### 5) Stacks (`static/stacks.html`)
- [ ] Build stack list/details view.
- [ ] Preserve deploy/update/remove behavior.
- [ ] Preserve log and error handling.

### 6) Apps (`static/apps.html`)
- [ ] Build catalog browser with search/filter/sort.
- [ ] Preserve app install flow and status feedback.

### 7) Settings (`static/settings.html`)
- [ ] Build settings sections with reusable field groups.
- [ ] Preserve save/reset and plugin toggles.

### 8) Storage/Network/Tools pages
- [ ] Migrate `pools`, `mounts`, `shares`, `plugins`.
- [ ] Migrate `disks`, `network`, `tailscale`, `tools`.
- [ ] Validate plugin-specific edge cases.

## Release readiness

- [ ] All legacy pages replaced or intentionally kept.
- [ ] Theming parity validated.
- [ ] Mobile and desktop smoke checks completed.
- [ ] Documentation updated.
