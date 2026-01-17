# Pi-Health Roadmap

A living document tracking planned improvements and feature ideas.

## Current Status

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

## Short Term (Next Release)

### Bug Fixes & Polish
- [ ] Handle 401 auth errors gracefully (redirect to login)
- [ ] Add favicon
- [ ] Fix theme.js 404 error
- [ ] Improve mobile responsiveness
- [ ] Add loading spinners for slow operations

### UX Improvements
- [ ] Toast notifications for actions (start/stop/restart)
- [ ] Confirmation dialogs for destructive actions
- [ ] Remember last visited tab in stack modal
- [ ] Auto-refresh toggle for containers page

---

## Medium Term

### Dashboard Enhancements
- [ ] Customizable dashboard widgets
- [ ] Drag-and-drop widget arrangement
- [ ] Quick actions on home page (restart stack, etc.)
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
- [ ] Push notifications (ntfy.sh, Pushover, etc.)
- [ ] Disk space warnings
- [ ] Container crash alerts

### Storage Improvements
- [ ] SSHFS mount management UI
- [ ] Disk health monitoring (SMART data display)
- [ ] Storage usage breakdown by folder
- [ ] SnapRAID sync progress indicator
- [ ] Scheduled scrub status

---

## Long Term

### Multi-System Management
- [ ] Manage multiple Pis from single dashboard
- [ ] Aggregate view across systems
- [ ] Sync configurations between systems

### Advanced Features
- [ ] Backup to cloud (rclone integration)
- [ ] VPN status indicator and controls
- [ ] Network traffic monitoring per container
- [ ] Reverse proxy management (Traefik/Caddy integration)
- [ ] SSL certificate management
- [ ] Scheduled system updates

### App Store Enhancements
- [ ] User-contributed app templates
- [ ] App ratings and reviews
- [ ] Version tracking and update notifications
- [ ] App configuration presets
- [ ] Import/export stack configurations

### Developer Experience
- [ ] API documentation
- [ ] Plugin system for custom extensions
- [ ] Webhook support for automation
- [ ] CLI tool for headless management

---

## Ideas Under Consideration

These need more thought/discussion:

- [ ] Home Assistant integration
- [ ] Prometheus/Grafana export
- [ ] Kubernetes support (k3s)
- [ ] ARM64 Docker image optimization
- [ ] Offline/local app catalog
- [ ] Two-factor authentication
- [ ] LDAP/SSO integration
- [ ] Dark/light mode toggle (beyond themes)
- [ ] Localization (i18n)

---

## Contributing

Have an idea? Open an issue on GitHub with the `enhancement` label!

Priority is determined by:
1. User demand (issues/votes)
2. Complexity vs. value
3. Alignment with project goals (lightweight, Pi-focused)

---

## Changelog

### v1.0.0 (Current)
- Initial release with core features
- Bare metal install support
- Helper service for privileged operations
