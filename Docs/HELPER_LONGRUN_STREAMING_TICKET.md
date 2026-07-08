# Ticket: Long-running privileged commands — helper timeout + live progress on real hardware

Date: 2026-07-07
Priority: P1 (correctness / operability on the target Pi)
Origin: Phase 4 review finding 5 (`Docs/UI_PHASE4_RELEASE_SIGNOFF.md`, Deferred item 1). This is the
"own ticket" the Phase 4 signoff was made conditional on.
Related files: `helper_client.py`, `storage_plugins/snapraid_plugin.py`, `storage_plugins/__init__.py`
(the SSE command route), `helper.py`/helper daemon.

## Problem
On real hardware (helper present) a SnapRAID `sync`/`scrub`/`diff`/`fix` runs through the helper
socket **synchronously**, and two things break:

1. **30-second client timeout on multi-minute operations.** `helper_client.helper_call` sets
   `sock.settimeout(30)` (`helper_client.py:64`) and converts a `socket.timeout` into `HelperError`
   (`helper_client.py:73`). A `sync` on a real array routinely exceeds 30s, so the UI reports an error
   **while snapraid keeps running as root inside the helper** — a confusing, split-brain state (the
   operation is progressing but the UI says it failed, and a retry could double-run it).
2. **"Live progress" is not realised on the helper path.** In `SnapRAIDPlugin.run_command` the helper
   branch (`storage_plugins/snapraid_plugin.py:598-635`) calls `helper_call('snapraid', …)` and only
   **after it returns** splits `stdout` into lines and parses log-tags (`:614-627`). So the
   `{"type":"tag",...}` progress events are all emitted at the end, not during the run. The streamed
   percent/ETA/speed the PH4-003 command runner renders (fixed in the Phase 4 review to coerce string
   tag values) therefore only appears on the **non-helper/dev subprocess path** (`:640+`), which
   streams line-by-line. Production users get a spinner that jumps straight to "done".

Net effect: PH4-003's acceptance ("commands runnable with … live progress") is met in dev but **not
verified on production hardware**, and long runs surface a spurious failure.

## Goals
1. A long privileged command (minutes) completes without a spurious UI error and without a root
   process orphaned from the UI's view.
2. Progress (log-tag events) streams to the UI **during** the run on the helper path, matching the
   dev path the command runner already consumes.
3. A repeatable **real-hardware sync smoke** that gates this ticket (and retro-validates Phase 4).

## Approach (options — pick during design)
The two goals share a root cause: the request/response helper protocol can't stream and forces a
short timeout. Options, roughly increasing in effort:

- **A. Per-command timeout override (minimum viable).** Let `helper_call` take a `timeout` (or
  `timeout=None`) and have the snapraid long-run commands pass a generous/`None` value. Removes the
  spurious failure. Does **not** deliver live progress (still one blocking round-trip) — so it only
  satisfies Goal 1.
- **B. Streaming helper responses (preferred).** Extend the helper protocol so `snapraid` with
  `log_tags` streams framed lines/tag-events back over the socket as they are produced, and have
  `run_command`'s helper branch `yield` them as it reads (mirroring the subprocess path). The SSE
  route (`storage_plugins/__init__.py`) already forwards yielded tag events. Satisfies Goals 1 + 2.
  Keep a heartbeat so an idle-but-alive long run doesn't trip any read timeout.
- **C. Async job + poll.** Helper starts the command detached, returns a job id; the UI polls
  status/among a job registry. Biggest change; only worth it if we also want survive-refresh
  semantics. Likely overkill for now — note as a fallback.

Recommendation: **B**, with **A** as the guaranteed floor if streaming proves fiddly on the daemon
side. Whichever is chosen, keep the helper allowlist constraints from the security review
(`cmd_snapraid` conf/log-target allowlist) intact.

## Tasks
1. Reproduce on the Pi: run a real `sync` from `/v2/pools` and capture the current failure (UI error
   at ~30s, `snapraid` still running via `pgrep`). Record it as the "before".
2. Implement A and/or B:
   - A: thread a `timeout` through `helper_call` (`helper_client.py`) and set it for the snapraid
     long-run commands; default for other calls stays 30s.
   - B: stream framed output/tag lines from the helper for `snapraid --log-tags`; in
     `snapraid_plugin.py:598-635` read-and-`yield` incrementally instead of buffering; add a
     heartbeat frame and a sane inter-frame read timeout.
3. Guard the split-brain: if a helper long-run does error/disconnect, surface that the operation may
   still be running and avoid offering an immediate duplicate run (the pre-sync threshold "Run
   anyway" and normal run buttons should reflect an in-flight state).
4. Real-hardware sync smoke (the gate): a documented, semi-automated procedure (script under
   `scripts/` or a `@pytest.mark.hardware` test skipped without an env flag) that, on the Pi with a
   real array, runs a sync and asserts: progress events arrive **before** completion, no HelperError
   before the real end, and the final summary matches `snapraid status`.
5. Unit coverage for the timeout plumbing (A) and the streaming reader (B) with a fake helper socket;
   assert tag events are yielded incrementally.

## Acceptance Criteria
1. A multi-minute `sync`/`scrub` on the target Pi completes with a success result in the UI (no
   ~30s HelperError) and the log-tag summary persists (`last_summary`/`last_log`).
2. (If B) progress percent/ETA/speed update in the command runner **while** the run is in progress on
   real hardware, not just at the end.
3. The real-hardware sync smoke passes and is documented; the Phase 4 signoff can be flipped to
   unconditional GO with a reference to it.
4. Security review constraints (helper conf/log-target allowlist, mutation lock behaviour) unchanged;
   existing unit + e2e suites stay green.

## Test rig
The primary Pi currently has a single attached disk, which cannot form a real multi-parity SnapRAID
array or drive a sync long enough to hit the 30s timeout. A second Pi with a 5-disk DAS is planned
and is the intended rig for this ticket: it exercises multi-parity (validating Phase 4 fix 3) and a
genuinely long-running sync (the 30s-timeout / live-progress scenario).

## Notes / risks
- The dev (non-helper) path already streams; keep it as the behavioural reference for B.
- Watch the M1 helper concurrency change: `snapraid` runs lock-free, so a long streaming read must
  not hold a lock that blocks status refreshes (it currently doesn't — preserve that).
- A alone ships value quickly (kills the spurious failure) even if B lands later; consider merging A
  first behind the same ticket.
