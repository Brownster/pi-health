# Agent Investigate MVP — alert → @agent (Mattermost, DAS Pi)

Date: 2026-07-09
Status: Draft — scoped on-ramp to `Docs/LIMEOS_AGENT_AUTOMATION_SPRINT.md` (the full sprint stays
deferred behind its entry gates; this MVP is a smaller, read-only subset).
Host: the new DAS Pi (runs LimeOS/pi-health for its own storage, the alert evaluator, Mattermost,
and on-demand model turns).

## Objective
Native checks post an incident to a Mattermost thread with **no model**. A human `@agent`s in that
thread to have it **investigate** (read-only). The model runs only when mentioned, headless and
one-shot, resuming a per-thread session for continuity. No autonomous action; no mutations in this MVP.

## Interaction model
```
native check fails ──► Mattermost incident thread            (model-free)
   you: "@agent investigate"  in that thread
        ──► one headless turn:  claude -p --resume <thread-session>
                                --allowed-tools limeops(read-only)
        ──► streamed reply in the thread, process exits
```
- **Alerts never invoke the model** (zero token spend on detection).
- **Investigate = read-only** (status/logs/disk/mount/SnapRAID status/connectivity): auto-allowed.
- **Act-tier is deferred** — restart/add-media/etc. and their approval flow are NOT in this MVP.
  Everything mutating (compose, SnapRAID writes, mounts, config, shell) stays denied.

## Decisions
1. **Claude-first.** Use Claude Code's native `--resume <session-id>` per thread (session state is a
   `.jsonl` on disk; process runs only during a turn). Codex/provider-neutral gateway deferred —
   revisit if/when we need both (that's the full sprint's LA-007).
2. **Tools are pinned to a read-only `limeops` surface.** The Claude turn runs with `--allowed-tools`
   limited to limeops read commands and **bash/edit/write denied**. Client-side restriction is
   defence-in-depth; limeops itself only exposes read operations in this MVP, so a prompt-injected
   log line cannot escalate.
3. **One session per Mattermost thread**, id derived deterministically from the root post id; **turns
   are serialised per session** (a per-session lock) so two mentions can't race the same `.jsonl`.
4. **LAN-only.** Mattermost is not exposed to the Internet in this MVP.
5. **Budget guard.** A per-day model-invocation cap + a model tier (triage on a small model, escalate
   only when needed) — exact numbers TBD (see Open decisions).

## Resource footprint (DAS Pi)
| Component | Lifecycle | Rough cost |
|---|---|---|
| Mattermost + Postgres | always-on | ~300–600 MB (the heaviest piece) |
| Alert evaluator | always-on | tens of MB, no model, no API |
| Mattermost mention listener | always-on | tens of MB |
| Claude headless turn | on-demand, per mention | ~100–200 MB transient + ~1–2 s Node start; inference is remote |

Inference runs on Anthropic's servers, not the Pi — the Pi cost is the always-on listeners plus a
short-lived orchestrator per turn.

## Bricks
| # | Brick | Model? | Notes |
|---|---|---|---|
| B1 | Mattermost + Postgres stack on the DAS Pi | No | compose stack; least-privileged bot account; incoming webhook secret; LAN-only |
| B2 | Native alert evaluator → Mattermost incidents | No | container down/unhealthy, SMART degraded, mount missing, SnapRAID failed; consecutive-failure + cooldown + dedup + recovery; state persisted across restarts; runs outside the API process. Lives in pi-health; testable in this repo now |
| B3 | Read-only `limeops` CLI | No | `status/logs(bounded)/disk/mount/snapraid status/network check`; versioned JSON envelope; reuses domain services (no UI scraping); redaction + output caps. Testable in this repo now |
| B4 | Mattermost mention listener → headless investigate | Yes (on-demand) | on `@agent` mention: `claude -p --resume <thread-session> --allowed-tools limeops…`; stream reply to thread; per-thread session + lock; dedup Mattermost events by id |
| B5 | Hardening + tests + signoff | — | prompt-injection can't escalate; read ops can't mutate; restart/reconnect recovery; budget cap enforced |

B2 and B3 are model-free, low-risk, and can start **in this repo now**, before the DAS Pi is fully
up. B1 is host infra on the DAS Pi. B4 needs B1+B3.

### B2 status (2026-07-09)
- **Core** (`alert_evaluator.py`, `alert_notifier.py`) — done: streak-gating, dedup, one-shot
  recovery, atomic-persisted state, Mattermost webhook sink. Tested.
- **Providers + daemon** (`alert_signals.py`, `alert_daemon.py`) — done: container (long-running
  only), SMART, mount, and SnapRAID signal providers; env config; best-effort per-subsystem
  collection; the tick loop. Container + mount readers are wired; **SMART and SnapRAID live readers
  are stubbed pending Pi deployment** (they need the privileged helper / plugin config) and a
  **systemd unit** — both land with B1 on the DAS Pi.
- Known MVP limitation: notification delivery is best-effort (a webhook outage when an incident
  opens is logged, not retried); a delivery queue is a follow-up.

## Relationship to the full LA sprint
This MVP is a deliberate subset and does **not** require the full sprint's entry gates (notably v1 UI
removal) because it is read-only with no mutation boundary. It reuses the sprint's principles
(limeops as the only tool surface, no raw shell to users, audit of each turn). When the full sprint
runs, B2→LA-006, B3→LA-004, B4→LA-007/LA-008, and the act-tier + approvals + provider-neutral gateway
land then.

## Open decisions (need answers before B4)
1. **API budget** — per-day invocation cap and monthly ceiling to design against.
2. **Model tier** — triage model (e.g. Haiku) + escalation policy, or single model.
3. **Mattermost data location** — which disk/volume on the DAS Pi holds the Postgres + Mattermost
   data (not the parity/data array).
4. **Auth** — how the agent authenticates to the local pi-health/limeops on the same host
   (unix socket + local identity vs a scoped token).

## Explicitly deferred
Act-tier (restart/add-media) + single-use approvals; provider-neutral gateway + Codex; autonomous
remediation; exposing Mattermost off-LAN; a LimeOS in-app chat surface.
