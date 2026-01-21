# MergerFS Roadmap

Goal: bring MergerFS setup and management in Pi-Health up to the official QuickStart expectations and make the Pools UI fully operable for MergerFS.

1) MergerFS-specific config UI
   - Create a custom form in `static/pools.html` for `mergerfs` that edits `config.pools[]` objects (not a flat key/value form).
   - Support add/remove pools, add/remove branches, mount point, create policy, min_free_space, options, enabled.
   - Provide sensible defaults for a new pool (name, mount point under `/mnt`, default policy).
   - Surface validation errors in the modal with clear field-level hints.

2) Persist configuration (apply)
   - Extend `MergerFSPlugin.apply_config()` to write system configuration, not just validate.
   - Write/replace `/etc/fstab` entries for each enabled pool (backup existing file first).
   - Optional: support `/etc/mergerfs/config/<pool>.ini` and `/etc/mergerfs/branches/<pool>/` symlinks for “config file” approach.
   - Ensure apply is safe: remove stale entries for pools that no longer exist or are disabled.

3) Unify mount options and QuickStart presets
   - Update `_cmd_mount()` to use the same options as `_generate_fstab_entry()`.
   - Allow `options` to override defaults (including `func.getattr`, `dropcacheonclose`, `cache.files`).
   - Add QuickStart presets (Linux >= 6.6 vs <= 6.5 + mmap) as selectable options in the UI.
   - Ensure `fsname=mergerfs` is consistent for live mounts and fstab.

4) Per-pool commands
   - Update Pools UI to pass `pool_name` for MergerFS commands (Mount/Unmount/Balance).
   - Provide a dropdown or prompt in the command section for pool selection.
   - Validate pool selection before running commands and show a friendly error if missing.

5) Status rendering
   - Update Pools UI to display per-pool status from `status.details.pools[]` for MergerFS.
   - Show mounted state, branch count, used percent, and mount point.
   - Make status reflect degraded pools when any mount is missing.

6) Stronger validation and safety checks
   - Validate branch paths exist and are distinct.
   - Validate mount points exist or are creatable under `/mnt`.
   - Validate `min_free_space` format (e.g., `4G`, `500M`).
   - Optional: check for `user_allow_other` when `allow_other` is used and warn in UI.
