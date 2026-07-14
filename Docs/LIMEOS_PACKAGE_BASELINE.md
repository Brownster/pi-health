# LimeOS Package Baseline and Controlled Updates (Design)

Date: 2026-07-13
Status: Draft for review
Origin: three dependency-drift defects during the AA-009 demo on Holly's Pi, all one root
cause — uncontrolled dependencies:
1. `python3-psutil` missing → broker `system.status` failed.
2. The Claude Code CLI silently auto-updated `2.1.205 → 2.1.207` and changed its
   `--json-schema` output contract → intermittent assistant failures.
3. Deployed `limeopsd`/`limeos-agent` systemd units diverged from the
   `agent_provider/provisioning.py` templates (system `python3` vs the repo venv).

Tactical mitigations already landed (commit `8f7b6f1`): Claude auto-updater disabled +
apt-hold, psutil guaranteed in the agent install. This document designs the durable
system.

## Objective
A declarative, versioned package baseline deployed with each LimeOS release, plus a
controlled update mechanism, so a LimeOS-critical dependency can never change its
behaviour under us without a tested release — while non-critical packages still get
routine security updates.

## Principles
1. **Declarative and versioned.** The baseline lives in the repo and ships with the
   release. The running host is reconciled *to* it, not the other way round.
2. **Pinned means pinned.** Critical packages are held at a stated version; their version
   only moves by editing the manifest in a tested release.
3. **Least authority.** Reconciliation is a helper-owned operation that accepts no
   arbitrary package names, repos, or versions — only what the manifest declares (same
   posture as the existing typed helper commands).
4. **Report, then (optionally) apply.** Drift and update results are observable; whether
   the nightly job *applies* non-critical updates or only reports is configurable
   (default: security-only apply + report the rest).
5. **Reuse what exists.** Drift/failure surfaces through the alertd → Mattermost incident
   pipeline; the assistant can explain it.

## The manifest — `config/limeos-packages.json`
```json
{
  "schema_version": "1",
  "packages": [
    {"name": "claude-code",   "manager": "apt",  "policy": "pinned",       "version": "2.1.207", "critical": true,  "extra": {"disable_self_update": true}},
    {"name": "python3-psutil","manager": "apt",  "policy": "present",       "critical": true},
    {"name": "docker-ce",     "manager": "apt",  "policy": "present-min",   "version": "24",     "critical": true},
    {"name": "unattended-upgrades", "manager": "apt", "policy": "present",  "critical": false}
  ]
}
```
- `policy`: `pinned` (exact, held) · `present-min` (>= version, may update) · `present`
  (installed, tracks distro) · `absent` (must not be installed).
- `manager`: `apt` first; `pip`/`npm`/`claude` slots exist but MVP is apt + the Claude
  self-updater flag.
- `critical`: informs update policy and whether drift raises an incident.

## Reconcile operation (helper-owned)
A fixed helper command `cmd_packages_reconcile(mode)` with `mode ∈ {check, apply}`:
- `check` (read-only): report each package's installed version vs. policy → `{ok, drift[]}`.
- `apply`: install missing, enforce pins (`apt-mark hold` + set component self-update off),
  bring `present-min` up if below floor, run security updates for non-critical, re-pin any
  critical that drifted. Never touches packages outside the manifest.
- No arbitrary parameters — it reads the shipped manifest only (like the other agent ops).

Exposed read-only through `limeops` as `packages.status` so the assistant can answer
"are we on the expected versions?" without any mutation authority.

## Nightly job (policy decided 2026-07-13)
A `limeos-package-reconcile.timer` (systemd, daily, randomized) runs each night:
1. **Auto-apply non-critical security updates** immediately (scoped `unattended-upgrades`,
   security pocket only), with `apt-mark hold` on every `critical` entry so distro
   upgrades cannot move them.
2. **Discover pending updates for held/critical packages** and post them to the
   **#limeos-events (updates)** channel — versions available vs. current. The user can
   ask `@limeos` about them (read-only), then **approve** specific updates.
3. **Approved updates apply on the next nightly run** — approval is recorded as a bounded,
   actor-bound token (same single-use/payload-bound contract as other mutations); the
   next reconcile consumes it, bumps the manifest pin, applies, and reports the result.
   Nothing critical moves without an explicit approval + a recorded manifest change.

Drift it cannot auto-correct, or any failure, posts a LimeOS incident via the existing
webhook.

## Release flow
- Version bumps to a `pinned` package happen by editing the manifest in a branch, testing
  on Holly, then releasing. The nightly job then converges every host to the new pin.
- The installer runs `reconcile apply` as its final step, so a fresh install matches the
  baseline (this subsumes the tactical psutil/hold fixes).

## Deployment path (decided 2026-07-13)
LimeOS code — including the agent packages under `/usr/lib/limeos-agent` — deploys via
the app's existing **self-update-from-repo** function, not manual file copies. The update
flow pulls the pushed repo and then re-runs the agent install/reconcile so
`/usr/lib/limeos-agent`, the systemd unit templates, and the package baseline all
converge to the release. This replaces the ad-hoc `scp` hotfixes used during the AA-009
demo and closes the unit-divergence gap (defect 3) at the same time: a deploy always
re-renders units from `provisioning.py`.

## Unit reconciliation (defect 3)
Fold a `check` of the deployed `limeopsd`/`limeos-agent` unit content against the
`provisioning.py` templates into `reconcile check`, and have `repair` re-render them, so a
host's units can't silently diverge from the release.

## Work packages
| ID | Package | Deliverable | Status |
|---|---|---|---|
| PB-001 | Manifest schema + `config/limeos-packages.json` + validator/tests | The versioned baseline | ✅ `bb5e21e` |
| PB-002 | `cmd_packages_reconcile` (helper) + `packages.status` limeops op | Read-only status + gated apply | ✅ done |
| PB-003 | Nightly timer + drift→Mattermost incident + unattended-upgrades scoping | Controlled updates | Planned |
| PB-004 | Deploy the agent runtime via self-update-from-repo; fix the module deploy gap | Reproducible installs | ✅ done |
| PB-005 | Target signoff on Holly (pin holds across an apt upgrade; drift detected + reported) | Evidence | Planned |

PB-004 landed: the self-update-from-repo flow (`pihealth_update_service.stream_update`) gained an
**agent** step that runs when agent code, the broker/policy, or the package baseline changed. When
the agent is installed it re-runs the idempotent runtime install (re-copying the agent packages
**and** the top-level `limeos_packages.py` + manifest — a deploy gap that would have broken
`packages.status` on the broker — and re-rendering the systemd unit templates so a deployed unit
cannot drift from the release), reconciles the package baseline (`apply`), and restarts the agent.
This replaces the manual `scp` hotfixes used during AA-009 and closes the unit-divergence gap
(defect 3): every deploy re-renders units from `provisioning.py`. The remaining PB-004 idea —
surfacing unit-template drift in the *repair* status even without a code change — folds into PB-003's
reconcile `check`.

PB-002 landed: `limeos_packages.py` gained the pure reconcile logic (`check_packages`,
`plan_actions`, `compliance_report`, injectable version comparator); `packages.status` is a
read-only limeops op (in the default policy + gateway allowlist) so the assistant can report
compliance without any mutation authority; and `cmd_packages_reconcile(mode)` (helper) does
`check` (read-only) or `apply` (manifest enforcement — install pinned versions, `apt-mark hold`,
install missing, upgrade below `present-min`, remove `absent`), taking only `mode` and reading
package names/versions solely from the validated manifest. Security-pocket updates stay with the
nightly job (PB-003).

## Open decisions
1. ~~Nightly apply scope~~ — decided: auto-apply non-critical security updates; held/critical
   updates are posted to the updates channel and applied on the next run after approval.
2. Managers beyond apt for MVP (pip/npm) — defer unless a critical pip/npm dep appears.
3. Whether `packages.status` drift should auto-open an incident or only answer on request.

---

## Related: Mattermost channel topology + assistant capability roadmap

These came up alongside the baseline work and shape where the agent goes next. Recorded
here so they are not lost; each is its own future effort.

### Channel topology (near-term, low-risk)
Split the single "LimeOS Alerts" channel into purpose-built channels so signal, chatter,
and requests don't collide:
- **#limeos-alerts** — model-free incident/recovery posts only (alertd). Terse, high-signal.
- **#limeos-events** — routine lifecycle/audit events (updates applied, package reconcile
  results, container up/down that isn't an incident). Informational.
- **#limeos-assistant** (or general) — human ↔ `@limeos` conversation, requests, "film
  night" style chat.
Mechanics: the alertd webhook already targets one channel; add per-purpose webhooks. The
bot's `allowed_channels` allowlist (already in the runtime config) governs where `@limeos`
responds — keep it to the assistant + alert channels so it can investigate alerts but
ignore the noise channel.

### Capability roadmap (this is the deferred mutation + approval phase)
The AA-000 baseline explicitly deferred mutation, approvals, and arbitrary access behind a
security review. The user's use cases map onto staged tiers, each needing the
single-use, payload-bound, actor-bound approval contract from the automation sprint before
any write reaches a service:

- **Tier A — allowlisted container ops** (restart/start/stop a named container): the
  smallest first mutation; approval in-thread; a new `limeops` write op behind the broker
  with its own policy, never shell.
- **Tier B — stack/compose edits** ("update compose.yaml", "add this app"): edits go
  through the existing validated stack-mutation + catalog-install services (which already
  have validation, backups, and CSRF on the web side) — the agent proposes a diff, a human
  approves, the change applies via those services, never a raw file write.
- **Tier C — media domain** ("suggest films for film-night, steered by watched history,
  left-field welcome"; "add that film to Radarr"): read Radarr/Sonarr/Jellyfin history for
  recommendations (read-only, safe), and `media.add` as an approved write to the existing
  catalog/media integration — reusing the media search + approved-add operations the
  automation sprint already specced (LA-005).

Guardrails carried from the automation sprint: everything mutating is deny-by-default,
requires an explicit single-use approval bound to the exact payload and actor, is audited,
and is impossible to trigger via prompt injection. Recommendations and history reads are
read-only and can land earlier; writes wait for the approval contract + the consolidated
security review (AA-008/AA-009 posture) to be extended for mutation.
