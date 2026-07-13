# LimeOS AI Agents AA-009 Target-Pi Signoff

Date: 2026-07-13
Target: Holly (`192.168.0.45`, hostname `wybie`) — Debian 12, aarch64
Predecessors: AA-000 through AA-008
Decision: **GO for the read-only assistant release** on this host. A repair/rollback UI
pass and the package-baseline follow-up are recommended before a second host.

## Outcome

The read-only Mattermost assistant is live and verified end-to-end on the target: a
`@limeos` mention in an alert thread produced a real, bounded diagnosis using only
read-only `limeops` operations, and every isolation, recovery, and separation property
required by AA-000/AA-008 was demonstrated on the running system.

## Evidence

| AA-009 item | Result | Evidence |
| --- | --- | --- |
| Install + provisioning on target | Pass | `limeopsd`, `limeos-agent` units + `limeos` bot live; broker socket at `/run/limeos/limeops.sock` |
| Claude auth under `lime-agent` | Pass | `claude auth status` → loggedIn, `authMethod: claude.ai`, Pro |
| Mention → threaded diagnostic reply | Pass | 18-container health inventory + per-stack table posted in-thread |
| Bot bootstrap + threaded delivery | Pass | connectivity-check root+reply from `verify_threaded_delivery` |
| **Alert-thread investigation (flagship)** | Pass | Stopped sonarr → alertd incident → `@limeos` in that thread → diagnosis (exit + recurring path-mapping import failures found in logs, distinguished from the exit). Audit: `context`, `container.status`, `container.logs` — with self-correction after `invalid_input` |
| Blocked-operation / read-only boundary | Pass | The assistant refused organically: "I have read-only access, so I can't restart the container myself." No mutating operation exists in policy; audit shows read ops only |
| Recovery notification | Pass | `docker start sonarr` → exactly one `recovery container:sonarr: sonarr is healthy` |
| Provider isolation | Pass | `lime-agent` groups = `{lime-agent, limeops-client}` only (not docker/pihealth/sudo). `docker ps`, `/var/run/docker.sock`, `/etc/limeos/credentials.env` all denied; own Claude creds readable. Running unit: `CapabilityBoundingSet=` empty, `ProtectSystem=strict`, `PrivateDevices=yes`, `NoNewPrivileges=yes`, `InaccessiblePaths` = repo + docker.sock + credentials.env + helper runtime |
| Broker authority separation | Pass | `limeops` is the only identity in `docker`+`pihealth`; `lime-agent` reaches only the limeops socket |
| Restart / dedup | Pass | `seen-events.json` unchanged (md5) across an `limeos-agent` restart; thread map preserved; service returns `active` |
| Disable interrupts assistant, not alerts | Pass | `systemctl stop limeos-agent` → agent `inactive` while `limeos-alertd` and `limeos-mattermost` stayed `running` |
| Repair (ordinary + full bot/config) | Recommended UI pass | Mechanism present (AA-008); exercise via the integrations card before a second host |
| Rollback (agent removal preserves Mattermost data) | By design; UI pass recommended | Agent units/credentials are separate from Mattermost, Postgres, alertd, and conversation state; verify the removal flow via the UI before a second host |

## Defects found and fixed during signoff

Three dependency-drift defects surfaced on real hardware; all fixed:

1. `python3-psutil` missing → broker `system.status` returned `upstream_failure`. Fixed
   live; the installer now guarantees it (commit `8f7b6f1`).
2. The Claude Code CLI auto-updated `2.1.205 → 2.1.207` and changed its `--json-schema`
   output shape (`structured_output` object → `result` JSON-string on tool-routed
   turns), causing intermittent "assistant is not available". Fixed: the parser accepts
   both shapes and maps CLI error results to unavailable (`7c20162`); the CLI's
   auto-updater is now disabled and the package held (`8f7b6f1`).
3. The alert-thread mention carried only the user's text, not the incident content
   (webhook attachments). Fixed: the listener fetches the thread root and injects the
   alert content on first mention (`a74acfa`).

These validate the package-baseline follow-up (`Docs/LIMEOS_PACKAGE_BASELINE.md`).

## Deployment notes for reconciliation before a second host

- Deployed `limeopsd`/`limeos-agent` units diverged from the `provisioning.py` templates
  (system `python3` + `PYTHONPATH=/usr/lib/limeos-agent` and
  `/var/lib/lime-agent/state`). Reconcile the templates/deploy so a clean install
  reproduces the working host (package-baseline PB-004).
- Agent code should deploy via the app's self-update-from-repo path (which also re-runs
  the agent install/reconcile), not manual file copies, closing the divergence gap.

## Decision

**GO for the read-only assistant on Holly.** The flagship alert-thread investigation,
the read-only boundary, provider isolation, restart/dedup, and disable-preserves-alerts
are all proven on the running target. Repair and rollback UI flows and the package
baseline are the recommended closeout items before deploying to a second host.
