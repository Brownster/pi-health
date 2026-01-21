# SnapRAID Improvement Roadmap

This roadmap converts the SnapRAID manual + log tags docs into concrete implementation upgrades for Pi-Health.

## 1) Command execution & log-tag parsing
- Add `--log "&>2"` (or file) + `--gui` to SnapRAID invocations so we can parse structured tags.
- Build a log-tag parser that turns tags into events (config summary, scan diffs, progress, errors, thermal stats).
- Use tag events to power progress UI: `run:pos`, `summary:*`, `msg:error|fatal`, `scan:*` counts.
- Emit normalized result payloads from SnapRAID commands where possible.

## 2) Status, diff, and health accuracy
- Replace regex-only parsing with log tags for `status`/`diff` where available.
- Track and expose:
  - last sync/scrub timestamps.
  - counts of added/removed/updated/moved/copied/restored from `summary:*`.
  - missing/damaged file counts via tags or structured parsing.
- Add explicit “sync required” / “safe to sync” signals based on tag summaries.

## 3) Config generation & validation upgrades
- Enforce SnapRAID requirements in UI + backend:
  - at least one parity, one data, one content file (already).
  - content files on multiple disks (best practice from docs).
  - warn if parity drive(s) smaller than largest data drive.
- Expose config options from docs:
  - `pool` (optional) with warning that mergerfs is recommended.
  - `autosave`, `hashsize`, `blocksize`, `nohidden`, `prehash` (already in config; add doc tooltips).
- Generate content files on multiple disks when marked by user.

## 4) Safety workflows
- Before `sync`, run `diff` and enforce delete/update thresholds using tag summary counts.
- Add “dry-run / check” path: `diff` + confirmation when deletions are high.
- Add `fix` filters: expose `-m` / `-e` options for missing/damaged via recovery options.

## 5) Scheduling & operations
- Add scrub options: `-p` percent and `-o` age; allow `-p bad` for targeted scrub.
- Update systemd unit ExecStart to include configured `-c` path and optional log tag output.
- Persist SnapRAID logs for history view (timestamped file via `--log ">>..."`).

## 6) UI enhancements (Pools)
- Show structured status cards (added/removed/updated, missing/damaged).
- Live progress: percent, ETA, speed, CPU from `run:pos` tags.
- Recovery actions: “Fix missing” / “Fix damaged” buttons based on recovery options.

## 7) Helper & API changes
- Extend helper `cmd_snapraid` to accept:
  - `conf_path`, `log_target`, `gui`, and extra args (percent, age_days, filter).
- Return parsed tag events (or raw log lines + parsed summary if tags unavailable).

## 8) Tests
- Unit tests for log-tag parser with samples from `Docs/snapraid-logtags.txt`.
- Tests for:
  - config generation with multiple parity/content drives.
  - threshold enforcement using tag summary.
  - command param assembly (`--log`, `--gui`, `-p`, `-o`, `-e`, `-m`).
