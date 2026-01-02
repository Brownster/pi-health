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

## Test Summary

- **Total tests:** 87
- **Passed:** 86
- **Skipped:** 1 (Docker-only environment test)

### Test Coverage by Module
| Module | Tests | Description |
|--------|-------|-------------|
| test_app.py | 28 | Authentication, protected endpoints, static pages |
| test_auth_utils.py | 2 | Shared login_required decorator |
| test_containers.py | 24 | Container CRUD, control, logs, network tests |
| test_stacks.py | 33 | Stack CRUD, backup, compose commands, .env files |
