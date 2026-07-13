# LimeOS Assistant Capability Roadmap (Design)

Date: 2026-07-13
Status: Draft for review
Precondition: AA-009 read-only signoff (`Docs/LIMEOS_AI_AGENTS_AA009_TARGET_SIGNOFF.md`)
Origin: the use cases raised alongside AA-009 — "fix the container", "update compose.yaml",
"add this app", "suggest films for film night, steered by what we've watched, left-field
welcome", "add that film to Radarr".

## The line this crosses
AA-000 froze the first release as **read-only** and explicitly deferred mutation,
approvals, and arbitrary access behind a separate security and identity review. This
roadmap is that deferred phase. Nothing here ships until the mutation posture below is
implemented and passes an AA-008-style adversarial review for writes.

## Non-negotiable posture for every write
Carried verbatim from the automation sprint and AA-000:
1. **Deny by default.** A write is impossible unless it is an explicitly registered,
   allowlisted operation with its own policy — never shell, never a raw file write, never
   the Docker or helper socket from the model.
2. **Single-use, payload-bound, actor-bound approval.** Each mutating action is proposed
   with its exact target and impact, then requires one approval bound to that exact
   payload and to a configured Mattermost approver identity. A changed payload needs a new
   approval. Approvals expire and cannot be replayed.
3. **Executed by trusted code, not the model.** The gateway validates the approval and
   calls an existing, already-hardened LimeOS service (stack mutation, catalog install,
   media integration) — the model only *proposes*; it never *performs*.
4. **Audited and injection-proof.** Every proposal, approval, and result is audited;
   hostile text in logs, alerts, media metadata, or chat can never manufacture an approval
   or expand capability.

## New machinery required (prerequisites)
- **A write-capable `limeops` surface** behind a *separate* write policy, distinct from the
  read policy, with its own allowlist and audit. Reads and writes stay in different policy
  files so a read release cannot accidentally grant a write.
- **An approval broker**: mint/validate single-use tokens bound to `{operation, normalized
  payload, approver, expiry}`; idempotent so a re-delivered approval cannot act twice.
- **Mattermost approval UX**: render a proposal with target/impact/expiry and approve/reject
  controls (reactions or buttons); restrict who can approve; record the approver.
- **A write security suite** (AA-008 for mutations) + a target signoff before enabling.

## Tiers (each an independently shippable step)

### Tier A — allowlisted container lifecycle (smallest first write)
Restart/start/stop a **named, allowlisted** container. New `container.restart` (etc.) write
op behind the write policy; the agent proposes, a human approves in-thread, execution goes
through the existing container operations service (never the Docker socket from the model).
This is the "fix the container" case and the minimum viable mutation to prove the approval
loop end to end.

### Tier B — stack / compose and catalog (`update compose.yaml`, `add this app`)
The agent proposes a **diff** (or a catalog install with its rendered fields); a human
approves; the change applies through the *existing* validated `StackMutationService` /
catalog install path — which already has schema validation, backups, and the web-side CSRF
posture. The model never writes the file; it produces a proposed change that trusted code
validates and applies, with the existing backup/rollback safety net.

### Tier C — media domain (recommendations + approved adds)
Split by risk:
- **Read-only, can land earliest:** read Radarr/Sonarr/Jellyfin library + watch history to
  power recommendations ("film night ... steer by watched, left-field welcome"). These are
  new read operations — no approval needed, same posture as the AA-002 diagnostics.
- **Approved write:** `media.add` (add to Radarr/Sonarr) as a single-use, approved action
  reusing the media search + approved-add operations already specced in the automation
  sprint (LA-005): search returns stable candidates, the user selects one exact result,
  approval binds to it, the add is idempotent.

## Sequencing
1. Write posture first: the write policy surface + approval broker + Mattermost approval UX
   + the write security suite. No user-facing mutation until this exists.
2. Tier C **reads** (recommendations) can proceed in parallel — they are read-only and
   deliver a delightful feature (film night) with no new risk.
3. Then Tier A (prove the loop on the safest mutation), Tier B, and Tier C writes, each
   with its own allowlist entry and signoff.

## Explicitly still out of scope until reviewed
Arbitrary shell or file access; SnapRAID/storage writes; compose lifecycle beyond the
validated service path; unattended (no-approval) mutation of any kind.
