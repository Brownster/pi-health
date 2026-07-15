# Overview and Performance Dashboard

Date: 2026-07-15  
Status: Approved for implementation

## Goal

Make the LimeOS Overview a glanceable, read-only health dashboard. A user should
understand whether the host is healthy, see what needs attention, and open any
managed web application without scanning a long page.

Keep detailed time-series analysis on the existing System Health page. Do not add
a Reporting or Investigation page until LimeOS can correlate metrics, alerts,
container events, and agent investigations.

## Product Decisions

1. Overview shows current health, workload counts, alerts, and compact application
   links.
2. System Health owns CPU, memory, temperature, and storage history.
3. Historical ranges are fixed to 24 hours, 7 days, and 30 days.
4. Metric collection runs every five minutes and retains 31 days.
5. Active incidents appear before the five most recent recoveries.
6. Automatic refresh is off by default.
7. Overview and System Health share the same browser refresh preference.
8. Other live pages keep their existing refresh behaviour.
9. The implementation uses bounded local storage and adds no external monitoring
   service.

## Page Model

### Overview

The Overview contains five compact regions in this order:

1. **Health summary:** `All systems operational`, `Attention required`,
   `Critical issues`, or `Status unavailable`, plus the contributing issue count.
2. **Current metrics:** CPU, memory, temperature, and primary storage cards. Each
   card shows the current value, supporting detail, threshold state, and a small
   24-hour sparkline after history is available.
3. **Workloads:** container and stack totals with running, unhealthy, partial, and
   down counts. Problem counts link to the relevant management page.
4. **Alerts:** active incidents ordered by severity and age, followed by up to five
   recent recoveries. Empty state confirms that monitored resources are healthy.
5. **Applications:** a dense launcher grid with an icon or initial, name, status
   dot, and external-link control. Running applications appear first. The first 12
   are visible initially; larger installations can expand the grid.

The Overview remains read-only. Commands such as restart, stop, silence, or repair
stay on their owning pages.

### System Health

The existing System Health page becomes the detailed Performance view without
adding a new navigation item. It retains current metrics, per-core CPU, storage,
network, and throttling information. It adds:

- CPU and memory percentage charts
- Temperature chart
- Primary storage usage chart
- A segmented 24h, 7d, and 30d range control
- Clear gaps where samples are unavailable
- Current, minimum, average, and maximum values for the selected range

Recharts follows the existing shadcn-style tokens and loads from a separate frontend
chunk. The Overview does not load the full chart library.

## Health Rules

Health uses the strongest current state. Each issue includes a stable code, severity,
label, detail, and destination path.

| State | Conditions |
| --- | --- |
| Critical | Critical active incident, unhealthy storage, missing required mount, down stack, or unhealthy container |
| Attention | Warning incident, partial stack, unexpectedly stopped container, degraded integration, or warning metric |
| Healthy | No active incidents, monitored workloads healthy, and metrics within thresholds |
| Unknown | An essential source cannot be read and no stronger known state exists |

Initial metric thresholds match the current Overview behaviour:

| Metric | Attention | Critical |
| --- | ---: | ---: |
| CPU | 60% | 85% |
| Memory | 70% | 90% |
| Temperature | 65 C | 80 C |
| Primary storage | 75% | 90% |

Missing metrics display `Unavailable`; they never display as zero. Source failures
degrade only the affected region so useful data remains visible.

## Overview API

Add an authenticated `GET /api/overview` endpoint. It returns one bounded snapshot:

```json
{
  "health": {
    "state": "healthy",
    "issues": []
  },
  "metrics": {
    "cpu_percent": 12.5,
    "memory_percent": 37.5,
    "memory_used": 3221225472,
    "memory_total": 8589934592,
    "temperature_celsius": 52.4,
    "disk_percent": 41.0,
    "disk_used": 440234147840,
    "disk_total": 1073741824000
  },
  "workloads": {
    "containers": {"total": 18, "running": 18, "unhealthy": 0, "stopped": 0},
    "stacks": {"total": 4, "healthy": 4, "partial": 0, "down": 0}
  },
  "alerts": {
    "active": [],
    "recent_recoveries": []
  },
  "applications": [],
  "warnings": [],
  "collected_at": "2026-07-15T12:00:00Z"
}
```

The service composes existing system, container, stack, and alert readers. It must
not turn a partial source failure into a 500 response. It records a warning and
continues with the remaining sections. Application entries expose only the fields
needed to build local web links.

## Alert Event Ledger

Alertd keeps its current active-incident state and adds a bounded event ledger at:

```text
/var/lib/limeos/alert-events.jsonl
```

Each record contains only:

```text
timestamp, event, key, kind, severity, summary
```

`event` is `incident` or `recovery`. The ledger excludes webhook URLs, Mattermost
post content, credentials, and delivery payloads. Alertd retains the latest 200
records using an atomic bounded rewrite. The Overview reads active incidents from
the status snapshot and returns the five newest recovery records.

An unavailable or malformed ledger produces an empty recovery list and a warning;
it does not affect alert evaluation or delivery.

## Metrics History

A systemd timer invokes a short-lived collector every five minutes. A timer avoids a
permanent process, works when no browser is open, and remains independent of the
optional Mattermost integration.

The collector writes to:

```text
/var/lib/limeos/metrics.sqlite3
```

SQLite uses the Python standard library. The database contains one table:

```sql
CREATE TABLE metric_samples (
    sampled_at INTEGER PRIMARY KEY,
    cpu_percent REAL,
    memory_percent REAL,
    temperature_celsius REAL,
    disk_percent REAL
);
```

Each collection transaction inserts one sample and deletes rows older than 31 days.
At five-minute resolution, a full retention window contains about 8,928 rows and
normally occupies only a few megabytes.

Add `GET /api/system/history?range=24h|7d|30d`. The endpoint accepts no arbitrary
dates or bucket sizes. It aggregates results into at most 360 ordered points:

- 24h: five-minute buckets
- 7d: thirty-minute buckets
- 30d: two-hour buckets

The response includes range boundaries, bucket size, points, and summary statistics.
Queries are read-only, bounded, and authenticated.

## Refresh Behaviour

Overview and System Health share this browser-only preference:

```json
{
  "enabled": false,
  "interval_seconds": 30
}
```

Store it under a versioned `localStorage` key. Both pages show:

- Manual refresh icon button
- Auto-refresh toggle
- 30-second or 60-second interval selector, disabled while auto refresh is off
- Last-updated timestamp

Auto refresh pauses while the document is hidden. When the user returns to a visible
tab, the page refreshes immediately and restarts its interval. A malformed stored
preference falls back to disabled and 30 seconds.

## Failure Handling

- Overview renders every successful section and identifies unavailable sections.
- History database absence returns an empty series, not a server error.
- Collector failure exits non-zero for systemd logging and leaves existing samples
  untouched.
- Database writes use a transaction and a short busy timeout.
- Alert-ledger failure never blocks incident evaluation or Mattermost delivery.
- Chart gaps remain gaps; the client does not interpolate missing readings.
- API payloads remain bounded regardless of retention size.

## Work Packages

| ID | Package | Depends on | Deliverable |
| --- | --- | --- | --- |
| OD-001 | Overview domain contract | Existing readers | Pure health aggregation, snapshot schema, and unit tests |
| OD-002 | Alert event history | Alertd | Bounded JSONL incident/recovery ledger and recovery reader |
| OD-003 | Overview frontend | OD-001 API contract | Glanceable layout, workload counts, alerts, compact launcher, and shared refresh controls |
| OD-004 | Metrics history | System telemetry | SQLite collector, systemd timer, retention, history query, and API |
| OD-005 | Performance charts | OD-004 API contract | Lazy Recharts views, range control, summaries, and shared refresh controls |
| OD-006 | Hardening and target signoff | OD-001..OD-005 | Responsive, accessibility, failure, retention, bundle, and Holly Pi verification |

OD-001 and OD-002 can proceed together. OD-003 can use an API fixture once OD-001
defines the contract. OD-004 is independent of the Overview work. OD-005 follows the
history contract.

## Testing

Backend tests cover health precedence, partial source failures, event-ledger bounds,
malformed records, metric retention, fixed-range validation, aggregation limits, and
empty history. Frontend tests cover refresh preference parsing, timer cleanup, hidden
tab behaviour, status ordering, app expansion, partial data, and chart range changes.

Playwright verifies desktop and mobile layouts, keyboard access, no horizontal
overflow, readable status colours, and stable card dimensions. Bundle inspection must
confirm that Recharts is absent from the Overview's initial chunk.

## Release Acceptance

1. A healthy host communicates `All systems operational` without scrolling on desktop.
2. Active problems identify the affected resource and link to its owning page.
3. Container and stack counts distinguish healthy, partial, unhealthy, and stopped
   states.
4. The launcher opens every detected running web application and remains compact with
   more than 12 entries.
5. Overview shows active incidents and the five latest recoveries.
6. Auto refresh defaults to off and shares its 30/60-second preference only between
   Overview and System Health.
7. Performance charts show bounded 24h, 7d, and 30d history with missing-data gaps.
8. Thirty-one days of collection remains within the expected low storage and CPU
   budget on Holly's Pi.
9. A failed metric, alert, stack, or container source does not hide healthy sections.
10. Existing Mattermost alert delivery and AI agent operation remain unaffected.
