# App Catalog Guide (Pi-Health)

Goal
- Provide an "app store" UX for building a single compose stack.
- Allow add/remove services without deleting host config folders.
- Handle VPN service as an optional dependency.

Core decisions
- Single stack (one compose file).
- VPN is optional globally, required only for apps that declare `requires: ["vpn"]`.
- Removing an app removes its service entry only (no host cleanup).

Catalog structure (proposal)
- Store templates in `catalog/` as YAML files.
- Each file defines:
  - `id`, `name`, `description`
  - `service` (compose service block)
  - `fields` (form inputs to fill template vars)
  - `requires` (dependencies like `vpn`)
  - `disabled_by_default` for optional apps

Template format
```yaml
id: sonarr
name: Sonarr
description: TV show manager
requires: ["vpn"]
disabled_by_default: false
fields:
  - key: TZ
    label: Timezone
    default: Europe/London
  - key: PUID
    label: PUID
    default: "1000"
  - key: PGID
    label: PGID
    default: "1000"
  - key: CONFIG_DIR
    label: Config root
    default: "/home/lucy/docker"
  - key: STORAGE_MOUNT
    label: Storage mount
    default: "/mnt/storage"
  - key: DOWNLOADS
    label: Downloads mount
    default: "/mnt/downloads"
service:
  image: linuxserver/sonarr:latest
  container_name: sonarr
  network_mode: "service:vpn"
  environment:
    - TZ={{TZ}}
    - PUID={{PUID}}
    - PGID={{PGID}}
  volumes:
    - {{CONFIG_DIR}}/sonarr:/config
    - {{STORAGE_MOUNT}}/tv:/tv
    - {{DOWNLOADS}}:/downloads
  restart: unless-stopped
```

VPN template example
```yaml
id: vpn
name: Gluetun VPN
description: VPN gateway for dependent services
fields:
  - key: CONFIG_DIR
    label: Config root
    default: "/home/lucy/docker"
  - key: VPN_ENV
    label: VPN env file
    default: "/home/lucy/docker/vpn/.env"
service:
  image: qmcgaw/gluetun:latest
  container_name: vpn
  cap_add:
    - NET_ADMIN
  devices:
    - /dev/net/tun:/dev/net/tun
  volumes:
    - {{CONFIG_DIR}}/vpn:/gluetun
  env_file:
    - {{VPN_ENV}}
  healthcheck:
    test: ["CMD-SHELL", "test -e /dev/net/tun && ip a show tun0 | grep -q inet"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 30s
  restart: unless-stopped
  ports:
    - 9117:9117
    - 8989:8989
    - 7878:7878
    - 9091:9091
    - 6789:6789
    - 6500:6500
    - 8686:8686
    - 8080:8080
    - 51413:51413
  networks:
    - vpn_network
```

Backend API (proposal)
- `GET /api/catalog` -> list templates (id, name, description, requires, disabled_by_default).
- `GET /api/catalog/<id>` -> full template with fields + service.
- `POST /api/catalog/install` -> payload: `{ id, values, stack }`.
- `POST /api/catalog/remove` -> payload: `{ id, stack }`.
- `GET /api/catalog/status` -> installed apps (based on current compose services).

Install flow
1) Client requests template details.
2) Client renders form from `fields` and collects values.
3) Server renders template with values (simple string replace `{{KEY}}`).
4) Server loads compose file (YAML), inserts service under `services:`.
5) If `requires` unmet (e.g., `vpn` missing), prompt:
   - "Add VPN now?" -> install `vpn` then proceed.
6) Save compose file and optionally run `docker compose up -d <service>`.

Remove flow
1) Server loads compose file, removes service key.
2) Do NOT delete host folders.
3) Optionally run `docker compose up -d` to reconcile.

Dependency rules
- If a service uses `network_mode: service:vpn`, enforce `requires: ["vpn"]`.
- Validate before install:
  - Required fields present.
  - Ports are not already in use (basic check).
  - Target compose file exists.

UI (proposal)
- New "Apps" page under navigation.
- App grid with "Install" or "Remove".
- Form modal for required fields.
- Warning banner if VPN required.
- "Installed" state based on `services` keys.

Safety and compatibility
- Ensure stack compose remains valid YAML.
- Keep a backup before writing (reuse existing backup logic).
- Allow advanced users to edit raw compose.

Implementation order
1) Catalog template format + loader.
2) Install/remove endpoints.
3) Apps UI (list + form modal).
4) Dependency prompts (VPN required).

Current status (in repo) - COMPLETE
- Catalog API fully implemented in `catalog_manager.py`:
  - `GET /api/catalog` (list)
  - `GET /api/catalog/<id>` (detail)
  - `GET /api/catalog/status` (installed services)
  - `POST /api/catalog/install` (fully implemented)
  - `POST /api/catalog/remove` (fully implemented)
  - `POST /api/catalog/check-dependencies` (new endpoint)
- Apps UI page at `static/apps.html` with:
  - Install modal with form fields
  - Remove with confirmation
  - Dependency prompts (VPN required)
- Catalog templates in `catalog/`:
  - vpn.yaml (Gluetun VPN gateway)
  - sonarr.yaml (TV show manager)
  - radarr.yaml (Movie manager)
  - prowlarr.yaml (Indexer manager)
  - transmission.yaml (Torrent client)
  - portainer.yaml (Docker management UI)
- 27 tests in `tests/test_catalog.py`

Features implemented:
- Template rendering with {{KEY}} variable substitution
- Dependency checking and enforcement
- Backup before compose file modifications
- Atomic file writes
- Optional service start after install
- Container stop/rm on remove
- Dependent service detection on remove
