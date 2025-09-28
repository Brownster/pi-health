# TRaSH Guides Auto‑Tuning (Assistant Design + Ready‑to‑Use Snippets)

This document shows how to let your ops‑copilot **suggest and (with approval) apply updates** based on the best practices from TRaSH‑Guides (folder structure, naming, quality profiles, release profiles, minimum file sizes, indexer categories, etc.). It uses your existing **Gateway + MCP** pattern and never changes anything without an explicit click‑to‑approve.

> TL;DR: The assistant reads current settings from Sonarr/Radarr/Prowlarr/Jellyfin → compares to curated TRaSH presets → renders a **dry‑run diff** → you approve → it applies via MCP tools and verifies.

---

## 0) Goals & Guardrails

* **Goals**

  * Keep libraries consistent with TRaSH: structure, naming, profiles, sizes, and filters.
  * Produce friendly, actionable **diffs** the family can understand.
  * Apply changes safely with rollback and audit.
* **Guardrails**

  * Read vs. Write split (dry‑run by default, approval for changes).
  * JSON Schema validation for all mutations; cooldowns; output redaction.
  * Version every preset set you apply (e.g., `trash:v2025-09-01`).

---

## 1) Data Sources (curated presets)

Create a small repo/folder in your ops project, pinning curated presets from TRaSH so you’re not scraping live content at runtime:

```
ops/trash-presets/
  radarr/
    quality-profiles/uhd-2160p-hybrid.json
    quality-profiles/hd-1080p-web.json
    release-profiles/radarr-remux-preferred.json
  sonarr/
    quality-profiles/uhd-2160p-webdl.json
    quality-profiles/hd-1080p-webdl.json
    release-profiles/sonarr-anime-smart.json
    release-profiles/sonarr-web-group-preferred.json
  common/
    file-naming/movie-naming.json
    file-naming/series-naming.json
    min-file-sizes.json
    folder-structure.json
    prowlarr-categories.json
```

> Tip: Store each preset with a `version`, `source`, `notes`, and a `checksum` so the assistant can detect drift.

---

## 2) Safe Workflow (what the assistant does)

1. **Collect** current config & telemetry via MCP:

   * Sonarr: `system/status`, `qualityProfile`, `releaseProfile`, `rootFolder`, `naming/config`, `mediaManagement`, `downloadClient`.
   * Radarr: same set for movies.
   * Prowlarr: `indexer` list, `categories`, `appProfiles`.
   * Jellyfin: library names/paths for cross‑checking naming compatibility.
2. **Compare** to pinned TRaSH presets → build a **proposed change set**.
3. **Render Dry‑Run**: unified diffs + a natural language summary.
4. **Approval** (per change family): naming, profiles, sizes, folders, indexers.
5. **Apply** via MCP tools (Radarr/Sonarr/Prowlarr endpoints) and verify.
6. **Rollback**: the assistant keeps pre‑change snapshots; one‑click revert.

---

## 3) Folder Structure (TRaSH‑style)

**Recommended**

```
/mnt/storage/Media/
  Movies/
    {Movie Title} ({Year})/
      {Movie Title} ({Year}).{imdbId}-{Edition?}.{Quality}.{ReleaseGroup}.{ext}
  TV/
    {Series Title} ({Year})/
      Season {season:00}/
        {Series Title} - S{season:00}E{episode:00} - {Episode Title}.{Quality}.{ReleaseGroup}.{ext}
```

**Why**

* Consistent parent folders; simple for Jellyfin scanners.
* Edition & Quality tokens keep remux/uhd separate from webrips.

**Gateway Rule**

* If root folders aren’t exactly `Movies` & `TV` under your storage path, propose to:

  * create the folders,
  * move existing items (dry‑run size/time estimate first), or
  * update Sonarr/Radarr root folder settings to the canonical paths.

---

## 4) File Naming Presets (examples)

### Movies (Radarr)

```
{Movie Title} ({Release Year}){[ - {Edition Tags}]} [{Quality Full}]{[ {MediaInfo VideoDynamicRange}]} - {Release Group}
```

* Examples:

  * `Dune (2021) [UHD Remux] [HDR10+] - FGT.mkv`
  * `The Martian (2015) [1080p WEB-DL] - NTb.mkv`

### Series (Sonarr)

```
{Series Title} ({Series Year}) - S{season:00}E{episode:00} - {Episode Title} [{Quality Full}] - {Release Group}
```

* Examples:

  * `Severance (2022) - S01E01 - Good News About Hell [1080p WEB-DL] - AMZN.mkv`
  * `Bluey (2018) - S03E14 - Obstacle Course [2160p WEB-DL][DV HDR10+] - TEPES.mkv`

**MCP actions**: the assistant sets Sonarr/Radarr `namingConfig` to these templates (dry‑run first, then apply).

---

## 5) Quality Profiles (ready‑to‑POST payloads)

> Keep only a few, family‑friendly presets. Below are representative payloads. Adjust IDs at runtime based on your instance.

### Radarr: UHD‑2160p (prioritize **Remux**, prefer **DV/HDR10+**, allow **WEB** fallback)

```json
{
  "name": "TRaSH UHD‑2160p (Remux→WEB)",
  "upgradeAllowed": true,
  "cutoff": 0,
  "items": [
    {"quality": {"id": 50, "name": "UHD Bluray Remux"}, "allowed": true},
    {"quality": {"id": 51, "name": "UHD Bluray"},       "allowed": true},
    {"quality": {"id": 19, "name": "WEBDL-2160p"},      "allowed": true},
    {"quality": {"id": 20, "name": "WEBRip-2160p"},     "allowed": true},
    {"quality": {"id": 18, "name": "WEBDL-1080p"},      "allowed": false}
  ],
  "formatItems": [
    {"format": {"name": "REMUX"},     "score": 1000},
    {"format": {"name": "DV"},        "score": 200},
    {"format": {"name": "HDR10+"},    "score": 180},
    {"format": {"name": "HDR10"},     "score": 120},
    {"format": {"name": "AMZN|NF"},   "score": 40}
  ]
}
```

### Radarr: HD‑1080p (prefer **WEB‑DL**, de‑prefer re‑encodes)

```json
{
  "name": "TRaSH HD‑1080p (WebDL)",
  "upgradeAllowed": true,
  "cutoff": 0,
  "items": [
    {"quality": {"id": 18, "name": "WEBDL-1080p"}, "allowed": true},
    {"quality": {"id": 17, "name": "WEBRip-1080p"},"allowed": true},
    {"quality": {"id": 7,  "name": "Bluray-1080p"}, "allowed": false}
  ],
  "formatItems": [
    {"format": {"name": "WEB-DL"}, "score": 150},
    {"format": {"name": "x265"},   "score": -100}
  ]
}
```

### Sonarr: UHD‑2160p WEB (DV/HDR+) + HD fallback for kids content

```json
{
  "name": "TRaSH UHD‑2160p Series (WEB)",
  "upgradeAllowed": true,
  "cutoff": 0,
  "items": [
    {"quality": {"id": 21, "name": "WEBDL-2160p"}, "allowed": true},
    {"quality": {"id": 22, "name": "WEBRip-2160p"},"allowed": true},
    {"quality": {"id": 5,  "name": "WEBDL-1080p"}, "allowed": true}
  ],
  "formatItems": [
    {"format": {"name": "DV"},     "score": 200},
    {"format": {"name": "HDR10+"}, "score": 180},
    {"format": {"name": "HDR10"},  "score": 120}
  ]
}
```

> The assistant maps actual `quality.id` values from your instance (`/api/v3/qualitydefinition`) before POSTing.

---

## 6) Release Profiles (filters & preferred words)

**Radarr (examples)**

```json
{
  "enable": true,
  "required": [],
  "ignored": ["cam|ts|telecine|r5|hdtv"],
  "preferred": [
    {"term": "remux", "score": 1000},
    {"term": "dv",    "score": 200},
    {"term": "hdr10+", "score": 180}
  ]
}
```

**Sonarr (examples)**

```json
{
  "required": ["web[-_. ]?dl|amzn|nf"],
  "ignored":  ["(?:^|[ ._-])(rawhd|hdtv|xvid)(?:$|[ ._-])"],
  "preferred": [
    {"term": "proper", "score": 50},
    {"term": "repack", "score": 40}
  ]
}
```

> Keep regexes simple and well‑commented. The assistant explains every rule in plain English before applying.

---

## 7) Minimum File Sizes (sanity checks)

Create `common/min-file-sizes.json` (examples):

```json
{
  "movie": {
    "2160p":  ">= 4.0 GB",
    "1080p":  ">= 1.8 GB",
    "720p":   ">= 1.0 GB"
  },
  "series": {
    "2160p":  ">= 2.5 GB",
    "1080p":  ">= 1.2 GB",
    "720p":   ">= 0.7 GB"
  }
}
```

**Assistant behavior**

* Computes rolling medians from your library.
* Flags items below thresholds with rationale: “Likely re‑encode/low bitrate WEBRip; you can keep, upgrade, or ignore for Kids.”

---

## 8) Prowlarr Categories & App Sync

`common/prowlarr-categories.json` (excerpt):

```json
{
  "usenet": ["2000", "2010", "2030", "2040"],
  "torrent": ["5000", "5010", "5040"]
}
```

* Assistant checks that Radarr/Sonarr app‑sync in Prowlarr maps these categories correctly.
* On drift, proposes a small patch (dry‑run first).

---

## 9) Hardlinks, Import & Permissions

* Sonarr/Radarr: enable **Completed Download Handling**, **Use Hardlinks** (if the filesystem allows), **Create empty series folders**.
* Ensure SABnzbd/clients download into a path on the same filesystem as the library for hardlinks.
* Umask/PUID/PGID: keep consistent across containers; assistant verifies and suggests fixes if permissions cause import failures.

---

## 10) MCP Tooling (what you’ll add)

Add **read‑only** tools for diffing + **mutating** tools for applying presets.

**Read‑only**

* `arr_get_quality_profiles(app)` → JSON
* `arr_get_release_profiles(app)` → JSON
* `arr_get_naming_config(app)` → JSON
* `arr_get_root_folders(app)` → JSON
* `prowlarr_get_categories()` → JSON

**Mutating (approval required)**

* `arr_set_quality_profile(app, payload)`
* `arr_set_release_profile(app, payload)`
* `arr_set_naming_config(app, payload)`
* `prowlarr_set_categories(payload)`

> Keep all payloads validated against schemas stored in your `policy.yaml`.

---

## 11) Gateway: Dry‑Run Report (example)

**Summary**

* Naming: 2 differences (Movies, Series)
* Quality Profiles: Radarr (add UHD preset), Sonarr (update UHD WEB)
* Release Profiles: Add Radarr DV/HDR preferences
* Prowlarr: Add Newznab 2040 (UHD) to Radarr app sync

**Diffs (unified)**

```diff
--- radarr.naming.json (current)
+++ radarr.naming.json (proposed)
@@
- "movieFormat": "{Movie Title} ({Release Year}) - {Quality} - {Release Group}"
+ "movieFormat": "{Movie Title} ({Release Year}){[ - {Edition Tags}]} [{Quality Full}]{[ {MediaInfo VideoDynamicRange}]} - {Release Group}"
```

```diff
--- prowlarr.categories.json (current)
+++ prowlarr.categories.json (proposed)
@@
- "usenet": ["2000","2010","2030"]
+ "usenet": ["2000","2010","2030","2040"]
```

**Action Cards**

* [Apply naming changes] [Apply Radarr profiles] [Apply Sonarr profiles] [Update Prowlarr]

---

## 12) Rollback Plan

* Before each mutation, snapshot the current document (`arr_backup/DATE/*.json`).
* One‑click **Revert** re‑POSTs the snapshot payloads.
* Keep last 10 snapshots per app.

---

## 13) Testing Plan

* **Unit**: schema validation, mapper from preset → instance IDs, diff builder.
* **Integration**: fake instances or dev stack with minimal libraries; confirm dry‑run output.
* **E2E**: approve in UI → POST → verify applied → confirm Jellyfin scans succeed with new names.

---

## 14) Example Prompts for the Family

* “Make our Movies & TV match the TRaSH guide.”
* “Why are some episodes tiny? Are they okay?”
* “Prefer Remux for movies but allow WEB if remux isn’t available.”
* “Add UHD indexer categories to Radarr.”

---

## 15) Ready‑to‑Use API Paths (Sonarr/Radarr)

* Sonarr: `/api/v3/qualityprofile`, `/api/v3/releaseprofile`, `/api/v3/naming`, `/api/v3/rootfolder`, `/api/v3/qualitydefinition`
* Radarr: same endpoints but movie‑scoped.
* Prowlarr: `/api/v1/indexer`, `/api/v1/applications/*`, `/api/v1/indexer/categories`

> The assistant uses your MCP servers to call these; the gateway keeps policy and approvals centralized.

---

## 16) Jellyfin Compatibility Checks

* Ensure series/episode patterns match Jellyfin’s TV naming recommendations.
* Validate library paths match your root folder changes.
* After renaming, assistant runs a targeted Jellyfin library refresh (with concurrency limits) to avoid spikes on the Pi.

---

## 17) Deliverables to Add to Your Repo

* `ops/trash-presets/**` (pinned presets + versions)
* `gateway/policy.yaml` (schemas + cooldowns)
* `gateway/tool_registry.yaml` (new tools + read/write flags)
* `gateway/prompts/trash_advisor.md` (system prompt for the AI)
* `tests/trash_diff.spec.ts` (diff + dry‑run unit tests)

---

### Done.

With this in place, the assistant can **suggest** TRaSH‑aligned updates, explain exactly what would change, and—only with your approval—apply them safely. If you want, I can generate the initial `ops/trash-presets/*` JSON files to get you started.
