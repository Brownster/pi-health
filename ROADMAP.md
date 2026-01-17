# Pi-Health Roadmap

A living document tracking planned improvements and feature ideas.

## Current Status (v1.0.0)

Pi-Health is functional with:
- System health monitoring (CPU, temp, disk)
- Docker container management with CPU/network stats
- Stack management (Docker Compose)
- App store for one-click deployments
- Disk management and fstab editing
- SnapRAID/MergerFS storage plugins
- Auto-update scheduler
- Multi-user authentication
- Theming (coraline, professional, minimal)

---

## Priority Features

These are the currently prioritized items for development.

### Phase 1: Bug Fixes & Polish ⭐ PRIORITY

#### Bug Fixes
- [ ] Handle 401 auth errors gracefully (redirect to login instead of JS error)
- [ ] Add favicon.ico
- [ ] Fix theme.js 404 error on pages that reference it
- [ ] Improve mobile responsiveness on all pages

#### UX Improvements
- [ ] **Toast notifications** - Non-blocking feedback for actions (start/stop/restart/save)
  - Success (green), error (red), info (blue) styles
  - Auto-dismiss after 3-5 seconds
  - Stack multiple notifications
- [ ] **Loading spinners** - Visual feedback during slow operations
  - Container stats fetching
  - Stack operations (up/down/pull)
  - Disk operations
  - API calls
- [ ] Confirmation dialogs for destructive actions (delete stack, unmount disk)

### Phase 2: Storage Enhancements ⭐ PRIORITY

#### SSHFS Mount Management UI
- [ ] List configured SSHFS mounts
- [ ] Add new SSHFS mount form:
  - Remote host/IP
  - Remote path
  - Local mount point
  - SSH user
  - SSH key selection or password
  - Mount options (reconnect, compression, etc.)
- [ ] Mount/unmount controls
- [ ] Connection status indicator
- [ ] Auto-mount on boot (fstab integration)
- [ ] Credential storage (secure)

#### Disk SMART Health Display
- [x] Read SMART data via smartctl
- [x] Display health summary per disk:
  - Overall health status (PASSED/FAILED)
  - Temperature
  - Power-on hours
  - Reallocated sectors
  - Pending sectors
  - NVMe percentage used / available spare
- [x] Warning indicators for concerning values
- [x] SMART test scheduling (short/long)
- [ ] Historical SMART data tracking
- [ ] Alerts when SMART values degrade

### Phase 3: Plugin System Enhancement ⭐ PRIORITY (Long Term)

#### Core Plugin Architecture
- [ ] Define plugin interface/API
- [ ] Plugin discovery and loading
- [ ] Plugin configuration storage
- [ ] Plugin enable/disable UI
- [ ] Plugin settings pages

#### Additional Filesystem Plugins
- [ ] **bcachefs** - Next-gen copy-on-write filesystem
  - Pool management
  - Replication/erasure coding settings
  - Tiered storage (SSD cache + HDD)
- [ ] **ZFS** (where available)
  - Pool creation and management
  - Dataset management
  - Snapshot scheduling
  - Scrub scheduling
- [ ] **Btrfs**
  - Subvolume management
  - Snapshot management
  - RAID configuration
  - Scrub scheduling
- [ ] **LVM**
  - Volume group management
  - Logical volume resize
  - Snapshot management
- [ ] **NFS exports** - Share folders via NFS
  - Export configuration
  - Client access rules
- [ ] **Samba shares** - Windows-compatible sharing
  - Share configuration
  - User access management

---

## Other Planned Features

### Dashboard Enhancements
- [ ] Customizable dashboard widgets
- [ ] Drag-and-drop widget arrangement
- [ ] Quick actions on home page
- [ ] System uptime display
- [ ] Recent activity log

### Container Features
- [ ] Live log streaming (WebSocket)
- [ ] Log search/filter
- [ ] Container shell access (web terminal)
- [ ] Health check status display
- [ ] Container dependency visualization
- [ ] Bulk actions (stop all, restart all)

### Monitoring & Alerts
- [ ] Historical metrics with graphs (CPU, memory, temp over time)
- [ ] Configurable alert thresholds
- [ ] Email notifications for alerts
- [ ] Push notifications (ntfy.sh, Pushover, Discord)
- [ ] Disk space warnings
- [ ] Container crash alerts

### Multi-System Management
- [ ] Manage multiple Pis from single dashboard
- [ ] Aggregate view across systems
- [ ] Sync configurations between systems

### App Store Enhancements
- [ ] User-contributed app templates
- [ ] Version tracking and update notifications
- [ ] Import/export stack configurations

---

## Development Notes

### Implementation Order

```
Phase 1 (Current Focus)
├── Bug Fixes
│   ├── 401 error handling
│   ├── favicon
│   └── theme.js fix
├── Toast Notifications
│   ├── Create notification component
│   ├── Add to all action handlers
│   └── Style variations
└── Loading Spinners
    ├── Create spinner component
    ├── Add to API calls
    └── Add to slow operations

Phase 2 (After Phase 1)
├── SSHFS Mount UI
│   ├── Backend: helper commands
│   ├── Backend: API endpoints
│   ├── Frontend: mount list
│   └── Frontend: add/edit form
└── SMART Health
    ├── Backend: smartctl parsing
    ├── Backend: API endpoints
    ├── Frontend: health cards
    └── Frontend: detail modal

Phase 3 (Long Term)
├── Plugin Architecture
│   ├── Define plugin spec
│   ├── Refactor existing plugins
│   └── Plugin manager UI
└── New Filesystem Plugins
    ├── bcachefs
    ├── ZFS
    ├── Btrfs
    └── NFS/Samba
```

### Technical Considerations

**Toast Notifications:**
- Use a notification store/queue
- CSS animations for enter/exit
- Position: top-right or bottom-right
- Z-index above modals

**Loading Spinners:**
- Inline spinners for buttons
- Overlay spinners for page sections
- Skeleton loaders for lists

**SSHFS:**
- Requires sshfs package
- Helper service needs sshfs/fusermount commands
- Credential security: use SSH keys where possible
- Consider autofs for auto-mounting

**SMART:**
- Requires smartmontools package
- Some USB enclosures don't pass SMART data
- Consider caching SMART data (expensive to query)
- Different attributes for SSD vs HDD

**Plugin System:**
- Python-based plugins
- Each plugin: manifest.json + plugin.py
- Hooks: on_load, on_config_change, get_status
- UI: plugin provides its own HTML template

---

## Progress Tracking

### Completed
- [x] Initial release
- [x] Bare metal install
- [x] Helper service
- [x] SnapRAID plugin
- [x] MergerFS plugin
- [x] Container stats (CPU/network)
- [x] Stack management
- [x] App catalog

### In Progress
- [ ] Phase 2: SSHFS (remaining)

### Completed
- [x] Phase 1: Bug fixes & polish (401 handling, favicon, toast notifications, loading spinners)
- [x] Phase 2: SMART Health (smartctl parsing, API endpoints, UI with health cards, detail modal, test scheduling)

---

## Contributing

Have an idea? Open an issue on GitHub with the `enhancement` label!

Priority is determined by:
1. User demand (issues/votes)
2. Complexity vs. value
3. Alignment with project goals (lightweight, Pi-focused)
