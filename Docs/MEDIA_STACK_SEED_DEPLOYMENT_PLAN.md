# Media Stack Seed Deployment — Implementation Plan

Status: In implementation — Phase 0 complete
Audience: implementing developer (assumes familiarity with the repo's service/helper/route pattern)
Owner: LimeOS / Pi-Health maintainers

Progress:
- 2026-07-09: Phase 0 implemented. Added the pure canonical `media_layout.py` model and
  layout-backed catalog defaults for media apps; installs now resolve the same layout defaults as
  catalog reads.
- 2026-07-09: Phase 1 implemented. Added helper-backed canonical folder provisioning plus
  `/api/media/layout` read/save and `/api/media/layout/provision` routes.
- 2026-07-09: Phase 2 implemented for the core media stack. Normalised download/container path
  contracts and added declarative `seed:` metadata for *arr apps, Prowlarr, download clients,
  Jackett, and Jellyfin.
- 2026-07-09: Phase 3A implemented. Added the Servarr client, streamed `/api/media/seed`
  backend, and idempotent *arr root/download-client seeding that removes forbidden
  `/downloads/...` root folders before adding canonical library roots.

## Context — why we are doing this

A real deployment (a family media Pi) filled its 120 GB download disk and stopped
importing. Root-causing it revealed the failure was **built into how we ship apps**, not
operator error:

- **Radarr and Sonarr had root folders pointing at the download directory**
  (`/downloads/completed/...`). So imported items were considered "already in place" and
  never moved to `/mnt/storage`; they piled up on the download disk forever.
- **Catalog defaults are inconsistent**: `catalog/sonarr.yaml` defaults the library to
  `/mnt/storage/tv`, `catalog/radarr.yaml` to `/mnt/storage/movies` (lowercase), while real
  libraries drifted to `TV`/`Movies` — producing duplicate case-variant folders.
- **`catalog_service.install()` only writes Docker volumes.** It never configures the app's
  own settings (root folders, download clients, categories, "remove completed"), so the
  operator hand-wires each *arr and can easily pick the wrong path.
- Downloads (`/mnt/downloads`, nvme) and media (`/mnt/storage`, sdb1) are separate
  filesystems, so imports **copy then delete** (move-on-complete). That is fine and is the
  chosen model — but it only reclaims space if the root folder is the library, which it wasn't.

## Goal & scope (decisions already made — do not re-litigate)

Ship the media stack so that **an operator who accepts every default gets a correct, working,
self-cleaning system**. Specifically:

- **Logical defaults**: accept-the-defaults → working system. No manual *arr configuration required.
- **Move-on-complete, not hardlinks**: keep the two-root `/mnt/storage` + `/mnt/downloads` model
  (may be separate disks). Imports move (copy+delete). Do **not** build a single-`/data`/hardlink layout.
- **Seed config**: opinionated, best-practice defaults equivalent to "configured by someone who
  knows what they're doing" — safety-critical wiring **plus** sensible quality/naming/recycle-bin.
- **Apply any safe out-of-the-box tweaks** that improve reliability (see §"Out-of-the-box tweaks").
- **Clean-install focus**: optimise for fresh deployments. Retrofit of existing installs is a
  bonus (the doctor, Phase 6), and nothing here may break an already-working stack.
- **Backup-able**: the layout + seed profile must be captured by backups and re-importable on a new Pi.

## The canonical layout contract (single source of truth)

One definition all apps derive from. Casing is **lowercase, fixed** (pick one, enforce
everywhere — this kills the `tv`/`TV` duplication).

```
storage_root   = /mnt/storage          # media library (may be its own disk)
downloads_root = /mnt/downloads         # download scratch (may be its own disk)
config_root    = /home/pi/docker        # per-app /config volumes
backup_root    = /mnt/backup

library/            (under storage_root)     downloads/         (under downloads_root)
  movies                                       incomplete/
  tv                                           complete/
  music                                          sonarr/       (Sonarr category)
  books                                          radarr/       (Radarr category)
  audiobooks                                     lidarr/       ...
  podcasts                                       readarr/
```

Container mount contract for media apps (unchanged style, made **consistent**):
- Library mount: `${storage_root}/<lib>:/<lib>` (e.g. `/mnt/storage/tv:/tv`).
- Downloads mount: `${downloads_root}:/downloads` — **identical container path in every app**.
- The *arr **root folder is the library mount** (`/tv`, `/movies`, …) — **never** `/downloads/...`.
- Download client completed dir = `/downloads/complete/<category>`; the *arr imports (moves)
  from there into its root folder.

## Architecture

Follow the existing pattern everywhere: **framework-neutral service module** (logic) +
**thin Flask route** in a `*_manager`/`app.py` blueprint (transport) + **privileged actions in
`pihealth_helper.py`** behind the command whitelist. Long-running work uses the streamed
background-operation transport (`OperationRegistry` + `operation_sse.stream_operation_response`);
copy `pihealth_update_service.py` + its route in `app.py` as the reference implementation.

New/changed components:

| Component | Kind | Purpose |
|---|---|---|
| `media_layout.py` | new module | Canonical layout constants + derivation helpers |
| `media_layout_service.py` | new service | Read/persist layout; drive folder provisioning |
| `media_seed_service.py` | new service | Data-driven *arr/client/mediaserver auto-config engine |
| `arr_client.py` | new module | Minimal REST client for Servarr apps (root folders, download clients, etc.) |
| `catalog/*.yaml` | edit | Consistent defaults + a `seed:` block per relevant app |
| `pihealth_helper.py` | edit | `media_layout_provision` command (mkdir/chown as root) |
| `app.py` / `catalog_manager.py` | edit | New routes; derive catalog defaults from layout |
| `backup_service.py` | edit | Include layout + seed profile in backup sources |
| `frontend/src/pages/apps-page.tsx` + `lib/` | edit | Quickstart card, provision/seed UI, streamed log |

---

## Phase 0 — Canonical layout model (foundation)

**Ticket 0.1 — `media_layout.py`**
- Define constants for the layout above and a `MediaLayout` dataclass with fields
  `storage_root, downloads_root, config_root, backup_root`.
- Helpers: `library_path(kind)`, `library_container_path(kind)` (`/tv`, `/movies`…),
  `download_incomplete_path()`, `download_complete_path(category)`, `all_library_dirs()`,
  `all_download_dirs()`.
- `LIBRARY_KINDS = {movies, tv, music, books, audiobooks, podcasts}` and
  `DOWNLOAD_CATEGORIES = {sonarr, radarr, lidarr, readarr, ...}`.
- Pure module, no I/O. Fully unit-tested.

**Ticket 0.2 — Derive catalog defaults from the layout**
- Today `catalog_manager._load_media_paths()` seeds only `downloads/storage/backup/config`, and
  `catalog_service.get_item(apply_media_paths=True)` maps a few field keys to those. Extend this so
  **every media app's path field defaults are computed from `MediaLayout`** (library + downloads
  subpaths), replacing the hardcoded per-app strings.
- Fix all lowercase/uppercase drift to the canonical scheme in one place.
- Acceptance: `GET /api/catalog/<id>?apply_media_paths=1` for sonarr/radarr/jellyfin/sabnzbd/transmission
  returns canonical, mutually-consistent defaults sourced from the layout. No hardcoded `tv`/`movies`
  literals remain in those YAMLs' defaults (they reference the layout).

---

## Phase 1 — Folder provisioning

**Ticket 1.1 — Helper command `media_layout_provision`**
- Add to `pihealth_helper.py` `COMMANDS`. Params: `storage_root, downloads_root, puid, pgid`.
- Validate roots are absolute and under `/mnt` (reuse the validation style of existing commands).
- Idempotently `mkdir -p` every dir in `all_library_dirs()` + `all_download_dirs()`, then
  `chown -R puid:pgid` and `chmod 0775`. Return `{created:[...], existing:[...]}`.
- Runs as root (the helper). Unit test: path validation rejects non-`/mnt`; idempotent on re-run.

**Ticket 1.2 — Service + route**
- `media_layout_service.py`: `provision()` calls the helper via the injected `HelperPort`; `layout()`
  returns the current `MediaLayout` (persisted at `${CONFIG_DIR}/media_layout.json`, `CONFIG_DIR` =
  `/etc/limeos` from `runtime_paths.py`; default from layout constants).
- Routes in `app.py` (core_api): `GET /api/media/layout`, `POST /api/media/layout/provision`
  (`@login_required @csrf_protect`).
- Acceptance: on a fresh box one POST creates the full tree owned by `1000:1000`; re-running is a no-op.

---

## Phase 2 — Catalog consistency + `seed:` metadata

**Ticket 2.1 — Normalise media app YAMLs**
- For every media app in `catalog/` (`sonarr, radarr, lidarr, prowlarr, jackett, sabnzbd,
  transmission, rdtclient, jellyfin, get_iplayer, jellyseerr, …`): make the volume mounts follow
  the container contract, downloads mounted identically as `/downloads`, and completed paths
  category-scoped (`/downloads/complete/<category>`). Defaults come from the layout (Phase 0).

**Ticket 2.2 — Add a declarative `seed:` block** to each app that needs post-install config. Example
(`catalog/sonarr.yaml`):

```yaml
seed:
  kind: arr                       # arr | downloadclient | indexer | mediaserver
  api:
    port: 8989
    config_file: "{{CONFIG_DIR}}/sonarr/config.xml"   # source of the API key
  root_folders: ["/tv"]           # library container path — NEVER /downloads
  forbid_root_under: ["/downloads"]
  download_clients:               # wire to sibling clients if present in the stack
    - implementation: Transmission
      category: sonarr
      remove_completed: true
      remove_failed: true
    - implementation: Sabnzbd
      category: sonarr
      remove_completed: true
  import_mode: move
  quality_profile: HD-1080p
  naming: standard
  recycle_bin: "/tv/.recycle"     # recoverable deletes
```

- This makes the seed engine (Phase 3) **data-driven** — no per-app Python.
- Acceptance: rendered compose for the media apps uses canonical paths; each seedable app carries a
  valid `seed:` block (add a schema-validation unit test over all catalog YAMLs).

---

## Phase 3 — Seed config engine (core value)

**Ticket 3.1 — `arr_client.py`** — minimal Servarr REST client (Sonarr/Radarr/Lidarr/Prowlarr share
the v3 API). Methods: `get/put/post/delete`, `read_api_key(config_xml)`, and typed helpers
`list_root_folders / add_root_folder / delete_root_folder`, `list_download_clients /
add_download_client`, `set_quality_profile_default`, `set_naming`, `set_media_management`
(recycle bin, import mode). Inject an HTTP transport so it is unit-testable with a fake.

**Ticket 3.2 — `media_seed_service.py`** — a generator `seed_stack(stack_name)` yielding streamed
operation events (mirror `pihealth_update_service.stream_update`). For each seedable service in the
stack's compose:
1. Resolve its `seed:` block + read the API key (helper reads `config_file`; the helper needs the
   config path in `ReadWritePaths`/readable — configs live under `config_root`).
2. `arr`: ensure each `root_folders` entry exists; **delete any root folder whose path starts with a
   `forbid_root_under` prefix** (this is the exact Holly bug); add/ensure each download client with
   its category + `remove_completed/remove_failed`; set import mode = move, recycle bin, quality
   profile, naming; enable Completed Download Handling.
3. `indexer` (Prowlarr): add the sibling *arr apps as Applications so indexers sync.
4. `mediaserver` (Jellyfin): create libraries pointing at the canonical media folders.
- **Idempotent + re-runnable**: check-before-create; never create a second identical client/root;
  log every change as a streamed line. Never point a root folder at downloads.

**Ticket 3.3 — Route** `POST /api/media/seed` (body: optional `stack`) → creates a
`kind='media_seed'` streamed operation returning `{operation_id, stream_url}`; add the SSE stream
route. Copy the wiring from the self-update endpoints in `app.py`.

**Ticket 3.4 — Tests** — unit-test `seed_stack` with a fake `arr_client` asserting: correct root
folder added; a pre-existing `/downloads/...` root folder is deleted; download client added once with
category + remove-completed; second run makes zero changes (idempotency). Integration test through the
streamed route with a mocked HTTP client.
- Acceptance: after installing the stack and running seed, Sonarr/Radarr have library-only root
  folders, download clients wired with categories + remove-completed, import mode = move; a test grab
  imports into the library and the source is removed. Re-running seed is a no-op.

---

## Phase 4 — "Media Server" one-click bundle

**Ticket 4.1 — Bundle definition** — introduce a catalog `bundle` (new YAML `kind: bundle`, e.g.
`catalog/bundles/media-server.yaml`) listing member app ids + install order + shared field values
(TZ, PUID/PGID, VPN toggle). Keep it data-driven.

**Ticket 4.2 — Quickstart orchestration** — `POST /api/media/quickstart` runs, as one streamed
operation: **provision folders (Phase 1) → install each member app (existing `catalog_service.install`)
→ wait healthy → seed (Phase 3)**. Reuse `OperationRegistry`; stream per-step progress.

**Ticket 4.3 — UI** — an "Install Media Server (recommended)" card pinned at the top of the app store
(`frontend/src/pages/apps-page.tsx`). One confirm dialog for the few real choices (timezone,
PUID/PGID, use VPN + creds), then a live log panel (reuse `lib/operations.ts` + the settings-page log
panel pattern from the self-update).
- Acceptance: on a clean Pi, one click yields a fully working, correctly-wired media stack with **no**
  manual *arr configuration; accepting all defaults is sufficient.

---

## Phase 5 — Backup / portable profile

**Ticket 5.1 — Include layout + seed profile in backups** — persist `media_layout.json` and a
`media_profile.json` (the resolved seed choices) under `CONFIG_DIR` (`/etc/limeos`) and add them to
`backup_service` sources (extend `DEFAULT_CONFIG`/`sources_provider`). Confirm `config_root`
(`/home/pi/docker/*`, the *arr configs) is already covered by the backup `config_dir` source.

**Ticket 5.2 — Export/import profile** — `GET /api/media/profile/export` (returns the layout + seed
choices JSON) and `POST /api/media/profile/import` (applies it: provision + seed). This lets an
operator carry a working setup to a new Pi.
- Acceptance: a backup archive contains layout + profile + app configs; on a fresh Pi, restore +
  import reproduces the working, seeded stack.

---

## Phase 6 — Media doctor (retrofit + ongoing safety; optional but recommended)

**Ticket 6.1** — `GET /api/media/doctor` runs the checks learned from the incident and returns typed
findings with optional one-click fixes (reuse the seed engine to fix):
- root folder under the downloads path (**critical**) → fix = re-seed root folders;
- download client `remove_completed` off → fix;
- media & downloads on different filesystems (info, since move-on-complete is intended);
- duplicate case-variant library dirs (e.g. `tv` **and** `TV`);
- orphaned/unimported pile-ups in the downloads tree (report size).

**Ticket 6.2 — UI** surface in the app store / settings with "Fix" buttons that call the seed engine.
- Acceptance: pointed at a Holly-style misconfig, the doctor flags the wrong root folder and the fix
  corrects it without touching unrelated config.

---

## Out-of-the-box tweaks the seed must apply (the "any tweaks we can do" ask)

Bake these into the `seed:` defaults so accept-the-defaults is genuinely production-grade:
- Download clients: **Remove Completed = on, Remove Failed = on**, category set, completed path =
  `/downloads/complete/<category>`.
- *arr **import mode = Move** (copy+delete across the two disks), Completed Download Handling enabled.
- **Recycle Bin configured** per library (recoverable deletes — the incident had 12 GB of
  months-old trash; a proper recycle bin with retention is safer than silent deletes).
- Sensible **quality profile default** (e.g. HD-1080p) and **Plex/Jellyfin-friendly naming**.
- **Prowlarr as the single indexer manager**, syncing indexers to the *arr apps.
- Jellyfin libraries pre-pointed at the canonical media folders; analytics off; auth on.
- Unmonitor/disable nothing the user added; only *add/correct* config.

## Backward-compatibility & safety rails

- Clean-install first: new defaults/paths apply to **new** installs. Do not rewrite existing stacks'
  compose or move a running operator's data. Retrofit only via the opt-in doctor (Phase 6).
- The seed engine must be **idempotent** and **additive** — check-before-create, never duplicate a
  client/root, and the only destructive action permitted is deleting a root folder that sits under a
  `forbid_root_under` prefix (the misconfiguration we are eliminating).
- Everything privileged goes through the helper whitelist; validate all paths under `/mnt`
  (`storage`/`downloads`) or `config_root`.

## Verification (end-to-end)

1. Fresh Pi, no manual config: run **Quickstart** → confirm the stack comes up, Sonarr/Radarr root
   folders are library-only, download clients wired with categories + remove-completed, import mode =
   move. Trigger one test grab; confirm it imports into `/mnt/storage/<lib>` and the download source is
   removed (space reclaimed).
2. Re-run **seed** → zero changes (idempotency).
3. Point the **doctor** at a deliberately mis-seeded app (root folder under `/downloads`) → it flags
   and fixes it.
4. **Backup → restore on a second box → import profile** → reproduces the working setup.
5. `pytest` green (new unit/integration tests for layout, provision, arr_client, seed, doctor); the
   streamed routes covered like the self-update tests.

## Suggested sequencing

Phase 0 → 1 → 2 (foundation, low risk) → **Phase 3 (the payoff)** → 4 (bundle) → 5 (backup) →
6 (doctor). Phases 0–2 are safe to merge independently; 3 is the core; 4–6 build on it.
