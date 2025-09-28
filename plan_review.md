# Ops-Copilot Integration – Developer Expansion

This document transforms the earlier high-level review into an implementation-ready blueprint that engineers can translate into tickets. It focuses on trust boundaries, data flows, tool contracts, UI behaviors, and operational guardrails so your daughters get reliable self-service help without exposing unsafe capabilities.

---

## 1. High-Level Architecture with Trust Boundaries

```
+-------------------------------+        +---------------------+
|         Daughter UI           |        |  Observability SaaS |
| (Browser + Approval Modals)   |        |  (optional webhook) |
+---------------+---------------+        +----------+----------+
                |                                   ^
                v                                   |
+-------------------------------+        +----------+----------+
|     Ops-Copilot Web Backend   |        |  Alert Fan-out      |
|  (FastAPI on Pi-5, Auth, RBAC)|        | (Email/SMS/Matrix)  |
+---------------+---------------+        +----------+----------+
                |                                   ^
                v                                   |
+-------------------------------+        +----------+----------+
|     MCP Runtime & Policy      |<------>| Secrets Vault/Files |
|   (OpenAI API client pool)    |        +---------------------+
+---------------+---------------+
                |
                v
   +------------+------------+--------------------+
   | Read-only Tool Adapters | Mutating Tool Adapters
   | (Status probes, logs)   | (Docker, Compose, service APIs)
   +------------+------------+--------------------+
                |
                v
   +------------+------------+--------------------+
   |   Media Services Stack (Docker on Pi-5)      |
   | Radarr | Sonarr | SABnzbd | Jellyfin | etc.  |
   +----------------------------------------------+
```

- **UI boundary:** Browsers authenticate to the Ops-Copilot backend via short-lived tokens. No direct access to MCP or service credentials.
- **Backend boundary:** The FastAPI layer enforces RBAC, rate-limits, and request validation before relaying prompts or approvals to the MCP runtime.
- **MCP boundary:** The AI runtime only calls allow-listed tools. All secret material stays in a local vault file readable only by the MCP process, and outbound egress is pinned to OpenAI endpoints via firewall rules.
- **Service boundary:** Media services remain isolated within Docker; mutating commands run via `docker`/`docker compose` subcommands with limited sudo.
- **Container isolation refinement:** Run the MCP runtime, backend, and each media service in separate containers with SELinux/AppArmor profiles and read-only root filesystems where possible. Deny mounting of the Docker socket except for the minimal supervisor sidecar that brokers approved actions.

---

## 2. Control & Data Flows

| Step | Actor | Action | Trust Boundary Crossing | Audit Artifact |
|------|-------|--------|--------------------------|----------------|
| 1 | Daughter | Submits "What's wrong?" | UI → Backend | Request log + user ID |
| 2 | Backend | Validates session, forwards prompt to MCP | Backend → MCP | Prompt log, sanitized context |
| 3 | MCP | Calls read-only probes (e.g., `get_jellyfin_status`) | MCP → Tool Adapter | Tool invocation log |
| 4 | MCP | Synthesizes diagnosis | MCP internal | Model response snapshot |
| 5 | Backend | Renders explanation + suggested fix | MCP → Backend → UI | Response log |
| 6 | Daughter | Approves fix | UI → Backend | Approval log + signature |
| 7 | Backend | Issues signed action to MCP | Backend → MCP | Action ticket |
| 8 | MCP | Runs mutating tool (e.g., `restart_container`) | MCP → Tool Adapter → Docker | Command log + stdout/stderr |
| 9 | Observability | Sends completion + health summary | Backend → Alert fan-out | Notification record |

---

## 3. Tooling Surface & Contracts

### 3.1 Read-Only Tools (auto-approved)

| Tool ID | Target | Command/Action | Inputs | Output Schema |
|---------|--------|----------------|--------|----------------|
| `get_container_status` | Docker | `docker ps --format` | `container_name` (enum) | `{state, uptime, restarts}` |
| `fetch_service_logs` | Docker | `docker logs --tail=200` | `service` (enum), `since` (ISO8601 optional) | `{lines:[string], truncated:bool}` |
| `check_disk_space` | Host | `df -h /mnt/media` (read-only) | none | `{percent_used, percent_free}` |
| `radarr_queue_status` | Radarr API | `GET /api/v3/queue` | none | Radarr queue JSON subset |
| `sonarr_health` | Sonarr API | `GET /api/v3/system/status` | none | Sonarr status JSON subset |
| `sabnzbd_queue` | SABnzbd API | `mode=qstatus` | none | `{slots:[{name, status, eta}]}` |
| `jellyfin_ping` | Jellyfin API | `GET /System/Ping` | none | `{is_alive: bool, latency_ms}` |

### 3.2 Mutating Tools (require explicit approval token)

| Tool ID | Action | Command | Inputs | Validation |
|---------|--------|---------|--------|------------|
| `restart_container` | Restart a service | `docker restart {container}` | `container` (enum) | Must match allowlist (`radarr`, `sonarr`, `sabnzbd`, `jellyfin`) |
| `compose_up` | Recreate stack | `docker compose up -d` | optional `service` | If `service` missing, warn and require second confirmation |
| `clear_radarr_queue_item` | Remove stuck download | `DELETE /queue/{id}` | `queue_id` (UUID) | MCP must reference prior read result |
| `pause_sabnzbd` | Pause downloads | `mode=pause` | `duration_minutes` (1-60) | Enforce numeric range |
| `resume_sabnzbd` | Resume downloads | `mode=resume` | none | Only callable if paused |

**Approval flow:** Backend issues signed approval token containing `tool_id`, inputs, expiration, and user signature. MCP must present token before mutating tool executes.

---

## 4. Guardrails & Safety Enforcement

- **Argument schemas:** Implement Pydantic models for each tool. Reject prompt-derived inputs that fail validation or reference resources outside the allowlist.
- **Rate limits:** Max 5 tool invocations per minute per session, configurable via Redis or in-memory token bucket.
- **Output redaction:** Redact API keys, hostnames, or emails via regex scrubbers before storing responses.
- **Timeouts:** Read tools timeout at 5s; mutating tools at 15s with automatic rollback message if exceeded.
- **Audit trail:** Append JSON entries to `/var/log/ops-copilot/audit.jsonl` with request ID, tool, inputs, actor, and outcome.
- **API governance:** Store OpenAI credentials in `libsodium`-encrypted files, rotate them quarterly, and instrument the backend to halt outbound calls if a key is suspected compromised (e.g., sudden 401 burst).

---

## 5. UI & Approval Experience

```
[Daughter asks question] → [Backend renders diagnosis card]
                              |
                              +-- Suggested Fix (if safe) --> ["Apply Fix" button]
                              |
                              +-- Fallback guidance --> ["Send FYI" button]
```

- **Diagnosis card:** Plain-language summary, confidence rating, and supporting telemetry snippets.
- **Approval modal:** Shows exact command, affected service, expected downtime, and audit ID. Requires checkbox acknowledgment + "Confirm" click.
- **History tab:** Timeline of prior incidents, actions taken, and links to logs.
- **Accessibility:** Large fonts, color-blind friendly status badges, responsive layout for tablets.

---

## 6. Model Hosting Strategy (API-first)

- **Primary path:** Use OpenAI's GPT-4o-mini (or successor) via API for both diagnosis and remediation planning. Maintain a rotating pool of API keys with least-privilege scopes and store them encrypted at rest. Configure outbound firewall rules so the MCP container can only reach `api.openai.com` over TLS, and terminate TLS in-container to preserve end-to-end encryption.
- **Offline/Degraded mode:** Ship lightweight, quantized `llama.cpp` weights as an optional module that can be toggled on if internet connectivity is lost. Clearly communicate reduced capability to the UI and automatically narrow the mutating tool allowlist while offline.
- **Usage governance:** Track token consumption per session and enforce a monthly budget ceiling. When 80% of the budget is consumed, alert via the observability channel and require guardian approval to continue unrestricted usage.

When using the API-first approach, keep inference outside of the Pi's constrained CPU and memory budget. The MCP container only orchestrates prompts, handles tool results, and manages safety policies, ensuring low footprint while benefitting from higher-quality model reasoning.

---

## 7. Monitoring, Alerts, and Fallbacks

- **Health checks:** Prometheus node exporter (read-only) feeding Grafana; MCP can query PromQL via read tool for anomaly detection.
- **Alert fan-out:** If an approved fix fails twice, trigger webhook to email/SMS/Matrix via alert service with templated message.
- **Escalation log:** When MCP cannot resolve, create `/var/log/ops-copilot/escalations/{timestamp}.md` with human-readable steps and link in UI.
- **Graceful degradation:** If MCP unavailable, UI displays troubleshooting checklist and encourages manual restart instructions.
- **API telemetry:** Export OpenAI latency, token usage, and error codes to Prometheus. Alert when p95 latency exceeds 6s or when non-2xx response rate crosses 5% within 10 minutes.

---

## 8. Testing & Simulation Plan

| Phase | Environment | Focus | Tools |
|-------|-------------|-------|-------|
| Unit | GitHub Actions / Pi-5 | Tool schema validation, prompt sanitizers | `pytest`, `schemathesis` |
| Integration | Pi-5 staging stack | MCP ↔ tool adapters ↔ services ↔ OpenAI API (sandbox key) | Docker Compose with mirrored test data, `pytest-recording` for API mocks |
| Dry-Run Scenarios | Production clone (weekend) | Simulate stalled downloads, container crash, disk full | Recorded scripts, `toxiproxy` for network faults |
| Disaster Rehearsal | Quarterly | Full outage + recovery drill with daughters observing UI | Runbook, capture feedback |

Automate synthetic incidents weekly (e.g., pause SABnzbd) and confirm MCP produces correct remediation plan before auto-resolving.

---

## 9. Incremental Build Tasks with Validation

| Step | Objective | Key Implementation Tasks | Verification & Test Points |
|------|-----------|--------------------------|----------------------------|
| 0. Baseline Platform | Prepare Pi-5 host and repo for iterative work. | Install system updates, provision dedicated `ops-copilot` user, clone repo, enable container runtime with per-service users. | Manual checklist confirming host hardening items complete; `docker info` succeeds under restricted user. |
| 1. Backend Skeleton | Stand up FastAPI service with auth + health checks. | Scaffold FastAPI project, implement OAuth device-flow for daughters, add `/healthz` and `/whoami` endpoints, set up logging middleware. | ✅ `pytest tests/test_health.py` (unit), curl calls returning expected JSON, authentication tokens expire as configured. |
| 2. UI Foundations | Deliver minimal UI with diagnosis placeholder. | Create React/Vue (or HTMX) frontend with login, status card placeholder, approval modal shell; wire to backend endpoints with mocked data. | ✅ `npm test` (component snapshot) or `pytest-playwright` smoke, manual UI walkthrough verifying responsive layout and accessibility checks. |
| 3. OpenAI API Integration | Connect backend to OpenAI with guardrails. | Implement secrets loading, client pool with retry/backoff, prompt templating, and budget tracker. | ✅ Integration test hitting OpenAI sandbox key (`pytest tests/test_openai_stub.py` with VCR), log inspection confirming token usage counters update. |
| 4. MCP Runtime (Read-Only) | Deploy MCP server with first tool adapters. | Configure MCP to call `get_container_status`, `radarr_queue_status`, etc.; enforce schema validation; connect backend prompt flow to MCP. | ✅ `pytest tests/tools/test_read_only.py`, manual run of scripted query verifying accurate diagnosis without approvals. |
| 5. UI Diagnosis Loop | Surface MCP answers and telemetry in UI. | Replace mocked responses with live MCP output, add confidence badges, embed last 5 log lines per service. | ✅ Cypress/Playwright E2E test for “What’s wrong?” scenario; confirm audit log entry appended. |
| 6. Approval Engine | Introduce approval tokens and history timeline. | Generate signed approval tokens, store in Redis/sqlite, enforce expiry checks in MCP; build UI modal with action summary and audit ID; add history view. | ✅ `pytest tests/test_approvals.py`, manual approve/reject flow verifying audit log + history updates. |
| 7. Mutating Tools | Add safe write actions with rollback messaging. | Implement `restart_container`, `pause_sabnzbd`, etc.; require double confirmation for stack-wide actions; add simulated rollback instructions on failure. | ✅ Integration test scenario (`pytest tests/tools/test_mutating.py` with Docker mocks), staging dry-run that restarts non-critical container and confirms UI notification. |
| 8. Observability & Alerts | Wire monitoring, notifications, and escalations. | Configure Prometheus scrapes, expose MCP metrics endpoint, integrate alert webhooks, generate escalation markdown on repeated failures. | ✅ `pytest tests/test_metrics.py`, manual alert trigger sending message to configured channel. |
| 9. Resilience & Docs | Final rehearsals and handoff artifacts. | Run offline-mode drill (switch to llama.cpp), execute disaster rehearsal with daughters, finalize runbooks and UI handbook. | ✅ Post-mortem document, checklist sign-off, daughters validate they can follow runbook unaided. |

---

## 10. Documentation Deliverables

- Runbooks per service (`docs/runbooks/{service}.md`).
- UI handbook with annotated screenshots for key flows.
- MCP tool reference (`docs/tools/reference.yaml`) for auditing.
- Annual review checklist to reassess model, guardrails, and daughters’ comfort level.

This expansion provides concrete artifacts—diagrams, tables, and phased roadmap—so engineers can implement the ops-copilot with confidence while preserving the safety-first vision for your family.

---

## 11. Reviewer Feedback Integration

- **API-first inference:** Adopt the OpenAI API as the default model path with strict egress controls, while keeping an offline-capable fallback for resilience.
- **Hardening container boundaries:** Layer SELinux/AppArmor profiles, read-only filesystems, and a supervised Docker socket broker so that only the approval service can issue mutating commands.
- **Operational telemetry:** Extend monitoring to cover API latency, token budgets, and credential health, ensuring issues surface before they impact your daughters.
- **Test coverage:** Update integration and dry-run scenarios to exercise API usage with sandbox keys and contract tests, validating the cloud dependency without risking production quota.
