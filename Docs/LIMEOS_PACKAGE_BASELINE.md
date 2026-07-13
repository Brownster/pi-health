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

## Nightly job
A `limeos-package-reconcile.timer` (systemd, daily, randomized) runs `reconcile apply` in
the configured mode. On drift it could not auto-correct, or any failure, it posts a
LimeOS incident via the existing webhook. Controlled OS updates = `unattended-upgrades`
scoped to the security pocket, with `apt-mark hold` on every `critical` manifest entry so
distro upgrades cannot move them.

## Release flow
- Version bumps to a `pinned` package happen by editing the manifest in a branch, testing
  on Holly, then releasing. The nightly job then converges every host to the new pin.
- The installer runs `reconcile apply` as its final step, so a fresh install matches the
  baseline (this subsumes the tactical psutil/hold fixes).

## Unit reconciliation (defect 3)
Fold a `check` of the deployed `limeopsd`/`limeos-agent` unit content against the
`provisioning.py` templates into `reconcile check`, and have `repair` re-render them, so a
host's units can't silently diverge from the release.

## Work packages
| ID | Package | Deliverable |
|---|---|---|
| PB-001 | Manifest schema + `config/limeos-packages.json` + validator/tests | The versioned baseline |
| PB-002 | `cmd_packages_reconcile` (helper) + `packages.status` limeops op | Read-only status + gated apply |
| PB-003 | Nightly timer + drift→Mattermost incident + unattended-upgrades scoping | Controlled updates |
| PB-004 | Installer runs reconcile; unit-template drift check in repair | Reproducible installs |
| PB-005 | Target signoff on Holly (pin holds across an apt upgrade; drift detected + reported) | Evidence |

## Open decisions
1. Nightly `apply` scope: security-only (recommended) vs. all non-critical vs. report-only.
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
