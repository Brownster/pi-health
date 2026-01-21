# Pi-Health Issues Tracker

## Critical Issues

### 1. Container List Scroll Reset
- [x] **Problem:** Every 10 seconds, auto-refresh destroys DOM and rebuilds table, losing scroll position
- [x] **Location:** `static/containers.html:334-354, 357-443, 763`
- [x] **Fix:** Implemented smart DOM updates - only full render on structural changes, in-place updates otherwise

### 2. Server-Side Authentication
- [x] **Problem:** Credentials hardcoded in client-side JS, no server validation
- [x] **Location:** `static/login.html:119-120`, `app.py`
- [x] **Fix:** Added Flask session-based auth with env var config (PIHEALTH_USERS, PIHEALTH_USER/PASSWORD)

### 3. API Endpoint Protection
- [x] **Problem:** All API endpoints accessible without authentication
- [x] **Location:** `app.py:746-794`, `compose_editor.py`
- [x] **Fix:** Added @login_required decorator to all protected endpoints

### 4. Add Logout Functionality
- [x] **Problem:** No way to logout without closing browser
- [x] **Location:** All HTML pages (navigation)
- [x] **Fix:** Added logout button to all pages, displays username, calls /api/logout

## Code Quality Issues

### 5. Duplicate Imports
- [x] **Problem:** `import subprocess` appears multiple times
- [x] **Location:** `app.py:6, 371, 677`
- [x] **Fix:** Removed duplicate imports from update_container() and system_action()

### 6. Duplicate getWebUIPort Function
- [ ] **Problem:** Same function defined in two files
- [ ] **Location:** `index.html:178-202`, `containers.html:307-331`
- [ ] **Fix:** Deferred - low priority, would require creating shared JS file

## UX Issues

### 7. Loading Flash on Auto-Refresh
- [x] **Problem:** "Loading..." shown every refresh cycle
- [x] **Location:** `containers.html:337`
- [x] **Fix:** Fixed as part of Issue #1 - only shows loading on initial load

### 8. No Auto-Refresh Indicator
- [ ] **Problem:** Users don't know when next refresh occurs
- [ ] **Location:** `containers.html`
- [ ] **Fix:** Add refresh countdown or toggle

## New Features

### 10. Stack Management (Phase 1 & 2 - Dockge-inspired)
- [x] **Backend:** Stack manager API (`stack_manager.py`)
- [x] **Frontend:** Stacks page (`stacks.html`)
- [x] **Features implemented:**
  - List/scan stacks from STACKS_PATH directory
  - Create/delete stacks
  - Edit compose.yaml and .env per stack
  - Start/stop/restart/pull with SSE streaming
  - View aggregated logs per stack
  - Stack status with container counts
- [x] **Security:** Stack name validation, path traversal prevention
- [x] **Tests:** 16 new tests for stack management

### 11. Bug Fix: compose_editor.py
- [x] **Problem:** Missing `datetime` and `shutil` imports
- [x] **Fix:** Added missing imports

### 12. Enhanced Monitoring - Container Resources
- [x] **Backend:** Container stats collection with TTL caching (`app.py`)
- [x] **Frontend:** CPU, Memory, Network columns in containers table
- [x] **Features:**
  - Per-container CPU usage percentage
  - Memory usage with limit and percentage
  - Network I/O (rx/tx bytes)
  - 5-second TTL cache for performance
  - Color-coded stats (green/yellow/red)
- [x] **Tests:** 7 new tests for container stats functions

### 13. Enhanced Monitoring - Pi-Specific Metrics (PiDoctor-inspired)
- [x] **Backend:** New `pi_monitor.py` module
- [x] **Frontend:** Raspberry Pi Metrics section in system.html
- [x] **Features:**
  - Throttling detection (under-voltage, freq capping, thermal)
  - CPU frequency and voltage display
  - WiFi signal strength with percentage
  - Auto-hide on non-Pi systems
  - iwconfig fallback for WiFi when /proc/net/wireless unavailable
- [x] **Tests:** 27 tests for Pi monitoring functions (including iwconfig)

### 14. Container Stats UI Improvements
- [x] **Network Column:** Now shows rates (bytes/sec) instead of cumulative bytes
- [x] **Memory Column:** Now shows used/limit with progress bar
- [x] **CPU/Memory:** Added mini color-coded progress bars
- [x] **Rate Tracking:** Client-side tracking for calculating network transfer rates

### 15. Auto-Update Scheduler (Watchtower Replacement)
- [x] **Backend:** New `update_scheduler.py` module with APScheduler
- [x] **Frontend:** New Settings page (`settings.html`) with auto-update configuration
- [x] **Features:**
  - Enable/disable auto-updates with toggle switch
  - Schedule presets: Daily 4am, Weekly Sunday 4am
  - Per-stack exclusion from auto-updates
  - Manual "Run Now" trigger
  - Last run results display with updated/skipped/failed counts
  - Next scheduled run time display
  - Concurrent update prevention with locking
- [x] **Config:** JSON config file (`config/auto_update.json`) with atomic writes
- [x] **Tests:** 25 new tests for scheduler module

## Testing

### 9. Ensure All Tests Pass
- [x] Run existing test suite
- [x] Add tests for new authentication endpoints (28 tests total)
- [x] Verify no regressions - 27 passed, 1 skipped (Docker-only)

---

## Progress Log

| Issue | Status | Date |
|-------|--------|------|
| 1. Scroll Reset | Complete | 2026-01-02 |
| 2. Server Auth | Complete | 2026-01-02 |
| 3. API Protection | Complete | 2026-01-02 |
| 4. Logout | Complete | 2026-01-02 |
| 5. Duplicate Imports | Complete | 2026-01-02 |
| 6. Duplicate Functions | Deferred | - |
| 7. Loading Flash | Complete | 2026-01-02 |
| 8. Refresh Indicator | Deferred | - |
| 9. Tests Pass | Complete | 2026-01-02 |
| 10. Stack Management | Complete | 2026-01-02 |
| 11. compose_editor bug | Complete | 2026-01-02 |
| 12. Container Resources | Complete | 2026-01-02 |
| 13. Pi Metrics | Complete | 2026-01-02 |
| 14. Container Stats UI | Complete | 2026-01-02 |
| 15. Auto-Update Scheduler | Complete | 2026-01-03 |
| 16. App Catalog Feature | Complete | 2026-01-03 |
| 17. Disk Management (Phase 0-3) | Complete | 2026-01-03 |

### 17. Disk Management Feature (Mini-Unraid Phases 0-3)
- [x] **Phase 0 - Privileged Helper:** `pihealth_helper.py` systemd service
  - Unix socket communication for safe privileged operations
  - Whitelisted commands: lsblk, blkid, mount, fstab management
  - Input validation and logging
- [x] **Phase 1 - Disk Inventory:** Read-only disk information
  - New `disk_manager.py` backend module
  - New `disks.html` UI page with device tree view
  - Partition info, mount status, usage stats
- [x] **Phase 2 - Mount Wizard:** Guided mounting
  - Mount/unmount endpoints with UUID-based fstab entries
  - Automatic backup before fstab modifications
  - Validation (must be under /mnt/)
- [x] **Phase 3 - Stack Integration:** Media paths configuration
  - Global media paths settings (downloads, storage, backup, config)
  - Integration with app catalog - paths auto-populate template defaults
- [x] **Tests:** 25 new tests for disk management
- [x] **Navigation:** Updated on all pages

### 16. App Catalog Feature
- [x] **Backend:** Complete catalog manager (`catalog_manager.py`)
- [x] **Frontend:** Apps page (`apps.html`) with install/remove
- [x] **Features implemented:**
  - Catalog templates in `catalog/` directory (VPN, Sonarr, Radarr, Prowlarr, Transmission, Portainer)
  - Install endpoint with template rendering ({{KEY}} substitution)
  - Remove endpoint with container stop/rm
  - Dependency checking (VPN required for *arr apps)
  - Backup before compose file modification
  - Optional service start on install
  - UI prompts for missing dependencies
- [x] **Security:** Template validation, atomic file writes, backup rotation
- [x] **Tests:** 27 new tests for catalog management

## Test Summary

- **Total tests:** 198
- **Passed:** 197
- **Skipped:** 1 (Docker-only environment test)

### Test Coverage by Module
| Module | Tests | Description |
|--------|-------|-------------|
| test_app.py | 28 | Authentication, protected endpoints, static pages |
| test_auth_utils.py | 2 | Shared login_required decorator |
| test_catalog.py | 27 | Catalog CRUD, install/remove, dependencies, templates |
| test_containers.py | 31 | Container CRUD, control, logs, network tests, stats |
| test_disk_manager.py | 25 | Disk inventory, mount/unmount, media paths, helper |
| test_stacks.py | 33 | Stack CRUD, backup, compose commands, .env files |
| test_pi_monitor.py | 27 | Throttling, CPU freq/voltage, WiFi signal, iwconfig fallback |
| test_update_scheduler.py | 25 | Auto-update config, schedule presets, update logic, endpoints |
